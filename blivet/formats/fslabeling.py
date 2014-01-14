# fslabeling.py
# Filesystem labeling classes for anaconda's storage configuration module.
#
# Copyright (C) 2014  Red Hat, Inc.
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

import fslabel

class FSLabeling(object):
    """An abstract class that represents filesystem labeling actions.
    """

    __metaclass__ = abc.ABCMeta

    @abc.abstractproperty
    def labelApp(self):
        """Application that may be used to label filesystem after the
           filesystem has been created.

           :rtype: object or None
           :return: the object representing the labeling application or None
           if no such object exists
        """
        raise NotImplementedError

    @abc.abstractmethod
    def labelFormatOK(self, label):
        """Returns True if this label is correctly formatted for this
           filesystem, otherwise False.

           :param str label: the label for this filesystem
           :rtype: bool
        """
        raise NotImplementedError

    @abc.abstractmethod
    def labelingArgs(self, label):
        """Returns the arguments for writing the label during filesystem
           creation. These arguments are intended to be passed to the
           appropriate mkfs application.

           :param str label: the label to use
           :return: the arguments
           :rtype: list of str
        """
        raise NotImplementedError

    @abc.abstractproperty
    def defaultLabel(self):
        """Returns the default label for this filesystem, which will be used
           if no label is specified.

           :return: the default label
           :rtype: str
        """
        raise NotImplementedError

class Ext2FSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.E2Label()

    def labelFormatOK(self, label):
        return len(label) < 17

    def labelingArgs(self, label):
        return ["-L", label]

    @property
    def defaultLabel(self):
        return ""

class FATFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.DosFsLabel()

    def labelFormatOK(self, label):
        return len(label) < 12

    def labelingArgs(self, label):
        return ["-n", label]

    @property
    def defaultLabel(self):
        return "NO NAME"

class JFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.JFSTune()

    def labelFormatOK(self, label):
        return len(label) < 17

    def labelingArgs(self, label):
        return ["-L", label]

    @property
    def defaultLabel(self):
        return ""

class ReiserFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.ReiserFSTune()

    def labelFormatOK(self, label):
        return len(label) < 17

    def labelingArgs(self, label):
        return ["-l", label]

    @property
    def defaultLabel(self):
        return ""

class XFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.XFSAdmin()

    def labelFormatOK(self, label):
        return ' ' not in label and len(label) < 13

    def labelingArgs(self, label):
        return ["-L", label]

    @property
    def defaultLabel(self):
        return ""

class HFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return None

    def labelFormatOK(self, label):
        return ':' not in label and len(label) < 28 and len(label) > 0

    def labelingArgs(self, label):
        return ["-l", label]

    @property
    def defaultLabel(self):
        return "Untitled"

class NTFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.NTFSLabel()

    def labelFormatOK(self, label):
        return len(label) < 129

    def labelingArgs(self, label):
        return ["-L", label]

    @property
    def defaultLabel(self):
        return ""
