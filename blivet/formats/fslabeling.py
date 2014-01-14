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

class Ext2FSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.E2Label()

    def labelFormatOK(self, label):
        return len(label) < 17

class FATFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.DosFsLabel()

    def labelFormatOK(self, label):
        return len(label) < 12

class JFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.JFSTune()

    def labelFormatOK(self, label):
        return len(label) < 17

class ReiserFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.ReiserFSTune()

    def labelFormatOK(self, label):
        return len(label) < 17

class XFSLabeling(FSLabeling):

    @property
    def labelApp(self):
        return fslabel.XFSAdmin()

    def labelFormatOK(self, label):
        return ' ' not in label and len(label) < 13
