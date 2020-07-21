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

from six import add_metaclass


@add_metaclass(abc.ABCMeta)
class FSLabeling(object):

    """An abstract class that represents filesystem labeling actions.
    """

    default_label = abc.abstractproperty(
        doc="Default label set on this filesystem at creation.")

    @abc.abstractmethod
    def label_format_ok(self, label):
        """Returns True if this label is correctly formatted for this
           filesystem, otherwise False.

           :param str label: the label for this filesystem
           :rtype: bool
        """
        raise NotImplementedError


class Ext2FSLabeling(FSLabeling):

    default_label = ""

    @classmethod
    def label_format_ok(cls, label):
        return len(label) < 17


class FATFSLabeling(FSLabeling):

    default_label = "NO NAME"

    @classmethod
    def label_format_ok(cls, label):
        return len(label) < 12


class JFSLabeling(FSLabeling):

    default_label = ""

    @classmethod
    def label_format_ok(cls, label):
        return len(label) < 17


class ReiserFSLabeling(FSLabeling):

    default_label = ""

    @classmethod
    def label_format_ok(cls, label):
        return len(label) < 17


class XFSLabeling(FSLabeling):

    default_label = ""

    @classmethod
    def label_format_ok(cls, label):
        return ' ' not in label and len(label) < 13


class HFSLabeling(FSLabeling):

    default_label = "Untitled"

    @classmethod
    def label_format_ok(cls, label):
        return ':' not in label and len(label) < 28 and len(label) > 0


class HFSPlusLabeling(FSLabeling):

    default_label = "Untitled"

    @classmethod
    def label_format_ok(cls, label):
        return ':' not in label and 0 < len(label) < 129


class NTFSLabeling(FSLabeling):

    default_label = ""

    @classmethod
    def label_format_ok(cls, label):
        return len(label) < 129


class F2FSLabeling(FSLabeling):

    default_label = ""

    @classmethod
    def label_format_ok(cls, label):
        return len(label) < 513
