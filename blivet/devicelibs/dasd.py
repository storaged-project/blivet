#
# dasd.py - DASD functions
#
# Copyright (C) 2015 Red Hat, Inc.  All rights reserved.
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
# Red Hat Author(s): Samantha N. Bueno <sbueno@redhat.com>
#                    Peter Jones <pjones@redhat.com>
#

import fcntl
import ctypes
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

# ioctl crap that the fcntl module should really do for us...
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRMASK = ((1 << _IOC_NRBITS)-1)
_IOC_TYPEMASK = ((1 << _IOC_TYPEBITS)-1)
_IOC_SIZEMASK = ((1 << _IOC_SIZEBITS)-1)
_IOC_DIRMASK = ((1 << _IOC_DIRBITS)-1)

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = (_IOC_NRSHIFT+_IOC_NRBITS)
_IOC_SIZESHIFT = (_IOC_TYPESHIFT+_IOC_TYPEBITS)
_IOC_DIRSHIFT = (_IOC_SIZESHIFT+_IOC_SIZEBITS)

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2

def _IOC(direction, typ, nr, size):
    return (((direction)  << _IOC_DIRSHIFT) | \
            ((typ)  << _IOC_TYPESHIFT) | \
            ((nr)   << _IOC_NRSHIFT) | \
            ((size) << _IOC_SIZESHIFT))

def _IO(typ, nr):
    return _IOC(_IOC_NONE, typ, nr, 0)
def _IOR(typ, nr, size):
    return _IOC(_IOC_READ, typ, nr, size)
def _IOW(typ, nr, size):
    return _IOC(_IOC_WRITE, typ, nr, size)
def _IOWR(typ, nr, size):
    return _IOC(_IOC_WRITE|_IOC_READ, typ, nr, size)

BLKSSZGET = int(_IO(0x12, 104))
BIODASDINFO2 = int(_IOR(ord('D'), 3, 416))

# and now just do our thing
class blksize(ctypes.Structure):
    _fields_ = [
        ('blksize', ctypes.c_uint),
    ]

class dasd_info(ctypes.Structure):
    _fields_ = [
        ('devno', ctypes.c_uint),
        ('real_devno', ctypes.c_uint),
        ('schid', ctypes.c_uint),
        ('cu_type_model', ctypes.c_uint),
        ('dev_type_model', ctypes.c_uint),
        ('open_count', ctypes.c_uint),
        ('req_queue_len', ctypes.c_uint),
        ('chanq_len', ctypes.c_uint),
        ('type', ctypes.c_char * 4),
        ('status', ctypes.c_uint),
        ('label_block', ctypes.c_uint),
        ('FBA_layout', ctypes.c_uint),
        ('characteristics_size', ctypes.c_uint),
        ('confdata_size', ctypes.c_uint),
        ('characteristics', ctypes.c_char * 64),
        ('configuration_data', ctypes.c_char * 256),
        ('format', ctypes.c_uint),
        ('features', ctypes.c_uint),
        ('reserved0', ctypes.c_uint),
        ('reserved1', ctypes.c_uint),
        ('reserved2', ctypes.c_uint),
        ('reserved3', ctypes.c_uint),
        ('reserved4', ctypes.c_uint),
        ('reserved5', ctypes.c_uint),
        ('reserved6', ctypes.c_uint),
        ('reserved7', ctypes.c_uint),
        ('reserved8', ctypes.c_uint),
    ]

DASD_FORMAT_CDL = 2

def is_ldl_dasd(device):
    """Determine whether or not a DASD is LDL formatted."""
    if not device.startswith("dasd"):
        # not a dasd; bail
        return False

    device = "/dev/%s" % (device,)

    f = open(device, "r")

    # poorly check if this is even a block device...
    arg = blksize()
    rc = fcntl.ioctl(f.fileno(), BLKSSZGET, arg, True)
    if rc < 0:
        return False

    # alright, it's a block device, so get some info about DASD...
    arg = dasd_info()
    rc = fcntl.ioctl(f.fileno(), BIODASDINFO2, arg)
    if rc < 0:
        return False

    # check we're not on an FBA DASD, since dasdfmt can't run on them
    if arg.type.startswith('FBA'):
        return False

    # check DASD volume label; "VOL1" is CDL formatted DASD, won't
    # require formatting
    if arg.format == DASD_FORMAT_CDL:
        return False
    return True

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
    """ Synthesizes a complete DASD number from a possibly partial one.

        :param str dev: a possibly partial DASD device number
        :returns: a synthesized DASD device number
        :rtype: str

        :raises: ValueError if dev is None or empty

        *) Assumes that the rightmost '.' if any, separates the bus number
           from the device number.
        *) Pads the device number on the left with 0s to a length of four
           characters.
        *) If no bus number extracted from dev, uses bus number default 0.0.

        A DASD number has the format n.n.hhhh, where n is any decimal
        digit and h any hexadecimal digit, e.g., 0.0.abcd, 0.0.002A.

        A properly formatted number can be synthesized from a partial number
        if the partial number is missing hexadecimal digits, e.g., 0.0.b, or
        missing a bus number, e.g., 0012. The minimal partial number
        contains a single digit. For example a will be extended to 0.0.000a.
        Wildly improper partial numbers, e.g., qu.er.ty will yield a wildly
        improper result.
    """
    if dev is None or dev == "":
        raise ValueError(_("You have not specified a device number or the number is invalid"))
    dev = dev.lower()
    (bus, _sep, dev) = dev.rpartition('.')

    padding = "0" * (4 - len(dev))
    bus = bus or '0.0'
    return bus + '.' + padding + dev

def online_dasd(dev):
    """ Given a device number, switch the device to be online.

        :param str dev: a DASD device number

        Raises a ValueError if a device with that number does not exist,
        is already online, or can not be put online.
    """
    online = "/sys/bus/ccw/drivers/dasd-eckd/%s/online" % (dev)

    if not os.path.exists(online):
        log.info("Freeing DASD device %s", dev)
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
                log.debug("echo %s > %s", "1", online)
                f.write("%s\n" % ("1"))
    except IOError as e:
        raise ValueError(_("Could not set DASD device %(dev)s online (%(e)s).") \
                        % {'dev': dev, 'e': e})

def write_dasd_conf(disks, root):
    """ Write /etc/dasd.conf to target system for all DASD devices
        configured during installation.
    """
    if not (arch.isS390() and disks):
        return

    with open(os.path.realpath(root + "/etc/dasd.conf"), "w") as f:
        for dasd in sorted(disks, key=lambda d: d.name):
            fields = [dasd.busid] + dasd.getOpts()
            f.write("%s\n" % " ".join(fields),)

    # check for hyper PAV aliases; they need to get added to dasd.conf as well
    sysfs = "/sys/bus/ccw/drivers/dasd-eckd"

    # in the case that someone is installing with *only* FBA DASDs,the above
    # sysfs path will not exist; so check for it and just bail out of here if
    # that's the case
    if not os.path.exists(sysfs):
        return

    # this does catch every DASD, even non-aliases, but we're only going to be
    # checking for a very specific flag, so there won't be any duplicate entries
    # in dasd.conf
    devs = [d for d in os.listdir(sysfs) if d.startswith("0.0")]
    with open(os.path.realpath(root + "/etc/dasd.conf"), "a") as f:
        for d in devs:
            aliasfile = "%s/%s/alias" % (sysfs, d)
            with open(aliasfile, "r") as falias:
                alias = falias.read().strip()

            # if alias == 1, then the device is an alias; otherwise it is a
            # normal dasd (alias == 0) and we can skip it, since it will have
            # been added to dasd.conf in the above block of code
            if alias == "1":
                f.write("%s\n" % d)
