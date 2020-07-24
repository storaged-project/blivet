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

from . import raid
from ..size import Size
from ..tasks import availability

import logging
log = logging.getLogger("blivet")

# this is the volume id btrfs always assigns to the top-level volume/tree
MAIN_VOLUME_ID = 5

# if any component device is less than this size, mkfs.btrfs will fail
MIN_MEMBER_SIZE = Size("16 MiB")

raid_levels = raid.RAIDLevels(["raid0", "raid1", "raid10", "single"])

metadata_levels = raid.RAIDLevels(["raid0", "raid1", "raid10", "single", "dup"])

EXTERNAL_DEPENDENCIES = [availability.BLOCKDEV_BTRFS_PLUGIN]


safe_name_characters = "0-9a-zA-Z._@/-"


def is_btrfs_name_valid(name):
    return '\x00' not in name
