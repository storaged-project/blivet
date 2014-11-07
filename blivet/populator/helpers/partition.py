# populator/helpers/partition.py
# Partition backend code for populating a DeviceTree.
#
# Copyright (C) 2009-2015  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

import os

import gi
gi.require_version("BlockDev", "1.0")
from gi.repository import BlockDev as blockdev

from ... import udev
from ...devicelibs import lvm
from ...devices import PartitionDevice
from ...errors import CorruptGPTError, DeviceError, DiskLabelScanError
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator

import logging
log = logging.getLogger("blivet")


class PartitionDevicePopulator(DevicePopulator):
    priority = 0

    @classmethod
    def match(cls, data):
        return (udev.device_is_partition(data) or udev.device_is_dm_partition(data))

    def run(self):
        name = udev.device_get_name(self.data)
        log_method_call(self, name=name)
        sysfs_path = udev.device_get_sysfs_path(self.data)

        if name.startswith("md"):
            name = blockdev.md.name_from_node(name)
            device = self._devicetree.get_device_by_name(name)
            if device:
                return device

        disk_name = udev.device_get_partition_disk(self.data)
        if disk_name.startswith("md"):
            disk_name = blockdev.md.name_from_node(disk_name)
        disk = self._devicetree.get_device_by_name(disk_name)

        if disk is None:
            # create a device instance for the disk
            new_info = udev.get_device(os.path.dirname(sysfs_path))
            if new_info:
                self._devicetree.handle_device(new_info)
                disk = self._devicetree.get_device_by_name(disk_name)

            if disk is None:
                # if the current device is still not in
                # the tree, something has gone wrong
                log.error("failure scanning device %s", disk_name)
                lvm.lvm_cc_addFilterRejectRegexp(name)
                return

        if not disk.partitioned:
            # Ignore partitions on:
            #  - devices we do not support partitioning of, like logical volumes
            #  - devices that do not have a usable disklabel
            #  - devices that contain disklabels made by isohybrid
            #
            if disk.partitionable and \
               disk.format.type != "iso9660" and \
               not disk.format.hidden and \
               not self._devicetree._is_ignored_disk(disk):
                if self.data.get("ID_PART_TABLE_TYPE") == "gpt":
                    msg = "corrupt gpt disklabel on disk %s" % disk.name
                    cls = CorruptGPTError
                else:
                    msg = "failed to scan disk %s" % disk.name
                    cls = DiskLabelScanError

                raise cls(msg)

            # there's no need to filter partitions on members of multipaths or
            # fwraid members from lvm since multipath and dmraid are already
            # active and lvm should therefore know to ignore them
            if not disk.format.hidden:
                lvm.lvm_cc_addFilterRejectRegexp(name)

            log.debug("ignoring partition %s on %s", name, disk.format.type)
            return

        device = None
        try:
            device = PartitionDevice(name, sysfs_path=sysfs_path,
                                     uuid=udev.device_get_partition_uuid(self.data),
                                     major=udev.device_get_major(self.data),
                                     minor=udev.device_get_minor(self.data),
                                     exists=True, parents=[disk])
        except DeviceError as e:
            # corner case sometime the kernel accepts a partition table
            # which gets rejected by parted, in this case we will
            # prompt to re-initialize the disk, so simply skip the
            # faulty partitions.
            # XXX not sure about this
            log.error("Failed to instantiate PartitionDevice: %s", e)
            return

        self._devicetree._add_device(device)
        return device
