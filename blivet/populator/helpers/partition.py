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

import copy
import six

from ... import udev
from ...devicelibs import lvm
from ...devices import PartitionDevice
from ...errors import DeviceError
from ...formats import get_format
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

        device = self._devicetree.get_device_by_name(name)
        if device:
            return device

        disk = None
        disk_name = udev.device_get_partition_disk(self.data)
        if disk_name:
            disk = self._devicetree.get_device_by_name(disk_name)
            if disk is None:
                # create a device instance for the disk
                disk_info = six.next((i for i in udev.get_devices()
                                      if udev.device_get_name(i) == disk_name), None)
                if disk_info is not None:
                    self._devicetree.handle_device(disk_info)
                    disk = self._devicetree.get_device_by_name(disk_name)

        if disk is None:
            # if the disk is still not in the tree something has gone wrong
            log.error("failure finding disk for %s", name)
            lvm.lvm_cc_addFilterRejectRegexp(name)
            return

        if not disk.partitioned or not disk.format.supported:
            # Ignore partitions on:
            #  - devices we do not support partitioning of, like logical volumes
            #  - devices that contain disklabels made by isohybrid
            #
            # For partitions on disklabels parted cannot make sense of, go ahead
            # and instantiate a PartitionDevice so our view of the layout is
            # complete.
            if not disk.partitionable or disk.format.type == "iso9660" or disk.format.hidden:
                # there's no need to filter partitions on members of multipaths or
                # fwraid members from lvm since multipath and dmraid are already
                # active and lvm should therefore know to ignore them
                if not disk.format.hidden:
                    lvm.lvm_cc_addFilterRejectRegexp(name)

                log.debug("ignoring partition %s on %s", name, disk.format.type)
                return

            if not disk.partitioned:
                log.info("ignoring '%s' format on disk that contains '%s'", disk.format.type, name)
                disk.format = get_format("disklabel", exists=True, device=disk.path)
                disk.original_format = copy.deepcopy(disk.format)

        try:
            device = PartitionDevice(name, sysfs_path=sysfs_path,
                                     uuid=udev.device_get_partition_uuid(self.data),
                                     major=udev.device_get_major(self.data),
                                     minor=udev.device_get_minor(self.data),
                                     exists=True, parents=[disk])
        except DeviceError as e:
            # This should only happen for the magic whole-disk partition on a sun disklabel.
            log.error("Failed to instantiate PartitionDevice: %s", e)
            return

        self._devicetree._add_device(device)
        return device
