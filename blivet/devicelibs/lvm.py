#
# lvm.py
# lvm functions
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

import math
from decimal import Decimal
import os

from collections import namedtuple

import logging
log = logging.getLogger("blivet")

from . import raid
from ..size import Size
from .. import util
from .. import arch
from ..errors import LVMError
from ..i18n import _, N_
from ..flags import flags

MAX_LV_SLOTS = 256

# some of lvm's defaults that we have no way to ask it for
LVM_PE_START = Size("1 MiB")
LVM_PE_SIZE = Size("4 MiB")

# thinp constants
LVM_THINP_MIN_METADATA_SIZE = Size("2 MiB")
LVM_THINP_MAX_METADATA_SIZE = Size("16 GiB")
LVM_THINP_MIN_CHUNK_SIZE = Size("64 KiB")
LVM_THINP_MAX_CHUNK_SIZE = Size("1 GiB")

LVM_THINP_DEFAULT_CHUNK_SIZE = Size("64 KiB")

LVM_MIN_CACHE_MD_SIZE = Size("8 MiB")

RAID_levels = raid.RAIDLevels(["raid0", "raid1", "linear"])

ThPoolProfile = namedtuple("ThPoolProfile", ["name", "desc"])
KNOWN_THPOOL_PROFILES = (ThPoolProfile("thin-generic", N_("Generic")),
                         ThPoolProfile("thin-performance", N_("Performance")))

def has_lvm():
    if util.find_program_in_path("lvm"):
        for line in open("/proc/devices").readlines():
            if "device-mapper" in line.split():
                return True

    return False

LVMETAD_SOCKET_PATH = "/run/lvm/lvmetad.socket"

# Start config_args handling code
#
# Theoretically we can handle all that can be handled with the LVM --config
# argument.  For every time we call an lvm_cc (lvm compose config) funciton
# we regenerate the config_args with all global info.
config_args_data = { "filterRejects": [],    # regular expressions to reject.
                     "filterAccepts": [] }   # regexp to accept

def _getConfigArgs(args):
    """lvm command accepts lvm.conf type arguments preceded by --config. """

    # These commands are read-only, so we can run them with read-only locking.
    # (not an exhaustive list, but these are the only ones used here)
    READONLY_COMMANDS = ('lvs', 'pvs', 'vgs')

    cmd = args[0]
    config_args = []

    filter_string = ""
    rejects = config_args_data["filterRejects"]
    for reject in rejects:
        filter_string += ("\"r|/%s$|\"," % reject)

    if filter_string:
        filter_string = "filter=[%s]" % filter_string.strip(",")

    # XXX consider making /tmp/blivet.lvm.XXXXX, writing an lvm.conf there, and
    #     setting LVM_SYSTEM_DIR
    devices_string = 'preferred_names=["^/dev/mapper/", "^/dev/md/", "^/dev/sd"]'
    if filter_string:
        devices_string += " %s" % filter_string

    # devices_string can have (inside the brackets) "dir", "scan",
    # "preferred_names", "filter", "cache_dir", "write_cache_state",
    # "types", "sysfs_scan", "md_component_detection".  see man lvm.conf.
    config_string = " devices { %s } " % (devices_string) # strings can be added
    if cmd in READONLY_COMMANDS:
        config_string += "global {locking_type=4} "
    if not flags.lvm_metadata_backup:
        config_string += "backup {backup=0 archive=0} "
    if config_string:
        config_args = ["--config", config_string]
    return config_args

def lvm_cc_addFilterRejectRegexp(regexp):
    """ Add a regular expression to the --config string."""
    log.debug("lvm filter: adding %s to the reject list", regexp)
    config_args_data["filterRejects"].append(regexp)

def lvm_cc_removeFilterRejectRegexp(regexp):
    """ Remove a regular expression from the --config string."""
    log.debug("lvm filter: removing %s from the reject list", regexp)
    try:
        config_args_data["filterRejects"].remove(regexp)
    except ValueError:
        log.debug("%s wasn't in the reject list", regexp)
        return

def lvm_cc_resetFilter():
    config_args_data["filterRejects"] = []
    config_args_data["filterAccepts"] = []
# End config_args handling code.

def getPossiblePhysicalExtents():
    """ Returns a list of possible values for physical extent of a volume group.

        :returns: list of possible extent sizes (:class:`~.size.Size`)
        :rtype: list
    """

    possiblePE = []
    curpe = Size("1 KiB")
    while curpe <= Size("16 GiB"):
        possiblePE.append(curpe)
        curpe = curpe * 2

    return possiblePE

def getMaxLVSize():
    """ Return the maximum size of a logical volume. """
    if arch.getArch() in ("x86_64", "ppc64", "ppc64le", "alpha", "ia64", "s390"): #64bit architectures
        return Size("8 EiB")
    else:
        return Size("16 TiB")

def clampSize(size, pesize, roundup=None):
    delta = size % pesize
    if not delta:
        return size

    if roundup:
        clamped = size + (pesize - delta)
    else:
        clamped = size - delta

    return clamped

def get_pv_space(size, disks, pesize=LVM_PE_SIZE):
    """ Given specs for an LV, return total PV space required. """
    # XXX default extent size should be something we can ask of lvm
    # TODO: handle striped and mirrored
    # this is adding one extent for the lv's metadata
    # pylint: disable=unused-argument
    if size == 0:
        return size

    space = clampSize(size, pesize, roundup=True) + pesize
    return space

def get_pool_padding(size, pesize=LVM_PE_SIZE, reverse=False):
    """ Return the size of the pad required for a pool with the given specs.

        reverse means the pad is already included in the specified size and we
        should calculate how much of the total is the pad
    """
    if not reverse:
        multiplier = Decimal('0.2')
    else:
        multiplier = Decimal('1.0') / Decimal('6')

    pad = min(clampSize(size * multiplier, pesize, roundup=True),
              clampSize(LVM_THINP_MAX_METADATA_SIZE, pesize, roundup=True))

    return pad

def get_pool_metadata_size(size, chunk_size=LVM_THINP_DEFAULT_CHUNK_SIZE, snapshots=100):
    argv = ["thin_metadata_size", "-n", "-ub",
            "-s%d" % size, "-b%d" % chunk_size, "-m%d" % snapshots]
    (ret, out) = util.run_program_and_capture_output(argv)
    if ret == 0 and out:
        return Size(out)
    else:
        raise LVMError("Failed to get metadata size from thin_metadata_size (ret: %d)" % ret)

def is_valid_thin_pool_metadata_size(size):
    """ Return True if size is a valid thin pool metadata vol size.

        :param size: metadata vol size to validate
        :type size: :class:`~.size.Size`
        :returns: whether the size is valid
        :rtype: bool
    """
    return (LVM_THINP_MIN_METADATA_SIZE <= size <= LVM_THINP_MAX_METADATA_SIZE)

# To support discard, chunk size must be a power of two. Otherwise it must be a
# multiple of 64 KiB.
def is_valid_thin_pool_chunk_size(size, discard=False):
    """ Return True if size is a valid thin pool chunk size.

        :param size: chunk size to validate
        :type size: :class:`~.size.Size`
        :keyword discard: whether discard support is required (default: False)
        :type discard: bool
        :returns: whether the size is valid
        :rtype: bool
    """
    if not LVM_THINP_MIN_CHUNK_SIZE <= size <= LVM_THINP_MAX_CHUNK_SIZE:
        return False

    if discard:
        return (math.log(size, 2) % 1.0 == 0)
    else:
        return (size % LVM_THINP_MIN_CHUNK_SIZE == 0)

def strip_lvm_warnings(buf):
    """ Strip out lvm warning lines

    :param str buf: A string returned from lvm
    :returns: A list of strings with warning lines stripped
    :rtype: list of strings
    """
    return [l for l in buf.splitlines() if l and not l.lstrip().startswith("WARNING:")]

def lvm(args, capture=False, ignore_errors=False):
    """ Runs lvm with specified arguments.

        :param bool capture: if True, return the output of the command.
        :param bool ignore_errors: if True, do not raise LVMError on failure
        :returns: the output of the command or None
        :rtype: str or NoneType
        :raises: LVMError if command fails
    """
    argv = ["lvm"] + args + _getConfigArgs(args)
    (ret, out) = util.run_program_and_capture_output(argv)
    if ret and not ignore_errors:
        raise LVMError("running "+ " ".join(argv) + " failed")
    if capture:
        return out

def pvcreate(device, data_alignment=None):
    args = ["pvcreate"]

    if data_alignment is not None:
        args.extend(["--dataalignment", "%dk" % data_alignment.convertTo(spec="KiB")])
    args.append(device)

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvcreate failed for %s: %s" % (device, msg))

def pvresize(device, size):
    args = ["pvresize",
            "--setphysicalvolumesize", ("%dm" % size.convertTo(spec="mib")),
            device]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvresize failed for %s: %s" % (device, msg))

def pvremove(device):
    args = ["pvremove", "--force", "--force", "--yes", device]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvremove failed for %s: %s" % (device, msg))

def pvscan(device):
    args = ["pvscan", "--cache", device]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvscan failed for %s: %s" % (device, msg))

def pvmove(source, dest=None):
    """ Move physical extents from one PV to another.

        :param str source: pv device path to move extents off of
        :keyword str dest: pv device path to move the extents onto
    """
    args = ["pvmove", source]
    if dest:
        args.append(dest)

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvmove failed for %s->%s: %s" % (source, dest, msg))

def parse_lvm_vars(line):
    info = {}
    for var in line.split():
        (name, equals, value) = var.partition("=")
        if not equals:
            continue

        if "," in value:
            val = value.strip().split(",")
        else:
            val = value.strip()

        info[name] = val

    return info

def pvinfo(device=None):
    """ Return a dict with information about LVM PVs.

        :keyword str device: path to PV device node (optional)
        :returns: dict containing PV path keys and udev info dict values
        :rtype: dict

        If device is None we let LVM report on all known PVs.

        If the PV was created with '--metadacopies 0', lvm will do some
        scanning of devices to determine from their metadata which VG
        this PV belongs to.

        pvs -o pv_name,pv_mda_count,vg_name,vg_uuid --config \
            'devices { scan = "/dev" filter = ["a/loop0/", "r/.*/"] }'
    """
    args = ["pvs",
            "--unit=k", "--nosuffix", "--nameprefixes",
            "--unquoted", "--noheadings",
            "-opv_name,pv_uuid,pe_start,vg_name,vg_uuid,vg_size,vg_free,"
            "vg_extent_size,vg_extent_count,vg_free_count,pv_count"]

    if device:
        args.append(device)

    buf = lvm(args, capture=True, ignore_errors=True)
    pvs = {}
    for line in buf.splitlines():
        info = parse_lvm_vars(line)
        if len(info.keys()) != 11:
            log.warning("ignoring pvs output line: %s", line)
            continue

        pvs[info["LVM2_PV_NAME"]] = info

    return pvs

def vgcreate(vg_name, pv_list, pe_size):
    argv = ["vgcreate"]
    if pe_size:
        argv.extend(["-s", "%sk" % pe_size.convertTo(spec="KiB")])
    argv.append(vg_name)
    argv.extend(pv_list)

    try:
        lvm(argv)
    except LVMError as msg:
        raise LVMError("vgcreate failed for %s: %s" % (vg_name, msg))

def vgremove(vg_name):
    args = ["vgremove", "--force", vg_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgremove failed for %s: %s" % (vg_name, msg))

def vgactivate(vg_name):
    args = ["vgchange", "-a", "y", vg_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgactivate failed for %s: %s" % (vg_name, msg))

def vgdeactivate(vg_name):
    args = ["vgchange", "-a", "n", vg_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgdeactivate failed for %s: %s" % (vg_name, msg))

def vgreduce(vg_name, pv, missing=False):
    """ Remove PVs from a VG.

        :param str pv: PV device path to remove
        :keyword bool missing: whether to remove missing PVs

        When missing is True any specified PV is ignored and vgreduce is
        instead called with the --removemissing option.

        .. note::

            This function does not move extents off of the PV before removing
            it from the VG. You must do that first by calling :func:`.pvmove`.
    """
    args = ["vgreduce"]
    if missing:
        args.extend(["--removemissing", "--force", vg_name])
    else:
        args.extend([vg_name, pv])

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgreduce failed for %s: %s" % (vg_name, msg))

def vgextend(vg_name, pv):
    """ Add a PV to a VG.

        :param str vg_name: the name of the VG
        :param str pv: device path of PV to add
    """
    args = ["vgextend", vg_name, pv]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgextend failed for %s: %s" % (vg_name, msg))

def vginfo(vg_name):
    """ Return a dict with information about an LVM VG.

        :returns: a udev info dict
        :rtype: dict
    """
    args = ["vgs", "--noheadings", "--nosuffix", "--nameprefixes", "--unquoted",
            "--units", "m",
            "-o", "uuid,size,free,extent_size,extent_count,free_count,pv_count",
            vg_name]

    buf = lvm(args, capture=True, ignore_errors=True)
    info = parse_lvm_vars(buf)
    if len(info.keys()) != 7:
        raise LVMError(_("vginfo failed for %s") % vg_name)

    return info

def lvs(vg_name=None):
    """ Return a dict with information about LVM LVs.

        :keyword str vgname: name of VG to list LVs from (optional)
        :returns: a dict with LV name keys and udev info dict values
        :rtype: dict

        If vg_name is None we let LVM report on all known LVs.
    """
    args = ["lvs",
            "-a", "--unit", "k", "--nosuffix", "--nameprefixes",
            "--unquoted", "--noheadings",
            "-ovg_name,lv_name,lv_uuid,lv_size,lv_attr,segtype"]
    if vg_name:
        args.append(vg_name)

    buf = lvm(args, capture=True, ignore_errors=True)
    logvols = {}
    for line in buf.splitlines():
        info = parse_lvm_vars(line)
        if len(info.keys()) != 6:
            log.debug("ignoring lvs output line: %s", line)
            continue

        lv_name = "%s-%s" % (info["LVM2_VG_NAME"], info["LVM2_LV_NAME"])
        logvols[lv_name] = info

    return logvols

def lvorigin(vg_name, lv_name):
    args = ["lvs", "--noheadings", "-o", "origin"] + \
            ["%s/%s" % (vg_name, lv_name)]

    buf = lvm(args, capture=True, ignore_errors=True)
    lines = strip_lvm_warnings(buf)
    try:
        origin = lines[0].strip()
    except IndexError:
        origin = ''

    return origin

def lvcreate(vg_name, lv_name, size, pvs=None):
    pvs = pvs or []

    args = ["lvcreate"] + \
            ["-L", "%dm" % size.convertTo(spec="mib")] + \
            ["-n", lv_name] + \
            ["-y"] + \
            [vg_name] + pvs

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvcreate failed for %s/%s: %s" % (vg_name, lv_name, msg))

def lvremove(vg_name, lv_name, force=False):
    args = ["lvremove"]
    if force:
        args.extend(["--force", "--yes"])

    args += ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvremove failed for %s: %s" % (lv_name, msg))

def lvresize(vg_name, lv_name, size):
    args = ["lvresize"] + \
            ["--force", "-L", "%dm" % size.convertTo(spec="mib")] + \
            ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvresize failed for %s: %s" % (lv_name, msg))

def lvactivate(vg_name, lv_name, ignore_skip=False):
    # see if lvchange accepts paths of the form 'mapper/$vg-$lv'
    args = ["lvchange", "-a", "y"]
    if ignore_skip:
        args.append("-K")

    args += ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvactivate failed for %s: %s" % (lv_name, msg))

def lvdeactivate(vg_name, lv_name):
    args = ["lvchange", "-a", "n"] + \
            ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvdeactivate failed for %s: %s" % (lv_name, msg))

def lvsnapshotmerge(vg_name, lv_name):
    """ Merge(/rollback/revert) a snapshot volume into its origin.

        .. note::

            This is an asynchronous procedure. See lvconvert(8) for details of
            how merge is handled by lvm.

    """
    args = ["lvconvert", "--merge", "%s/%s" % (vg_name, lv_name), lv_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvsnapshotmerge failed for %s: %s" % (lv_name, msg))

def lvsnapshotcreate(vg_name, snap_name, size, origin_name):
    """
        :param str vg_name: the volume group name
        :param str snap_name: the name of the new snapshot
        :param :class:`~.size.Size` size: the snapshot's size
        :param str origin_name: the name of the origin logical volume
    """
    args = ["lvcreate", "-s", "-L", "%dm" % size.convertTo(spec="MiB"),
            "-n", snap_name, "%s/%s" % (vg_name, origin_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvsnapshotcreate failed for %s/%s: %s" % (vg_name, snap_name, msg))

def thinpoolcreate(vg_name, lv_name, size, metadatasize=None, chunksize=None, profile=None):
    args = ["lvcreate", "--thinpool", "%s/%s" % (vg_name, lv_name),
            "--size", "%dm" % size.convertTo(spec="mib")]

    if metadatasize:
        # default unit is MiB
        args += ["--poolmetadatasize", "%d" % metadatasize.convertTo(spec="mib")]

    if chunksize:
        # default unit is KiB
        args += ["--chunksize", "%d" % chunksize.convertTo(spec="kib")]

    if profile:
        args += ["--profile=%s" % profile]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvcreate failed for %s/%s: %s" % (vg_name, lv_name, msg))

def thinlvcreate(vg_name, pool_name, lv_name, size):
    args = ["lvcreate", "--thinpool", "%s/%s" % (vg_name, pool_name),
            "--virtualsize", "%dm" % size.convertTo(spec="MiB"),
            "-n", lv_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvcreate failed for %s/%s: %s" % (vg_name, lv_name, msg))

def thinsnapshotcreate(vg_name, snap_name, origin_name, pool_name=None):
    """
        :param str vg_name: the volume group name
        :param str snap_name: the name of the new snapshot
        :param str origin_name: the name of the origin logical volume
        :keyword str pool_name: the name of the pool to create the snapshot in
    """
    args = ["lvcreate", "-s", "-n", snap_name, "%s/%s" % (vg_name, origin_name)]
    if pool_name:
        args.extend(["--thinpool", pool_name])
    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvcreate (snapshot) failed for %s/%s: %s" % (vg_name, snap_name, msg))

def thinlvpoolname(vg_name, lv_name):
    args = ["lvs", "--noheadings", "-o", "pool_lv"] + \
            ["%s/%s" % (vg_name, lv_name)]

    buf = lvm(args, capture=True, ignore_errors=True)
    lines = strip_lvm_warnings(buf)
    try:
        pool = lines[0].strip()
    except IndexError:
        pool = ''

    return pool

def cachepoolname(vg_name, lv_name):
    """Get the name of the cache pool attached to the vg_name/lv_name LV or "" """
    # exactly the same as thin pool name
    return thinlvpoolname(vg_name, lv_name)

def cachepool_default_md_size(cache_size):
    """Get the default metadata size for the cache (pool) of size cache_size
    :param cache_size: size of the cache (pool)
    :type cache_size: :class:`~.size.Size`

    """
    # according to lvmcache(7)
    return max(cache_size / 1000, LVM_MIN_CACHE_MD_SIZE)

def cachepool_create(vg_name, lv_name, data_size, md_size, mode, pvs):
    """Create a cache pool LV with the given parameters
    :param str vg_name: name of the VG to create the pool in
    :param str lv_name: name of the cache pool LV
    :param data_size: size of the cache pool's data part
    :type data_size: :class:`~.size.Size`
    :param md_size: size of the cache pool's metadata part
    :type md_size: :class:`~.size.Size`
    :param str mode: mode for the cache pool
    :param pvs: names of the PVs to allocate the cache pool on
    :type pvs: list of str

    """

    args = ["lvcreate", "--type", "cache-pool", "-L", "%dm" % data_size.convertTo(spec="MiB"),
            "--poolmetadatasize", "%dm" % md_size.convertTo(spec="MiB"),
            "-n", lv_name]
    if mode:
        args.extend(["--cachemode", mode])
    args.append(vg_name)
    args.extend(pvs)

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("Failed to create cache pool '%s-%s': %s" % (vg_name, lv_name, msg))

def lvcreate_cached(vg_name, lv_name, lv_size, cache_data_size, cache_md_size,
                    mode, slow_pvs, fast_pvs):
    """Create a cached LV with the given parameters
    :param str vg_name: name of the VG to create the LV in
    :param str lv_name: name of the LV
    :param lv_size: size of the LV
    :type lv_size: :class:`~.size.Size`
    :param cache_data_size: size of the cache (pool)'s data part
    :type cache_data_size: :class:`~.size.Size`
    :param cache_md_size: size of the cache (pool)'s metadata part
    :type cache_md_size: :class:`~.size.Size`
    :param str mode: mode for the cache pool
    :param slow_pvs: names of the PVs to allocate the LV on
    :type slow_pvs: list of str
    :param fast_pvs: names of the PVs to allocate the cache (pool) on
    :type fast_pvs: list of str

    """

    # create the cache pool first (so that it gets allocated on the fast PVs)
    cachepool_create(vg_name, lv_name+"_cache", cache_data_size, cache_md_size, mode, fast_pvs)

    # create the LV itself on all PVs, preferring the slow ones
    lvcreate(vg_name, lv_name, lv_size, slow_pvs + fast_pvs)

    vg_lv_name = lambda lv_name: "%s/%s" % (vg_name, lv_name)

    # attach the cache pool to the LV
    args = ["lvconvert", "--type", "cache", "--cachepool", vg_lv_name(lv_name+"_cache"), vg_lv_name(lv_name)]
    try:
        lvm(args)
    except LVMError as msg:
        msg = "Failed to attach cache pool '%s' to the LV '%s': %s" % (vg_lv_name(lv_name+"_cache"),
                                                                       vg_lv_name(lv_name),
                                                                       msg)
        raise LVMError(msg)

def lvmetad_socket_exists():
    return os.path.exists(LVMETAD_SOCKET_PATH)
