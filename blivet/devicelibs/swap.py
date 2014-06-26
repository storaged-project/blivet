# swap.py
# Python module for managing swap devices.
#
# Copyright (C) 2009  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#

import resource
import os
from decimal import Decimal

from ..errors import DMError, OldSwapError, SuspendError, SwapError, UnknownSwapError
from .. import util
from . import dm
from ..size import Size

import logging
log = logging.getLogger("blivet")

# maximum ratio of swap size to disk size (10 %)
MAX_SWAP_DISK_RATIO = Decimal('0.1')

def mkswap(device, label=None):
    # We use -f to force since mkswap tends to refuse creation on lvs with
    # a message about erasing bootbits sectors on whole disks. Bah.
    argv = ["-f"]
    if label is not None:
        argv.extend(["-L", label])
    argv.append(device)

    ret = util.run_program(["mkswap"] + argv)

    if ret:
        raise SwapError("mkswap failed for '%s'" % device)

def swapon(device, priority=None):
    pagesize = resource.getpagesize()
    buf = None
    sig = None

    if pagesize > 2048:
        num = pagesize
    else:
        num = 2048

    try:
        fd = os.open(device, os.O_RDONLY)
        buf = os.read(fd, num)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except (OSError, UnboundLocalError):
            pass

    if buf is not None and len(buf) == pagesize:
        sig = buf[pagesize - 10:]
        if sig == 'SWAP-SPACE':
            raise OldSwapError
        if sig == 'S1SUSPEND\x00' or sig == 'S2SUSPEND\x00':
            raise SuspendError

    if sig != 'SWAPSPACE2':
        raise UnknownSwapError

    argv = []
    if isinstance(priority, int) and 0 <= priority <= 32767:
        argv.extend(["-p", "%d" % priority])
    argv.append(device)

    rc = util.run_program(["swapon"] + argv)

    if rc:
        raise SwapError("swapon failed for '%s'" % device)

def swapoff(device):
    rc = util.run_program(["swapoff", device])

    if rc:
        raise SwapError("swapoff failed for '%s'" % device)

def swapstatus(device):
    alt_dev = None
    if device.startswith("/dev/mapper/"):
        # get the real device node for device-mapper devices since the ones
        # with meaningful names are just symlinks
        try:
            alt_dev = "/dev/%s" % dm.dm_node_from_name(device.split("/")[-1])
        except DMError:
            alt_dev = None

    lines = open("/proc/swaps").readlines()
    status = False
    for line in lines:
        if not line.strip():
            continue

        swap_dev = line.split()[0]
        if swap_dev in [device, alt_dev]:
            status = True
            break

    return status

def swapSuggestion(quiet=False, hibernation=False, disk_space=None):
    """
    Suggest the size of the swap partition that will be created.

    :param quiet: whether to log size information or not
    :type quiet: bool
    :param hibernation: calculate swap size big enough for hibernation
    :type hibernation: bool
    :param disk_space: how much disk space is available
    :type disk_space: int
    :return: calculated swap size

    """

    mem = util.total_memory()
    mem = ((mem/16)+1)*16
    if not quiet:
        log.info("Detected %s of memory", mem)

    two_GiB = Size("2GiB")
    four_GiB = Size("4GiB")
    eight_GiB = Size("8GiB")
    sixtyfour_GiB = Size("64 GiB")

    #chart suggested in the discussion with other teams
    if mem < two_GiB:
        swap = 2 * mem

    elif two_GiB <= mem < eight_GiB:
        swap = mem

    elif eight_GiB <= mem < sixtyfour_GiB:
        swap = mem / 2

    else:
        swap = four_GiB

    if hibernation:
        if mem <= sixtyfour_GiB:
            swap = mem + swap
        else:
            log.info("Ignoring --hibernation option on systems with %s of RAM or more", sixtyfour_GiB)

    if disk_space is not None and not hibernation:
        max_swap = disk_space * MAX_SWAP_DISK_RATIO
        if swap > max_swap:
            log.info("Suggested swap size (%(swap)s) exceeds %(percent)d %% of "
                     "disk space, using %(percent)d %% of disk space (%(size)s) "
                     "instead.", {"percent": MAX_SWAP_DISK_RATIO*100,
                                  "swap": swap,
                                  "size": max_swap})
            swap = max_swap

    if not quiet:
        log.info("Swap attempt of %s", swap)

    return swap

