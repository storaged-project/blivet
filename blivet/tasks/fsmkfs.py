# fsmkfs.py
# Filesystem formatting classes.
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
import shlex

from ..errors import FSError, FSWriteLabelError, FSWriteUUIDError
from .. import util

from . import availability
from . import fstask
from . import task

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSMkfsTask(fstask.FSTask, metaclass=abc.ABCMeta):

    can_label = abc.abstractproperty(doc="whether this task labels")
    can_set_uuid = abc.abstractproperty(doc="whether this task can set UUID")
    can_nodiscard = abc.abstractproperty(doc="whether this task can set nodiscard option")


class FSMkfs(task.BasicApplication, FSMkfsTask, metaclass=abc.ABCMeta):

    """An abstract class that represents filesystem creation actions. """
    description = "mkfs"

    label_option = abc.abstractproperty(
        doc="Option for setting a filesystem label.")

    nodiscard_option = abc.abstractproperty(
        doc="Option for setting nodiscrad option for mkfs.")

    args = abc.abstractproperty(doc="options for creating filesystem")

    @abc.abstractmethod
    def get_uuid_args(self, uuid):
        """Return a list of arguments for setting a filesystem UUID.

           :param uuid: the UUID to set
           :type uuid: str
           :rtype: list of str
        """
        raise NotImplementedError

    # IMPLEMENTATION methods

    @property
    def can_label(self):
        """ Whether this task can label the filesystem.

            :returns: True if this task can label the filesystem
            :rtype: bool
        """
        return self.label_option is not None

    @property
    def can_set_uuid(self):
        """Whether this task can set the UUID of a filesystem.

           :returns: True if UUID can be set
           :rtype: bool
        """
        return self.get_uuid_args is not None

    @property
    def can_nodiscard(self):
        """Whether this task can set nodiscard option for a filesystem.

           :returns: True if nodiscard can be set
           :rtype: bool
        """
        return self.nodiscard_option is not None

    @property
    def _label_options(self):
        """ Any labeling options that a particular filesystem may use.

            :returns: labeling options
            :rtype: list of str
        """
        # Do not know how to set label while formatting.
        if self.label_option is None:
            return []

        # No label to set
        if self.fs.label is None:
            return []

        if self.fs.label_format_ok(self.fs.label):
            return [self.label_option, self.fs.label]
        else:
            raise FSWriteLabelError("Choosing not to apply label (%s) during creation of filesystem %s. Label format is unacceptable for this filesystem." % (self.fs.label, self.fs.type))

    @property
    def _nodiscard_option(self):
        """ Any nodiscard options that a particular filesystem may use.

            :returns: nodiscard options
            :rtype: list of str
        """
        # Do not know how to set nodiscard while formatting.
        if self.nodiscard_option is None:
            return []

        # nodiscard option not requested
        if not self.fs._mkfs_nodiscard:
            return []

        return self.nodiscard_option

    @property
    def _uuid_options(self):
        """Any UUID options that a particular filesystem may use.

           :returns: UUID options
           :rtype: list of str
           :raises: FSWriteUUIDError
        """
        if self.get_uuid_args is None or self.fs.uuid is None:
            return []

        if self.fs.uuid_format_ok(self.fs.uuid):
            return self.get_uuid_args(self.fs.uuid)
        else:
            raise FSWriteUUIDError("Choosing not to apply UUID (%s) during"
                                   " creation of filesystem %s. UUID format"
                                   " is unacceptable for this filesystem."
                                   % (self.fs.uuid, self.fs.type))

    def _format_options(self, options=None, label=False, set_uuid=False, nodiscard=False):
        """Get a list of format options to be used when creating the
           filesystem.

           :param options: any special options
           :type options: list of str or None
           :param bool label: if True, label if possible, default is False
           :param bool set_uuid: whether set UUID if possible, default is False
        """
        options = options or []

        if not isinstance(options, list):
            raise FSError("options parameter must be a list.")

        label_options = self._label_options if label else []
        uuid_options = self._uuid_options if set_uuid else []
        nodiscard_option = self._nodiscard_option if nodiscard else []
        create_options = shlex.split(self.fs.create_options or "")
        return (options + self.args + label_options + uuid_options +
                nodiscard_option + create_options + [self.fs.device])

    def _mkfs_command(self, options, label, set_uuid, nodiscard):
        """Return the command to make the filesystem.

           :param options: any special options
           :type options: list of str or None
           :param label: whether to set a label
           :type label: bool
           :param set_uuid: whether to set an UUID
           :type set_uuid: bool
           :param nodiscard: whether to run mkfs with nodiscard option
           :type nodiscard: bool
           :returns: the mkfs command
           :rtype: list of str
        """
        return [str(self.ext)] + self._format_options(options, label, set_uuid, nodiscard)

    def do_task(self, options=None, label=False, set_uuid=False, nodiscard=False):
        """Create the format on the device and label if possible and desired.

           :param options: any special options, may be None
           :type options: list of str or NoneType
           :param bool label: whether to label while creating, default is False
           :param bool set_uuid: whether to set an UUID while creating, default
                                 is False
        """
        # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        options = options or []
        cmd = self._mkfs_command(options, label, set_uuid, nodiscard)
        try:
            ret = util.run_program(cmd)
        except OSError as e:
            raise FSError(e)

        if ret:
            raise FSError("format failed: %s" % ret)


class GFS2Mkfs(FSMkfs):
    ext = availability.MKFS_GFS2_APP
    label_option = "-t"
    nodiscard_option = None
    get_uuid_args = None

    @property
    def args(self):
        return ["-j", "1", "-p", "lock_nolock", "-O"]


class HFSPlusMkfs(FSMkfs):
    ext = availability.MKFS_HFSPLUS_APP
    label_option = "-v"
    nodiscard_option = None
    get_uuid_args = None

    @property
    def args(self):
        return []


class FSBlockDevMkfs(task.BasicApplication, FSMkfsTask, metaclass=abc.ABCMeta):

    """An abstract class that represents filesystem creation actions. """
    description = "mkfs"
    can_nodiscard = False
    can_set_uuid = False
    can_label = False
    fstype = None
    force = False

    def do_task(self, options=None, label=False, set_uuid=False, nodiscard=False):
        """Create the format on the device and label if possible and desired.

           :param options: any special options, may be None
           :type options: list of str or NoneType
           :param bool label: whether to label while creating, default is False
           :param bool set_uuid: whether to set an UUID while creating, default
                                 is False
        """
        # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        if set_uuid and self.fs.uuid and not self.fs.uuid_format_ok(self.fs.uuid):
            raise FSWriteUUIDError("Choosing not to apply UUID (%s) during"
                                   " creation of filesystem %s. UUID format"
                                   " is unacceptable for this filesystem."
                                   % (self.fs.uuid, self.fs.type))
        if label and self.fs.label and not self.fs.label_format_ok(self.fs.label):
            raise FSWriteLabelError("Choosing not to apply label (%s) during"
                                    " creation of filesystem %s. Label format"
                                    " is unacceptable for this filesystem."
                                    % (self.fs.label, self.fs.type))

        if self.fs.create_options:
            create_options = shlex.split(self.fs.create_options)
        else:
            create_options = []
        if options:
            create_options += options

        try:
            bd_options = BlockDev.FSMkfsOptions(label=self.fs.label if label else None,
                                                uuid=self.fs.uuid if set_uuid else None,
                                                no_discard=self.fs._mkfs_nodiscard if nodiscard else False,
                                                force=self.force)
            BlockDev.fs.mkfs(self.fs.device, self.fstype, bd_options, extra={k: '' for k in create_options})
        except BlockDev.FSError as e:
            raise FSError(str(e))


class BTRFSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_BTRFS_MKFS
    fstype = "btrfs"
    can_nodiscard = True
    can_set_uuid = True
    # XXX btrfs supports labels but we don't really support standalone btrfs
    # and use labels as btrfs volume names
    can_label = False


class Ext2FSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_EXT_MKFS
    fstype = "ext2"
    can_nodiscard = True
    can_set_uuid = True
    can_label = True


class Ext3FSMkfs(Ext2FSMkfs):
    fstype = "ext3"


class Ext4FSMkfs(Ext2FSMkfs):
    fstype = "ext4"


class FATFSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_VFAT_MKFS
    fstype = "vfat"
    can_nodiscard = False
    can_set_uuid = True
    can_label = True


class NTFSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_NTFS_MKFS
    fstype = "ntfs"
    can_nodiscard = False
    can_set_uuid = False
    can_label = True


class XFSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_XFS_MKFS
    fstype = "xfs"
    can_nodiscard = True
    can_set_uuid = True
    can_label = True
    force = True


class F2FSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_F2FS_MKFS
    fstype = "f2fs"
    can_nodiscard = True
    can_set_uuid = False
    can_label = True


class UnimplementedFSMkfs(task.UnimplementedTask, FSMkfsTask):

    @property
    def can_label(self):
        return False

    @property
    def can_set_uuid(self):
        return False

    @property
    def can_nodiscard(self):
        return False
