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
zfcpconf = "/etc/zfcp.conf"


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

        self._device_online_path = os.path.join(zfcpsysfs, self.devnum, "online")

    # Force str and unicode types in case any of the properties are unicode
    def _to_string(self):
        return str(self.devnum)

    def __str__(self):
        return self._to_string()

    def _free_device(self):
        """Remove the device from the I/O ignore list to make it visible to the system.

        :raises: ValueError if the device cannot be removed from the I/O ignore list
        """

        if not os.path.exists(self._device_online_path):
            log.info("Freeing zFCP device %s", self.devnum)
            util.run_program(["zfcp_cio_free", "-d", self.devnum])

        if not os.path.exists(self._device_online_path):
            raise ValueError(_("zFCP device %s not found, not even in device ignore list.") %
                             (self.devnum,))

    def _set_zfcp_device_online(self):
        """Set the zFCP device online.

        :raises: ValueError if the device cannot be set online
        """

        try:
            with open(self._device_online_path) as f:
                devonline = f.readline().strip()
            if devonline != "1":
                logged_write_line_to_file(self._device_online_path, "1")
        except OSError as e:
            raise ValueError(_("Could not set zFCP device %(devnum)s "
                               "online (%(e)s).")
                             % {'devnum': self.devnum, 'e': e})

    def _set_zfcp_device_offline(self):
        """Set the zFCP device offline.

        :raises: ValueError if the device cannot be set offline
        """

        try:
            logged_write_line_to_file(self._device_online_path, "0")
        except OSError as e:
            raise ValueError(_("Could not set zFCP device %(devnum)s "
                               "offline (%(e)s).")
                             % {'devnum': self.devnum, 'e': e})

    @abstractmethod
    def _is_associated_with_fcp(self, fcphbasysfs, fcpwwpnsysfs, fcplunsysfs):
        """Decide if the provided FCP addressing corresponds to the path stored in the zFCP device.

        :returns: True or False
        """

    def online_device(self):
        """Initialize the device and make its storage block device(s) ready to use.

        :returns: True if success
        :raises: ValueError if the device cannot be initialized
        """

        self._free_device()
        self._set_zfcp_device_online()
        return True

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

        super().online_device()

        portadd = "%s/%s/port_add" % (zfcpsysfs, self.devnum)
        portdir = "%s/%s/%s" % (zfcpsysfs, self.devnum, self.wwpn)
        unitadd = "%s/unit_add" % (portdir)
        unitdir = "%s/%s" % (portdir, self.fcplun)
        failed = "%s/failed" % (unitdir)

        # Activating using devnum, WWPN, and LUN despite available zFCP auto LUN scan should still
        # be possible as this method was used as a workaround until the support for zFCP auto LUN
        # scan devices has been implemented. Just log a warning message and continue.
        if has_auto_lun_scan(self.devnum):
            log.warning("zFCP device %s in NPIV mode brought online. All LUNs will be activated "
                        "automatically although WWPN and LUN have been provided.", self.devnum)

        # create the sysfs directory for the WWPN/port
        if not os.path.exists(portdir):
            if os.path.exists(portadd):
                # older zfcp sysfs interface
                try:
                    logged_write_line_to_file(portadd, self.wwpn)
                    udev.settle()
                except OSError as e:
                    raise ValueError(_("Could not add WWPN %(wwpn)s to zFCP "
                                       "device %(devnum)s (%(e)s).")
                                     % {'wwpn': self.wwpn,
                                         'devnum': self.devnum,
                                         'e': e})
            else:
                # newer zfcp sysfs interface with auto port scan
                raise ValueError(_("WWPN %(wwpn)s not found at zFCP device "
                                   "%(devnum)s.") % {'wwpn': self.wwpn,
                                                     'devnum': self.devnum})
        else:
            if os.path.exists(portadd):
                # older zfcp sysfs interface
                log.info("WWPN %(wwpn)s at zFCP device %(devnum)s already "
                         "there.", {'wwpn': self.wwpn,
                                    'devnum': self.devnum})

        # create the sysfs directory for the LUN/unit
        if not os.path.exists(unitdir):
            try:
                logged_write_line_to_file(unitadd, self.fcplun)
                udev.settle()
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

        # check the state of the LUN
        fail = "0"
        try:
            f = open(failed, "r")
            fail = f.readline().strip()
            f.close()
        except OSError as e:
            raise ValueError(_("Could not read failed attribute of LUN "
                               "%(fcplun)s at WWPN %(wwpn)s on zFCP device "
                               "%(devnum)s (%(e)s).")
                             % {'fcplun': self.fcplun,
                                 'wwpn': self.wwpn,
                                 'devnum': self.devnum,
                                 'e': e})
        if fail != "0":
            self.offline_device()
            raise ValueError(_("Failed LUN %(fcplun)s at WWPN %(wwpn)s on "
                               "zFCP device %(devnum)s removed again.")
                             % {'fcplun': self.fcplun,
                                 'wwpn': self.wwpn,
                                 'devnum': self.devnum})

        return True

    def offline_device(self):
        """Remove the zFCP device from the system."""

        portadd = "%s/%s/port_add" % (zfcpsysfs, self.devnum)
        portremove = "%s/%s/port_remove" % (zfcpsysfs, self.devnum)
        unitremove = "%s/%s/%s/unit_remove" % (zfcpsysfs, self.devnum, self.wwpn)
        portdir = "%s/%s/%s" % (zfcpsysfs, self.devnum, self.wwpn)
        devdir = "%s/%s" % (zfcpsysfs, self.devnum)

        try:
            self.offline_scsi_device()
        except OSError as e:
            raise ValueError(_("Could not correctly delete SCSI device of "
                               "zFCP %(devnum)s %(wwpn)s %(fcplun)s "
                               "(%(e)s).")
                             % {'devnum': self.devnum, 'wwpn': self.wwpn,
                                 'fcplun': self.fcplun, 'e': e})

        # remove the LUN
        try:
            logged_write_line_to_file(unitremove, self.fcplun)
        except OSError as e:
            raise ValueError(_("Could not remove LUN %(fcplun)s at WWPN "
                               "%(wwpn)s on zFCP device %(devnum)s "
                               "(%(e)s).")
                             % {'fcplun': self.fcplun, 'wwpn': self.wwpn,
                                 'devnum': self.devnum, 'e': e})

        # remove the WWPN only if there are no other LUNs attached
        if os.path.exists(portadd):
            # only try to remove ports with older zfcp sysfs interface
            for lun in os.listdir(portdir):
                if lun.startswith("0x") and \
                        os.path.isdir(os.path.join(portdir, lun)):
                    log.info("Not removing WWPN %s at zFCP device %s since port still has other LUNs, e.g. %s.",
                             self.wwpn, self.devnum, lun)
                    return True

            try:
                logged_write_line_to_file(portremove, self.wwpn)
            except OSError as e:
                raise ValueError(_("Could not remove WWPN %(wwpn)s on zFCP "
                                   "device %(devnum)s (%(e)s).")
                                 % {'wwpn': self.wwpn,
                                     'devnum': self.devnum, 'e': e})

        # check if there are other WWPNs existing for the zFCP device number
        if os.path.exists(portadd):
            # older zfcp sysfs interface
            for port in os.listdir(devdir):
                if port.startswith("0x") and \
                        os.path.isdir(os.path.join(devdir, port)):
                    log.info("Not setting zFCP device %s offline since it still has other ports, e.g. %s.",
                             self.devnum, port)
                    return True
        else:
            # newer zfcp sysfs interface with auto port scan
            luns = glob.glob("%s/0x????????????????/0x????????????????"
                             % (devdir,))
            if len(luns) != 0:
                log.info("Not setting zFCP device %s offline since it still has other LUNs, e.g. %s.",
                         self.devnum, luns[0])
                return True

        # no other WWPNs/LUNs exists for this device number, it's safe to bring it offline
        self._set_zfcp_device_offline()

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

        super().online_device()

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

        This class will automatically online to ZFCP drives configured in
        /tmp/fcpconfig when the startup() method gets called. It can also be
        used to manually configure ZFCP devices through the add_fcp() method.

        As this class needs to make sure that /tmp/fcpconfig configured
        drives are only onlined once and as it keeps a global list of all ZFCP
        devices it is implemented as a Singleton.
    """

    def __init__(self):
        self.fcpdevs = set()
        self.has_read_config = False
        self.down = True

    # So that users can write zfcp() to get the singleton instance
    def __call__(self):
        return self

    def __deepcopy__(self, memo_dict):
        # pylint: disable=unused-argument
        return self

    def read_config(self):
        try:
            f = open(zfcpconf, "r")
        except OSError:
            log.info("no %s; not configuring zfcp", zfcpconf)
            return

        lines = [x.strip().lower() for x in f.readlines()]
        f.close()

        for line in lines:
            if line.startswith("#") or line == '':
                continue

            fields = line.split()

            # zFCP auto LUN scan available
            if len(fields) == 1:
                devnum = fields[0]
                wwpn = None
                fcplun = None
            elif len(fields) == 3:
                devnum = fields[0]
                wwpn = fields[1]
                fcplun = fields[2]
            elif len(fields) == 5:
                # support old syntax of:
                # devno scsiid wwpn scsilun fcplun
                devnum = fields[0]
                wwpn = fields[2]
                fcplun = fields[4]
            else:
                log.warning("Invalid line found in %s: %s", zfcpconf, line)
                continue

            try:
                self.add_fcp(devnum, wwpn, fcplun)
            except ValueError as e:
                log.warning("%s", str(e))

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
        if not self.has_read_config:
            self.read_config()
            self.has_read_config = True
            # read_config calls add_fcp which calls online_device already
            return

        if len(self.fcpdevs) == 0:
            return
        for d in self.fcpdevs:
            try:
                d.online_device()
            except ValueError as e:
                log.warning("%s", str(e))

    def write(self, root):
        if len(self.fcpdevs) == 0:
            return
        f = open(root + zfcpconf, "w")
        for d in self.fcpdevs:
            f.write("%s\n" % (d,))
        f.close()

        f = open(root + "/etc/modprobe.conf", "a")
        f.write("alias scsi_hostadapter zfcp\n")
        f.close()


# Create ZFCP singleton
zfcp = zFCP()
