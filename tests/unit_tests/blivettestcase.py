
import unittest
from unittest.mock import Mock, patch

import parted

import blivet as blivet
from blivet.formats import get_format

# device classes for brevity's sake -- later on, that is
from blivet.devices import StorageDevice
from blivet.devices import PartitionDevice


class BlivetTestCase(unittest.TestCase):

    """ BlivetUnitTestCase

        This is a base class for unit test cases. It sets up imports of
        the blivet package. There are lots of little patches to prevent various
        pieces of code from trying to access filesystems and/or devices
        on the host system, along with a couple of convenience methods.

    """

    @patch("blivet.formats.fs.Ext4FS.supported", return_value=True)
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    def setUp(self, *args):  # pylint: disable=unused-argument,arguments-differ
        self.storage = blivet.Blivet()

        # device status
        self.storage_status = blivet.devices.StorageDevice.status
        self.dm_status = blivet.devices.DMDevice.status
        self.luks_status = blivet.devices.LUKSDevice.status
        self.vg_status = blivet.devices.LVMVolumeGroupDevice.status
        self.md_status = blivet.devices.MDRaidArrayDevice.status
        self.file_status = blivet.devices.FileDevice.status
        blivet.devices.StorageDevice.status = False
        blivet.devices.DMDevice.status = False
        blivet.devices.LUKSDevice.status = False
        blivet.devices.LVMVolumeGroupDevice.status = False
        blivet.devices.MDRaidArrayDevice.status = False
        blivet.devices.FileDevice.status = False

        # prevent PartitionDevice from trying to dig around in the partition's
        # geometry
        self.partition_set_target = PartitionDevice._set_target_size
        self.partition_align_target = PartitionDevice.align_target_size
        self.partition_max = PartitionDevice.max_size
        self.partition_min = PartitionDevice.min_size
        blivet.devices.PartitionDevice._set_target_size = StorageDevice._set_target_size
        blivet.devices.PartitionDevice.align_target_size = StorageDevice.align_target_size
        blivet.devices.PartitionDevice.max_size = StorageDevice.max_size
        blivet.devices.PartitionDevice.min_size = StorageDevice.min_size

        self.addCleanup(self._clean_up)

        def partition_probe(device):
            if isinstance(device._parted_partition, Mock):
                # don't clobber a Mock we already set up here
                part_mock = device._parted_partition
            else:
                part_mock = Mock()

            attrs = {"getLength.return_value": int(device._size),
                     "getDeviceNodeName.return_value": device.name,
                     "type": parted.PARTITION_NORMAL}
            part_mock.configure_mock(**attrs)
            device._parted_partition = part_mock
            device._current_size = device._size
            device._part_type = parted.PARTITION_NORMAL
            device._bootable = False

        self.partition_probe = PartitionDevice.probe
        PartitionDevice.probe = partition_probe

        self.get_active_mounts = blivet.formats.fs.mounts_cache._get_active_mounts
        blivet.formats.fs.mounts_cache._get_active_mounts = Mock()

    def _clean_up(self):
        blivet.devices.StorageDevice.status = self.storage_status
        blivet.devices.DMDevice.status = self.dm_status
        blivet.devices.LUKSDevice.status = self.luks_status
        blivet.devices.LVMVolumeGroupDevice.status = self.vg_status
        blivet.devices.MDRaidArrayDevice.status = self.md_status
        blivet.devices.FileDevice.status = self.file_status

        blivet.devices.PartitionDevice._set_target_size = self.partition_set_target
        blivet.devices.PartitionDevice.align_target_size = self.partition_align_target
        blivet.devices.PartitionDevice.max_size = self.partition_max
        blivet.devices.PartitionDevice.min_size = self.partition_min

        blivet.devices.PartitionDevice.probe = self.partition_probe

        blivet.formats.fs.mounts_cache._get_active_mounts = self.get_active_mounts

    def new_device(self, *args, **kwargs):
        """ Return a new Device instance suitable for testing. """
        device_class = kwargs.pop("device_class")

        # we intentionally don't pass the "exists" kwarg to the constructor
        # because this causes issues with some devices (especially partitions)
        # but we still need it for some LVs like VDO because we can't create
        # those so we need to fake their existence even for the constructor
        if device_class is blivet.devices.LVMLogicalVolumeDevice:
            exists = kwargs.get("exists", False)
        else:
            exists = kwargs.pop("exists", False)

        part_type = kwargs.pop("part_type", parted.PARTITION_NORMAL)
        device = device_class(*args, **kwargs)

        if exists:
            device._current_size = kwargs.get("size")

        if isinstance(device, blivet.devices.PartitionDevice):
            # if exists:
            #    device.parents = device.req_disks
            device.parents = device.req_disks

            parted_partition = Mock()

            if device.disk:
                part_num = device.name[len(device.disk.name):].split("p")[-1]
                parted_partition.number = int(part_num)

            parted_partition.type = part_type
            parted_partition.path = device.path
            parted_partition.get_device_node_name = Mock(return_value=device.name)
            if len(device.parents) == 1:
                disk_name = device.parents[0].name
                number = device.name.replace(disk_name, "")
                try:
                    parted_partition.number = int(number)
                except ValueError:
                    pass

            device._parted_partition = parted_partition
        elif isinstance(device, blivet.devices.LVMVolumeGroupDevice) and exists:
            device._complete = True

        device.exists = exists
        device.format.exists = exists

        if isinstance(device, blivet.devices.PartitionDevice):
            # PartitionDevice.probe sets up data needed for resize operations
            device.probe()

        return device

    def new_format(self, *args, **kwargs):
        """ Return a new DeviceFormat instance suitable for testing.

            Keyword Arguments:

                device_instance - StorageDevice instance this format will be
                                  created on. This is needed for setup of
                                  resizable formats.

            All other arguments are passed directly to
            blivet.formats.get_format.
        """
        exists = kwargs.pop("exists", False)
        device_instance = kwargs.pop("device_instance", None)
        fmt = get_format(*args, **kwargs)
        if isinstance(fmt, blivet.formats.disklabel.DiskLabel):
            fmt._parted_device = Mock()
            fmt._parted_disk = Mock()
            attrs = {"partitions": []}
            fmt._parted_disk.configure_mock(**attrs)

        fmt.exists = exists
        if exists:
            fmt._resizable = fmt.__class__._resizable

        if fmt.resizable and device_instance:
            fmt._size = device_instance.current_size

        return fmt

    def destroy_all_devices(self, disks=None):
        """ Remove all devices from the devicetree.

            Keyword Arguments:

                disks - a list of names of disks to remove partitions from

            Note: this is largely ripped off from partitioning.clear_partitions.

        """
        partitions = self.storage.partitions

        # Sort partitions by descending partition number to minimize confusing
        # things like multiple "destroy sda5" actions due to parted renumbering
        # partitions. This can still happen through the UI but it makes sense to
        # avoid it where possible.
        partitions.sort(key=lambda p: p.parted_partition.number, reverse=True)
        for part in partitions:
            if disks and part.disk.name not in disks:
                continue

            devices = self.storage.device_deps(part)
            while devices:
                leaves = [d for d in devices if d.isleaf]
                for leaf in leaves:
                    self.storage.destroy_device(leaf)
                    devices.remove(leaf)

            self.storage.destroy_device(part)

    def schedule_create_device(self, device):
        """ Schedule an action to create the specified device.

            Verify that the device is not already in the tree and that the
            act of scheduling/registering the action also adds the device to
            the tree.

            Return the DeviceAction instance.
        """
        if hasattr(device, "req_disks") and \
           len(device.req_disks) == 1 and \
           not device.parents:
            device.parents = device.req_disks

        devicetree = self.storage.devicetree

        self.assertEqual(devicetree.get_device_by_name(device.name), None)
        action = blivet.deviceaction.ActionCreateDevice(device)
        devicetree.actions.add(action)
        self.assertEqual(devicetree.get_device_by_name(device.name), device)
        return action

    def schedule_destroy_device(self, device):
        """ Schedule an action to destroy the specified device.

            Verify that the device exists initially and that the act of
            scheduling/registering the action also removes the device from
            the tree.

            Return the DeviceAction instance.
        """
        devicetree = self.storage.devicetree

        self.assertEqual(devicetree.get_device_by_name(device.name), device)
        action = blivet.deviceaction.ActionDestroyDevice(device)
        devicetree.actions.add(action)
        self.assertEqual(devicetree.get_device_by_name(device.name), None)
        return action

    def schedule_create_format(self, device, fmt):
        """ Schedule an action to write a new format to a device.

            Verify that the device is already in the tree, that it is not
            already set up to contain the specified format, and that the act
            of registering/scheduling the action causes the new format to be
            reflected in the tree.

            Return the DeviceAction instance.
        """
        devicetree = self.storage.devicetree

        self.assertNotEqual(device.format, fmt)
        self.assertEqual(devicetree.get_device_by_name(device.name), device)
        action = blivet.deviceaction.ActionCreateFormat(device, fmt)
        devicetree.actions.add(action)
        _device = devicetree.get_device_by_name(device.name)
        self.assertEqual(_device.format, fmt)
        return action

    def schedule_destroy_format(self, device):
        """ Schedule an action to remove a format from a device.

            Verify that the device is already in the tree and that the act
            of registering/scheduling the action causes the new format to be
            reflected in the tree.

            Return the DeviceAction instance.
        """
        devicetree = self.storage.devicetree

        self.assertEqual(devicetree.get_device_by_name(device.name), device)
        action = blivet.deviceaction.ActionDestroyFormat(device)
        devicetree.actions.add(action)
        _device = devicetree.get_device_by_name(device.name)
        self.assertEqual(_device.format.type, None)
        return action
