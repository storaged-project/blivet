# populator/helpers/disk.py
# Disk backend code for populating a DeviceTree.
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

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

from ... import udev
from ... import util
from ...devices import DASDDevice, DiskDevice, FcoeDiskDevice, iScsiDiskDevice
from ...devices import MDBiosRaidArrayDevice, ZFCPDiskDevice
from ...devices import device_path_to_name
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator

import logging
log = logging.getLogger("blivet")


class DiskDevicePopulator(DevicePopulator):
    priority = 10

    @classmethod
    def match(cls, data):
        return (udev.device_is_disk(data) and
                not udev.device_is_cdrom(data) and
                not udev.device_is_partition(data) and
                not udev.device_is_dm(data) and
                not (udev.device_is_md(data) and not udev.device_get_md_container(data)))

    def run(self):
        name = udev.device_get_name(self.data)
        log_method_call(self, name=name)
        sysfs_path = udev.device_get_sysfs_path(self.data)
        serial = udev.device_get_serial(self.data)
        bus = udev.device_get_bus(self.data)

        vendor = util.get_sysfs_attr(sysfs_path, "device/vendor")
        model = util.get_sysfs_attr(sysfs_path, "device/model")

        kwargs = {"serial": serial, "vendor": vendor, "model": model, "bus": bus}
        if udev.device_is_iscsi(self.data) and not self._populator._cleanup:
            disk_type = iScsiDiskDevice
            initiator = udev.device_get_iscsi_initiator(self.data)
            target = udev.device_get_iscsi_name(self.data)
            address = udev.device_get_iscsi_address(self.data)
            port = udev.device_get_iscsi_port(self.data)
            nic = udev.device_get_iscsi_nic(self.data)
            kwargs["initiator"] = initiator
            if initiator == self._populator.iscsi.initiator:
                node = self._populator.iscsi.get_node(target, address, port, nic)
                kwargs["node"] = node
                kwargs["ibft"] = node in self._populator.iscsi.ibft_nodes
                kwargs["nic"] = self._populator.iscsi.ifaces.get(node.iface, node.iface)
                log.info("%s is an iscsi disk", name)
            else:
                # qla4xxx partial offload
                kwargs["node"] = None
                kwargs["ibft"] = False
                kwargs["nic"] = "offload:not_accessible_via_iscsiadm"
                kwargs["fw_address"] = address
                kwargs["fw_port"] = port
                kwargs["fw_name"] = name
        elif udev.device_is_fcoe(self.data):
            disk_type = FcoeDiskDevice
            kwargs["nic"] = udev.device_get_fcoe_nic(self.data)
            kwargs["identifier"] = udev.device_get_fcoe_identifier(self.data)
            log.info("%s is an fcoe disk", name)
        elif udev.device_get_md_container(self.data):
            name = udev.device_get_md_name(self.data)
            disk_type = MDBiosRaidArrayDevice
            parent_path = udev.device_get_md_container(self.data)
            parent_name = device_path_to_name(parent_path)
            container = self._populator.devicetree.get_device_by_name(parent_name)
            if not container:
                parent_sys_name = blockdev.md.node_from_name(parent_name)
                container_sysfs = "/sys/class/block/" + parent_sys_name
                container_info = udev.get_device(container_sysfs)
                if not container_info:
                    log.error("failed to find md container %s at %s",
                              parent_name, container_sysfs)
                    return

                self._populator.add_udev_device(container_info)
                container = self._populator.devicetree.get_device_by_name(parent_name)
                if not container:
                    log.error("failed to scan md container %s", parent_name)
                    return

            kwargs["parents"] = [container]
            kwargs["level"] = udev.device_get_md_level(self.data)
            kwargs["member_devices"] = udev.device_get_md_devices(self.data)
            kwargs["uuid"] = udev.device_get_md_uuid(self.data)
            kwargs["exists"] = True
            del kwargs["model"]
            del kwargs["serial"]
            del kwargs["vendor"]
            del kwargs["bus"]
        elif udev.device_is_dasd(self.data) and not self._populator._cleanup:
            disk_type = DASDDevice
            kwargs["busid"] = udev.device_get_dasd_bus_id(self.data)
            kwargs["opts"] = {}

            for attr in ['readonly', 'use_diag', 'erplog', 'failfast']:
                kwargs["opts"][attr] = udev.device_get_dasd_flag(self.data, attr)

            log.info("%s is a dasd device", name)
        elif udev.device_is_zfcp(self.data):
            disk_type = ZFCPDiskDevice

            for attr in ['hba_id', 'wwpn', 'fcp_lun']:
                kwargs[attr] = udev.device_get_zfcp_attribute(self.data, attr=attr)

            log.info("%s is a zfcp device", name)
        else:
            disk_type = DiskDevice
            log.info("%s is a disk", name)

        device = disk_type(name,
                           major=udev.device_get_major(self.data),
                           minor=udev.device_get_minor(self.data),
                           sysfs_path=sysfs_path, **kwargs)

        if disk_type == DASDDevice:
            self._populator.dasd.append(device)

        self._populator.devicetree._add_device(device)
        return device
