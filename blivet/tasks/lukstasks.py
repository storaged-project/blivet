# lukstasks.py
# Tasks for a LUKS format.
#
# Copyright (C) 2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Anne Mulhern <amulhern@redhat.com>

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

from .. import util

from ..devicelibs import crypto
from ..errors import LUKSError
from ..size import Size

from . import availability
from . import task
from . import dfresize


class LUKSResize(task.BasicApplication, dfresize.DFResizeTask):
    """ Handle resize of LUKS device. """

    description = "resize luks device"

    ext = availability.BLOCKDEV_CRYPTO_PLUGIN

    # units for specifying new size
    unit = crypto.SECTOR_SIZE

    def __init__(self, a_luks):
        """ Initializer.

            :param :class:`~.formats.luks.LUKS` a_luks: a LUKS format object
        """
        self.luks = a_luks

    def do_task(self):
        """ Resizes the LUKS format. """
        try:
            blockdev.crypto.luks_resize(self.luks.map_name, self.luks.target_size.convert_to(self.unit))
        except blockdev.CryptoError as e:
            raise LUKSError(e)
