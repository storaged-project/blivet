#
# mdraid.py
# mdraid functions
#
# Copyright (C) 2009  Red Hat, Inc.  All rights reserved.
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
# Author(s): Dave Lehman <dlehman@redhat.com>
#

import os

from .. import util
from ..errors import *

import logging
log = logging.getLogger("blivet")

# these defaults were determined empirically
MD_SUPERBLOCK_SIZE = 2.0    # MB
MD_CHUNK_SIZE = 0.5         # MB

# raidlevels constants
RAID10 = 10
RAID6 = 6
RAID5 = 5
RAID4 = 4
RAID1 = 1
RAID0 = 0

raid_levels = [ RAID0, RAID1, RAID4, RAID5, RAID6, RAID10 ]

raid_descriptors = {RAID10: ("raid10", "RAID10", "10", 10),
                    RAID6: ("raid6", "RAID6", "6", 6),
                    RAID5: ("raid5", "RAID5", "5", 5),
                    RAID4: ("raid4", "RAID4", "4", 4),
                    RAID1: ("raid1", "mirror", "RAID1", "1", 1),
                    RAID0: ("raid0", "stripe", "RAID0", "0", 0)}

def raidLevel(descriptor):
    for level in raid_levels:
        if isRaid(level, descriptor):
            return level
    else:
        raise MDRaidError("invalid raid level descriptor %s" % descriptor)

def raidLevelString(level):
    if level in raid_descriptors.keys():
        return raid_descriptors[level][0]
    else:
        raise MDRaidError("invalid raid level constant %s" % level)

def isRaid(raid, raidlevel):
    """Return whether raidlevel is a valid descriptor of raid"""
    if raid in raid_descriptors:
        return raidlevel in raid_descriptors[raid]
    else:
        raise MDRaidError("invalid raid level %d" % raid)

def get_raid_min_members(raidlevel):
    """Return the minimum number of raid members required for raid level"""
    raid_min_members = {RAID10: 4,
                        RAID6: 4,
                        RAID5: 3,
                        RAID4: 3,
                        RAID1: 2,
                        RAID0: 2}

    for raid, min_members in raid_min_members.items():
        if isRaid(raid, raidlevel):
            return min_members

    raise MDRaidError("invalid raid level %d" % raidlevel)

def get_raid_max_spares(raidlevel, nummembers):
    """Return the maximum number of raid spares for raidlevel."""
    raid_max_spares = {RAID10: lambda: max(0, nummembers - get_raid_min_members(RAID10)),
                       RAID6: lambda: max(0, nummembers - get_raid_min_members(RAID6)),
                       RAID5: lambda: max(0, nummembers - get_raid_min_members(RAID5)),
                       RAID4: lambda: max(0, nummembers - get_raid_min_members(RAID4)),
                       RAID1: lambda: max(0, nummembers - get_raid_min_members(RAID1)),
                       RAID0: lambda: 0}

    for raid, max_spares_func in raid_max_spares.items():
        if isRaid(raid, raidlevel):
            return max_spares_func()

    raise MDRaidError("invalid raid level %d" % raidlevel)

def get_raid_superblock_size(size, version=None):
    """ mdadm has different amounts of space reserved for its use depending
    on the metadata type and size of the array.

    0.9 use 2.0 MB
    1.0 use 2.0 MB
    1.1 or 1.2 use the formula lifted from mdadm/super1.c to calculate it
    based on the array size.
    """
    # mdadm 3.2.4 made a major change in the amount of space used for 1.1 and 1.2
    # in order to reserve space for reshaping. See commit 508a7f16 in the
    # upstream mdadm repository.
    headroom = MD_SUPERBLOCK_SIZE
    if version is None or version in ["default", "1.1", "1.2"]:
        # MDADM: We try to leave 0.1% at the start for reshape
        # MDADM: operations, but limit this to 128Meg (0.1% of 10Gig)
        # MDADM: which is plenty for efficient reshapes
        # NOTE: In the mdadm code this is in 512b sectors. Converted to use MB
        headroom = 128
        while headroom << 10 > size:
            headroom >>= 1
    log.info("Using %sMB superBlockSize" % (headroom))
    return headroom

def get_member_space(size, disks, level=None):
    space = 0   # size of *each* member device

    if isinstance(level, str):
        level = raidLevel(level)

    min_members = get_raid_min_members(level)
    if disks < min_members:
        raise MDRaidError("raid%d requires at least %d disks"
                         % (level, min_members))

    if level == RAID0:
        # you need the sum of the member sizes to equal your desired capacity
        space = size / disks
    elif level == RAID1:
        # you need each member's size to equal your desired capacity
        space = size
    elif level in (RAID4, RAID5):
        # you need the sum of all but one members' sizes to equal your desired
        # capacity
        space = size / (disks - 1)
    elif level == RAID6:
        # you need the sum of all but two members' sizes to equal your desired
        # capacity
        space = size / (disks - 2)
    elif level == RAID10:
        # you need the sum of the member sizes to equal twice your desired
        # capacity
        space = size / (disks / 2.0)

    space += get_raid_superblock_size(size)

    return space * disks

def mdadm(args):
    ret = util.run_program(["mdadm"] + args)
    if ret:
        raise MDRaidError("running mdadm " + " ".join(args) + " failed")

def mdcreate(device, level, disks, spares=0, metadataVer=None, bitmap=False):
    argv = ["--create", device, "--run", "--level=%s" % level]
    raid_devs = len(disks) - spares
    argv.append("--raid-devices=%d" % raid_devs)
    if spares:
        argv.append("--spare-devices=%d" % spares)
    if metadataVer:
        argv.append("--metadata=%s" % metadataVer)
    if bitmap:
        argv.append("--bitmap=internal")
    argv.extend(disks)
    
    try:
        mdadm(argv)
    except MDRaidError as msg:
        raise MDRaidError("mdcreate failed for %s: %s" % (device, msg))

def mddestroy(device):
    args = ["--zero-superblock", device]

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mddestroy failed for %s: %s" % (device, msg))

def mdadd(device):
    args = ["--incremental", "--quiet"]
    args.append(device)

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mdadd failed for %s: %s" % (device, msg))

def mdactivate(device, members=[], super_minor=None, uuid=None):
    if super_minor is None and not uuid:
        raise MDRaidError("mdactivate requires either a uuid or a super-minor")
    
    if uuid:
        identifier = "--uuid=%s" % uuid
    else:
        identifier = ""

    args = ["--assemble", device, identifier, "--run"]
    args += members

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mdactivate failed for %s: %s" % (device, msg))

def mddeactivate(device):
    args = ["--stop", device]

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mddeactivate failed for %s: %s" % (device, msg))

def mdexamine(device):
    _vars = util.capture_output(["mdadm",
                                 "--examine", "--export", device]).split()
    _bvars = util.capture_output(["mdadm",
                                 "--examine", "--brief", device]).split()

    info = {}
    if len(_bvars) > 1 and _bvars[1].startswith("/dev/md"):
        info["DEVICE"] = _bvars[1]
        _bvars = _bvars[2:]

    for var in _vars:
        (name, equals, value) = var.partition("=")
        if not equals:
            continue

        info[name.upper()] = value.strip()

    if "MD_METADATA" not in info:
        for var in _bvars:
            (name, equals, value) = var.partition("=")
            if not equals:
                continue

            if name == "metadata":
                info["MD_METADATA"] = value

    return info

def md_node_from_name(name):
    named_path = "/dev/md/" + name
    try:
        node = os.path.basename(os.readlink(named_path))
    except OSError as e:
        raise MDRaidError("md_node_from_name failed: %s" % e)
    else:
        return node

def name_from_md_node(node):
    md_dir = "/dev/md"
    name = None
    # It's sad, but it's what we've got.
    for link in os.listdir(md_dir):
        full_path = "%s/%s" % (md_dir, link)
        md_name = os.path.basename(os.readlink(full_path))
        log.debug("link: %s -> %s" % (link, os.readlink(full_path)))
        if md_name == node:
            name = link
            break

    if not name:
        raise MDRaidError("name_from_md_node(%s) failed" % node)

    log.debug("returning %s" % name)
    return name
