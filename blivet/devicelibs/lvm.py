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

from collections import namedtuple

import logging
log = logging.getLogger("blivet")

from . import raid
from ..size import Size
from ..i18n import N_
from ..flags import flags

# some of lvm's defaults that we have no way to ask it for
LVM_PE_START = Size("1 MiB")
LVM_PE_SIZE = Size("4 MiB")

# thinp constants
LVM_THINP_MIN_METADATA_SIZE = Size("2 MiB")
LVM_THINP_MAX_METADATA_SIZE = Size("16 GiB")
LVM_THINP_MIN_CHUNK_SIZE = Size("64 KiB")
LVM_THINP_MAX_CHUNK_SIZE = Size("1 GiB")

RAID_levels = raid.RAIDLevels(["raid0", "raid1", "linear"])

ThPoolProfile = namedtuple("ThPoolProfile", ["name", "desc"])
KNOWN_THPOOL_PROFILES = (ThPoolProfile("thin-generic", N_("Generic")),
                         ThPoolProfile("thin-performance", N_("Performance")))

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
