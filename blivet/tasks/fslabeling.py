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
import string

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSLabeling(object, metaclass=abc.ABCMeta):

    """An abstract class that represents filesystem labeling actions.
    """

    @classmethod
    @abc.abstractmethod
    def label_format_ok(cls, label):
        """Returns True if this label is correctly formatted for this
           filesystem, otherwise False.

           :param str label: the label for this filesystem
           :rtype: bool
        """
        raise NotImplementedError

    @classmethod
    def _blockdev_check_label(cls, fstype, label):
        try:
            BlockDev.fs.check_label(fstype, label)
        except BlockDev.FSError:
            return False
        else:
            return True


class Ext2FSLabeling(FSLabeling):

    @classmethod
    def label_format_ok(cls, label):
        return cls._blockdev_check_label("ext2", label)


class FATFSLabeling(FSLabeling):

    @classmethod
    def label_format_ok(cls, label):
        return cls._blockdev_check_label("vfat", label)


class XFSLabeling(FSLabeling):

    @classmethod
    def label_format_ok(cls, label):
        return cls._blockdev_check_label("xfs", label)


class HFSPlusLabeling(FSLabeling):

    @classmethod
    def label_format_ok(cls, label):
        return ':' not in label and 0 < len(label) < 129


class NTFSLabeling(FSLabeling):

    @classmethod
    def label_format_ok(cls, label):
        return cls._blockdev_check_label("ntfs", label)


class F2FSLabeling(FSLabeling):

    @classmethod
    def label_format_ok(cls, label):
        return cls._blockdev_check_label("f2fs", label)


class GFS2Labeling(FSLabeling):

    @classmethod
    def label_format_ok(cls, label):
        try:
            clustername, lockspace = label.split(":")
        except ValueError:
            return False

        if len(clustername) > 32 or len(lockspace) > 30:
            return False

        allowed = string.ascii_letters + string.digits + "-_"
        return all(c in allowed for c in clustername) and all(c in allowed for c in lockspace)
