# fsinfo.py
# Filesystem information gathering classes.
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

from . import availability
from . import fstask
from . import task

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSInfo(task.BasicApplication, fstask.FSTask, metaclass=abc.ABCMeta):

    """ An abstract class that represents an information gathering app. """

    description = "filesystem info"

    @abc.abstractmethod
    def _get_info(self):
        raise NotImplementedError

    def do_task(self):  # pylint: disable=arguments-differ
        """ Returns information from the command.

            :returns: a string representing the output of the command
            :rtype: str
            :raises FSError: if info cannot be obtained
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        try:
            info = self._get_info()
        except BlockDev.FSError as e:
            raise FSError("failed to gather fs info: %s" % e)
        return info


class Ext2FSInfo(FSInfo):
    ext = availability.BLOCKDEV_EXT_INFO

    def _get_info(self):
        return BlockDev.fs.ext2_get_info(self.fs.device)


class NTFSInfo(FSInfo):
    ext = availability.BLOCKDEV_NTFS_INFO

    def _get_info(self):
        return BlockDev.fs.ntfs_get_info(self.fs.device)


class XFSInfo(FSInfo):
    ext = availability.BLOCKDEV_XFS_INFO

    def _get_info(self):
        return BlockDev.fs.xfs_get_info(self.fs.device)


class UnimplementedFSInfo(fstask.UnimplementedFSTask):
    pass
