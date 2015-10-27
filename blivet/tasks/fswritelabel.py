# fswritelabel.py
# Filesystem label writing classes.
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

from .. import util
from ..errors import FSWriteLabelError

from . import availability
from . import fstask
from . import task


@add_metaclass(abc.ABCMeta)
class FSWriteLabel(task.BasicApplication, fstask.FSTask):

    """ An abstract class that represents writing a label for a filesystem. """

    description = "write filesystem label"

    args = abc.abstractproperty(doc="arguments for writing a label")

    # IMPLEMENTATION methods

    @property
    def _set_command(self):
        """Get the command to label the filesystem.

           :return: the command
           :rtype: list of str
        """
        return [str(self.ext)] + self.args

    def do_task(self):
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSWriteLabelError("\n".join(error_msgs))

        rc = util.run_program(self._set_command)
        if rc:
            raise FSWriteLabelError("label failed")


class DosFSWriteLabel(FSWriteLabel):
    ext = availability.DOSFSLABEL_APP

    @property
    def args(self):
        return [self.fs.device, self.fs.label]


class Ext2FSWriteLabel(FSWriteLabel):
    ext = availability.E2LABEL_APP

    @property
    def args(self):
        return [self.fs.device, self.fs.label]


class JFSWriteLabel(FSWriteLabel):
    ext = availability.JFSTUNE_APP

    @property
    def args(self):
        return ["-L", self.fs.label, self.fs.device]


class NTFSWriteLabel(FSWriteLabel):
    ext = availability.NTFSLABEL_APP

    @property
    def args(self):
        return [self.fs.device, self.fs.label]


class ReiserFSWriteLabel(FSWriteLabel):
    ext = availability.REISERFSTUNE_APP

    @property
    def args(self):
        return ["-l", self.fs.label, self.fs.device]


class XFSWriteLabel(FSWriteLabel):
    ext = availability.XFSADMIN_APP

    @property
    def args(self):
        return ["-L", self.fs.label if self.fs.label != "" else "--", self.fs.device]


class UnimplementedFSWriteLabel(fstask.UnimplementedFSTask):
    pass
