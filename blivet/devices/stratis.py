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

import uuid

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from ..static_data import stratis_info
from ..storage_log import log_method_call
from ..errors import DeviceError
from .. import devicelibs


class StratisPoolDevice(StorageDevice):
    """ A stratis pool device """

    _type = "stratis_pool"
    _resizable = False
    _packages = ["stratisd", "stratis-cli"]
    _dev_dir = "/dev/stratis"

    @property
    def size(self):
        """ The size of this pool """
        # sum up the sizes of the block devices
        return sum(parent.size for parent in self.parents)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        bd_list = [bd.path for bd in self.parents]
        devicelibs.stratis.create_pool(self.name, bd_list)

    def _post_create(self):
        super(StratisPoolDevice, self)._post_create()
        self.format.exists = True

        # refresh stratis info
        stratis_info.drop_cache()

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

    def dracut_setup_args(self):
        return set(["stratis.rootfs.pool_uuid=%s" % self.uuid] +
                   ["stratis.rootfs.uuids_paths=/dev/disk/by-uuid/%s" % str(uuid.UUID(p.uuid)) for p in self.parents])


class StratisFilesystemDevice(StorageDevice):
    """ A stratis pool device """

    _type = "stratis_filesystem"
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

    @property
    def path(self):
        return "%s/%s/%s" % (self._dev_dir, self.pool.name, self.fsname)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.create_filesystem(self.fsname, self.pool.uuid)

    def _post_create(self):
        super(StratisFilesystemDevice, self)._post_create()

        # refresh stratis info
        stratis_info.drop_cache()

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
