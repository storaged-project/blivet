# fswritelabel.py
# Filesystem label writing classes.
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

from ..errors import FSWriteLabelError

from . import availability
from . import fstask
from . import task

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSWriteLabel(task.BasicApplication, fstask.FSTask):
    """ An abstract class that represents writing a label for a filesystem. """

    description = "write filesystem label"
    fstype = None

    # IMPLEMENTATION methods

    def do_task(self):  # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSWriteLabelError("\n".join(error_msgs))

        try:
            BlockDev.fs.set_label(self.fs.device, self.fs.label, self.fstype)
        except BlockDev.FSError as e:
            raise FSWriteLabelError(str(e))


class DosFSWriteLabel(FSWriteLabel):
    fstype = "vfat"
    ext = availability.BLOCKDEV_VFAT_LABEL


class Ext2FSWriteLabel(FSWriteLabel):
    fstype = "ext2"
    ext = availability.BLOCKDEV_EXT_LABEL


class NTFSWriteLabel(FSWriteLabel):
    fstype = "ntfs"
    ext = availability.BLOCKDEV_NTFS_LABEL


class XFSWriteLabel(FSWriteLabel):
    fstype = "xfs"
    ext = availability.BLOCKDEV_XFS_LABEL


class UnimplementedFSWriteLabel(fstask.UnimplementedFSTask):
    pass
