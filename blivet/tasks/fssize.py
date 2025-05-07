# fssize.py
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
import os

from .. import udev
from ..errors import FSError
from ..size import Size

from . import fstask


import logging
log = logging.getLogger("blivet")


class FSSize(fstask.FSTask, metaclass=abc.ABCMeta):

    """ An abstract class that represents size information extraction. """
    description = "current filesystem size"

    udev = False

    # TASK methods

    @property
    def _availability_errors(self):
        return []

    @property
    def depends_on(self):
        return [self.fs._info]

    @abc.abstractmethod
    def _get_size_tools(self):
        raise NotImplementedError

    def _get_size_udev(self):
        # just make sure udev has up-to-date information
        udev.trigger(action="change", path=self.fs.device)
        udev.settle()
        udev_info = udev.get_device(device_node=self.fs.device)
        if not udev_info:
            raise FSError("Failed to obtain udev information for device %s" % self.fs.device)

        last_block = udev.device_get_format_lastblock(udev_info)
        block_size = udev.device_get_format_blocksize(udev_info)
        if not last_block or not block_size:
            raise FSError("Failed to obtain filesystem size for %s from udev" % self.fs.device)

        return Size(int(last_block) * int(block_size))

    def do_task(self):  # pylint: disable=arguments-differ
        """ Returns the size of the filesystem.

            :returns: the size of the filesystem
            :rtype: :class:`~.size.Size`
            :raises FSError: on failure
        """

        # try to get size from udev if supported
        if self.udev:
            try:
                size = self._get_size_udev()
            except FSError as e:
                log.info("Failed to obtain filesystem size for %s from udev: %s",
                         self.fs.device, str(e))
            else:
                return size

        # fallback to filesystem tools
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        if self.fs._current_info is None:
            try:
                if self.fs._info.available:
                    self.fs._current_info = self.fs._info.do_task()
            except FSError as e:
                log.info("Failed to obtain info for device %s: %s", self.fs.device, e)

        if self.fs._current_info is None:
            raise FSError("No info available for size computation.")

        return self._get_size_tools()


class Ext2FSSize(FSSize):
    udev = True

    def _get_size_tools(self):
        return Size(self.fs._current_info.block_size * self.fs._current_info.block_count)


class NTFSSize(FSSize):
    def _get_size_tools(self):
        return Size(self.fs._current_info.size)


class XFSSize(FSSize):
    udev = True

    def _get_size_tools(self):
        return Size(self.fs._current_info.block_size * self.fs._current_info.block_count)


class FATFSSize(FSSize):
    def _get_size_tools(self):
        return Size(self.fs._current_info.cluster_size * self.fs._current_info.cluster_count)


class TmpFSSize(fstask.FSTask):
    description = "current filesystem size"

    @property
    def _availability_errors(self):
        return []

    @property
    def depends_on(self):
        return []

    def do_task(self):  # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        stat = os.statvfs(self.fs.system_mountpoint)
        return Size(stat.f_bsize * stat.f_blocks)


class UnimplementedFSSize(fstask.UnimplementedFSTask):
    pass
