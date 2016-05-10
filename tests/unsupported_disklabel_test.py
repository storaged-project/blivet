# vim:set fileencoding=utf-8

import unittest
from mock import patch, sentinel, DEFAULT

from blivet import Blivet
from blivet.deviceaction import ActionDestroyFormat
from blivet.devices import DiskDevice
from blivet.devices import DiskFile
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import PartitionDevice
from blivet.devicetree import DeviceTree
from blivet.formats import getFormat
from blivet.size import Size
from blivet.util import sparsetmpfile


class UnsupportedDiskLabelTestCase(unittest.TestCase):
    def setUp(self):
        disk1 = DiskDevice("testdisk", size=Size("300 GiB"), exists=True,
                           fmt=getFormat("disklabel", exists=True))
        disk1.format._supported = False
        partition1 = PartitionDevice("testpart1", size=Size("150 GiB"), exists=True,
                                     parents=[disk1], fmt=getFormat("ext4", exists=True))
        partition2 = PartitionDevice("testpart2", size=Size("100 GiB"), exists=True,
                                     parents=[disk1], fmt=getFormat("lvmpv", exists=True))

        # To be supported, all of a devices ancestors must be supported.
        disk2 = DiskDevice("testdisk2", size=Size("300 GiB"), exists=True,
                           fmt=getFormat("lvmpv", exists=True))

        vg = LVMVolumeGroupDevice("testvg", exists=True, parents=[partition2, disk2])

        lv = LVMLogicalVolumeDevice("testlv", exists=True, size=Size("64 GiB"),
                                    parents=[vg], fmt=getFormat("ext4", exists=True))

        with sparsetmpfile("addparttest", Size("50 MiB")) as disk_file:
            disk3 = DiskFile(disk_file)
            disk3.format = getFormat("disklabel", device=disk3.path, exists=False)

        self.disk1 = disk1
        self.disk2 = disk2
        self.disk3 = disk3
        self.partition1 = partition1
        self.partition2 = partition2
        self.vg = vg
        self.lv = lv

    def test_unsupported_disklabel(self):
        """ Test behavior of partitions on unsupported disklabels. """
        # Verify basic properties of the disk and disklabel.
        self.assertTrue(self.disk1.partitioned)
        self.assertFalse(self.disk1.format.supported)
        self.assertTrue(self.disk3.partitioned)
        self.assertTrue(self.disk3.format.supported)  # normal disklabel is supported

        # Verify some basic properties of the partitions.
        self.assertFalse(self.partition1.disklabelSupported)
        self.assertFalse(self.partition2.disklabelSupported)
        self.assertEqual(self.partition1.disk, self.disk1)
        self.assertEqual(self.partition2.disk, self.disk1)
        self.assertIsNone(self.partition1.partedPartition)
        self.assertIsNone(self.partition2.partedPartition)
        self.assertFalse(self.partition1.isMagic)
        self.assertFalse(self.partition2.isMagic)

        # Verify that probe returns without changing anything.
        partition1_type = sentinel.partition1_type
        self.partition1._partType = partition1_type
        self.partition1.probe()
        self.assertEqual(self.partition1.partType, partition1_type)
        self.partition1._partType = None

        # partition1 is not resizable even though it contains a resizable filesystem
        self.assertEqual(self.partition1.resizable, False)

        # lv is resizable as usual
        with patch.object(self.lv.format, "_resizable", new=True):
            self.assertEqual(self.lv.resizable, True)

        # the lv's destroy method should call devicelibs.lvm.lvremove as usual
        with patch.object(self.lv, "_preDestroy"):
            with patch("blivet.devicelibs.lvm.lvremove") as lvremove:
                self.lv.destroy()
                self.assertTrue(lvremove.called)

        # the vg's destroy method should call devicelibs.lvm.vgremove as usual
        with patch.object(self.vg, "_preDestroy"):
            with patch.multiple("blivet.devicelibs.lvm",
                                vgreduce=DEFAULT,
                                vgdeactivate=DEFAULT,
                                vgremove=DEFAULT) as mocks:
                self.vg.destroy()
        self.assertTrue(mocks["vgreduce"].called)
        self.assertTrue(mocks["vgdeactivate"].called)
        self.assertTrue(mocks["vgremove"].called)

        # the partition's destroy method shouldn't try to call any disklabel methods
        with patch.object(self.partition2, "_preDestroy"):
            with patch.object(self.partition2.disk, "originalFormat") as disklabel:
                self.partition2.destroy()
        self.assertEqual(len(disklabel.mock_calls), 0)
        self.assertTrue(self.partition2.exists)

        # Destroying the disklabel should set all partitions to non-existing.
        # XXX This part is handled by ActionList.
        devicetree = DeviceTree()
        devicetree._addDevice(self.disk1)
        devicetree._addDevice(self.partition1)
        devicetree._addDevice(self.partition2)
        devicetree._addDevice(self.disk2)
        devicetree._addDevice(self.vg)
        devicetree._addDevice(self.lv)

        unsupported_disklabel = self.disk1.format
        action = ActionDestroyFormat(self.disk1)
        devicetree._actions.append(action)
        action._applied = True
        self.assertTrue(self.disk1.format.exists)
        self.assertTrue(self.partition1.exists)
        self.assertTrue(self.partition2.exists)
        with patch.object(unsupported_disklabel, "destroy") as destroy:
            with patch.object(devicetree, "_preProcessActions"):
                with patch.object(devicetree, "_postProcessActions"):
                    devicetree.processActions()

        self.assertTrue(destroy.called)
        self.assertFalse(self.partition1.exists)
        self.assertFalse(self.partition2.exists)

    def test_recursiveRemove(self):
        b = Blivet()
        devicetree = b.devicetree
        devicetree._addDevice(self.disk1)
        devicetree._addDevice(self.partition1)
        devicetree._addDevice(self.partition2)
        devicetree._addDevice(self.disk2)
        devicetree._addDevice(self.vg)
        devicetree._addDevice(self.lv)

        self.assertIn(self.disk1, devicetree.devices)
        self.assertIn(self.partition1, devicetree.devices)
        self.assertIn(self.lv, devicetree.devices)
        self.assertEqual(b.devicetree.getDeviceByName(self.disk1.name), self.disk1)
        self.assertIsNotNone(devicetree.getDeviceByName(self.partition1.name))
        self.assertIsNotNone(devicetree.getDeviceByName(self.partition1.name, hidden=True))
        self.assertIsNotNone(devicetree.getDeviceByName(self.lv.name, hidden=True))
        self.assertIsNotNone(devicetree.getDeviceByPath(self.lv.path, hidden=True))
        self.assertIsNotNone(devicetree.getDeviceByID(self.partition2.id, hidden=True,
                                                      incomplete=True))
        self.assertEqual(len(devicetree.getDependentDevices(self.disk1)), 4)
        with patch('blivet.ActionDestroyFormat.apply'):
            b.recursiveRemove(self.disk1)
            self.assertTrue(self.disk1 in devicetree.devices)
            self.assertFalse(self.partition1 in devicetree.devices)
            self.assertFalse(self.partition2 in devicetree.devices)
            self.assertFalse(self.vg in devicetree.devices)
            self.assertFalse(self.lv in devicetree.devices)
