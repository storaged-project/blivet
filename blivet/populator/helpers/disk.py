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
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from ... import udev
from ... import util
from ...devices import DASDDevice, DiskDevice, FcoeDiskDevice, iScsiDiskDevice
from ...devices import MDBiosRaidArrayDevice, ZFCPDiskDevice, NVDIMMNamespaceDevice
from ...devices import device_path_to_name
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator

import logging
log = logging.getLogger("blivet")


class DiskDevicePopulator(DevicePopulator):
    priority = 10
    _device_class = DiskDevice

    @classmethod
    def match(cls, data):
        return udev.device_is_disk(data)

    def _get_kwargs(self):
        sysfs_path = udev.device_get_sysfs_path(self.data)
        kwargs = {
            "sysfs_path": sysfs_path,
            "serial": udev.device_get_serial(self.data),
            "vendor": util.get_sysfs_attr(sysfs_path, "device/vendor"),
            "model": util.get_sysfs_attr(sysfs_path, "device/model"),
            "bus": udev.device_get_bus(self.data),
            "wwn": udev.device_get_wwn(self.data)
        }

        if self._device_class == DiskDevice:
            kwargs["major"] = udev.device_get_major(self.data)
            kwargs["minor"] = udev.device_get_minor(self.data)
            log.info("%s is a disk", udev.device_get_name(self.data))

        return kwargs

    def run(self):
        name = udev.device_get_name(self.data)
        log_method_call(self, name=name)

        kwargs = self._get_kwargs()
        device = self._device_class(name, **kwargs)
        self._devicetree._add_device(device)
        return device


class iScsiDevicePopulator(DiskDevicePopulator):
    priority = 20
    _device_class = iScsiDiskDevice

    @classmethod
    def match(cls, data):
        from ...iscsi import iscsi
        return (super(iScsiDevicePopulator, iScsiDevicePopulator).match(data) and
                udev.device_is_iscsi(data) and iscsi.initiator and
                iscsi.initiator == udev.device_get_iscsi_initiator(data))

    def _get_kwargs(self):
        from ...iscsi import iscsi
        kwargs = super(iScsiDevicePopulator, self)._get_kwargs()
        kwargs["initiator"] = udev.device_get_iscsi_initiator(self.data)
        kwargs["address"] = udev.device_get_iscsi_address(self.data)
        kwargs["port"] = udev.device_get_iscsi_port(self.data)
        kwargs["target"] = udev.device_get_iscsi_name(self.data)
        kwargs["lun"] = udev.device_get_iscsi_lun(self.data)
        kwargs["name"] = udev.device_get_name(self.data)
        kwargs["iface"] = udev.device_get_iscsi_nic(self.data)
        kwargs["offload"] = kwargs["initiator"] != iscsi.initiator
        kwargs["id_path"] = udev.device_get_path(self.data)
        log.info("%s is an iscsi disk", kwargs["name"])

        # Backward compatibility attributes - to be removed
        if kwargs["offload"]:
            # qla4xxx partial offload
            kwargs["node"] = None
            kwargs["ibft"] = False
            kwargs["nic"] = "offload:not_accessible_via_iscsiadm"
        else:
            node = iscsi.get_node(kwargs["target"],
                                  kwargs["address"],
                                  kwargs["port"],
                                  kwargs["iface"])
            kwargs["node"] = node
            kwargs["ibft"] = node in iscsi.ibft_nodes
            if node:
                kwargs["nic"] = iscsi.ifaces.get(node.iface, node.iface)
            else:
                kwargs["nic"] = ""

        return kwargs


class FCoEDevicePopulator(DiskDevicePopulator):
    priority = 20

    _device_class = FcoeDiskDevice

    @classmethod
    def match(cls, data):
        return (super(FCoEDevicePopulator, FCoEDevicePopulator).match(data) and
                udev.device_is_fcoe(data))

    def _get_kwargs(self):
        kwargs = super(FCoEDevicePopulator, self)._get_kwargs()
        kwargs["nic"] = udev.device_get_fcoe_nic(self.data)
        kwargs["identifier"] = udev.device_get_fcoe_identifier(self.data)
        kwargs["id_path"] = udev.device_get_path(self.data)
        log.info("%s is an fcoe disk", udev.device_get_name(self.data))
        return kwargs


class MDBiosRaidDevicePopulator(DiskDevicePopulator):
    priority = 20

    _device_class = MDBiosRaidArrayDevice

    @classmethod
    def match(cls, data):
        return (super(MDBiosRaidDevicePopulator, MDBiosRaidDevicePopulator).match(data) and
                udev.device_get_md_container(data))

    def _get_kwargs(self):
        kwargs = super(MDBiosRaidDevicePopulator, self)._get_kwargs()
        parent_path = udev.device_get_md_container(self.data)
        parent_name = device_path_to_name(parent_path)
        container = self._devicetree.get_device_by_name(parent_name)

        # FIXME: Move this whole block to an add_parent_devices method or similar
        if not container:
            parent_sys_name = blockdev.md.node_from_name(parent_name)
            container_sysfs = "/sys/class/block/" + parent_sys_name
            container_info = udev.get_device(container_sysfs)
            if not container_info:
                log.error("failed to find md container %s at %s",
                          parent_name, container_sysfs)
                return

            self._devicetree.handle_device(container_info)
            container = self._devicetree.get_device_by_name(parent_name)
            if not container:
                log.error("failed to scan md container %s", parent_name)
                return

        kwargs["parents"] = [container]
        kwargs["level"] = udev.device_get_md_level(self.data)
        kwargs["member_devices"] = udev.device_get_md_devices(self.data)
        kwargs["uuid"] = udev.device_get_md_uuid(self.data)
        kwargs["exists"] = True
        # remove some kwargs that don't make sense for md
        del kwargs["model"]
        del kwargs["serial"]
        del kwargs["vendor"]
        del kwargs["bus"]
        del kwargs["wwn"]
        return kwargs


class DASDDevicePopulator(DiskDevicePopulator):
    priority = 20

    _device_class = DASDDevice

    @classmethod
    def match(cls, data):
        return (super(DASDDevicePopulator, DASDDevicePopulator).match(data) and
                udev.device_is_dasd(data))

    def _get_kwargs(self):
        kwargs = super(DASDDevicePopulator, self)._get_kwargs()
        kwargs["busid"] = udev.device_get_dasd_bus_id(self.data)
        kwargs["opts"] = {}
        for attr in ['readonly', 'use_diag', 'erplog', 'failfast']:
            kwargs["opts"][attr] = udev.device_get_dasd_flag(self.data, attr)

        log.info("%s is a dasd device", udev.device_get_name(self.data))
        return kwargs


class ZFCPDevicePopulator(DiskDevicePopulator):
    priority = 20

    _device_class = ZFCPDiskDevice

    @classmethod
    def match(cls, data):
        return (super(ZFCPDevicePopulator, ZFCPDevicePopulator).match(data) and
                udev.device_is_zfcp(data))

    def _get_kwargs(self):
        kwargs = super(ZFCPDevicePopulator, self)._get_kwargs()

        for attr in ['hba_id', 'wwpn', 'fcp_lun']:
            kwargs[attr] = udev.device_get_zfcp_attribute(self.data, attr=attr)

        log.info("%s is a zfcp device", udev.device_get_name(self.data))
        return kwargs


class NVDIMMNamespaceDevicePopulator(DiskDevicePopulator):
    priority = 20

    _device_class = NVDIMMNamespaceDevice

    @classmethod
    def match(cls, data):
        return (super(NVDIMMNamespaceDevicePopulator, NVDIMMNamespaceDevicePopulator).match(data) and
                udev.device_is_nvdimm_namespace(data))

    def _get_kwargs(self):
        kwargs = super(NVDIMMNamespaceDevicePopulator, self)._get_kwargs()

        from ...static_data import nvdimm
        ninfo = nvdimm.get_namespace_info(self.data.get("DEVNAME"))

        kwargs["mode"] = blockdev.nvdimm_namespace_get_mode_str(ninfo.mode)
        kwargs["devname"] = ninfo.dev
        kwargs["uuid"] = ninfo.uuid
        kwargs["sector_size"] = ninfo.sector_size
        kwargs["id_path"] = udev.device_get_path(self.data)

        log.info("%s is an NVDIMM namespace device", udev.device_get_name(self.data))
        return kwargs
