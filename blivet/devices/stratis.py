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

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from ..static_data import stratis_info
from ..size import Size
from ..storage_log import log_method_call
from .. import devicelibs


class StratisPoolDevice(StorageDevice):
    """ A stratis pool device """

    _type = "stratis_pool"
    _resizable = False
    _packages = ["stratisd", "stratis-cli"]
    _dev_dir = "/dev/stratis"

    def read_current_size(self):
        size = Size(0)
        if self.exists and self.uuid in stratis_info.pools.keys():
            size = stratis_info.pools[self.uuid].physical_size
        return size

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.remove_pool(self.uuid)

    def dracut_setup_args(self):
        return set(["stratis.rootfs.pool_uuid=%s" % self.uuid] +
                   ["stratis.rootfs.uuids_paths=/dev/disk/by-uuid/%s" % p.uuid for p in self.parents])


class StratisFilesystemDevice(StorageDevice):
    """ A stratis pool device """

    _type = "stratis_filesystem"
    _resizable = False
    _packages = ["stratisd", "stratis-cli"]
    _dev_dir = "/dev/stratis"

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

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        devicelibs.stratis.remove_filesystem(self.pool.uuid, self.uuid)

    def dracut_setup_args(self):
        return set(["root=%s" % self.path])
