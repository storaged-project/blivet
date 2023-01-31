#
# zfcp.py - mainframe zfcp configuration install data
#
# Copyright (C) 2001, 2002, 2003, 2004  Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author(s): Karsten Hopp <karsten@redhat.com>
#

import os
import re
from abc import ABC, abstractmethod
import glob
from . import udev
from . import util
from .i18n import _

import gi
gi.require_version("BlockDev", "3.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")


def logged_write_line_to_file(fn, value):
    f = open(fn, "w")
    log.debug("echo %s > %s", value, fn)
    f.write("%s\n" % (value))
    f.close()


zfcpsysfs = "/sys/bus/ccw/drivers/zfcp"
scsidevsysfs = "/sys/bus/scsi/devices"


def _is_lun_scan_allowed():
    """Return True if automatic LUN scanning is enabled by the kernel."""

    allow_lun_scan = util.get_kernel_module_parameter("zfcp", "allow_lun_scan")
    return allow_lun_scan == "Y"


def _is_port_in_npiv_mode(device_id):
    """Return True if the device ID is configured in NPIV mode. See
    https://www.ibm.com/docs/en/linux-on-systems?topic=devices-use-npiv
    """

    port_in_npiv_mode = False
    port_type_path = "/sys/bus/ccw/devices/{}/host*/fc_host/host*/port_type".format(device_id)
    port_type_paths = glob.glob(port_type_path)
    try:
        for filename in port_type_paths:
            with open(filename) as f:
                port_type = f.read()
            if re.search(r"(^|\s)NPIV(\s|$)", port_type):
                port_in_npiv_mode = True
    except OSError as e:
        log.warning("Couldn't read the port_type attribute of the %s device: %s", device_id, str(e))
        port_in_npiv_mode = False

    return port_in_npiv_mode


def has_auto_lun_scan(device_id):
    """Return True if the given zFCP device ID is configured in NPIV (N_Port ID Virtualization)
    mode and zFCP auto LUN scan is not disabled.

    :returns: True or False
    """

    # LUN scanning disabled by the kernel module prevents using zFCP auto LUN scan
    if not _is_lun_scan_allowed():
        log.warning("Automatic LUN scanning is disabled by the zfcp kernel module.")
        return False

    # The port itself has to be configured in NPIV mode
    if not _is_port_in_npiv_mode(device_id):
        log.warning("The zFCP device %s is not configured in NPIV mode.", device_id)
        return False

    return True


class ZFCPDeviceBase(ABC):
    """An abstract base class for zFCP storage devices."""

    def __init__(self, devnum):
        self.devnum = blockdev.s390.sanitize_dev_input(devnum)
        if not self.devnum:
            raise ValueError(_("You have not specified a device number or the number is invalid"))

    # Force str and unicode types in case any of the properties are unicode
    def _to_string(self):
        return str(self.devnum)

    def __str__(self):
        return self._to_string()

    def _set_zfcp_device_online(self):
        """Set the zFCP device online.

        :raises: ValueError if the device cannot be set online
        """

        try:
            util.run_program(["chzdev", "--enable", "zfcp-host", self.devnum,
                              "--yes", "--no-root-update", "--force"])
        except OSError as e:
            raise ValueError(_("Could not set zFCP device %(devnum)s "
                               "online (%(e)s).")
                             % {'devnum': self.devnum, 'e': e})

    def _set_zfcp_device_offline(self):
        """Set the zFCP device offline.

        :raises: ValueError if the device cannot be set offline
        """

        try:
            util.run_program(["chzdev", "--disable", "zfcp-host", self.devnum,
                              "--yes", "--no-root-update", "--force"])
        except OSError as e:
            raise ValueError(_("Could not set zFCP device %(devnum)s "
                               "offline (%(e)s).")
                             % {'devnum': self.devnum, 'e': e})

    @abstractmethod
    def _is_associated_with_fcp(self, fcphbasysfs, fcpwwpnsysfs, fcplunsysfs):
        """Decide if the provided FCP addressing corresponds to the path stored in the zFCP device.

        :returns: True or False
        """

    @abstractmethod
    def online_device(self):
        """Initialize the device and make its storage block device(s) ready to use.

        :returns: True if success
        :raises: ValueError if the device cannot be initialized
        """

    def offline_scsi_device(self):
        """Find SCSI devices associated to the zFCP device and remove them from the system."""

        # A list of existing SCSI devices in format Host:Bus:Target:Lun
        scsi_devices = [f for f in os.listdir(scsidevsysfs) if re.search(r'^[0-9]+:[0-9]+:[0-9]+:[0-9]+$', f)]

        scsi_device_found = False
        for scsidev in scsi_devices:
            fcpsysfs = os.path.join(scsidevsysfs, scsidev)

            with open(os.path.join(fcpsysfs, "hba_id")) as f:
                fcphbasysfs = f.readline().strip()
            with open(os.path.join(fcpsysfs, "wwpn")) as f:
                fcpwwpnsysfs = f.readline().strip()
            with open(os.path.join(fcpsysfs, "fcp_lun")) as f:
                fcplunsysfs = f.readline().strip()

            if self._is_associated_with_fcp(fcphbasysfs, fcpwwpnsysfs, fcplunsysfs):
                scsi_device_found = True
                scsidel = os.path.join(scsidevsysfs, scsidev, "delete")
                logged_write_line_to_file(scsidel, "1")
                udev.settle()

        if not scsi_device_found:
            log.warning("No scsi device found to delete for zfcp %s", self)


class ZFCPDeviceFullPath(ZFCPDeviceBase):
    """A class for zFCP devices where zFCP auto LUN scan is not available. Such
    devices have to be specified by a device number, WWPN and LUN.
    """

    def __init__(self, devnum, wwpn, fcplun):
        super().__init__(devnum)

        self.wwpn = blockdev.s390.zfcp_sanitize_wwpn_input(wwpn)
        if not self.wwpn:
            raise ValueError(_("You have not specified a worldwide port name or the name is invalid."))

        self.fcplun = blockdev.s390.zfcp_sanitize_lun_input(fcplun)
        if not self.fcplun:
            raise ValueError(_("You have not specified a FCP LUN or the number is invalid."))

    # Force str and unicode types in case any of the properties are unicode
    def _to_string(self):
        return "{} {} {}".format(self.devnum, self.wwpn, self.fcplun)

    def _is_associated_with_fcp(self, fcphbasysfs, fcpwwpnsysfs, fcplunsysfs):
        """Decide if the provided FCP addressing corresponds to the path stored in the zFCP device.

        :returns: True or False
        """

        return (fcphbasysfs == self.devnum and
                fcpwwpnsysfs == self.wwpn and
                fcplunsysfs == self.fcplun)

    def online_device(self):
        """Initialize the device and make its storage block device(s) ready to use.

        :returns: True if success
        :raises: ValueError if the device cannot be initialized
        """

        portdir = "%s/%s/%s" % (zfcpsysfs, self.devnum, self.wwpn)
        unitdir = "%s/%s" % (portdir, self.fcplun)

        # create the sysfs directory for the LUN/unit
        if not os.path.exists(unitdir):
            try:
                util.run_program(["chzdev", "--enable", "zfcp-lun",
                                  "%s:%s:%s" % (self.devnum, self.wwpn, self.fcplun),
                                  "--yes", "--no-root-update", "--force"])
            except OSError as e:
                raise ValueError(_("Could not add LUN %(fcplun)s to WWPN "
                                   "%(wwpn)s on zFCP device %(devnum)s "
                                   "(%(e)s).")
                                 % {'fcplun': self.fcplun, 'wwpn': self.wwpn,
                                     'devnum': self.devnum, 'e': e})
        else:
            raise ValueError(_("LUN %(fcplun)s at WWPN %(wwpn)s on zFCP "
                               "device %(devnum)s already configured.")
                             % {'fcplun': self.fcplun,
                                 'wwpn': self.wwpn,
                                 'devnum': self.devnum})

        # Activating using devnum, WWPN, and LUN despite available zFCP auto LUN scan should still
        # be possible as this method was used as a workaround until the support for zFCP auto LUN
        # scan devices has been implemented. Just log a warning message and continue.
        if has_auto_lun_scan(self.devnum):
            log.warning("zFCP device %s in NPIV mode brought online. All LUNs will be activated "
                        "automatically although WWPN and LUN have been provided.", self.devnum)

        return True

    def offline_device(self):
        """Remove the zFCP device from the system."""

        # remove the LUN
        try:
            util.run_program(["chzdev", "--disable", "zfcp-lun",
                              "%s:%s:%s" % (self.devnum, self.wwpn, self.fcplun),
                              "--yes", "--no-root-update", "--force"])
        except OSError as e:
            raise ValueError(_("Could not remove LUN %(fcplun)s at WWPN "
                               "%(wwpn)s on zFCP device %(devnum)s "
                               "(%(e)s).")
                             % {'fcplun': self.fcplun, 'wwpn': self.wwpn,
                                 'devnum': self.devnum, 'e': e})

        return True


class ZFCPDevice(ZFCPDeviceFullPath):
    """Class derived from ZFCPDeviceFullPath to reserve backward compatibility for applications
    using the ZFCPDevice class. ZFCPDeviceFullPath should be used instead in new code.
    """


class ZFCPDeviceAutoLunScan(ZFCPDeviceBase):
    """Class for zFCP devices configured in NPIV mode and zFCP auto LUN scan not disabled. Only
    a zFCP device number is needed for such devices.
    """

    def online_device(self):
        """Initialize the device and make its storage block device(s) ready to use.

        :returns: True if success
        :raises: ValueError if the device cannot be initialized
        """

        self._set_zfcp_device_online()

        if not has_auto_lun_scan(self.devnum):
            raise ValueError(_("zFCP device %s cannot use auto LUN scan.") % self)

        return True

    def offline_device(self):
        """Remove the zFCP device from the system.

        :returns: True if success
        :raises: ValueError if the device cannot be brought offline
         """

        try:
            self.offline_scsi_device()
        except OSError as e:
            raise ValueError(_("Could not correctly delete SCSI device of "
                               "zFCP %(zfcpdev)s (%(e)s).")
                             % {'zfcpdev': self, 'e': e})

        self._set_zfcp_device_offline()

        return True

    def _is_associated_with_fcp(self, fcphbasysfs, _fcpwwpnsysfs, _fcplunsysfs):
        """Decide if the provided FCP addressing corresponds to the zFCP device.

        :returns: True or False
        """

        return fcphbasysfs == self.devnum


class zFCP:

    """ ZFCP utility class.

        This class is used to manually configure ZFCP devices through the
        add_fcp() method, which is used by the anaconda GUI or by kickstart.

        As this class needs to make sure that configured
        drives are only onlined once and as it keeps a global list of all ZFCP
        devices it is implemented as a Singleton.

        In particular, this class does not create objects for any other method
        that enables ZFCP devices such as rd.zfcp= or any device auto
        configuration. These methods make zfcp-attached SCSI disk block devices
        available, which ZFCPDiskDevice [devices/disk.py] can directly
        discover.
    """

    def __init__(self):
        self.fcpdevs = set()
        self.down = True

    # So that users can write zfcp() to get the singleton instance
    def __call__(self):
        return self

    def __deepcopy__(self, memo_dict):
        # pylint: disable=unused-argument
        return self

    def add_fcp(self, devnum, wwpn=None, fcplun=None):
        if wwpn and fcplun:
            d = ZFCPDeviceFullPath(devnum, wwpn, fcplun)
        else:
            d = ZFCPDeviceAutoLunScan(devnum)

        if d.online_device():
            self.fcpdevs.add(d)

    def shutdown(self):
        if self.down:
            return
        self.down = True
        if len(self.fcpdevs) == 0:
            return
        for d in self.fcpdevs:
            try:
                d.offline_device()
            except ValueError as e:
                log.warning("%s", str(e))

    def startup(self):
        if not self.down:
            return
        self.down = False

        if len(self.fcpdevs) == 0:
            return
        for d in self.fcpdevs:
            try:
                d.online_device()
            except ValueError as e:
                log.warning("%s", str(e))

    def write(self, root):
        pass


# Create ZFCP singleton
zfcp = zFCP()
