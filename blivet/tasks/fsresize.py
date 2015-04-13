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

from six import add_metaclass

from ..errors import FSError
from ..size import B, KiB, MiB, GiB, KB, MB, GB
from ..import util

from . import availability
from . import task

@add_metaclass(abc.ABCMeta)
class FSResizeTask(task.Task):
    """ The abstract properties that any resize task must have. """

    unit = abc.abstractproperty(doc="Resize unit.")
    size_fmt = abc.abstractproperty(doc="Size format string.")


@add_metaclass(abc.ABCMeta)
class FSResize(task.BasicApplication, FSResizeTask):
    """ An abstract class for resizing a filesystem. """

    description = "resize filesystem"

    args = abc.abstractproperty(doc="Resize arguments.")

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs

    # TASK methods

    @property
    def unready(self):
        if not self.fs.exists:
            return "filesystem has not been created"

        if not os.path.exists(self.fs.device):
            return "device does not exist"

        return False

    @property
    def unable(self):
        return False

    # IMPLEMENTATION methods

    @abc.abstractmethod
    def sizeSpec(self):
        """ Returns a string specification for the target size of the command.
            :returns: size specification
            :rtype: str
        """
        raise NotImplementedError()

    def _resizeCommand(self):
        return [str(self.ext)] + self.args

    def doTask(self):
        """ Resize the device.

            :raises FSError: on failure
        """
        error_msg = self.impossible
        if error_msg:
            raise FSError(error_msg)

        try:
            ret = util.run_program(self._resizeCommand())
        except OSError as e:
            raise FSError(e)

        if ret:
            raise FSError("resize failed: %s" % ret)

class Ext2FSResize(FSResize):
    ext = availability.RESIZE2FS_APP
    unit = MiB
    # No unit specifier is interpreted not as bytes, but block size
    size_fmt = {KiB: "%dK", MiB: "%dM", GiB: "%dG"}[unit]

    def sizeSpec(self):
        return self.size_fmt % self.fs.targetSize.convertTo(self.unit)

    @property
    def args(self):
        return ["-p", self.fs.device, self.sizeSpec()]

class NTFSResize(FSResize):
    ext = availability.NTFSRESIZE_APP
    unit = B
    size_fmt = {B: "%d", KB: "%dK", MB: "%dM", GB: "%dG"}[unit]

    def sizeSpec(self):
        return self.size_fmt % self.fs.targetSize.convertTo(self.unit)

    @property
    def args(self):
        return [
           "-ff", # need at least two 'f's to fully supress interaction
           "-s", self.sizeSpec(),
           self.fs.device
        ]

class TmpFSResize(FSResize):

    ext = availability.MOUNT_APP
    unit = MiB
    size_fmt = {KiB: "%dk", MiB: "%dm", GiB: "%dg"}[unit]

    def sizeSpec(self):
        return "size=%s" % (self.size_fmt % self.fs.targetSize.convertTo(self.unit))

    @property
    def unready(self):
        # TmpFS does not require a device in order to be mounted.
        if not self.fs.exists:
            return "filesystem has not been created"

        return False

    @property
    def args(self):
        # This is too closely mixed in w/ TmpFS object, due to the
        # fact that resizing is done by mounting and that the options are
        # therefore mount options. The situation is hard to avoid, though.
        opts = self.fs.mountopts or ",".join(self.fs._mount.options)
        options = ("remount", opts, self.sizeSpec())
        return ['-o', ",".join(options), self.fs._type, self.fs.systemMountpoint]

class UnimplementedFSResize(task.UnimplementedTask, FSResizeTask):

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs

    @property
    def unit(self):
        raise NotImplementedError()

    @property
    def size_fmt(self):
        raise NotImplementedError()
