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
import re

from six import add_metaclass

from ..errors import FSReadLabelError
from .. import util

from . import availability
from . import fstask
from . import task


@add_metaclass(abc.ABCMeta)
class FSReadLabel(task.BasicApplication, fstask.FSTask):

    """ An abstract class that represents reading a filesystem's label. """
    description = "read filesystem label"

    label_regex = abc.abstractproperty(
        doc="Matches the string output by the reading application.")

    args = abc.abstractproperty(doc="arguments for reading a label.")

    # IMPLEMENTATION methods

    @property
    def _read_command(self):
        """Get the command to read the filesystem label.

           :return: the command
           :rtype: list of str
        """
        return [str(self.ext)] + self.args

    def _extract_label(self, labelstr):
        """Extract the label from an output string.

           :param str labelstr: the string containing the label information

           :return: the label
           :rtype: str

           Raises an FSReadLabelError if the label can not be extracted.
        """
        match = re.match(self.label_regex, labelstr)
        if match is None:
            raise FSReadLabelError("Unknown format for application %s" % self.ext)
        return match.group('label')

    def do_task(self):
        """ Get the label.

            :returns: the filesystem label
            :rtype: str
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSReadLabelError("\n".join(error_msgs))

        (rc, out) = util.run_program_and_capture_output(self._read_command)
        if rc != 0:
            raise FSReadLabelError("read label failed")

        label = out.strip()

        return label if label == "" else self._extract_label(label)


class DosFSReadLabel(FSReadLabel):
    ext = availability.DOSFSLABEL_APP
    label_regex = r'(?P<label>.*)'

    @property
    def args(self):
        return [self.fs.device]


class Ext2FSReadLabel(FSReadLabel):
    ext = availability.E2LABEL_APP
    label_regex = r'(?P<label>.*)'

    @property
    def args(self):
        return [self.fs.device]


class NTFSReadLabel(FSReadLabel):
    ext = availability.NTFSLABEL_APP
    label_regex = r'(?P<label>.*)'

    @property
    def args(self):
        return [self.fs.device]


class XFSReadLabel(FSReadLabel):
    ext = availability.XFSADMIN_APP
    label_regex = r'label = "(?P<label>.*)"'

    @property
    def args(self):
        return ["-l", self.fs.device]


class UnimplementedFSReadLabel(fstask.UnimplementedFSTask):
    pass
