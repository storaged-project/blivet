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

from collections import defaultdict

from .container import ContainerDevice
from .lib import LINUX_SECTOR_SIZE
from .storage import StorageDevice
from ..static_data import stratis_info
from ..storage_log import log_method_call
from ..errors import DeviceError, StratisError, InconsistentParentSectorSize
from ..size import Size, ROUND_DOWN
from ..tasks import availability
from ..util import default_namedtuple
from .. import devicelibs


StratisClevisConfig = default_namedtuple("StratisClevisConfig", ["pin",
                                                                 ("tang_url", None),
                                                                 ("tang_thumbprint", None)])


class StratisPoolDevice(ContainerDevice):
    """ A stratis pool device """

    _type = "stratis pool"
    _resizable = False
    _packages = ["stratisd", "stratis-cli"]
    _dev_dir = "/dev/stratis"
    _format_immutable = True
    _external_dependencies = [availability.STRATISPREDICTUSAGE_APP, availability.STRATIS_DBUS]

    def __init__(self, *args, **kwargs):
        """
            :encrypted: whether this pool is encrypted or not
            :type encrypted: bool
            :keyword passphrase: device passphrase
            :type passphrase: str
            :keyword key_file: path to a file containing a key
            :type key_file: str
            :keyword clevis: clevis configuration
            :type: StratisClevisConfig
        """
        self._encrypted = kwargs.pop("encrypted", False)
        self.__passphrase = kwargs.pop("passphrase", None)
        self._key_file = kwargs.pop("key_file", None)
        self._clevis = kwargs.pop("clevis", None)

        super(StratisPoolDevice, self).__init__(*args, **kwargs)

    @property
    def device_id(self):
        # STRATIS-<pool name>
        return "STRATIS-%s" % self.name

    @property
    def blockdevs(self):
        """ A list of this pool block devices """
        return self.parents[:]

    @property
    def filesystems(self):
        """ A list of this pool block filesystems """
        return self.children[:]

    @property
    def size(self):
        """ The size of this pool """
        # sum up the sizes of the block devices
        return sum(parent.size for parent in self.parents)

    @property
    def _physical_size(self):
        if self.exists:
            pool_info = stratis_info.get_pool_info(self.name)
            if not pool_info:
                raise DeviceError("Failed to get information about pool %s" % self.name)
            return pool_info.physical_size
        else:
            return self.size

    @property
    def _pool_metadata_size(self):
        return devicelibs.stratis.pool_used([bd.size for bd in self.blockdevs],
                                            self.encrypted)

    @property
    def _physical_used(self):
        physical_used = Size(0)

        # filesystems
        for filesystem in self.filesystems:
            physical_used += filesystem.used_size

        # pool metadata
        physical_used += self._pool_metadata_size

        return physical_used

    @property
    def free_space(self):
        """ Free space in the pool usable for new filesystems """
        return self._physical_size - self._physical_used

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
        return bool((self.__passphrase not in ["", None]) or
                    (self._key_file and os.access(self._key_file, os.R_OK)))

    def _pre_create(self):
        super(StratisPoolDevice, self)._pre_create()

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
                                       key_file=self._key_file,
                                       clevis=self._clevis)

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

    def _add_parent(self, parent):
        super(StratisPoolDevice, self)._add_parent(parent)

        # we are creating new pool
        if not self.exists:
            sector_sizes = defaultdict(list)
            for ss, name in [(p.sector_size, p.name) for p in self.blockdevs + [parent]]:  # pylint: disable=no-member
                sector_sizes[ss].append(name)
            if len(sector_sizes.keys()) != 1:
                msg = "Cannot create pool '%s'. "\
                      "The following disks have inconsistent sector size:\n" % self.name
                for sector_size in sector_sizes.keys():
                    msg += "%s: %d\n" % (", ".join(sector_sizes[sector_size]), sector_size)

                raise InconsistentParentSectorSize(msg)

        parent.format.pool_name = self.name
        parent.format.pool_uuid = self.uuid

    def _add(self, member):
        devicelibs.stratis.add_device(self.uuid, member.path)

    def _remove(self, member):
        raise DeviceError("Removing members from a Stratis pool is not supported")

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
    _external_dependencies = [availability.STRATISPREDICTUSAGE_APP, availability.STRATIS_DBUS]
    _min_size = Size("512 MiB")

    def __init__(self, name, parents=None, size=None, uuid=None, exists=False):
        if size is None:
            size = devicelibs.stratis.STRATIS_FS_SIZE

        # round size down to the nearest sector
        if not exists and size % LINUX_SECTOR_SIZE:
            log.info("%s: rounding size %s down to the nearest sector", name, size)
            size = size.round_to_nearest(LINUX_SECTOR_SIZE, ROUND_DOWN)

        if not exists and parents[0].free_space <= devicelibs.stratis.filesystem_md_size(size):
            raise StratisError("cannot create new stratis filesystem, not enough free space in the pool")

        super(StratisFilesystemDevice, self).__init__(name=name, size=size, uuid=uuid,
                                                      parents=parents, exists=exists)

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
    def device_id(self):
        # STRATIS-<pool name>/<fsname>
        return "STRATIS-%s/%s" % (self.pool.name, self.fsname)

    @property
    def pool(self):
        if not self.parents:
            # this should never happen but just to be sure
            return None

        return self.parents[0]

    @property
    def used_size(self):
        """ Size used by this filesystem in the pool """
        if not self.exists:
            return devicelibs.stratis.filesystem_md_size(self.size)
        else:
            fs_info = stratis_info.get_filesystem_info(self.pool.name, self.fsname)
            if not fs_info:
                raise DeviceError("Failed to get information about filesystem %s" % self.name)
            return fs_info.used_size

    def _set_size(self, newsize):
        log_method_call(self, self.name,
                        status=self.status, size=self._size, newsize=newsize)
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if not self.exists:
            md_size = devicelibs.stratis.filesystem_md_size(newsize)
            if md_size > self.pool.free_space:
                raise DeviceError("not enough free space in pool")

        super(StratisFilesystemDevice, self)._set_size(newsize)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.create_filesystem(name=self.fsname, pool_uuid=self.pool.uuid,
                                             fs_size=self.size)

    def _post_create(self):
        super(StratisFilesystemDevice, self)._post_create()

        fs_info = stratis_info.get_filesystem_info(self.pool.name, self.fsname)
        if not fs_info:
            raise DeviceError("Failed to get information about newly created filesystem %s" % self.name)
        self.uuid = fs_info.uuid

        self.format.pool_uuid = fs_info.pool_uuid

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.remove_filesystem(self.pool.uuid, self.uuid)

    def dracut_setup_args(self):
        return set(["root=%s" % self.path])
