#
# crypto.py
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
#            Martin Sivak <msivak@redhat.com>
#

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev

from ..size import Size, ROUND_DOWN
from ..tasks import availability
from ..util import total_memory, available_memory

import logging
log = logging.getLogger("blivet")

LUKS_METADATA_SIZE = Size("2 MiB")
MIN_CREATE_ENTROPY = 256  # bits
SECTOR_SIZE = Size("512 B")

EXTERNAL_DEPENDENCIES = [availability.BLOCKDEV_CRYPTO_PLUGIN]

LUKS_VERSIONS = {"luks1": BlockDev.CryptoLUKSVersion.LUKS1,
                 "luks2": BlockDev.CryptoLUKSVersion.LUKS2}
DEFAULT_LUKS_VERSION = "luks2"


def calculate_luks2_max_memory():
    """ Calculates maximum RAM that will be used during LUKS format.
        The calculation is based on currenly available (free) memory.
        This value will be used for the 'max_memory_kb' option for the
        'argon2' key derivation function.
    """
    free_mem = available_memory()
    total_mem = total_memory()

    # we want to always use at least 128 MiB
    if free_mem < Size("128 MiB"):
        log.warning("Less than 128 MiB RAM is currently free, LUKS2 format may fail.")
        return Size("128 MiB")

    # upper limit from cryptsetup is max(half RAM, 1 GiB)
    elif free_mem >= Size("1 GiB") or free_mem >= (total_mem / 2):
        return None

    # free rounded to multiple of 128 MiB
    else:
        return free_mem.round_to_nearest(Size("128 MiB"), ROUND_DOWN)
