# fslabel.py
# Filesystem labeling classes for anaconda's storage configuration module.
#
# Copyright (C) 2013  Red Hat, Inc.
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
import re

from .. import errors

class FSLabelApp(object):
    """An abstract class that represents actions associated with a
       filesystem's labeling application.
    """
    __metaclass__ = abc.ABCMeta

    name = abc.abstractproperty(
       doc="The name of the filesystem labeling application.")

    reads = abc.abstractproperty(
        doc="Whether this application can read a label as well as write one.")

    _label_regex = abc.abstractproperty(
        doc="Matches the string output by the label reading application.")

    @abc.abstractmethod
    def _writeLabelArgs(self, fs):
        """Returns a list of the arguments for writing a label.

           :param FS fs: a filesystem object

           :return: the arguments
           :rtype: list of str

           It can be assumed in this function that fs.label is a str.
        """
        raise NotImplementedError

    def setLabelCommand(self, fs):
        """Get the command to label the filesystem.

           :param FS fs: a filesystem object
           :return: the command
           :rtype: list of str

           Raises an exception if fs.label is None.
        """
        if fs.label is None:
            raise fs.FSError("makes no sense to write a label when accepting default label")
        return [self.name] + self._writeLabelArgs(fs)

    @abc.abstractmethod
    def _readLabelArgs(self, fs):
        """Returns a list of arguments for reading a label.

           :param FS fs: a filesystem object
           :return: the arguments
           :rtype: list of str
        """
        raise NotImplementedError

    def readLabelCommand(self, fs):
        """Get the command to read the filesystem label.

           :param FS fs: a filesystem object
           :return: the command
           :rtype: list of str

           Raises an FSError if this application can not read the label.
        """
        if not self.reads:
            raise errors.FSError("Application %s can not read the filesystem label." % self.name)
        return [self.name] + self._readLabelArgs(fs)

    def extractLabel(self, labelstr):
        """Extract the label from an output string.

           :param str labelstr: the string containing the label information

           :return: the label
           :rtype: str

           Raises an FSError if the label can not be extracted.
        """
        if not self.reads or self._label_regex is None:
            raise errors.FSError("Unknown format for application %s" % self.name)
        match = re.match(self._label_regex, labelstr)
        if match is None:
            raise errors.FSError("Unknown format for application %s" % self.name)
        return match.group('label')


class E2Label(FSLabelApp):
    """Application used by ext2 and its descendants."""

    name = property(lambda s: "e2label")
    reads = property(lambda s: True)

    _label_regex = property(lambda s: r'(?P<label>.*)')

    def _writeLabelArgs(self, fs):
        return [fs.device, fs.label]

    def _readLabelArgs(self, fs):
        return [fs.device]

E2Label = E2Label()

class DosFsLabel(FSLabelApp):
    """Application used by FATFS."""

    name = property(lambda s: "dosfslabel")
    reads = property(lambda s: True)

    _label_regex = property(lambda s: r'(?P<label>.*)')

    def _writeLabelArgs(self, fs):
        return [fs.device, fs.label]

    def _readLabelArgs(self, fs):
        return [fs.device]

DosFsLabel = DosFsLabel()

class JFSTune(FSLabelApp):
    """Application used by JFS."""

    name = property(lambda s: "jfs_tune")
    reads = property(lambda s: False)

    _label_regex = property(lambda s: None)

    def _writeLabelArgs(self, fs):
        return ["-L", fs.label, fs.device]

    def _readLabelArgs(self, fs):
        raise NotImplementedError

JFSTune = JFSTune()

class ReiserFSTune(FSLabelApp):
    """Application used by ReiserFS."""

    name = property(lambda s: "reiserfstune")
    reads = property(lambda s: False)

    _label_regex = property(lambda s: None)

    def _writeLabelArgs(self, fs):
        return ["-l", fs.label, fs.device]

    def _readLabelArgs(self, fs):
        raise NotImplementedError

ReiserFSTune = ReiserFSTune()

class XFSAdmin(FSLabelApp):
    """Application used by XFS."""

    name = property(lambda s: "xfs_admin")
    reads = property(lambda s: True)

    _label_regex = property(lambda s: r'label = "(?P<label>.*)"')

    def _writeLabelArgs(self, fs):
        return ["-L", fs.label if fs.label != "" else "--", fs.device]

    def _readLabelArgs(self, fs):
        return ["-l", fs.device]

XFSAdmin = XFSAdmin()

class NTFSLabel(FSLabelApp):
    """Application used by NTFS."""

    name = property(lambda s: "ntfslabel")
    reads = property(lambda s: True)

    _label_regex = property(lambda s: r'label = "(?P<label>.*)"')

    def _writeLabelArgs(self, fs):
        return [fs.device, fs.label]

    def _readLabelArgs(self, fs):
        return [fs.device]

NTFSLabel = NTFSLabel()
