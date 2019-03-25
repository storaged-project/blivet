# populator/helpers/disklabel.py
# Disklabel backend code for populating a DeviceTree.
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
import six

from ... import formats
from ... import udev
from ...errors import InvalidDiskLabelError
from ...storage_log import log_exception_info, log_method_call
from .formatpopulator import FormatPopulator

import logging
log = logging.getLogger("blivet")


class DiskLabelFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "disklabel"

    @classmethod
    def match(cls, data, device):
        # XXX ignore disklabels on multipath or biosraid member disks
        return (bool(udev.device_get_disklabel_type(data)) and
                not udev.device_is_biosraid_member(data) and
                udev.device_get_format(data) != "iso9660" and
                not (device.is_disk and udev.device_get_format(data) == "mpath_member"))

    def _get_kwargs(self):
        kwargs = super(DiskLabelFormatPopulator, self)._get_kwargs()
        kwargs["uuid"] = udev.device_get_disklabel_uuid(self.data)
        return kwargs

    def run(self):
        disklabel_type = udev.device_get_disklabel_type(self.data)
        log_method_call(self, device=self.device.name, label_type=disklabel_type)
        # if there is no disklabel on the device
        # blkid doesn't understand dasd disklabels, so bypass for dasd
        if disklabel_type is None and not \
           (self.device.is_disk and udev.device_is_dasd(self.data)):
            log.debug("device %s does not contain a disklabel", self.device.name)
            return

        if self.device.partitioned:
            # this device is already set up
            log.debug("disklabel format on %s already set up", self.device.name)
            return

        try:
            self.device.setup()
        except Exception:  # pylint: disable=broad-except
            log_exception_info(log.warning,
                               "setup of %s failed, aborting disklabel handler",
                               [self.device.name])
            return

        kwargs = self._get_kwargs()

        # special handling for unsupported partitioned devices
        if not self.device.partitionable:
            try:
                fmt = formats.get_format("disklabel", **kwargs)
            except InvalidDiskLabelError:
                log.warning("disklabel detected but not usable on %s",
                            self.device.name)
            else:
                self.device.format = fmt
            return

        try:
            fmt = formats.get_format("disklabel", **kwargs)
        except InvalidDiskLabelError as e:
            log.info("no usable disklabel on %s", self.device.name)
            log.debug(e)
        else:
            self.device.format = fmt

    def update(self):
        self.device.format.update_parted_disk()

        # Reconcile the new partition list with the old.

        # Remove any partitions that are no longer present from the devicetree.
        #   On GPT we will use the partition UUIDs.
        #   On DOS we will use the partition start/end sectors since the UUIDs are a joke.
        #
        # XXX We use the udev device list because we think it could be more current. Does
        #     this even make sense?
        udev_devices = udev.get_devices()
        parted_partitions = self.device.format.partitions
        for partition in self.device.children[:]:
            start_sector = partition.parted_partition.geometry.start
            udev_device = None
            if self.device.format.label_type == "gpt":
                udev_device = six.next((ud for ud in udev_devices
                                        if udev.device_get_partition_uuid(ud) == partition.uuid),
                                       None)
            else:
                udev_device = six.next((ud for ud in udev_devices
                                        if udev.device_get_partition_disk(ud) == self.device.name and
                                        int(ud.get("ID_PART_ENTRY_OFFSET")) == start_sector),
                                       None)

            if udev_device is None:
                self._devicetree.recursive_remove(partition, modparent=False, actions=False)
                continue

            parted_partition = six.next((pp for pp in parted_partitions
                                         if os.path.basename(pp.path) == udev.device_get_name(udev_device)),
                                        None)
            log.debug("got parted_partition %s for partition %s",
                      parted_partition.path.split("/")[-1], partition.name)
            partition.parted_partition = parted_partition

        # Add any new partitions to the devicetree.
        for parted_partition in self.device.format.partitions:
            partition_name = os.path.basename(parted_partition.path)
            start_sector = parted_partition.geometry.start
            udev_device = six.next((ud for ud in udev_devices
                                    if udev.device_get_name(ud) == partition_name and
                                    int(ud.get("ID_PART_ENTRY_OFFSET")) == start_sector),
                                   None)

            if udev_device is None:
                continue

            self._devicetree.handle_device(udev_device)
