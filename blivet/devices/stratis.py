# devices/stratis.py
#
# Copyright (C) 2020  Red Hat, Inc.
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
# Red Hat Author(s): Vojtech Trefny <vtrefny@redhat.com>
#

import os

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from ..static_data import stratis_info
from ..storage_log import log_method_call
from ..errors import DeviceError, StratisError
from .. import devicelibs


class StratisPoolDevice(StorageDevice):
    """ A stratis pool device """

    _type = "stratis pool"
    _resizable = False
    _packages = ["stratisd", "stratis-cli"]
    _dev_dir = "/dev/stratis"
    _format_immutable = True

    def __init__(self, *args, **kwargs):
        """
            :encrypted: whether this pool is encrypted or not
            :type encrypted: bool
            :keyword passphrase: device passphrase
            :type passphrase: str
            :keyword key_file: path to a file containing a key
            :type key_file: str
        """
        self._encrypted = kwargs.pop("encrypted", False)
        self.__passphrase = kwargs.pop("passphrase", None)
        self._key_file = kwargs.pop("key_file", None)

        super(StratisPoolDevice, self).__init__(*args, **kwargs)

    @property
    def size(self):
        """ The size of this pool """
        # sum up the sizes of the block devices
        return sum(parent.size for parent in self.parents)

    @property
    def encrypted(self):
        """ True if this device is encrypted. """
        return self._encrypted

    @encrypted.setter
    def encrypted(self, encrypted):
        self._encrypted = encrypted

    @property
    def key_file(self):
        """ Path to key file to be used in /etc/crypttab """
        return self._key_file

    def _set_passphrase(self, passphrase):
        """ Set the passphrase used to access this device. """
        self.__passphrase = passphrase

    passphrase = property(fset=_set_passphrase)

    @property
    def has_key(self):
        return ((self.__passphrase not in ["", None]) or
                (self._key_file and os.access(self._key_file, os.R_OK)))

    def _pre_create(self, **kwargs):
        super(StratisPoolDevice, self)._pre_create(**kwargs)

        if self.encrypted and not self.has_key:
            raise StratisError("cannot create encrypted stratis pool without key")

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        bd_list = [bd.path for bd in self.parents]
        devicelibs.stratis.create_pool(name=self.name,
                                       devices=bd_list,
                                       encrypted=self.encrypted,
                                       passphrase=self.__passphrase,
                                       key_file=self._key_file)

    def _post_create(self):
        super(StratisPoolDevice, self)._post_create()
        self.format.exists = True

        pool_info = stratis_info.get_pool_info(self.name)
        if not pool_info:
            raise DeviceError("Failed to get information about newly created pool %s" % self.name)
        self.uuid = pool_info.uuid

        for parent in self.parents:
            parent.format.pool_name = self.name
            parent.format.pool_uuid = self.uuid

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.remove_pool(self.uuid)

    def add_hook(self, new=True):
        super(StratisPoolDevice, self).add_hook(new=new)
        if new:
            return

        for parent in self.parents:
            parent.format.pool_name = self.name
            parent.format.pool_uuid = self.uuid

    def remove_hook(self, modparent=True):
        if modparent:
            for parent in self.parents:
                parent.format.pool_name = None
                parent.format.pool_uuid = None

        super(StratisPoolDevice, self).remove_hook(modparent=modparent)

    def dracut_setup_args(self):
        return set(["stratis.rootfs.pool_uuid=%s" % self.uuid])


class StratisFilesystemDevice(StorageDevice):
    """ A stratis pool device """

    _type = "stratis filesystem"
    _resizable = False
    _packages = ["stratisd", "stratis-cli"]
    _dev_dir = "/dev/stratis"

    def __init__(self, *args, **kwargs):
        if kwargs.get("size") is None and not kwargs.get("exists"):
            kwargs["size"] = devicelibs.stratis.STRATIS_FS_SIZE

        super(StratisFilesystemDevice, self).__init__(*args, **kwargs)

    def _get_name(self):
        """ This device's name. """
        if self.pool is not None:
            return "%s/%s" % (self.pool.name, self._name)
        else:
            return super(StratisFilesystemDevice, self)._get_name()

    @property
    def fsname(self):
        """ The Stratis filesystem name (not including pool name). """
        return self._name

    @property
    def pool(self):
        if not self.parents:
            # this should never happen but just to be sure
            return None

        return self.parents[0]

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.create_filesystem(self.fsname, self.pool.uuid)

    def _post_create(self):
        super(StratisFilesystemDevice, self)._post_create()

        fs_info = stratis_info.get_filesystem_info(self.pool.name, self.fsname)
        if not fs_info:
            raise DeviceError("Failed to get information about newly created filesystem %s" % self.name)
        self.uuid = fs_info.uuid

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.remove_filesystem(self.pool.uuid, self.uuid)

    def dracut_setup_args(self):
        return set(["root=%s" % self.path])
