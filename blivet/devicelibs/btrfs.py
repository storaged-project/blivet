#
# btrfs.py
# btrfs functions
#
# Copyright (C) 2011-2014  Red Hat, Inc.  All rights reserved.
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
# Author(s): David Lehman <dlehman@redhat.com>
#

import os
import re

from .. import util
from ..errors import *

import logging
log = logging.getLogger("blivet")

# this is the volume id btrfs always assigns to the top-level volume/tree
MAIN_VOLUME_ID = 5

def btrfs(args, capture=False):
    if capture:
        exec_func = util.capture_output
    else:
        exec_func = util.run_program

    argv = ["btrfs"] + args

    ret = exec_func(argv)
    if ret and not capture:
        raise BTRFSError(ret)
    return ret

def create_volume(devices, label=None, data=None, metadata=None):
    """Create a btrfs filesystem on the list of devices specified by devices.

       Optional arguments label, data, metadata corresponds to flags
       accepted by mkfs.btrfs.

       For now, data and metadata must be strings mkfs.btrfs understands.
    """
    if not devices:
        raise ValueError("no devices specified")
    elif any([not os.path.exists(d) for d in devices]):
        raise ValueError("one or more specified devices not present")

    args = []
    if data:
        args.append("--data=%s" % data)

    if metadata:
        args.append("--metadata=%s" % metadata)

    if label:
        args.append("--label=%s" % label)

    args.extend(devices)

    ret = util.run_program(["mkfs.btrfs"] + args)
    if ret:
        raise BTRFSError(ret)

    return ret

# destroy is handled using wipefs

def add(mountpoint, device):
    if not os.path.ismount(mountpoint):
        raise ValueError("volume not mounted")

    return btrfs(["device", "add", device, mountpoint])

def remove(mountpoint, device):
    if not os.path.ismount(mountpoint):
        raise ValueError("volume not mounted")

    return btrfs(["device", "delete", device, mountpoint])

def create_subvolume(mountpoint, name):
    """Create a subvolume named name below mountpoint mountpoint."""
    if not os.path.ismount(mountpoint):
        raise ValueError("volume not mounted")

    path = os.path.normpath("%s/%s" % (mountpoint, name))
    args = ["subvol", "create", path]
    return btrfs(args)

def delete_subvolume(mountpoint, name):
    if not os.path.ismount(mountpoint):
        raise ValueError("volume not mounted")

    path = os.path.normpath("%s/%s" % (mountpoint, name))
    args = ["subvol", "delete", path]
    return btrfs(args)

_SUBVOL_REGEX_STR = r'ID (\d+) gen \d+ parent (\d+) top level \d+ path (.+)\n'
_SUBVOL_REGEX = re.compile(_SUBVOL_REGEX_STR)

# get a list of subvolumes from a mounted btrfs filesystem
def list_subvolumes(mountpoint):
    if not os.path.ismount(mountpoint):
        raise ValueError("volume not mounted")

    args = ["subvol", "list", "-p", mountpoint]
    buf = btrfs(args, capture=True)
    vols = []
    for group in _SUBVOL_REGEX.findall(buf):
        vols.append({"id": int(group[0]), "parent": int(group[1]),
                     "path": group[2]})

    return vols

def get_default_subvolume(mountpoint):
    if not os.path.ismount(mountpoint):
        raise ValueError("volume not mounted")

    args = ["subvol", "get-default", mountpoint]
    buf = btrfs(args, capture=True)
    m = re.match(r'ID (\d+) .*', buf)
    try:
        default = int(m.groups()[0])
    except IndexError:
        raise BTRFSError("failed to get default subvolume from %s" % mountpoint)

    return default

_DEVICE_REGEX_STR = r'devid[ \t]+(\d+)[ \t]+size[ \t]+(\S+)[ \t]+used[ \t]+(\S+)[ \t]+path[ \t]+(\S+)\n'
_DEVICE_REGEX = re.compile(_DEVICE_REGEX_STR)

def list_devices(device):
    """List the devices in the filesystem in which this device participates. """
    args = ["filesystem", "show", device]
    buf = btrfs(args, capture=True)
    return [{"id" : g[0], "size" : g[1], "used" : g[2], "path" : g[3] } for g in _DEVICE_REGEX.findall(buf)]

_HEADER_REGEX_STR = r'Label: (?P<label>\S+)[ \t]+uuid: (?P<uuid>\S+)\s+Total devices (?P<num_devices>\d+)[ \t]+FS bytes used (?P<fs_bytes_used>\S+)\n'
_HEADER_REGEX = re.compile(_HEADER_REGEX_STR)

def summarize_filesystem(device):
    """Summarize some general information about the filesystem in which this
       device participates.
    """
    args = ["filesystem", "show", device]
    buf = btrfs(args, capture=True)
    return _HEADER_REGEX.search(buf).groupdict()
