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
import os
import re

from collections import namedtuple
import itertools

import gi
gi.require_version("BlockDev", "3.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")

from . import raid
from ..size import Size
from ..i18n import N_
from ..flags import flags
from ..static_data import lvs_info
from ..tasks import availability
from ..util import run_program

from contextlib import contextmanager

# some of lvm's defaults that we have no way to ask it for
LVM_PE_START = Size("1 MiB")
LVM_PE_SIZE = Size("4 MiB")

# thinp constants
LVM_THINP_MIN_METADATA_SIZE = Size("2 MiB")
LVM_THINP_MAX_METADATA_SIZE = Size("16 GiB")
LVM_THINP_MIN_CHUNK_SIZE = Size("64 KiB")
LVM_THINP_MAX_CHUNK_SIZE = Size("1 GiB")
LVM_THINP_ADDRESSABLE_CHUNK_SIZE = Size("17455015526400 B")  # 15.88 TiB

# cache constants
LVM_CACHE_MIN_METADATA_SIZE = Size("8 MiB")
LVM_CACHE_MAX_METADATA_SIZE = Size("16 GiB")
LVM_CACHE_DEFAULT_MODE = blockdev.LVMCacheMode.WRITETHROUGH

raid_levels = raid.RAIDLevels(["linear", "striped", "raid0", "raid1", "raid4", "raid5", "raid6", "raid10"])
raid_seg_types = list(itertools.chain.from_iterable([level.names for level in raid_levels if level.name != "linear"]))

ThPoolProfile = namedtuple("ThPoolProfile", ["name", "desc"])
KNOWN_THPOOL_PROFILES = (ThPoolProfile("thin-generic", N_("Generic")),
                         ThPoolProfile("thin-performance", N_("Performance")))

EXTERNAL_DEPENDENCIES = [availability.BLOCKDEV_LVM_PLUGIN]

LVMETAD_SOCKET_PATH = "/run/lvm/lvmetad.socket"

safe_name_characters = "0-9a-zA-Z._-"

if hasattr(blockdev.LVMTech, "DEVICES"):
    try:
        blockdev.lvm.is_tech_avail(blockdev.LVMTech.DEVICES, 0)  # pylint: disable=no-member
    except blockdev.LVMError:
        HAVE_LVMDEVICES = False
    else:
        HAVE_LVMDEVICES = True
else:
    HAVE_LVMDEVICES = False


LVM_DEVICES_FILE = "/etc/lvm/devices/system.devices"

# list of devices that LVM is allowed to use
# with LVM >= 2.0.13 we'll use this for the --devices option and when creating
# the /etc/lvm/devices/system.devices file
# with older versions of LVM we will use this for the --config based filtering
_lvm_devices = set()


def _set_global_config():
    """lvm command accepts lvm.conf type arguments preceded by --config. """

    device_string = ""

    if not HAVE_LVMDEVICES:
        # now explicitly "accept" all LVM devices
        for device in _lvm_devices:
            device_string += "\"a|%s$|\"," % device

        # now add all devices to the "reject" filter
        device_string += "\"r|.*|\""

        filter_string = "filter=[%s]" % device_string

        config_string = " devices { %s } " % filter_string
    else:
        config_string = ""

    if not flags.lvm_metadata_backup:
        config_string += "backup {backup=0 archive=0} "
    if flags.debug:
        config_string += "log {level=7 file=/tmp/lvm.log syslog=0}"

    blockdev.lvm.set_global_config(config_string)


def _set_lvm_devices():
    if not HAVE_LVMDEVICES:
        return

    blockdev.lvm.set_devices_filter(list(_lvm_devices))


def needs_config_refresh(fn):
    if not availability.BLOCKDEV_LVM_PLUGIN.available:
        return lambda *args, **kwargs: None

    def fn_with_refresh(*args, **kwargs):
        ret = fn(*args, **kwargs)
        _set_global_config()
        _set_lvm_devices()
        return ret

    return fn_with_refresh


@needs_config_refresh
def lvm_devices_add(path):
    """ Add a device (PV) to the list of devices LVM is allowed to use """
    log.debug("lvm filter: device %s added to the list of allowed devices", path)
    _lvm_devices.add(path)


@needs_config_refresh
def lvm_devices_remove(path):
    """ Remove a device (PV) to the list of devices LVM is allowed to use """
    log.debug("lvm filter: device %s removed from the list of allowed devices", path)
    try:
        _lvm_devices.remove(path)
    except KeyError:
        log.debug("%s wasn't in the devices list", path)
        return


@needs_config_refresh
def lvm_devices_reset():
    log.debug("lvm filter: clearing the lvm devices list")
    _lvm_devices.clear()


def lvm_devices_copy():
    return _lvm_devices.copy()


@needs_config_refresh
def lvm_devices_restore(devices):
    log.debug("lvm filter: restoring the lvm devices list to %s", ", ".join(list(devices)))
    _lvm_devices = devices


@contextmanager
def empty_lvm_devices():
    devices = lvm_devices_copy()
    lvm_devices_reset()

    yield

    lvm_devices_restore(devices)


def determine_parent_lv(internal_lv, lvs, lv_info):
    """Try to determine which of the lvs is the parent of the internal_lv

    :param internal_lv: the internal LV to determine parent LV from
    :type internal_lv: :class:`~.devices.lvm.LMVInternalLogicalVolumeDevice`
    :param lvs: LVs searched for a potential parent LV
    :type lvs: :class:`~.devices.lvm.LMVLogicalVolumeDevice`
    :param lv_info: all available information about LVs
    :type lv_info: dict

    """
    for lv in lvs:
        # parent LVs has to be part of the same VG
        if lv.vg.name != internal_lv.vg.name:
            continue

        # skip the internal_lv itself
        if internal_lv.lvname == lv.lvname:
            continue

        info = lv_info.get(lv.name)
        if info is None:
            # internal LVs look like "vg_name-[int_lv_name]" in lv_info so let's
            # try that too
            info = lv_info.get("%s-%s" % (lv.vg.name, lv.display_lvname))
        if info:
            # cache pools are internal LVs of cached LVs
            pool_name = info.pool_lv
            if pool_name and pool_name.strip("[]") == internal_lv.lvname:
                return lv

            # pools have internal data and metadata LVs
            data_lv_name = info.data_lv
            if data_lv_name and data_lv_name.strip("[]") == internal_lv.lvname:
                return lv
            metadata_lv_name = info.metadata_lv
            if metadata_lv_name and metadata_lv_name.strip("[]") == internal_lv.lvname:
                return lv

        # try name matching
        # check if the lv's name is the name of the internal LV without the suffix
        # e.g. 'pool' and 'pool_tmeta'
        if re.match(lv.lvname + internal_lv.name_suffix + "$", internal_lv.lvname):
            return lv

    return None


def lvmetad_socket_exists():
    return os.path.exists(LVMETAD_SOCKET_PATH)


def ensure_lv_is_writable(vg_name, lv_name):
    lv_info = lvs_info.cache.get("%s-%s" % (vg_name, lv_name))
    if lv_info is None:
        return

    if lv_info.attr[1] == 'w':
        return

    try:
        rc = run_program(['lvchange', '-prw', "%s/%s" % (vg_name, lv_name)])
    except OSError:
        rc = -1

    return rc == 0


def is_lvm_name_valid(name):
    # No . or ..
    if name == '.' or name == '..':
        return False

    # Check that all characters are in the allowed set and that the name
    # does not start with a -
    if not re.match('^[a-zA-Z0-9+_.][a-zA-Z0-9+_.-]*$', name):
        return False

    # According to the LVM developers, vgname + lvname is limited to 126 characters
    # minus the number of hyphens, and possibly minus up to another 8 characters
    # in some unspecified set of situations. Instead of figuring all of that out,
    # no one gets a vg or lv name longer than, let's say, 55.
    if len(name) > 55:
        return False

    return True


def recommend_thpool_chunk_size(thpool_size):
    # calculation of the recommended chunk size by LVM is so complicated that we
    # can't really replicate it, but we know that 64 KiB chunk size gives us
    # upper limit of ~15.88 TiB so we will just add 64 KiB to the chunk size
    # for every ~15.88 TiB of thinpool data size
    return min(math.ceil(thpool_size / LVM_THINP_ADDRESSABLE_CHUNK_SIZE) * LVM_THINP_MIN_CHUNK_SIZE,
               LVM_THINP_MAX_CHUNK_SIZE)


def is_valid_cache_md_size(md_size):
    return md_size >= LVM_CACHE_MIN_METADATA_SIZE and md_size <= LVM_CACHE_MAX_METADATA_SIZE
