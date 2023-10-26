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

import six

from ..errors import FSError
from ..size import Size
from .. import util

from . import availability
from . import fstask
from . import task


@six.add_metaclass(abc.ABCMeta)
class FSSize(fstask.FSTask):

    """ An abstract class that represents size information extraction. """
    description = "current filesystem size"

    # TASK methods

    @property
    def _availability_errors(self):
        return []

    @property
    def depends_on(self):
        return [self.fs._info]

    @abc.abstractmethod
    def _get_size(self):
        raise NotImplementedError

    # IMPLEMENTATION methods

    def do_task(self):  # pylint: disable=arguments-differ
        """ Returns the size of the filesystem.

            :returns: the size of the filesystem
            :rtype: :class:`~.size.Size`
            :raises FSError: on failure
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        if self.fs._current_info is None:
            raise FSError("No info available for size computation.")

        return self._get_size()


class Ext2FSSize(FSSize):
    def _get_size(self):
        return Size(self.fs._current_info.block_size * self.fs._current_info.block_count)


class NTFSSize(FSSize):
    def _get_size(self):
        return Size(self.fs._current_info.size)


class XFSSize(FSSize):
    def _get_size(self):
        return Size(self.fs._current_info.block_size * self.fs._current_info.block_count)


class TmpFSSize(task.BasicApplication, fstask.FSTask):
    description = "current filesystem size"

    ext = availability.DF_APP

    @property
    def _size_command(self):
        return [str(self.ext), self.fs.system_mountpoint, "--output=size"]

    def do_task(self):  # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        try:
            (ret, out) = util.run_program_and_capture_output(self._size_command)
            if ret:
                raise FSError("Failed to execute command %s." % self._size_command)
        except OSError:
            raise FSError("Failed to execute command %s." % self._size_command)

        lines = out.splitlines()
        if len(lines) != 2 or lines[0].strip() != "1K-blocks":
            raise FSError("Failed to parse output of command %s." % self._size_command)

        return Size("%s KiB" % lines[1])


class UnimplementedFSSize(fstask.UnimplementedFSTask):
    pass
