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
from . import udev
from . import util
from .i18n import _
from .util import stringize, unicodeize

import gi
gi.require_version("BlockDev", "2.0")

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


class ZFCPDevice:
    """
        .. warning::
            Since this is a singleton class, calling deepcopy() on the instance
            just returns ``self`` with no copy being created.
    """

    def __init__(self, devnum, wwpn, fcplun):
        self.devnum = blockdev.s390.sanitize_dev_input(devnum)
        self.wwpn = blockdev.s390.zfcp_sanitize_wwpn_input(wwpn)
        self.fcplun = blockdev.s390.zfcp_sanitize_lun_input(fcplun)

        if not self.devnum:
            raise ValueError(_("You have not specified a device number or the number is invalid"))
        if not self.wwpn:
            raise ValueError(_("You have not specified a worldwide port name or the name is invalid."))
        if not self.fcplun:
            raise ValueError(_("You have not specified a FCP LUN or the number is invalid."))

    # Force str and unicode types in case any of the properties are unicode
    def _to_string(self):
        return "%s %s %s" % (self.devnum, self.wwpn, self.fcplun)

    def __str__(self):
        return stringize(self._to_string())

    def __unicode__(self):
        return unicodeize(self._to_string())

    def online_device(self):
        online = "%s/%s/online" % (zfcpsysfs, self.devnum)
        portadd = "%s/%s/port_add" % (zfcpsysfs, self.devnum)
        portdir = "%s/%s/%s" % (zfcpsysfs, self.devnum, self.wwpn)
        unitadd = "%s/unit_add" % (portdir)
        unitdir = "%s/%s" % (portdir, self.fcplun)
        failed = "%s/failed" % (unitdir)

        if not os.path.exists(online):
            log.info("Freeing zFCP device %s", self.devnum)
            util.run_program(["zfcp_cio_free", "-d", self.devnum])

        if not os.path.exists(online):
            raise ValueError(_("zFCP device %s not found, not even in device ignore list.") %
                             (self.devnum,))

        try:
            f = open(online, "r")
            devonline = f.readline().strip()
            f.close()
            if devonline != "1":
                logged_write_line_to_file(online, "1")
        except IOError as e:
            raise ValueError(_("Could not set zFCP device %(devnum)s "
                               "online (%(e)s).")
                             % {'devnum': self.devnum, 'e': e})

        if not os.path.exists(portdir):
            if os.path.exists(portadd):
                # older zfcp sysfs interface
                try:
                    logged_write_line_to_file(portadd, self.wwpn)
                    udev.settle()
                except IOError as e:
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

        if not os.path.exists(unitdir):
            try:
                logged_write_line_to_file(unitadd, self.fcplun)
                udev.settle()
            except IOError as e:
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

        fail = "0"
        try:
            f = open(failed, "r")
            fail = f.readline().strip()
            f.close()
        except IOError as e:
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

    def offline_scsi_device(self):
        f = open("/proc/scsi/scsi", "r")
        lines = f.readlines()
        f.close()
        # alternatively iterate over /sys/bus/scsi/devices/*:0:*:*/

        for line in lines:
            if not line.startswith("Host"):
                continue
            scsihost = line.split()
            host = scsihost[1]
            channel = "0"
            devid = scsihost[5]
            lun = scsihost[7]
            scsidev = "%s:%s:%s:%s" % (host[4:], channel, devid, lun)
            fcpsysfs = "%s/%s" % (scsidevsysfs, scsidev)
            scsidel = "%s/%s/delete" % (scsidevsysfs, scsidev)

            f = open("%s/hba_id" % (fcpsysfs), "r")
            fcphbasysfs = f.readline().strip()
            f.close()
            f = open("%s/wwpn" % (fcpsysfs), "r")
            fcpwwpnsysfs = f.readline().strip()
            f.close()
            f = open("%s/fcp_lun" % (fcpsysfs), "r")
            fcplunsysfs = f.readline().strip()
            f.close()

            if fcphbasysfs == self.devnum \
                    and fcpwwpnsysfs == self.wwpn \
                    and fcplunsysfs == self.fcplun:
                logged_write_line_to_file(scsidel, "1")
                udev.settle()
                return

        log.warning("no scsi device found to delete for zfcp %s %s %s",
                    self.devnum, self.wwpn, self.fcplun)

    def offline_device(self):
        offline = "%s/%s/online" % (zfcpsysfs, self.devnum)
        portadd = "%s/%s/port_add" % (zfcpsysfs, self.devnum)
        portremove = "%s/%s/port_remove" % (zfcpsysfs, self.devnum)
        unitremove = "%s/%s/%s/unit_remove" % (zfcpsysfs, self.devnum, self.wwpn)
        portdir = "%s/%s/%s" % (zfcpsysfs, self.devnum, self.wwpn)
        devdir = "%s/%s" % (zfcpsysfs, self.devnum)

        try:
            self.offline_scsi_device()
        except IOError as e:
            raise ValueError(_("Could not correctly delete SCSI device of "
                               "zFCP %(devnum)s %(wwpn)s %(fcplun)s "
                               "(%(e)s).")
                             % {'devnum': self.devnum, 'wwpn': self.wwpn,
                                 'fcplun': self.fcplun, 'e': e})

        try:
            logged_write_line_to_file(unitremove, self.fcplun)
        except IOError as e:
            raise ValueError(_("Could not remove LUN %(fcplun)s at WWPN "
                               "%(wwpn)s on zFCP device %(devnum)s "
                               "(%(e)s).")
                             % {'fcplun': self.fcplun, 'wwpn': self.wwpn,
                                 'devnum': self.devnum, 'e': e})

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
            except IOError as e:
                raise ValueError(_("Could not remove WWPN %(wwpn)s on zFCP "
                                   "device %(devnum)s (%(e)s).")
                                 % {'wwpn': self.wwpn,
                                     'devnum': self.devnum, 'e': e})

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
            import glob
            luns = glob.glob("%s/0x????????????????/0x????????????????"
                             % (devdir,))
            if len(luns) != 0:
                log.info("Not setting zFCP device %s offline since it still has other LUNs, e.g. %s.",
                         self.devnum, luns[0])
                return True

        try:
            logged_write_line_to_file(offline, "0")
        except IOError as e:
            raise ValueError(_("Could not set zFCP device %(devnum)s "
                               "offline (%(e)s).")
                             % {'devnum': self.devnum, 'e': e})

        return True


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
        except IOError:
            log.info("no %s; not configuring zfcp", zfcpconf)
            return

        lines = [x.strip().lower() for x in f.readlines()]
        f.close()

        for line in lines:
            if line.startswith("#") or line == '':
                continue

            fields = line.split()

            if len(fields) == 3:
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

    def add_fcp(self, devnum, wwpn, fcplun):
        d = ZFCPDevice(devnum, wwpn, fcplun)
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

# vim:tw=78:ts=4:et:sw=4
