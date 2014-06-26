#
# mdraid.py
# mdraid functions
#
# Copyright (C) 2009-2014  Red Hat, Inc.  All rights reserved.
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
from ..errors import MDRaidError
from ..size import Size
from . import raid

import logging
log = logging.getLogger("blivet")

# these defaults were determined empirically
MD_SUPERBLOCK_SIZE = Size("2 MiB")
MD_CHUNK_SIZE = Size("512 KiB")

class MDRaidLevels(raid.RAIDLevels):
    @classmethod
    def isRaidLevel(cls, level):
        return super(MDRaidLevels, cls).isRaidLevel(level) and \
           hasattr(level, 'get_max_spares') and \
           hasattr(level, 'get_space') and \
           hasattr(level, 'get_recommended_stride') and \
           hasattr(level, 'get_size')

RAID_levels = MDRaidLevels(["raid0", "raid1", "raid4", "raid5", "raid6", "raid10", "container", "linear"])

def get_raid_superblock_size(size, version=None):
    """ mdadm has different amounts of space reserved for its use depending
    on the metadata type and size of the array.

    :param size: size of the array
    :type size: :class:`~.size.Size`
    :param version: metadata version
    :type version: str

    0.9 use 2.0 MiB
    1.0 use 2.0 MiB
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
        # NOTE: In the mdadm code this is in 512b sectors. Converted to use MiB
        headroom = int(Size("128 MiB"))
        while headroom << 10 > size and headroom > Size("1 MiB"):
            headroom >>= 1

        headroom = Size(headroom)

    log.info("Using %s superBlockSize", headroom)
    return headroom

def mdadm(args):
    ret = util.run_program(["mdadm"] + args)
    if ret:
        raise MDRaidError("running mdadm " + " ".join(args) + " failed")

def mdcreate(device, level, disks, spares=0, metadataVer=None, bitmap=False):
    """ Create an mdarray from a list of devices.

        :param str device: the path for the array
        :param level: the level of the array
        :type level: :class:`~.devicelibs.raid.RAIDLevel` or string
        :param disks: the members of the array
        :type disks: list of str
        :param int spares: the number of spares in the array
        :param str metadataVer: one of the mdadm metadata versions
        :param bool bitmap: whether to create an internal bitmap on the device

        Note that if the level is specified as a string, rather than by means
        of a RAIDLevel object, it is not checked for validity. It is the
        responsibility of the invoking method to verify that mdadm recognizes
        the string.
    """
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

def mdadd(array, device, incremental=False, raid_devices=None):
    """ Add a device to an array.

        :param str array: path to the array to add the device to
        :param str device: path to the device to add to the array
        :keyword bool incremental: add the device incrementally (see note below)
        :keyword int raid_devices: the number of active member devices

        The raid_devices parameter is used when adding devices to a raid
        array that has no actual redundancy. In this case it is necessary
        to explicitly grow the array all at once rather than manage it in
        the sense of adding spares.

        Whether the new device will be added as a spare or an active member is
        decided by mdadm.

        .. note::

            Incremental add is used during block device discovery and is a
            different operation than changing the member set of an array.

    """
    if incremental:
        args = ["--incremental", "--quiet"]
    elif raid_devices is None:
        args = [array, "--add"]
    else:
        args = ["--grow", array, "--raid-devices", str(raid_devices), "--add"]

    args.append(device)

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mdadd failed for %s: %s" % (device, msg))

def mdremove(array, device, fail=False):
    """ Remove a device from an array.

        :param str array: path to the array to remove the device from
        :param str device: path to the device to remove
        :keyword bool fail: mark the device as failed before removing it

        .. note::

            Only spares and failed devices can be removed. To remove an active
            member device you must specify fail=True.
    """
    args = [array]
    if fail:
        args.extend(["--fail", device])

    args.extend(["--remove", device])

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mdremove failed for %s: %s" % (device, msg))

def mdactivate(device, members=None, uuid=None):
    """Assemble devices given by members into a single device.

       Use uuid value to identify devices in members to include in device.

       :param device: the device to be assembled
       :param type: str
       :param members: the component devices
       :param type: list of str or NoneType
    """
    members = members or []

    if not uuid:
        raise MDRaidError("mdactivate requires a uuid")

    identifier = "--uuid=%s" % uuid

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
            log.debug("link: %s -> %s", link, os.readlink(full_path))
            if md_name == node:
                name = link
                break

    if not name:
        raise MDRaidError("name_from_md_node(%s) failed" % node)

    log.debug("returning %s", name)
    return name
