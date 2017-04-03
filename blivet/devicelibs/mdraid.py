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
import re
import string

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

def mdadm(args, capture=False):
    """ Run mdadm with specified arguments.

        :param bool capture: if True, return the output of the command
        :returns: the output of the command or None
        :rtype: str or NoneType
        :raises: MDRaidError if command fails
    """
    argv = ["mdadm"] + args
    (ret, out) = util.run_program_and_capture_output(argv)
    if ret:
        raise MDRaidError(ret)
    if capture:
        return out

def mdcreate(device, level, disks, spares=0, metadataVer=None, bitmap=False, chunkSize=MD_CHUNK_SIZE):
    """ Create an mdarray from a list of devices.

        :param str device: the path for the array
        :param level: the level of the array
        :type level: :class:`~.devicelibs.raid.RAIDLevel` or string
        :param disks: the members of the array
        :type disks: list of str
        :param int spares: the number of spares in the array
        :param str metadataVer: one of the mdadm metadata versions
        :param bool bitmap: whether to create an internal bitmap on the device
        :param chunkSize: chunk size for the array
        :type chunkSize: :class:`~.size.Size`

        Note that if the level is specified as a string, rather than by means
        of a RAIDLevel object, it is not checked for validity. It is the
        responsibility of the invoking method to verify that mdadm recognizes
        the string.
    """
    argv = ["--create", device, "--run", "--level=%s" % level]
    raid_devs = len(disks) - spares
    argv.append("--raid-devices=%d" % raid_devs)
    if chunkSize:
        argv.append("--chunk=%d" % int(chunkSize.convertTo("KiB")))
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

def mdnominate(device):
    """ Attempt to add a device to the array to which it belongs.

        Belonging is determined by mdadm's rules.

        May start the array once a sufficient number of devices are added
        to the array.

        :param str device: path to the device to add
        :rtype: NoneType
        :raises: MDRaidError

        .. seealso:: mdadd
    """
    args = ['--incremental', '--quiet', device]

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mdnominate failed for %s: %s" % (device, msg))

def mdadd(array, device, raid_devices=None):
    """ Add a device to an array.

        :param str array: path to the array to add the device to
        :param str device: path to the device to add to the array
        :keyword int raid_devices: the number of active member devices
        :rtype: NoneType
        :raises: MDRaidError

        The raid_devices parameter is used when adding devices to a raid
        array that has no actual redundancy. In this case it is necessary
        to explicitly grow the array all at once rather than manage it in
        the sense of adding spares.

        Whether the new device will be added as a spare or an active member is
        decided by mdadm.

        .. seealso:: mdnominate
    """
    if raid_devices is None:
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

def mdactivate(device, members=None, array_uuid=None):
    """Assemble devices given by members into a single device.

       Use array_uuid to identify the devices in members to include in
       the assembled array.

       :param str device: the device to be assembled
       :param members: the component devices to be considered for inclusion
       :type members: list of str or NoneType
       :param array_uuid: the UUID of the array
       :type array_uuid: str or NoneType

       :raises: :class:`~.errors.MDRaidError` if no array_uuid specified
       or assembly failed
    """
    members = members or []

    if not array_uuid:
        raise MDRaidError("mdactivate requires a uuid")

    identifier = "--uuid=%s" % array_uuid

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

def mdrun(device):
    """Start a possibly degraded array.

       :param str device: the device to be started

       :raises :class:`~.errors.MDRaidError`: on failure
    """
    args = ["--run", device]

    try:
        mdadm(args)
    except MDRaidError as msg:
        raise MDRaidError("mdrun failed for %s: %s" % (device, msg))

def process_UUIDS(info, UUID_keys):
    """ Extract and convert expected UUIDs to canonical form.
        Reassign canonicalized UUIDs to corresponding keys.

        :param dict info: a dictionary of key/value pairs
        :param tuple UUID_keys: a list of keys known to be UUIDs
    """
    for k, v in ((k, info[k]) for k in UUID_keys if k in info):
        try:
            # extract mdadm UUID, e.g., '3386ff85:f5012621:4a435f06:1eb47236'
            the_uuid = re.match(r"(([a-f0-9]){8}:){3}([a-f0-9]){8}", v)

            info[k] = util.canonicalize_UUID(the_uuid.group())
        except (ValueError, AttributeError) as e:
            # the unlikely event that mdadm's UUIDs change their format
            log.warning('uuid value %s could not be canonicalized: %s', v, e)
            info[k] = v # record the value, since mdadm provided something

def mdexamine(device):
    """ Run mdadm --examine to obtain information about an array member.

        :param str device: path of the member device
        :rtype: a dict of strings
        :returns: a dict containing labels and values extracted from output
    """
    try:
        _vars = mdadm(["--examine", "--export", device], capture=True).split()
        _bvars = mdadm(["--examine", "--brief", device], capture=True).split()
    except MDRaidError as e:
        raise MDRaidError("mdexamine failed for %s: %s" % (device, e))

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
                break

    process_UUIDS(info, ('MD_UUID', 'MD_DEV_UUID'))

    return info

def mddetail(device):
    """Run mdadm --detail in order to read information about an array.

       Note: The --export flag is not used. According to the man pages
       the export flag just formats the output as key=value pairs for
       easy import, but in the case of --detail it also omits the majority
       of the information, including information of real use like the
       number of spares in the array.

       :param str device: path of the array device
       :rtype: a dict of strings
       :returns: a dict containing labels and values extracted from output
    """
    try:
        lines = mdadm(["--detail", device], capture=True).split("\n")
    except MDRaidError as e:
        raise MDRaidError("mddetail failed for %s: %s" % (device, e))

    info = {}
    for (name, colon, value) in (line.strip().partition(" : ") for line in lines):
        value = value.strip()
        name = name.strip().upper()
        if colon and value and name:
            info[name] = value

    process_UUIDS(info, ('UUID',))

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

def mduuid_from_canonical(a_uuid):
    """ Change a canonicalized uuid to mdadm's preferred format.

        :param str a_uuid: a string representing a UUID.

        :returns: a UUID in mdadm's preferred format
        :rtype: str

        :raises MDRaidError: if it can not do the conversion

        mdadm's UUIDs are actual 128 bit uuids, but it formats them strangely.
        This converts a uuid from canonical form to mdadm's form.
        Example:
            mdadm UUID: '3386ff85:f5012621:4a435f06:1eb47236'
        canonical UUID: '3386ff85-f501-2621-4a43-5f061eb47236'
    """
    NUM_DIGITS = 32
    a_uuid = a_uuid.replace('-', '')

    if len(a_uuid) != NUM_DIGITS:
        raise MDRaidError("Missing digits in stripped UUID %s." % a_uuid)

    if any(c not in string.hexdigits for c in a_uuid):
        raise MDRaidError("Non-hex digits in stripped UUID %s." % a_uuid)

    CHUNK_LEN = 8
    return ":".join(a_uuid[n:n+CHUNK_LEN] for n in range(0, NUM_DIGITS, CHUNK_LEN))
