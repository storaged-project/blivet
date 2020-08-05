# devices/file.py
# Classes to represent various types of files and directories.
#
# Copyright (C) 2009-2014  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

import os
import stat

from .. import util
from ..storage_log import log_method_call
from ..size import Size

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice


class FileDevice(StorageDevice):

    """ A file on a filesystem.

        This exists because of swap files.
    """
    _type = "file"
    _dev_dir = ""

    def __init__(self, path, fmt=None, size=None,
                 exists=False, parents=None):
        """
            :param path: full path to the file
            :type path: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
        """
        if not os.path.isabs(path):
            raise ValueError("FileDevice requires an absolute path")

        StorageDevice.__init__(self, path, fmt=fmt, size=size,
                               exists=exists, parents=parents)

    @property
    def fstab_spec(self):
        return self.name

    @property
    def path(self):
        try:
            root = self.parents[0].format.system_mountpoint
            mountpoint = self.parents[0].format.mountpoint
        except (AttributeError, IndexError):
            root = ""
        else:
            # trim the mountpoint down to the chroot since we already have
            # the otherwise fully-qualified path
            while mountpoint.endswith("/"):
                mountpoint = mountpoint[:-1]
            if mountpoint:
                root = root[:-len(mountpoint)]

        return os.path.normpath("%s%s" % (root, self.name))

    def read_current_size(self):
        size = Size(0)
        if self.exists and os.path.exists(self.path):
            st = os.stat(self.path)
            size = Size(st[stat.ST_SIZE])

        return size

    def _pre_setup(self, orig=False):
        if self.format and self.format.exists and not self.format.status:
            self.format.device = self.path

        return StorageDevice._pre_setup(self, orig=orig)

    def _pre_teardown(self, recursive=None):
        if self.format and self.format.exists and not self.format.status:
            self.format.device = self.path

        return StorageDevice._pre_teardown(self, recursive=recursive)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        # all this fuss is so we write the zeros 1MiB at a time
        zero = "\0"
        block_size = 1024 ** 2
        (count, rem) = divmod(int(self.size), block_size)

        zeros = zero * block_size
        for _n in range(count):
            os.write(fd, zeros.encode("utf-8"))

        if rem:
            # write out however many more zeros it takes to hit our size target
            size_target = zero * rem
            os.write(fd, size_target.encode("utf-8"))

        os.close(fd)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        os.unlink(self.path)

    def is_name_valid(self, name):
        # Override StorageDevice.is_name_valid to allow /
        return not('\x00' in name or name == '.' or name == '..')

    def update_sysfs_path(self):
        pass


class SparseFileDevice(FileDevice):

    """A sparse file on a filesystem.
    This exists for sparse disk images."""
    _type = "sparse file"

    def _create(self):
        """Create a sparse file."""
        log_method_call(self, self.name, status=self.status)
        util.create_sparse_file(self.path, self.size)


class DirectoryDevice(FileDevice):

    """ A directory on a filesystem.

        This exists because of bind mounts.
    """
    _type = "directory"

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        util.makedirs(self.path)
