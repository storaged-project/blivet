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

from ..size import Size
from ..tasks import availability

LUKS_METADATA_SIZE = Size("2 MiB")
MIN_CREATE_ENTROPY = 256  # bits
SECTOR_SIZE = Size("512 B")

EXTERNAL_DEPENDENCIES = [availability.BLOCKDEV_CRYPTO_PLUGIN]
