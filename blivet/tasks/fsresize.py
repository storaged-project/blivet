# fsresize.py
# Filesystem resizing classes.
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

from ..errors import FSError
from ..size import B, MiB

from . import availability
from . import task
from . import fstask
from . import dfresize

import logging
log = logging.getLogger("blivet")

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSResizeTask(fstask.FSTask):
    """ The abstract properties that any resize task must have. """


class FSResize(task.BasicApplication, FSResizeTask):

    """ An abstract class for resizing a filesystem. """

    description = "resize filesystem"

    # IMPLEMENTATION methods

    def do_task(self):  # pylint: disable=arguments-differ
        """ Resize the device.

            :raises FSError: on failure
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        try:
            BlockDev.fs.resize(self.fs.device, self.fs.target_size.convert_to(B), self.fs.type)
        except BlockDev.FSError as e:
            raise FSError(str(e))


class Ext2FSResize(FSResize):
    ext = availability.BLOCKDEV_EXT_RESIZE
    unit = MiB


class NTFSResize(FSResize):
    ext = availability.BLOCKDEV_NTFS_RESIZE
    unit = B


class XFSResize(FSResize):
    ext = availability.BLOCKDEV_XFS_RESIZE
    unit = B


class TmpFSResize(FSResize):
    ext = availability.BLOCKDEV_FS_PLUGIN
    unit = MiB

    def do_task(self):  # pylint: disable=arguments-differ
        """ Resize the device.

            :raises FSError: on failure
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        # This is too closely mixed in w/ TmpFS object, due to the
        # fact that resizing is done by mounting and that the options are
        # therefore mount options. The situation is hard to avoid, though.
        opts = self.fs.mountopts or ",".join(self.fs._mount.options)
        options = ("remount", opts, "size=%dm" % self.fs.target_size.convert_to(MiB))

        try:
            BlockDev.fs.mount(device=None, mountpoint=self.fs.system_mountpoint, fstype=self.fs._type, options=",".join(options))
        except BlockDev.FSError as e:
            raise FSError(str(e))


class UnimplementedFSResize(dfresize.UnimplementedDFResize, FSResizeTask):
    unit = B
