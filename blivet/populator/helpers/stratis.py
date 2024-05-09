# populator/helpers/stratis.py
# Stratis backend code for populating a DeviceTree.
#
# Copyright (C) 2020  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): Vojtech Trefny <vtrefny@redhat.com>
#

import copy
import json

from ...callbacks import callbacks
from ... import udev
from ...formats import get_format
from ...devices.stratis import StratisPoolDevice, StratisFilesystemDevice, StratisClevisConfig
from ...devicelibs.stratis import STRATIS_FS_SIZE
from ...storage_log import log_method_call
from .formatpopulator import FormatPopulator

from ...static_data import stratis_info

import logging
log = logging.getLogger("blivet")


class StratisFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "stratis"

    @classmethod
    def match(cls, data, device):  # pylint: disable=arguments-differ,unused-argument
        if super(StratisFormatPopulator, cls).match(data, device):
            return True

        # locked stratis pools are managed here
        for pool in stratis_info.locked_pools:
            if device.path in pool.devices:
                return True

        # unlocked encrypted pools are also managed here
        if udev.device_get_format(data) == "crypto_LUKS":
            holders = udev.device_get_holders(data)
            if holders:
                fs = udev.device_get_format(holders[0])
                if fs == cls._type_specifier:
                    return True

        return False

    def _get_blockdev_uuid(self):
        if udev.device_get_format(self.data) == "crypto_LUKS":
            holders = udev.device_get_holders(self.data)
            if holders:
                return udev.device_get_uuid(holders[0])

        return udev.device_get_uuid(self.data)

    def _get_kwargs(self):
        kwargs = super(StratisFormatPopulator, self)._get_kwargs()

        name = udev.device_get_name(self.data)
        uuid = self._get_blockdev_uuid()
        kwargs["uuid"] = uuid

        # stratis block device hosting an encrypted pool
        kwargs["locked_pool"] = False
        for pool in stratis_info.locked_pools:
            if self.device.path in pool.devices:
                kwargs["locked_pool"] = True
                kwargs["pool_uuid"] = pool.uuid
                kwargs["locked_pool_key_desc"] = pool.key_desc
                kwargs["locked_pool_clevis_pin"] = pool.clevis
                return kwargs

        bd_info = stratis_info.blockdevs.get(uuid)
        if bd_info:
            if bd_info.pool_name:
                kwargs["pool_name"] = bd_info.pool_name
            else:
                log.warning("Stratis block device %s has no pool_name", name)
            if bd_info.pool_uuid:
                kwargs["pool_uuid"] = bd_info.pool_uuid
            else:
                log.warning("Stratis block device %s has no pool_uuid", name)

        return kwargs

    def _add_pool_device(self):
        bd_info = stratis_info.blockdevs.get(self.device.format.uuid)
        if not bd_info:
            # no info about the stratis block device -> we're done
            return

        if not bd_info.pool_name:
            log.info("stratis block device %s has no pool", self.device.name)
            return

        pool_info = stratis_info.pools.get(bd_info.pool_uuid)
        if pool_info is None:
            log.warning("Failed to get information about Stratis pool %s (%s)",
                        bd_info.pool_name, bd_info.pool_uuid)
            return

        pool_device = self._devicetree.get_device_by_uuid(bd_info.pool_uuid)
        if pool_device and self.device not in pool_device.parents:
            pool_device.parents.append(self.device)
            callbacks.parent_added(device=pool_device, parent=self.device)
        elif pool_device is None:
            # TODO: stratis duplicate pool name

            if pool_info.clevis:
                if pool_info.clevis[0] == "tang":
                    try:
                        data = json.loads(pool_info.clevis[1])
                    except json.JSONDecodeError:
                        log.warning("failed to decode tang configuration for stratis pool %s",
                                    self.device.name)
                        clevis_info = StratisClevisConfig(pin=pool_info.clevis[0])
                    else:
                        clevis_info = StratisClevisConfig(pin=pool_info.clevis[0],
                                                          tang_url=data["url"],
                                                          tang_thumbprint=data["thp"])
                else:
                    clevis_info = StratisClevisConfig(pin=pool_info.clevis[0])
            else:
                clevis_info = None

            pool_device = StratisPoolDevice(pool_info.name,
                                            parents=[self.device],
                                            uuid=pool_info.uuid,
                                            size=pool_info.physical_size,
                                            exists=True,
                                            encrypted=pool_info.encrypted,
                                            clevis=clevis_info)
            self._devicetree._add_device(pool_device)

        # now add filesystems on this pool
        for fs_info in stratis_info.filesystems.values():
            if fs_info.pool_uuid != pool_info.uuid:
                continue

            fs_device = self._devicetree.get_device_by_uuid(fs_info.uuid)
            if fs_device is not None:
                log.debug("stratis filesystem already added %s", fs_info.name)
                continue

            pool_device = self._devicetree.get_device_by_uuid(fs_info.pool_uuid)
            if not pool_device:
                log.info("stratis pool %s has not been added yet", fs_info.pool_name)
                return

            fs_device = StratisFilesystemDevice(fs_info.name, parents=[pool_device],
                                                uuid=fs_info.uuid, size=STRATIS_FS_SIZE,
                                                exists=True)
            self._devicetree._add_device(fs_device)

            # do format handling now
            udev_info = udev.get_device(fs_device.sysfs_path)
            if not udev_info:
                return

            self._devicetree.handle_format(udev_info, fs_device)
            fs_device.original_format = copy.deepcopy(fs_device.format)

    def run(self):
        log_method_call(self, pv=self.device.name)
        super(StratisFormatPopulator, self).run()

        if not self.device.format.locked_pool:
            self._add_pool_device()


class StratisXFSFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "stratis xfs"

    @classmethod
    def match(cls, data, device):  # pylint: disable=arguments-differ,unused-argument
        """ Return True if this helper is appropriate for the given device.

            :param :class:`pyudev.Device` data: udev data describing a device
            :param device: device instance corresponding to the udev data
            :type device: :class:`~.devices.StorageDevice`
            :returns: whether this class is appropriate for the specified device
            :rtype: bool
        """
        if device.type == "stratis filesystem" and udev.device_get_format(data) == "xfs":
            return True

        return False

    def run(self):
        """ Create a format instance and associate it with the device instance. """
        kwargs = self._get_kwargs()
        kwargs["pool_uuid"] = self.device.pool.uuid
        log.info("type detected on '%s' is '%s'", self.device.name, self.type_spec)
        self.device.format = get_format(self.type_spec, **kwargs)
