# fssync.py
# Filesystem syncing classes.
#
# Copyright (C) 2014  Red Hat, Inc.
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


class FSSync(task.BasicApplication, fstask.FSTask, metaclass=abc.ABCMeta):

    """ An abstract class that represents syncing a filesystem. """

    description = "filesystem syncing"

    @abc.abstractmethod
    def do_task(self):  # pylint: disable=arguments-differ
        raise NotImplementedError()


class XFSSync(FSSync):

    """ Sync application for XFS. """

    ext = availability.BLOCKDEV_FS_PLUGIN

    def _get_mountpoint(self, root=None):
        mountpoint = self.fs.system_mountpoint
        if root is not None and root.replace('/', ''):
            if mountpoint == root:
                mountpoint = '/'
            else:
                mountpoint = mountpoint[len(root):]

        return mountpoint

    def do_task(self, root="/"):
        # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        error_msg = None
        mountpoint = self._get_mountpoint(root=root)
        try:
            BlockDev.fs.freeze(mountpoint)
        except BlockDev.FSError as e:
            error_msg = "failed to sync filesystem: %s" % e

        try:
            BlockDev.fs.unfreeze(mountpoint)
        except BlockDev.FSError as e:
            error_msg = "failed to sync filesystem: %s" % e

        if error_msg:
            raise FSError(error_msg)


class UnimplementedFSSync(fstask.UnimplementedFSTask):
    pass
