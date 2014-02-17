#!/usr/bin/python

import unittest
from mock import Mock

import parted

import pyanaconda.anaconda_log
pyanaconda.anaconda_log.init()

import pyanaconda.iutil
import blivet as blivet
from blivet.formats import getFormat

# device classes for brevity's sake -- later on, that is
from blivet.devices import StorageDevice
from blivet.devices import DiskDevice
from blivet.devices import PartitionDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import DMDevice
from blivet.devices import LUKSDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import FileDevice


class StorageTestCase(unittest.TestCase):
    """ StorageTestCase

        This is a base class for storage test cases. It sets up imports of
        the blivet package, along with an Anaconda instance and a Storage
        instance. There are lots of little patches to prevent various pieces
        of code from trying to access filesystems and/or devices on the host
        system, along with a couple of convenience methods.

    """
    def __init__(self, *args, **kwargs):
        pyanaconda.iutil.execWithRedirect = Mock()
        pyanaconda.iutil.execWithCapture = Mock()
        super(StorageTestCase, self).__init__(*args, **kwargs)

        self.setUpStorage()

    def setUpStorage(self):
        self.setUpDeviceLibs()
        self.storage = blivet.Blivet()

        # device status
        blivet.devices.StorageDevice.status = False
        blivet.devices.DMDevice.status = False
        blivet.devices.LUKSDevice.status = False
        blivet.devices.LVMVolumeGroupDevice.status = False
        blivet.devices.MDRaidArrayDevice.status = False
        blivet.devices.FileDevice.status = False

        # prevent PartitionDevice from trying to dig around in the partition's
        # geometry
        blivet.devices.PartitionDevice._setTargetSize = StorageDevice._setTargetSize

        # prevent Ext2FS from trying to run resize2fs to get a filesystem's
        # minimum size
        blivet.formats.fs.Ext2FS.minSize = blivet.formats.DeviceFormat.minSize

    def setUpDeviceLibs(self):
        # devicelibs shouldn't be touching or looking at the host system

        # lvm is easy because all calls to /sbin/lvm are via lvm()
        blivet.devicelibs.lvm.lvm = Mock()

        # mdraid is easy because all calls to /sbin/mdadm are via mdadm()
        blivet.devicelibs.mdraid.mdadm = Mock()

        # swap
        blivet.devicelibs.swap.swapstatus = Mock(return_value=False)
        blivet.devicelibs.swap.swapon = Mock()
        blivet.devicelibs.swap.swapoff = Mock()

        # dm
        blivet.devicelibs.dm = Mock()

        # crypto/luks
	blivet.devicelibs.crypto.luks_status = Mock(return_value=False)
	blivet.devicelibs.crypto.luks_uuid = Mock()
	blivet.devicelibs.crypto.luks_format = Mock()
	blivet.devicelibs.crypto.luks_open = Mock()
	blivet.devicelibs.crypto.luks_close = Mock()
	blivet.devicelibs.crypto.luks_add_key = Mock()
	blivet.devicelibs.crypto.luks_remove_key = Mock()

        # this list would normally be obtained by parsing /proc/mdstat
	blivet.devicelibs.mdraid.raid_levels = \
					[blivet.devicelibs.mdraid.RAID10,
					 blivet.devicelibs.mdraid.RAID0,
					 blivet.devicelibs.mdraid.RAID1,
					 blivet.devicelibs.mdraid.RAID4,
					 blivet.devicelibs.mdraid.RAID5,
					 blivet.devicelibs.mdraid.RAID6]

    def newDevice(*args, **kwargs):
        """ Return a new Device instance suitable for testing. """
        args = args[1:] # drop self arg
        device_class = kwargs.pop("device_class")
        exists = kwargs.pop("exists", False)
        part_type = kwargs.pop("part_type", parted.PARTITION_NORMAL)
        device = device_class(*args, **kwargs)

        if exists:
            # set up mock parted.Device w/ correct size
            device._partedDevice = Mock()
            device._partedDevice.getSize = Mock(return_value=float(device.size))
            device._partedDevice.sectorSize = 512

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
            partedPartition.getSize = Mock(return_value=float(device.size))
            device._partedPartition = partedPartition

        device.exists = exists
        device.format.exists = exists

        if isinstance(device, blivet.devices.PartitionDevice):
            # PartitionDevice.probe sets up data needed for resize operations
            device.probe()

        return device

    def newFormat(*args, **kwargs):
        """ Return a new DeviceFormat instance suitable for testing.

            Keyword Arguments:

                device_instance - StorageDevice instance this format will be
                                  created on. This is needed for setup of
                                  resizable formats.

            All other arguments are passed directly to
            blivet.formats.getFormat.
        """
        args = args[1:] # drop self arg
        exists = kwargs.pop("exists", False)
        device_instance = kwargs.pop("device_instance", None)
        format = getFormat(*args, **kwargs)
        if isinstance(format, blivet.formats.disklabel.DiskLabel):
            format._partedDevice = Mock()
            format._partedDisk = Mock()

        format.exists = exists

        if format.resizable and device_instance:
            format._size = device_instance.currentSize

        return format

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

    def scheduleCreateDevice(self, *args, **kwargs):
        """ Schedule an action to create the specified device.

            Verify that the device is not already in the tree and that the
            act of scheduling/registering the action also adds the device to
            the tree.

            Return the DeviceAction instance.
        """
        device = kwargs.pop("device")
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

    def scheduleDestroyDevice(self, *args, **kwargs):
        """ Schedule an action to destroy the specified device.

            Verify that the device exists initially and that the act of
            scheduling/registering the action also removes the device from
            the tree.

            Return the DeviceAction instance.
        """
        device = kwargs.pop("device")
        devicetree = self.storage.devicetree

        self.assertEqual(devicetree.getDeviceByName(device.name), device)
        action = blivet.deviceaction.ActionDestroyDevice(device)
        devicetree.registerAction(action)
        self.assertEqual(devicetree.getDeviceByName(device.name), None)
        return action

    def scheduleCreateFormat(self, *args, **kwargs):
        """ Schedule an action to write a new format to a device.

            Verify that the device is already in the tree, that it is not
            already set up to contain the specified format, and that the act
            of registering/scheduling the action causes the new format to be
            reflected in the tree.

            Return the DeviceAction instance.
        """
        device = kwargs.pop("device")
        format = kwargs.pop("format")
        devicetree = self.storage.devicetree

        self.assertNotEqual(device.format, format)
        self.assertEqual(devicetree.getDeviceByName(device.name), device)
        action = blivet.deviceaction.ActionCreateFormat(device, format)
        devicetree.registerAction(action)
        _device = devicetree.getDeviceByName(device.name)
        self.assertEqual(_device.format, format)
        return action

    def scheduleDestroyFormat(self, *args, **kwargs):
        """ Schedule an action to remove a format from a device.

            Verify that the device is already in the tree and that the act
            of registering/scheduling the action causes the new format to be
            reflected in the tree.

            Return the DeviceAction instance.
        """
        device = kwargs.pop("device")
        devicetree = self.storage.devicetree

        self.assertEqual(devicetree.getDeviceByName(device.name), device)
        action = blivet.deviceaction.ActionDestroyFormat(device)
        devicetree.registerAction(action)
        _device = devicetree.getDeviceByName(device.name)
        self.assertEqual(_device.format.type, None)
        return action
