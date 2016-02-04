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

import os
import re

from collections import namedtuple
import itertools

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")

from . import raid
from ..size import Size
from ..i18n import N_
from ..flags import flags
from ..tasks import availability

# some of lvm's defaults that we have no way to ask it for
LVM_PE_START = Size("1 MiB")
LVM_PE_SIZE = Size("4 MiB")

# thinp constants
LVM_THINP_MIN_METADATA_SIZE = Size("2 MiB")
LVM_THINP_MAX_METADATA_SIZE = Size("16 GiB")
LVM_THINP_MIN_CHUNK_SIZE = Size("64 KiB")
LVM_THINP_MAX_CHUNK_SIZE = Size("1 GiB")

raid_levels = raid.RAIDLevels(["linear", "striped", "raid1", "raid4", "raid5", "raid6", "raid10"])
raid_seg_types = list(itertools.chain.from_iterable([level.names for level in raid_levels if level.name != "linear"]))

ThPoolProfile = namedtuple("ThPoolProfile", ["name", "desc"])
KNOWN_THPOOL_PROFILES = (ThPoolProfile("thin-generic", N_("Generic")),
                         ThPoolProfile("thin-performance", N_("Performance")))

EXTERNAL_DEPENDENCIES = [availability.BLOCKDEV_LVM_PLUGIN]

LVMETAD_SOCKET_PATH = "/run/lvm/lvmetad.socket"

# Start config_args handling code
#
# Theoretically we can handle all that can be handled with the LVM --config
# argument.  For every time we call an lvm_cc (lvm compose config) funciton
# we regenerate the config_args with all global info.
config_args_data = {"filterRejects": [],    # regular expressions to reject.
                    "filterAccepts": []}   # regexp to accept


def _set_global_config():
    """lvm command accepts lvm.conf type arguments preceded by --config. """

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
    config_string = " devices { %s } " % (devices_string)  # strings can be added
    if not flags.lvm_metadata_backup:
        config_string += "backup {backup=0 archive=0} "
    if flags.debug:
        config_string += "log {level=7 file=/tmp/lvm.log}"

    blockdev.lvm.set_global_config(config_string)


def needs_config_refresh(fn):
    if not availability.BLOCKDEV_LVM_PLUGIN.available:
        return lambda *args, **kwargs: None

    def fn_with_refresh(*args, **kwargs):
        ret = fn(*args, **kwargs)
        _set_global_config()
        return ret

    return fn_with_refresh


@needs_config_refresh
def lvm_cc_addFilterRejectRegexp(regexp):
    """ Add a regular expression to the --config string."""
    log.debug("lvm filter: adding %s to the reject list", regexp)
    config_args_data["filterRejects"].append(regexp)


@needs_config_refresh
def lvm_cc_removeFilterRejectRegexp(regexp):
    """ Remove a regular expression from the --config string."""
    log.debug("lvm filter: removing %s from the reject list", regexp)
    try:
        config_args_data["filterRejects"].remove(regexp)
    except ValueError:
        log.debug("%s wasn't in the reject list", regexp)
        return


@needs_config_refresh
def lvm_cc_resetFilter():
    config_args_data["filterRejects"] = []
    config_args_data["filterAccepts"] = []


def determine_parent_lv(vg_name, internal_lv, lvs):
    """Try to determine which of the lvs is the parent of the internal_lv

    :param str vg_name: name of the VG the internal_lv and lvs belong to
    :type internal_lv: :class:`~.devices.lvm.LMVInternalLogicalVolumeDevice`
    :type lvs: :class:`~.devices.lvm.LMVLogicalVolumeDevice`

    """
    # try name matching first (fast, cheap, often works)
    for lv in lvs:
        if internal_lv.lvname == lv.lvname:
            # skip the internal_lv itself
            continue

        # check if the lv's name is the name of the internal LV without the suffix
        # e.g. 'pool' and 'pool_tmeta'
        if re.match(lv.lvname + internal_lv.name_suffix + "$", internal_lv.lvname):
            return lv

    # now try checking relations between LVs
    for lv in lvs:
        # cache pools are internal LVs of cached LVs
        try:
            pool_name = blockdev.lvm.cache_pool_name(vg_name, lv.lvname)
        except blockdev.LVMError:
            # cannot determine, just go on
            pass
        else:
            if pool_name == internal_lv.lvname:
                return lv

        # pools have internal data and metadata LVs
        try:
            data_lv_name = blockdev.lvm.data_lv_name(vg_name, lv.lvname)
        except blockdev.LVMError:
            # cannot determine, just go on
            pass
        else:
            if data_lv_name == internal_lv.lvname:
                return lv
        try:
            metadata_lv_name = blockdev.lvm.metadata_lv_name(vg_name, lv.lvname)
        except blockdev.LVMError:
            # cannot determine, just go on
            pass
        else:
            if metadata_lv_name == internal_lv.lvname:
                return lv

    return None


def lvmetad_socket_exists():
    return os.path.exists(LVMETAD_SOCKET_PATH)
