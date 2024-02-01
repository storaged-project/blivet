import unittest
from unittest.mock import patch, sentinel, DEFAULT

from blivet.actionlist import ActionList
from blivet.deviceaction import ActionDestroyFormat
from blivet.devices import DiskDevice
from blivet.devices import DiskFile
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import PartitionDevice
from blivet.devicetree import DeviceTree
from blivet.formats import get_format
from blivet.size import Size
from blivet.util import sparsetmpfile


class UnsupportedDiskLabelTestCase(unittest.TestCase):
    def setUp(self):
        disk1 = DiskDevice("testdisk", size=Size("300 GiB"), exists=True,
                           fmt=get_format("disklabel", exists=True))
        disk1.format._supported = False

        with self.assertLogs("blivet", level="INFO") as cm:
            partition1 = PartitionDevice("testpart1", size=Size("150 GiB"), exists=True,
                                         parents=[disk1], fmt=get_format("ext4", exists=True))
        self.assertTrue("disklabel is unsupported" in "\n".join(cm.output))

        with self.assertLogs("blivet", level="INFO") as cm:
            partition2 = PartitionDevice("testpart2", size=Size("100 GiB"), exists=True,
                                         parents=[disk1], fmt=get_format("lvmpv", exists=True))
        self.assertTrue("disklabel is unsupported" in "\n".join(cm.output))

        # To be supported, all of a devices ancestors must be supported.
        disk2 = DiskDevice("testdisk2", size=Size("300 GiB"), exists=True,
                           fmt=get_format("lvmpv", exists=True))

        vg = LVMVolumeGroupDevice("testvg", exists=True, parents=[partition2, disk2])

        lv = LVMLogicalVolumeDevice("testlv", exists=True, size=Size("64 GiB"),
                                    parents=[vg], fmt=get_format("ext4", exists=True))

        with sparsetmpfile("addparttest", Size("50 MiB")) as disk_file:
            disk3 = DiskFile(disk_file)
            disk3.format = get_format("disklabel", device=disk3.path, exists=False)

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
        self.assertFalse(self.partition1.disk.format.supported)
        self.assertFalse(self.partition2.disk.format.supported)
        self.assertEqual(self.partition1.disk, self.disk1)
        self.assertEqual(self.partition2.disk, self.disk1)
        self.assertIsNone(self.partition1.parted_partition)
        self.assertIsNone(self.partition2.parted_partition)
        self.assertFalse(self.partition1.is_magic)
        self.assertFalse(self.partition2.is_magic)

        # Verify that probe returns without changing anything.
        partition1_type = sentinel.partition1_type
        self.partition1._part_type = partition1_type
        self.partition1.probe()
        self.assertEqual(self.partition1.part_type, partition1_type)
        self.partition1._part_type = None

        # partition1 is not resizable even though it contains a resizable filesystem
        self.assertEqual(self.partition1.resizable, False)

        # lv is resizable as usual
        with patch.object(self.lv.format, "_resizable", new=True):
            self.assertEqual(self.lv.resizable, True)

        # the lv's destroy method should call blockdev.lvm.lvremove as usual
        with patch.object(self.lv, "_pre_destroy"):
            with patch("blivet.devices.lvm.blockdev.lvm.lvremove") as lvremove:
                self.lv.destroy()
                self.assertTrue(lvremove.called)

        # the vg's destroy method should call blockdev.lvm.vgremove as usual
        with patch.object(self.vg, "_pre_destroy"):
            with patch.multiple("blivet.devices.lvm.blockdev.lvm",
                                vgreduce=DEFAULT,
                                vgdeactivate=DEFAULT,
                                vgremove=DEFAULT) as mocks:
                self.vg.destroy()
        self.assertTrue(mocks["vgreduce"].called)
        self.assertTrue(mocks["vgdeactivate"].called)
        self.assertTrue(mocks["vgremove"].called)

        # the partition's destroy method shouldn't try to call any disklabel methods
        with patch.object(self.partition2, "_pre_destroy"):
            with patch.object(self.partition2.disk, "original_format") as disklabel:
                self.partition2.destroy()
        self.assertEqual(len(disklabel.mock_calls), 0)
        self.assertTrue(self.partition2.exists)

        # Destroying the disklabel should set all partitions to non-existing.
        # XXX This part is handled by ActionList.
        actions = ActionList()
        unsupported_disklabel = self.disk1.format
        actions.add(ActionDestroyFormat(self.disk1))
        self.assertTrue(self.disk1.format.exists)
        self.assertTrue(self.partition1.exists)
        self.assertTrue(self.partition2.exists)
        with patch.object(unsupported_disklabel, "_pre_destroy"):
            with patch.object(unsupported_disklabel, "_destroy") as destroy:
                with patch.object(actions, "_pre_process"):
                    with patch.object(actions, "_post_process"):
                        actions.process(devices=[self.partition1, self.partition2, self.disk1])

        self.assertTrue(destroy.called)
        self.assertFalse(unsupported_disklabel.exists)
        self.assertFalse(self.partition1.exists)
        self.assertFalse(self.partition2.exists)

    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    def test_recursive_remove(self, *args):  # pylint: disable=unused-argument
        devicetree = DeviceTree()
        devicetree._add_device(self.disk1)
        devicetree._add_device(self.partition1)
        devicetree._add_device(self.partition2)
        devicetree._add_device(self.disk2)
        devicetree._add_device(self.vg)
        devicetree._add_device(self.lv)

        self.assertIn(self.disk1, devicetree.devices)
        self.assertIn(self.partition1, devicetree.devices)
        self.assertIn(self.lv, devicetree.devices)
        self.assertEqual(devicetree.get_device_by_name(self.disk1.name), self.disk1)
        self.assertIsNotNone(devicetree.get_device_by_name(self.partition1.name))
        self.assertIsNotNone(devicetree.get_device_by_name(self.partition1.name, hidden=True))
        self.assertIsNotNone(devicetree.get_device_by_name(self.lv.name, hidden=True))
        self.assertIsNotNone(devicetree.get_device_by_path(self.lv.path, hidden=True))
        self.assertIsNotNone(devicetree.get_device_by_id(self.partition2.id, hidden=True,
                                                         incomplete=True))
        self.assertEqual(len(devicetree.get_dependent_devices(self.disk1)), 4)
        with patch('blivet.devicetree.ActionDestroyFormat.apply'):
            devicetree.recursive_remove(self.disk1)
            self.assertTrue(self.disk1 in devicetree.devices)
            self.assertFalse(self.partition1 in devicetree.devices)
            self.assertFalse(self.partition2 in devicetree.devices)
            self.assertFalse(self.vg in devicetree.devices)
            self.assertFalse(self.lv in devicetree.devices)
