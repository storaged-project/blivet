#!/usr/bin/python

import unittest
from mock import Mock

import parted

import blivet as blivet
from blivet.formats import getFormat

# device classes for brevity's sake -- later on, that is
from blivet.devices import StorageDevice
from blivet.devices import PartitionDevice

class StorageTestCase(unittest.TestCase):
    """ StorageTestCase

        This is a base class for storage test cases. It sets up imports of
        the blivet package, along with an Anaconda instance and a Storage
        instance. There are lots of little patches to prevent various pieces
        of code from trying to access filesystems and/or devices on the host
        system, along with a couple of convenience methods.

    """
    def setUp(self):
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
        self.partition_set_target = PartitionDevice._setTargetSize
        self.partition_align_target = PartitionDevice.alignTargetSize
        self.partition_max = PartitionDevice.maxSize
        self.partition_min = PartitionDevice.minSize
        blivet.devices.PartitionDevice._setTargetSize = StorageDevice._setTargetSize
        blivet.devices.PartitionDevice.alignTargetSize = StorageDevice.alignTargetSize
        blivet.devices.PartitionDevice.maxSize = StorageDevice.maxSize
        blivet.devices.PartitionDevice.minSize = StorageDevice.minSize

        def partition_probe(device):
            if isinstance(device._partedPartition, Mock):
                # don't clobber a Mock we already set up here
                part_mock = device._partedPartition
            else:
                part_mock = Mock()

            attrs = {"getLength.return_value": int(device._size),
                     "getDeviceNodeName.return_value": device.name,
                     "type": parted.PARTITION_NORMAL}
            part_mock.configure_mock(**attrs)
            device._partedPartition = part_mock
            device._currentSize = device._size
            device._partType = parted.PARTITION_NORMAL
            device._bootable = False

        self.partition_probe = PartitionDevice.probe
        PartitionDevice.probe = partition_probe

    def tearDown(self):
        blivet.devices.StorageDevice.status = self.storage_status
        blivet.devices.DMDevice.status = self.dm_status
        blivet.devices.LUKSDevice.status = self.luks_status
        blivet.devices.LVMVolumeGroupDevice.status = self.vg_status
        blivet.devices.MDRaidArrayDevice.status = self.md_status
        blivet.devices.FileDevice.status = self.file_status

        blivet.devices.PartitionDevice._setTargetSize = self.partition_set_target
        blivet.devices.PartitionDevice.alignTargetSize = self.partition_align_target
        blivet.devices.PartitionDevice.maxSize = self.partition_max
        blivet.devices.PartitionDevice.minSize = self.partition_min

        blivet.devices.PartitionDevice.probe = self.partition_probe

    def newDevice(self, *args, **kwargs):
        """ Return a new Device instance suitable for testing. """
        device_class = kwargs.pop("device_class")
        exists = kwargs.pop("exists", False)
        part_type = kwargs.pop("part_type", parted.PARTITION_NORMAL)
        device = device_class(*args, **kwargs)

        if exists:
            device._currentSize = kwargs.get("size")

        if isinstance(device, blivet.devices.PartitionDevice):
            #if exists:
            #    device.parents = device.req_disks
            device.parents = device.req_disks

            partedPartition = Mock()

            if device.disk:
                part_num = device.name[len(device.disk.name):].split("p")[-1]
                partedPartition.number = int(part_num)

            partedPartition.type = part_type
            partedPartition.path = device.path
            partedPartition.getDeviceNodeName = Mock(return_value=device.name)
            if len(device.parents) == 1:
                disk_name = device.parents[0].name
                number = device.name.replace(disk_name, "")
                try:
                    partedPartition.number = int(number)
                except ValueError:
                    pass

            device._partedPartition = partedPartition
        elif isinstance(device, blivet.devices.LVMVolumeGroupDevice) and exists:
            device._complete = True

        device.exists = exists
        device.format.exists = exists

        if isinstance(device, blivet.devices.PartitionDevice):
            # PartitionDevice.probe sets up data needed for resize operations
            device.probe()

        return device

    def newFormat(self, *args, **kwargs):
        """ Return a new DeviceFormat instance suitable for testing.

            Keyword Arguments:

                device_instance - StorageDevice instance this format will be
                                  created on. This is needed for setup of
                                  resizable formats.

            All other arguments are passed directly to
            blivet.formats.getFormat.
        """
        exists = kwargs.pop("exists", False)
        device_instance = kwargs.pop("device_instance", None)
        fmt = getFormat(*args, **kwargs)
        if isinstance(fmt, blivet.formats.disklabel.DiskLabel):
            fmt._partedDevice = Mock()
            fmt._partedDisk = Mock()
            attrs = {"partitions": []}
            fmt._partedDisk.configure_mock(**attrs)

        fmt.exists = exists
        if exists:
            fmt._resizable = fmt.__class__._resizable

        if fmt.resizable and device_instance:
            fmt._size = device_instance.currentSize

        return fmt

    def destroyAllDevices(self, disks=None):
        """ Remove all devices from the devicetree.

            Keyword Arguments:

                disks - a list of names of disks to remove partitions from

            Note: this is largely ripped off from partitioning.clearPartitions.

        """
        partitions = self.storage.partitions

        # Sort partitions by descending partition number to minimize confusing
        # things like multiple "destroy sda5" actions due to parted renumbering
        # partitions. This can still happen through the UI but it makes sense to
        # avoid it where possible.
        partitions.sort(key=lambda p: p.partedPartition.number, reverse=True)
        for part in partitions:
            if disks and part.disk.name not in disks:
                continue

            devices = self.storage.deviceDeps(part)
            while devices:
                leaves = [d for d in devices if d.isleaf]
                for leaf in leaves:
                    self.storage.destroyDevice(leaf)
                    devices.remove(leaf)

            self.storage.destroyDevice(part)

    def scheduleCreateDevice(self, device):
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

        self.assertEqual(devicetree.getDeviceByName(device.name), None)
        action = blivet.deviceaction.ActionCreateDevice(device)
        devicetree.registerAction(action)
        self.assertEqual(devicetree.getDeviceByName(device.name), device)
        return action

    def scheduleDestroyDevice(self, device):
        """ Schedule an action to destroy the specified device.

            Verify that the device exists initially and that the act of
            scheduling/registering the action also removes the device from
            the tree.

            Return the DeviceAction instance.
        """
        devicetree = self.storage.devicetree

        self.assertEqual(devicetree.getDeviceByName(device.name), device)
        action = blivet.deviceaction.ActionDestroyDevice(device)
        devicetree.registerAction(action)
        self.assertEqual(devicetree.getDeviceByName(device.name), None)
        return action

    def scheduleCreateFormat(self, device, fmt):
        """ Schedule an action to write a new format to a device.

            Verify that the device is already in the tree, that it is not
            already set up to contain the specified format, and that the act
            of registering/scheduling the action causes the new format to be
            reflected in the tree.

            Return the DeviceAction instance.
        """
        devicetree = self.storage.devicetree

        self.assertNotEqual(device.format, fmt)
        self.assertEqual(devicetree.getDeviceByName(device.name), device)
        action = blivet.deviceaction.ActionCreateFormat(device, fmt)
        devicetree.registerAction(action)
        _device = devicetree.getDeviceByName(device.name)
        self.assertEqual(_device.format, fmt)
        return action

    def scheduleDestroyFormat(self, device):
        """ Schedule an action to remove a format from a device.

            Verify that the device is already in the tree and that the act
            of registering/scheduling the action causes the new format to be
            reflected in the tree.

            Return the DeviceAction instance.
        """
        devicetree = self.storage.devicetree

        self.assertEqual(devicetree.getDeviceByName(device.name), device)
        action = blivet.deviceaction.ActionDestroyFormat(device)
        devicetree.registerAction(action)
        _device = devicetree.getDeviceByName(device.name)
        self.assertEqual(_device.format.type, None)
        return action
