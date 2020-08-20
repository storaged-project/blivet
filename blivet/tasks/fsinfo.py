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

from six import add_metaclass

from ..errors import FSError
from .. import util

from . import availability
from . import fstask
from . import task


@add_metaclass(abc.ABCMeta)
class FSInfo(task.BasicApplication, fstask.FSTask):

    """ An abstract class that represents an information gathering app. """

    description = "filesystem info"

    options = abc.abstractproperty(
        doc="Options for invoking the application.")

    @property
    def _info_command(self):
        """ Returns the command for reading filesystem information.

            :returns: a list of appropriate options
            :rtype: list of str
        """
        return [str(self.ext)] + self.options + [self.fs.device]

    def do_task(self):
        """ Returns information from the command.

            :returns: a string representing the output of the command
            :rtype: str
            :raises FSError: if info cannot be obtained
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        error_msg = None
        try:
            (rc, out) = util.run_program_and_capture_output(self._info_command)
            if rc:
                error_msg = "failed to gather fs info: %s" % rc
        except OSError as e:
            error_msg = "failed to gather fs info: %s" % e
        if error_msg:
            raise FSError(error_msg)
        return out


class Ext2FSInfo(FSInfo):
    ext = availability.DUMPE2FS_APP
    options = ["-h"]


class JFSInfo(FSInfo):
    ext = availability.JFSTUNE_APP
    options = ["-l"]


class NTFSInfo(FSInfo):
    ext = availability.NTFSINFO_APP
    options = ["-m"]


class ReiserFSInfo(FSInfo):
    ext = availability.DEBUGREISERFS_APP
    options = []


class XFSInfo(FSInfo):
    ext = availability.XFSDB_APP
    options = ["-c", "sb 0", "-c", "p dblocks", "-c", "p blocksize", "-r"]


class UnimplementedFSInfo(fstask.UnimplementedFSTask):
    pass
