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

import abc
import os
import tempfile

from contextlib import contextmanager
from six import add_metaclass

from ..errors import FSError
from ..size import B, KiB, MiB, GiB, KB, MB, GB
from ..import util

from . import availability
from . import task
from . import fstask
from . import dfresize

import logging
log = logging.getLogger("blivet")


@add_metaclass(abc.ABCMeta)
class FSResizeTask(fstask.FSTask):
    """ The abstract properties that any resize task must have. """

    size_fmt = abc.abstractproperty(doc="Size format string.")


@add_metaclass(abc.ABCMeta)
class FSResize(task.BasicApplication, FSResizeTask):

    """ An abstract class for resizing a filesystem. """

    description = "resize filesystem"

    args = abc.abstractproperty(doc="Resize arguments.")

    # IMPLEMENTATION methods

    @abc.abstractmethod
    def size_spec(self):
        """ Returns a string specification for the target size of the command.
            :returns: size specification
            :rtype: str
        """
        raise NotImplementedError()

    def _resize_command(self):
        return [str(self.ext)] + self.args

    def do_task(self):
        """ Resize the device.

            :raises FSError: on failure
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        try:
            ret = util.run_program(self._resize_command())
        except OSError as e:
            raise FSError(e)

        if ret:
            raise FSError("resize failed: %s" % ret)


class Ext2FSResize(FSResize):
    ext = availability.RESIZE2FS_APP
    unit = MiB

    # No bytes specification is described in the man pages. A number without
    # any suffix is interpreted as indicating the number of filesystem blocks.
    # A suffix of "s" specifies a 512 byte sector. It is omitted here because
    # the lookup is only by standard binary units.
    size_fmt = {KiB: "%dK", MiB: "%dM", GiB: "%dG"}[unit]

    def size_spec(self):
        return self.size_fmt % self.fs.target_size.convert_to(self.unit)

    @property
    def args(self):
        return ["-p", self.fs.device, self.size_spec()]


class NTFSResize(FSResize):
    ext = availability.NTFSRESIZE_APP
    unit = B
    size_fmt = {B: "%d", KB: "%dK", MB: "%dM", GB: "%dG"}[unit]

    def size_spec(self):
        return self.size_fmt % self.fs.target_size.convert_to(self.unit)

    @property
    def args(self):
        return [
            "-ff",  # need at least two 'f's to fully suppress interaction
            "-s", self.size_spec(),
            self.fs.device
        ]


class XFSResize(FSResize):
    ext = availability.XFSRESIZE_APP
    unit = B
    size_fmt = None

    @contextmanager
    def _do_temp_mount(self):
        if self.fs.status:
            yield
        else:
            dev_name = os.path.basename(self.fs.device)
            tmpdir = tempfile.mkdtemp(prefix="xfs-tempmount-%s" % dev_name)
            log.debug("mounting XFS on '%s' to '%s' for resize", self.fs.device, tmpdir)
            try:
                self.fs.mount(mountpoint=tmpdir)
            except FSError as e:
                raise FSError("Failed to mount XFS filesystem for resize: %s" % str(e))

            try:
                yield
            finally:
                util.umount(mountpoint=tmpdir)
                os.rmdir(tmpdir)

    def _get_block_size(self):
        if self.fs._current_info:
            # this should be set by update_size_info()
            for line in self.fs._current_info.split("\n"):
                if line.startswith("blocksize ="):
                    return int(line.split("=")[-1])

        raise FSError("Failed to get XFS filesystem block size for resize")

    def size_spec(self):
        # size for xfs_growfs is in blocks
        return str(self.fs.target_size.convert_to(self.unit) / self._get_block_size())

    @property
    def args(self):
        return [self.fs.system_mountpoint, "-D", self.size_spec()]

    def do_task(self):
        """ Resizes the XFS format. """

        with self._do_temp_mount():
            super(XFSResize, self).do_task()


class TmpFSResize(FSResize):

    ext = availability.MOUNT_APP
    unit = MiB
    size_fmt = {KiB: "%dk", MiB: "%dm", GiB: "%dg"}[unit]

    def size_spec(self):
        return "size=%s" % (self.size_fmt % self.fs.target_size.convert_to(self.unit))

    @property
    def args(self):
        # This is too closely mixed in w/ TmpFS object, due to the
        # fact that resizing is done by mounting and that the options are
        # therefore mount options. The situation is hard to avoid, though.
        opts = self.fs.mountopts or ",".join(self.fs._mount.options)
        options = ("remount", opts, self.size_spec())
        return ['-o', ",".join(options), self.fs._type, self.fs.system_mountpoint]


class UnimplementedFSResize(dfresize.UnimplementedDFResize, FSResizeTask):

    @property
    def size_fmt(self):
        raise NotImplementedError()
