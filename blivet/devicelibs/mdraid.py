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

from ..errors import *
from . import raid

import logging
log = logging.getLogger("blivet")

# these defaults were determined empirically
MD_SUPERBLOCK_SIZE = 2.0    # MB
MD_CHUNK_SIZE = 0.5         # MB

class MDRaidLevels(raid.RAIDLevels):
    @classmethod
    def isRaidLevel(cls, level):
        """Every mdraid level must define min_members."""
        try:
            min_members = level.min_members
            return super(MDRaidLevels, cls).isRaidLevel(level) and min_members > 0
        except AttributeError:
            return False

_RAID_levels = MDRaidLevels()

# raidlevels constants
RAID10 = _RAID_levels.raidLevel(10).number
RAID6 = _RAID_levels.raidLevel(6).number
RAID5 = _RAID_levels.raidLevel(5).number
RAID4 = _RAID_levels.raidLevel(4).number
RAID1 = _RAID_levels.raidLevel(1).number
RAID0 = _RAID_levels.raidLevel(0).number

raid_levels = [ RAID0, RAID1, RAID4, RAID5, RAID6, RAID10 ]

class Container(object):
    name = "container"
    names = [name]
    nick = None
    min_members = 1
    def get_recommended_stride(self, member_devices):
        return None
    def get_size(self, member_count, smallest_member_size, chunk_size):
        raise MDRaidError("get_size is not defined for level container.")
    def get_raw_array_size(self, member_count, smallest_member_size):
        raise MDRaidError("get_raw_array_size is not defined for level container.")
    def __str__(self):
        return self.name

Container = Container()
_RAID_levels.addRaidLevel(Container)

def getRaidLevel(descriptor):
    """Return an object for this raid level descriptor.
       Raises an MDRaidError if the descriptor is not valid.
    """
    try:
        return _RAID_levels.raidLevel(descriptor)
    except RaidError as e:
        raise MDRaidError(e.message)

def raidLevel(descriptor):
    """Return an integer code corresponding to this raid level descriptor.
       Raises an MDRaidError if the descriptor is not valid or does not
       have a corresponding numeric code.
    """
    try:
        return _RAID_levels.raidLevel(descriptor).number
    except RaidError as e:
        raise MDRaidError(e.message)
    except ValueError:
        raise MDRaidError(e.message)

def raidLevelString(descriptor, use_nick=False):
    """Returns the canonical name for the descriptor. Raises an
       MDRaidError if there is no corresponding level for the descriptor.

       Return the nickname if use_nick is True.
    """
    try:
        return _RAID_levels.raidLevelString(descriptor, use_nick)
    except RaidError as e:
        raise MDRaidError(e.message)

def get_raid_min_members(descriptor):
    """Return the minimum number of raid members required for this raid
       level descriptor. Raises an MDRaidError if the descriptor is
       invalid.
    """
    try:
        return _RAID_levels.raidLevel(descriptor).min_members
    except RaidError as e:
        raise MDRaidError(e.message)

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
    """Return the total mB required to store size data.
       The steps are:
         * Find the size required for each member
         * Add to that the superblock size
         * multiply that by the number of disks to get the required total size.
       :param size: amount of data
       :type size: natural number

       :param disks: number of disks
       :type disks: natural number

       Raises and MDRaidError if there is no level correspondign to level
       or if the number of disks is less than the minimum number required
       for the raid level.
    """
    try:
        space = _RAID_levels.raidLevel(level).get_base_member_size(size, disks) + \
           get_raid_superblock_size(size)
    except RaidError as e:
        raise MDRaidError(e.message)
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
    if os.path.isdir(md_dir):
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
