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

from six import add_metaclass

from ..errors import FSError, FSWriteLabelError, FSWriteUUIDError
from .. import util

from . import availability
from . import fstask
from . import task


@add_metaclass(abc.ABCMeta)
class FSMkfsTask(fstask.FSTask):

    can_label = abc.abstractproperty(doc="whether this task labels")
    can_set_uuid = abc.abstractproperty(doc="whether this task can set UUID")


@add_metaclass(abc.ABCMeta)
class FSMkfs(task.BasicApplication, FSMkfsTask):

    """An abstract class that represents filesystem creation actions. """
    description = "mkfs"

    label_option = abc.abstractproperty(
        doc="Option for setting a filesystem label.")

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

    def _format_options(self, options=None, label=False, set_uuid=False):
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
        create_options = shlex.split(self.fs.create_options or "")
        return (options + self.args + label_options + uuid_options +
                create_options + [self.fs.device])

    def _mkfs_command(self, options, label, set_uuid):
        """Return the command to make the filesystem.

           :param options: any special options
           :type options: list of str or None
           :param label: whether to set a label
           :type label: bool
           :param set_uuid: whether to set an UUID
           :type set_uuid: bool
           :returns: the mkfs command
           :rtype: list of str
        """
        return [str(self.ext)] + self._format_options(options, label, set_uuid)

    def do_task(self, options=None, label=False, set_uuid=False):
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
        cmd = self._mkfs_command(options, label, set_uuid)
        try:
            ret = util.run_program(cmd)
        except OSError as e:
            raise FSError(e)

        if ret:
            raise FSError("format failed: %s" % ret)


class BTRFSMkfs(FSMkfs):
    ext = availability.MKFS_BTRFS_APP
    label_option = None

    def get_uuid_args(self, uuid):
        return ["-U", uuid]

    @property
    def args(self):
        return []


class Ext2FSMkfs(FSMkfs):
    ext = availability.MKE2FS_APP
    label_option = "-L"

    _opts = []

    def get_uuid_args(self, uuid):
        return ["-U", uuid]

    @property
    def args(self):
        return self._opts + (["-T", self.fs.fsprofile] if self.fs.fsprofile else [])


class Ext3FSMkfs(Ext2FSMkfs):
    _opts = ["-t", "ext3"]


class Ext4FSMkfs(Ext3FSMkfs):
    _opts = ["-t", "ext4"]


class FATFSMkfs(FSMkfs):
    ext = availability.MKDOSFS_APP
    label_option = "-n"

    def get_uuid_args(self, uuid):
        return ["-i", uuid.replace('-', '')]

    @property
    def args(self):
        return []


class GFS2Mkfs(FSMkfs):
    ext = availability.MKFS_GFS2_APP
    label_option = None
    get_uuid_args = None

    @property
    def args(self):
        return ["-j", "1", "-p", "lock_nolock", "-O"]


class HFSMkfs(FSMkfs):
    ext = availability.HFORMAT_APP
    label_option = "-l"
    get_uuid_args = None

    @property
    def args(self):
        return []


class HFSPlusMkfs(FSMkfs):
    ext = availability.MKFS_HFSPLUS_APP
    label_option = "-v"
    get_uuid_args = None

    @property
    def args(self):
        return []


class JFSMkfs(FSMkfs):
    ext = availability.MKFS_JFS_APP
    label_option = "-L"
    get_uuid_args = None

    @property
    def args(self):
        return ["-q"]


class NTFSMkfs(FSMkfs):
    ext = availability.MKNTFS_APP
    label_option = "-L"
    get_uuid_args = None

    @property
    def args(self):
        return []


class ReiserFSMkfs(FSMkfs):
    ext = availability.MKREISERFS_APP
    label_option = "-l"

    def get_uuid_args(self, uuid):
        return ["-u", uuid]

    @property
    def args(self):
        return ["-f", "-f"]


class XFSMkfs(FSMkfs):
    ext = availability.MKFS_XFS_APP
    label_option = "-L"

    def get_uuid_args(self, uuid):
        return ["-m", "uuid=" + uuid]

    @property
    def args(self):
        return ["-f"]


class F2FSMkfs(FSMkfs):
    ext = availability.MKFS_F2FS_APP
    label_option = "-l"
    get_uuid_args = None

    @property
    def args(self):
        return []


class UnimplementedFSMkfs(task.UnimplementedTask, FSMkfsTask):

    @property
    def can_label(self):
        return False

    @property
    def can_set_uuid(self):
        return False
