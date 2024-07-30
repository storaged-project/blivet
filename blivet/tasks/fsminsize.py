# fsminsize.py
# Filesystem size gathering classes.
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

from ..errors import FSError
from ..size import Size

from . import availability
from . import fstask
from . import task

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSMinSize(task.BasicApplication, fstask.FSTask, metaclass=abc.ABCMeta):

    """ An abstract class that represents min size information extraction. """

    description = "minimum filesystem size"

    @abc.abstractmethod
    def do_task(self):  # pylint: disable=arguments-differ
        """ Returns the minimum size for this filesystem object.

            :rtype: :class:`~.size.Size`
            :returns: the minimum size
            :raises FSError: if filesystem can not be obtained
        """
        raise NotImplementedError()


class Ext2FSMinSize(FSMinSize):
    ext = availability.BLOCKDEV_EXT_MIN_SIZE

    def do_task(self):  # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        return Size(BlockDev.fs.ext2_get_min_size(self.fs.device))


class NTFSMinSize(FSMinSize):
    ext = availability.BLOCKDEV_NTFS_MIN_SIZE

    def do_task(self):  # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        return Size(BlockDev.fs.ntfs_get_min_size(self.fs.device))


class UnimplementedFSMinSize(fstask.UnimplementedFSTask):
    pass
