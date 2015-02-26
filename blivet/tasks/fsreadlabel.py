# fsreadlabel.py
# Filesystem label reading classes.
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
import re

from six import add_metaclass

from ..errors import FSReadLabelError
from .. import util

from . import availability
from . import task

@add_metaclass(abc.ABCMeta)
class FSReadLabel(task.Task):
    """ An abstract class that represents reading a filesystem's label. """
    description = "read filesystem label"

    app_name = abc.abstractproperty(
       doc="The name of the filesystem labeling application.")

    label_regex = abc.abstractproperty(
        doc="Matches the string output by the reading application.")

    args = abc.abstractproperty(doc="arguments for reading a label.")

    @classmethod
    def _app(cls):
        return availability.Application(availability.Path(), cls.app_name)

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
            return "device %s does not exist" % self.fs.device.name

        return False

    @property
    def unable(self):
        return False

    @property
    def dependsOn(self):
        return []

    # IMPLEMENTATION methods

    def _readCommand(self):
        """Get the command to read the filesystem label.

           :return: the command
           :rtype: list of str
        """
        return [str(self._app())] + self.args

    def _extractLabel(self, labelstr):
        """Extract the label from an output string.

           :param str labelstr: the string containing the label information

           :return: the label
           :rtype: str

           Raises an FSReadLabelError if the label can not be extracted.
        """
        match = re.match(self.label_regex, labelstr)
        if match is None:
            raise FSReadLabelError("Unknown format for application %s" % self._app())
        return match.group('label')

    def doTask(self):
        """ Get the label.

            :returns: the filesystem label
            :rtype: str
        """
        error_msg = self.impossible
        if error_msg:
            raise FSReadLabelError(error_msg)

        (rc, out) = util.run_program_and_capture_output(self._readCommand())
        if rc:
            raise FSReadLabelError("read label failed")

        label = out.strip()

        return label if label == "" else self._extractLabel(label)

class DosFSReadLabel(FSReadLabel):
    app_name = "dosfslabel"
    label_regex = r'(?P<label>.*)'

    @property
    def args(self):
        return [self.fs.device]

class Ext2FSReadLabel(FSReadLabel):
    app_name = "e2label"
    label_regex = r'(?P<label>.*)'

    @property
    def args(self):
        return [self.fs.device]

class NTFSReadLabel(FSReadLabel):
    app_name = "ntfslabel"
    label_regex = r'(?P<label>.*)'

    @property
    def args(self):
        return [self.fs.device]

class XFSReadLabel(FSReadLabel):
    app_name = "xfs_admin"
    label_regex = r'label = "(?P<label>.*)"'

    @property
    def args(self):
        return ["-l", self.fs.device]
