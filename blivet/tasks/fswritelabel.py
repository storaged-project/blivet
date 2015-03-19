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
import os

from six import add_metaclass

from .. import util
from ..errors import FSWriteLabelError

from . import availability
from . import task

@add_metaclass(abc.ABCMeta)
class FSWriteLabel(task.Task):
    """ An abstract class that represents writing a label for a filesystem. """

    description = "write filesystem label"

    app_name = abc.abstractproperty(
       doc="The name of the filesystem labeling application.")

    args = abc.abstractproperty(doc="arguments for writing a label")

    @classmethod
    def _app(cls):
        return availability.application(cls.app_name)

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs

    # TASK methods

    @classmethod
    def available(cls):
        return cls._app().available

    @property
    def _unavailable(self):
        if not self._app().available:
            return "application %s is not available" % self._app()

        return False

    @property
    def unready(self):
        if not self.fs.exists:
            return "filesystem has not been created"

        if not os.path.exists(self.fs.device):
            return "device (%s) does not exist" % self.fs.device.name

        return False

    @property
    def unable(self):
        if self.fs.label is None:
            return "makes no sense to write a label when accepting default label"

        if not self.fs.labelFormatOK(self.fs.label):
            return "bad label format for labelling application %s" % self._app()

        return False

    @property
    def dependsOn(self):
        return []

    # IMPLEMENTATION methods

    def _setCommand(self):
        """Get the command to label the filesystem.

           :return: the command
           :rtype: list of str

           Requires that self.unavailable, self.unable, self.unready are False.
        """
        return [str(self._app())] + self.args

    def doTask(self):
        error_msg = self.impossible
        if error_msg:
            raise FSWriteLabelError(error_msg)

        rc = util.run_program(self._setCommand())
        if rc:
            raise FSWriteLabelError("label failed")

class DosFSWriteLabel(FSWriteLabel):
    app_name = "dosfslabel"

    @property
    def args(self):
        return [self.fs.device, self.fs.label]

class Ext2FSWriteLabel(FSWriteLabel):
    app_name = "e2label"

    @property
    def args(self):
        return [self.fs.device, self.fs.label]

class JFSWriteLabel(FSWriteLabel):
    app_name = "jfs_tune"

    @property
    def args(self):
        return ["-L", self.fs.label, self.fs.device]

class NTFSWriteLabel(FSWriteLabel):
    app_name = "ntfslabel"

    @property
    def args(self):
        return [self.fs.device, self.fs.label]

class ReiserFSWriteLabel(FSWriteLabel):
    app_name = "reiserfstune"

    @property
    def args(self):
        return ["-l", self.fs.label, self.fs.device]

class XFSWriteLabel(FSWriteLabel):
    app_name = "xfs_admin"

    @property
    def args(self):
        return ["-L", self.fs.label if self.fs.label != "" else "--", self.fs.device]

class UnimplementedFSWriteLabel(task.UnimplementedTask):

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs
