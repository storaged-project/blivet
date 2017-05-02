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
from collections import namedtuple

import six

from ..errors import FSError
from ..size import Size
from .. import util

from . import availability
from . import fstask
from . import task

_tags = ("count", "size")
_Tags = namedtuple("_Tags", _tags)


@six.add_metaclass(abc.ABCMeta)
class FSSize(fstask.FSTask):

    """ An abstract class that represents size information extraction. """
    description = "current filesystem size"

    tags = abc.abstractproperty(
        doc="Strings used for extracting components of size.")

    # TASK methods

    @property
    def _availability_errors(self):
        return []

    @property
    def depends_on(self):
        return [self.fs._info]

    # IMPLEMENTATION methods

    def do_task(self):
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

        # Setup initial values
        values = {}
        for k in _tags:
            values[k] = None

        # Attempt to set values from info
        for line in (l.strip() for l in self.fs._current_info.splitlines()):
            key = six.next((k for k in _tags if line.startswith(getattr(self.tags, k))), None)
            if not key:
                continue

            if values[key] is not None:
                raise FSError("found two matches for key %s" % key)

            # Look for last numeric value in matching line
            fields = line.split()
            fields.reverse()
            for field in fields:
                try:
                    values[key] = int(field)
                    break
                except ValueError:
                    continue

        # Raise an error if a value is missing
        missing = six.next((k for k in _tags if values[k] is None), None)
        if missing is not None:
            raise FSError("Failed to parse info for %s." % missing)

        return values["count"] * Size(values["size"])


class Ext2FSSize(FSSize):
    tags = _Tags(size="Block size:", count="Block count:")


class JFSSize(FSSize):
    tags = _Tags(size="Physical block size:", count="Aggregate size:")


class NTFSSize(FSSize):
    tags = _Tags(size="Cluster Size:", count="Volume Size in Clusters:")


class ReiserFSSize(FSSize):
    tags = _Tags(size="Blocksize:", count="Count of blocks on the device:")


class XFSSize(FSSize):
    tags = _Tags(size="blocksize =", count="dblocks =")


class TmpFSSize(task.BasicApplication, fstask.FSTask):
    description = "current filesystem size"

    ext = availability.DF_APP

    @property
    def _size_command(self):
        return [str(self.ext), self.fs.system_mountpoint, "--output=size"]

    def do_task(self):
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
