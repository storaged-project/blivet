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

import hashlib
import os

import gi
gi.require_version("BlockDev", "3.0")

from gi.repository import BlockDev

from ..size import Size, ROUND_DOWN
from ..tasks import availability
from ..util import total_memory, available_memory, run_program_and_capture_output

import logging
log = logging.getLogger("blivet")

LUKS1_METADATA_SIZE = Size("2 MiB")
LUKS2_METADATA_SIZE = Size("16 MiB")
LUKS_METADATA_SIZE = LUKS2_METADATA_SIZE  # luks2 is default
MIN_CREATE_ENTROPY = 256  # bits
SECTOR_SIZE = Size("512 B")

EXTERNAL_DEPENDENCIES = [availability.BLOCKDEV_CRYPTO_PLUGIN]

LUKS_VERSIONS = {"luks1": BlockDev.CryptoLUKSVersion.LUKS1,
                 "luks2": BlockDev.CryptoLUKSVersion.LUKS2}
DEFAULT_LUKS_VERSION = "luks2"

OPAL_TYPES = {"luks2-hw-opal": BlockDev.CryptoLUKSHWEncryptionType.OPAL_HW_AND_SW,
              "luks2-hw-opal-only": BlockDev.CryptoLUKSHWEncryptionType.OPAL_HW_ONLY}

DEFAULT_INTEGRITY_ALGORITHM = "crc32c"

# from linux/drivers/md/dm-integrity.c
MAX_JOURNAL_SIZE = 131072 * SECTOR_SIZE


def calculate_luks2_max_memory():
    """ Calculates maximum RAM that will be used during LUKS format.
        The calculation is based on currently available (free) memory.
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


def _integrity_tag_size(hash_alg):
    if hash_alg.startswith("crc32"):
        return 4

    try:
        h = hashlib.new(hash_alg)
    except ValueError:
        log.debug("unknown/unsupported hash '%s' for integrity", hash_alg)
        return 4
    else:
        return h.digest_size


def calculate_integrity_metadata_size(device_size, algorithm=DEFAULT_INTEGRITY_ALGORITHM):
    tag_size = _integrity_tag_size(algorithm)
    # metadata (checksums) size
    msize = Size(device_size * tag_size / (SECTOR_SIZE + tag_size))
    msize = (msize / SECTOR_SIZE + 1) * SECTOR_SIZE  # round up to sector

    # superblock and journal metadata
    msize += Size("1 MiB")

    # journal size, based on linux/drivers/md/dm-integrity.c
    jsize = min(MAX_JOURNAL_SIZE, Size(int(device_size) >> 7))
    jsize = (jsize / SECTOR_SIZE + 1) * SECTOR_SIZE  # round up to sector

    return msize + jsize


def get_optimal_luks_sector_size(device):
    rc, out = run_program_and_capture_output(["blockdev", "--getss", device])
    if rc != 0:
        log.warning("Failed to get logical sector size for %s: %s", device, out)
        return 0
    try:
        logical_block_size = int(out)
    except ValueError:
        log.warning("Failed to get logical sector size for %s from '%s'", device, out)
        return 0

    rc, out = run_program_and_capture_output(["blockdev", "--getpbsz", device])
    if rc != 0:
        log.warning("Failed to get physical sector size for %s: %s", device, out)
        return 0
    try:
        physical_block_size = int(out)
    except ValueError:
        log.warning("Failed to get physical sector size for %s from '%s'", device, out)
        return 0

    if logical_block_size == physical_block_size:
        # same logical and physical block size: let cryptsetup decide
        return 0
    else:
        # XXX when logical and physical block size differ, we don't want to let cryptsetup
        # decide because it will choose 4096 for disks with 4096 physical block size and
        # 512 logical block size which will make it harder to combine these in a single
        # LVM volume group if used as PVs
        return SECTOR_SIZE


def is_fips_enabled():
    if not os.path.exists("/proc/sys/crypto/fips_enabled"):
        # if the file doesn't exist, we are definitely not in FIPS mode
        return False

    with open("/proc/sys/crypto/fips_enabled", "r") as f:
        enabled = f.read()
    return enabled.strip() == "1"
