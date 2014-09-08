#
# dasd.py - DASD functions
#
# Copyright (C) 2013 Red Hat, Inc.  All rights reserved.
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
# Red Hat Author(s): Samantha N. Bueno
#

import os
from blivet.errors import DasdFormatError
from blivet.devices import deviceNameToDiskByPath
from blivet import util
from blivet import arch

import logging
log = logging.getLogger("blivet")

import gettext
_ = lambda x: gettext.ldgettext("blivet", x)
P_ = lambda x, y, z: gettext.ldngettext("blivet", x, y, z)

def get_dasd_ports():
    """ Return comma delimited string of valid DASD ports. """
    ports = []

    with open("/proc/dasd/devices", "r") as f:
        lines = (line.strip() for line in f.readlines())

    for line in lines:
        if "unknown" in line:
            continue

        if "(FBA )" in line or "(ECKD)" in line:
            ports.append(line.split('(')[0])

    return ','.join(ports)

def format_dasd(dasd):
    """ Run dasdfmt on a DASD. Aside from one type of device noted below, this
        function _does not_ check if a DASD needs to be formatted, but rather,
        assumes the list passed needs formatting.

        We don't need to show or update any progress bars, since disk actions
        will be taking place all in the progress hub, which is just one big
        progress bar.
    """
    try:
        rc = util.run_program(["/sbin/dasdfmt", "-y", "-d", "cdl", "-b", "4096", "/dev/" + dasd])
    except Exception as err:
        raise DasdFormatError(err)

    if rc:
        raise DasdFormatError("dasdfmt failed: %s" % rc)

def make_dasd_list(dasds, disks):
    """ Create a list of DASDs recognized by the system. """
    if not arch.isS390():
        return

    log.info("Generating DASD list...")
    for dev in (d for d in disks if d.type == "dasd"):
        if dev not in dasds:
            dasds.append(dev)

    return dasds

def make_unformatted_dasd_list(dasds):
    """ Return a list of DASDS which are not formatted. """
    unformatted = []

    for dasd in dasds:
        if dasd_needs_format(dasd):
            unformatted.append(dasd)

    return unformatted

def dasd_needs_format(dasd):
    """ Check if a DASD needs to have dasdfmt run against it or not.
        Return True if we do need dasdfmt, False if not.
    """
    statusfile = "/sys/block/%s/device/status" % (dasd,)
    if not os.path.isfile(statusfile):
        return False

    with open(statusfile, "r") as f:
        status = f.read().strip()

    if status in ["unformatted"]:
        bypath = deviceNameToDiskByPath(dasd)
        if not bypath:
            bypath = "/dev/" + dasd

        log.info("  %s (%s) status is %s, needs dasdfmt", dasd, bypath, status)
        return True

    return False

def sanitize_dasd_dev_input(dev):
    """ Given a user-supplied device number, make sure the input is sane, and
        raise an error if it is not.

    :param dev: string representing a DASD device number
    """
    if dev is None or dev == "":
        raise ValueError(_("You have not specified a device number or the number is invalid"))
    dev = dev.lower()
    bus = dev[:dev.rfind(".") + 1]
    dev = dev[dev.rfind(".") + 1:]

    dev = "0" * (4 - len(dev)) + dev
    if not bus:
        return "0.0." + dev
    else:
        return bus + dev

def online_dasd(dev):
    """ Given a device number, switch the device to be online.

    :param dev: string representing a DASD device number; acceptable formats
                include 0.0.abcd, 0.0.ABCD, abcd, ABCD, where 'abcd' are
                hexadecimal numbers.
    """
    online = "/sys/bus/ccw/drivers/dasd-eckd/%s/online" % (dev)

    if not os.path.exists(online):
        log.info("Freeing DASD device %s" % dev)
        util.run_program(["dasd_cio_free", "-d", dev])

    if not os.path.exists(online):
        raise ValueError(_("DASD device %s not found, not even in device ignore list.")
            % dev)

    try:
        with open(online, "r") as f:
            devonline = f.readline().strip()
        if devonline == "1":
            raise ValueError(_("Device %s is already online.") % dev)
        else:
            with open(online, "w") as f:
                log.debug("echo %s > %s" % ("1", online))
                f.write("%s\n" % ("1"))
    except IOError as e:
        raise ValueError(_("Could not set DASD device %(dev)s online (%(e)s).") \
                        % {'dev': dev, 'e': e})

def write_dasd_conf(disks, root):
    """ Write /etc/dasd.conf to target system for all DASD devices
        configured during installation.
    """
    if not (arch.isS390() or disks):
        return

    with open(os.path.realpath(root + "/etc/dasd.conf"), "w") as f:
        for dasd in sorted(disks, key=lambda d: d.name):
            fields = [dasd.busid] + dasd.getOpts()
            f.write("%s\n" % " ".join(fields),)
