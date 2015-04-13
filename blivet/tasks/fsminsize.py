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
import os

from six import add_metaclass

from ..errors import FSError
from .. import util
from ..size import Size

from . import availability
from . import task

@add_metaclass(abc.ABCMeta)
class FSMinSize(task.BasicApplication):
    """ An abstract class that represents min size information extraction. """

    description = "minimum filesystem size"

    options = abc.abstractproperty(doc="Options for use with app.")

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs

    @property
    def unready(self):
        if not self.fs.exists:
            return "filesystem has not been created"
        if not os.path.exists(self.fs.device):
            return "device %s does not exist" % self.fs.device.name
        return False

    def _resizeCommand(self):
        return [str(self.ext)] + self.options + [self.fs.device]

    def _getResizeInfo(self):
        """ Get info from fsresize program.

            :rtype: str
            :returns: output returned by fsresize program
        """
        error_msg = None
        try:
            (rc, out) = util.run_program_and_capture_output(self._resizeCommand())
        except OSError as e:
            error_msg = "failed to gather info from resize program: %s" % e
        if rc:
            error_msg = "failed to gather info from resize program: %s" % e

        if error_msg:
            raise FSError(error_msg)
        return out

    @abc.abstractmethod
    def doTask(self):
        """ Returns the minimum size for this filesystem object.

            :rtype: :class:`~.size.Size`
            :returns: the minimum size
            :raises FSError: if filesystem can not be obtained
        """
        raise NotImplementedError()

class Ext2FSMinSize(FSMinSize):

    ext = availability.RESIZE2FS_APP
    options = ["-P"]

    @property
    def unable(self):
        if self.fs._current_info is None:
            return "No filesystem info available to extract block size from."
        return False

    @property
    def dependsOn(self):
        return [self.fs._info]

    def _extractBlockSize(self):
        """ Extract block size from filesystem info.

            :returns: block size of fileystem or None
            :rtype: :class:`~.size.Size` or NoneType
        """
        blockSize = None
        for line in (l.strip() for l in self.fs._current_info.splitlines() if l.startswith("Block size:")):
            try:
                blockSize = int(line.split(" ")[-1])
                break
            except ValueError:
                continue

        return Size(blockSize) if blockSize else None

    def _extractNumBlocks(self, info):
        """ Extract the number of blocks from the resizefs info.

           :returns: the number of blocks or None
           :rtype: int or NoneType
        """
        numBlocks = None
        for line in info.splitlines():
            (text, _sep, value) = line.partition(":")
            if "minimum size of the filesystem" not in text:
                continue

            try:
                numBlocks = int(value.strip())
                break
            except ValueError:
                break

        return numBlocks

    def doTask(self):
        error_msg = self.impossible
        if error_msg:
            raise FSError(error_msg)

        blockSize = self._extractBlockSize()
        if blockSize is None:
            raise FSError("failed to get block size for %s filesystem on %s" % (self.fs.mountType, self.fs.device.name))

        resize_info = self._getResizeInfo()
        numBlocks = self._extractNumBlocks(resize_info)
        if numBlocks is None:
            raise FSError("failed to get minimum block number for %s filesystem on %s" % (self.fs.mountType, self.fs.device.name))

        return blockSize * numBlocks

class NTFSMinSize(FSMinSize):

    ext = availability.NTFSRESIZE_APP
    options = ["-m"]

    @property
    def unable(self):
        return False

    @property
    def dependsOn(self):
        return []

    def _extractMinSize(self, info):
        """ Extract the minimum size from the resizefs info.

            :param str info: info obtained from resizefs prog
            :rtype: :class:`~.size.Size` or NoneType
            :returns: the minimum size, or None
        """
        minSize = None
        for line in info.splitlines():
            (text, _sep, value) = line.partition(":")
            if "Minsize" not in text:
                continue

            try:
                minSize = Size("%d MB" % int(value.strip()))
            except ValueError:
                break

        return minSize


    def doTask(self):
        error_msg = self.impossible
        if error_msg:
            raise FSError(error_msg)

        resize_info = self._getResizeInfo()
        minSize = self._extractMinSize(resize_info)
        if minSize is None:
            raise FSError("Unable to discover minimum size of filesystem on %s" % self.fs.device)
        return minSize

class UnimplementedFSMinSize(task.UnimplementedTask):

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs
