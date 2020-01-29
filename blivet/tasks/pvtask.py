# coding=utf-8
# pvtask.py
# Tasks for a LVMPV format.
#
# Copyright (C) 2016  Red Hat, Inc.
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
# Red Hat Author(s): Vojtěch Trefný <vtrefny@redhat.com>

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from ..errors import PhysicalVolumeError
from ..size import Size, B

from . import availability
from . import task
from . import dfresize


class PVSize(task.BasicApplication):
    """ Obtain information about the size of a LVMPV format. """

    ext = availability.BLOCKDEV_LVM_PLUGIN

    description = "size of a LVMPV format"

    def __init__(self, a_pv):
        """ Initializer.

            :param :class:`~.formats.lvmpv.LVMPhysicalVolume` a_pv: a LVMPV format object
        """
        self.pv = a_pv

    def do_task(self):
        """ Returns the size of the LVMPV format.

            :returns: the size of the LVMPV format
            :rtype: :class:`~.size.Size`
            :raises :class:`~.errors.PhysicalVolumeError`: if size cannot be obtained
        """

        try:
            pv_info = blockdev.lvm.pvinfo(self.pv.device)
            pv_size = pv_info.pv_size
        except blockdev.LVMError as e:
            raise PhysicalVolumeError(e)

        return Size(pv_size)


class PVResize(task.BasicApplication, dfresize.DFResizeTask):
    """ Handle resize of the LVMPV format. """

    description = "resize the LVMPV format"

    ext = availability.BLOCKDEV_LVM_PLUGIN
    unit = B

    def __init__(self, a_pv):
        """ Initializer.

            :param :class:`~.formats.lvmpv.LVMPhysicalVolume` a_pv: a LVMPV format object
        """
        self.pv = a_pv

    def do_task(self):
        """ Resizes the LVMPV format. """
        try:
            blockdev.lvm.pvresize(self.pv.device, self.pv.target_size.convert_to(self.unit))
        except blockdev.LVMError as e:
            raise PhysicalVolumeError(e)
