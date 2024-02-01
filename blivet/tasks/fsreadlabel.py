# fsreadlabel.py
# Filesystem label reading classes.
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

import abc

from ..errors import FSReadLabelError

from . import availability
from . import fstask
from . import task


class FSReadLabel(task.BasicApplication, fstask.FSTask, metaclass=abc.ABCMeta):

    """ An abstract class that represents reading a filesystem's label. """
    description = "read filesystem label"

    @property
    def depends_on(self):
        return [self.fs._info]

    # IMPLEMENTATION methods

    def do_task(self):  # pylint: disable=arguments-differ
        """ Get the label.

            :returns: the filesystem label
            :rtype: str
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSReadLabelError("\n".join(error_msgs))

        if self.fs._current_info is None:
            raise FSReadLabelError("No info available for size computation.")

        return self.fs._current_info.label


class DosFSReadLabel(FSReadLabel):
    ext = availability.BLOCKDEV_VFAT_INFO


class Ext2FSReadLabel(FSReadLabel):
    ext = availability.BLOCKDEV_EXT_INFO


class NTFSReadLabel(FSReadLabel):
    ext = availability.BLOCKDEV_NTFS_INFO


class XFSReadLabel(FSReadLabel):
    ext = availability.BLOCKDEV_XFS_INFO


class UnimplementedFSReadLabel(fstask.UnimplementedFSTask):
    pass
