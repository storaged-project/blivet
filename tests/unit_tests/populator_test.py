import unittest
from unittest.mock import call, patch, sentinel, Mock, PropertyMock

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev as blockdev

from blivet.devices import DiskDevice, DMDevice, FileDevice, LoopDevice
from blivet.devices import MDRaidArrayDevice, MultipathDevice, OpticalDevice
from blivet.devices import PartitionDevice, StorageDevice
from blivet.devices import NVMeNamespaceDevice, NVMeFabricsNamespaceDevice
from blivet.devicelibs import lvm
from blivet.devicetree import DeviceTree
from blivet.formats import get_device_format_class, get_format, DeviceFormat
from blivet.formats.disklabel import DiskLabel
from blivet.populator.helpers import DiskDevicePopulator, DMDevicePopulator, LoopDevicePopulator
from blivet.populator.helpers import LVMDevicePopulator, MDDevicePopulator, MultipathDevicePopulator
from blivet.populator.helpers import OpticalDevicePopulator, PartitionDevicePopulator
from blivet.populator.helpers import LVMFormatPopulator, MDFormatPopulator
from blivet.populator.helpers import NVMeNamespaceDevicePopulator, NVMeFabricsNamespaceDevicePopulator
from blivet.populator.helpers import get_format_helper, get_device_helper
from blivet.populator.helpers.boot import EFIFormatPopulator, MacEFIFormatPopulator
from blivet.populator.helpers.formatpopulator import FormatPopulator
from blivet.populator.helpers.disklabel import DiskLabelFormatPopulator
from blivet.size import Size


class PopulatorHelperTestCase(unittest.TestCase):
    helper_class = None


class DMDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = DMDevicePopulator

    @patch("blivet.udev.device_is_dm_luks", return_value=False)
    @patch("blivet.udev.device_is_dm_integrity", return_value=False)
    @patch("blivet.udev.device_is_dm_bitlk", return_value=False)
    @patch("blivet.udev.device_is_dm_lvm", return_value=False)
    @patch("blivet.udev.device_is_dm_mpath", return_value=False)
    @patch("blivet.udev.device_is_dm_partition", return_value=False)
    @patch("blivet.udev.device_is_dm_raid", return_value=False)
    @patch("blivet.udev.device_is_dm_stratis", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=True)
    def test_match(self, *args):
        """Test matching of dm device populator."""
        device_is_dm = args[0]
        device_is_dm_luks = args[5]
        self.assertTrue(self.helper_class.match(None))
        device_is_dm.return_value = False
        self.assertFalse(self.helper_class.match(None))

        # verify that setting one of the required False return values to True prevents success
        device_is_dm_luks.return_value = True
        self.assertFalse(self.helper_class.match(None))
        device_is_dm_luks.return_value = False

    @patch("blivet.udev.device_is_dm_luks", return_value=False)
    @patch("blivet.udev.device_is_dm_integrity", return_value=False)
    @patch("blivet.udev.device_is_dm_bitlk", return_value=False)
    @patch("blivet.udev.device_is_dm_lvm", return_value=False)
    @patch("blivet.udev.device_is_dm_mpath", return_value=False)
    @patch("blivet.udev.device_is_dm_partition", return_value=False)
    @patch("blivet.udev.device_is_dm_raid", return_value=False)
    @patch("blivet.udev.device_is_dm_stratis", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for dm devices."""
        device_is_dm = args[0]
        device_is_dm_lvm = args[6]
        data = {'SYS_PATH': 'dummy'}
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_dm.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_dm.return_value = True

        # verify that setting one of the required False return values to True prevents success
        device_is_dm_lvm.return_value = True
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_dm_lvm.return_value = False

    @patch.object(DeviceTree, "get_device_by_name")
    @patch.object(DMDevice, "status", return_value=True)
    @patch.object(DMDevice, "update_sysfs_path")
    @patch.object(DeviceTree, "_add_parent_devices")
    @patch("blivet.udev.device_get_name")
    @patch("blivet.udev.device_get_sysfs_path", return_value=sentinel.sysfs_path)
    def test_run(self, *args):
        """Test dm device populator."""
        device_get_name = args[1]

        devicetree = DeviceTree()

        # The general case for dm devices is that adding the parent devices
        # will result in the dm device itself being in the tree.
        device = Mock()
        device.id = 0
        devicetree.get_device_by_name.return_value = device
        data = {"DM_UUID": sentinel.dm_uuid}
        helper = self.helper_class(devicetree, data)

        parent = Mock()
        parent.id = 0
        parent.parents = []
        devicetree._add_parent_devices.return_value = [parent]
        devicetree._add_device(parent)
        devicetree.get_device_by_name.return_value = None
        device_name = "dmdevice"
        device_get_name.return_value = device_name

        device = helper.run()
        self.assertIsInstance(device, DMDevice)
        self.assertTrue(device in devicetree.devices)
        self.assertEqual(device.dm_uuid, sentinel.dm_uuid)
        self.assertEqual(device.name, device_name)
        self.assertEqual(device.sysfs_path, sentinel.sysfs_path)
        self.assertEqual(list(device.parents), [parent])


class LoopDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = LoopDevicePopulator

    def test_match(self, *args):
        """Test matching of loop device populator."""
        # LoopDevicePopulator.match just runs the check if device is loop
        # The backing file check is now performed in the "run" method.
        # Test intentionally left empty

    @patch("blivet.populator.helpers.loop.blockdev.loop.info")
    @patch("blivet.udev.device_get_name")
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_dm_luks", return_value=False)
    @patch("blivet.udev.device_is_dm_integrity", return_value=False)
    @patch("blivet.udev.device_is_dm_bitlk", return_value=False)
    @patch("blivet.udev.device_is_dm_lvm", return_value=False)
    @patch("blivet.udev.device_is_dm_mpath", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for loop devices."""
        device_is_loop = args[0]
        loop_info = args[7]
        data = {'SYS_PATH': 'dummy'}
        loop_info.return_value = Mock(baking_file="foobar")
        self.assertEqual(get_device_helper(data), self.helper_class)

        loop_info.return_value = Mock(baking_file=None)
        self.assertEqual(get_device_helper(data), self.helper_class)
        loop_info.return_value = Mock(baking_file="foobar")

        # verify that setting one of the required True return values to False prevents success
        device_is_loop.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_loop.return_value = True

        # You can't be assured that setting any of the False return values to True will trigger
        # a failure because the ordering is not complete, meaning any of several device helpers
        # could be the first helper class checked.

    @patch.object(DeviceTree, "get_device_by_name")
    @patch.object(FileDevice, "status", return_value=True)
    @patch.object(LoopDevice, "status", return_value=True)
    @patch("blivet.populator.helpers.loop.blockdev.loop.info")
    @patch("blivet.udev.device_get_name")
    @patch("blivet.udev.device_get_sysfs_path", return_value=sentinel.sysfs_path)
    def test_run(self, *args):
        """Test loop device populator."""
        device_get_name = args[1]
        loop_info = args[2]

        devicetree = DeviceTree()
        data = Mock()

        # Add backing file and loop device.
        devicetree.get_device_by_name.return_value = None
        device_name = "loop3"
        device_get_name.return_value = device_name
        backing_file = "/some/file"

        loop_info.return_value = Mock(backing_file=None)
        helper = self.helper_class(devicetree, data)
        device = helper.run()

        self.assertIsNone(device)

        loop_info.return_value = Mock(backing_file=backing_file)

        device = helper.run()

        self.assertIsInstance(device, LoopDevice)
        self.assertTrue(device in devicetree.devices)
        self.assertTrue(device.exists)
        self.assertEqual(device.name, device_name)
        self.assertIsInstance(device.parents[0], FileDevice)
        self.assertTrue(device.parents[0].exists)

        self.assertEqual(devicetree.get_device_by_name.call_count, 1)  # pylint: disable=no-member
        devicetree.get_device_by_name.assert_called_with(backing_file)  # pylint: disable=no-member


class LVMDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = LVMDevicePopulator

    @patch("blivet.udev.device_is_dm_lvm", return_value=True)
    def test_match(self, *args):
        """Test matching of lvm device populator."""
        device_is_dm_lvm = args[0]
        self.assertTrue(self.helper_class.match(None))
        device_is_dm_lvm.return_value = False
        self.assertFalse(self.helper_class.match(None))

    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_dm_mpath", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_dm_luks", return_value=False)
    @patch("blivet.udev.device_is_dm_integrity", return_value=False)
    @patch("blivet.udev.device_is_dm_bitlk", return_value=False)
    @patch("blivet.udev.device_is_dm_lvm", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for lvm devices."""
        device_is_dm_lvm = args[0]
        data = {'SYS_PATH': 'dummy'}
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_dm_lvm.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_dm_lvm.return_value = True

        # You can't be assured that setting any of the False return values to True will trigger
        # a failure because the ordering is not complete, meaning any of several device helpers
        # could be the first helper class checked.

    @patch.object(DeviceTree, "get_device_by_device_id")
    @patch.object(DeviceTree, "_add_parent_devices")
    @patch("blivet.udev.device_get_name")
    @patch("blivet.udev.device_get_lv_vg_name")
    def test_run(self, *args):
        """Test lvm device populator."""
        device_get_lv_vg_name = args[0]
        device_get_name = args[1]
        get_device_by_device_id = args[3]

        devicetree = DeviceTree()
        data = Mock()

        lv_name = "lvtest"
        vg_name = "vg_test"

        # Add parent devices and then look up the device.
        device_get_name.return_value = lv_name
        devicetree.get_device_by_device_id.return_value = None

        # pylint: disable=unused-argument
        def _get_device_by_device_id(device_id, **kwargs):
            if device_id == "LVM-" + lv_name:
                return sentinel.lv_device

        get_device_by_device_id.side_effect = _get_device_by_device_id
        device_get_lv_vg_name.return_value = vg_name
        helper = self.helper_class(devicetree, data)

        self.assertEqual(helper.run(), sentinel.lv_device)
        self.assertEqual(devicetree.get_device_by_device_id.call_count, 3)  # pylint: disable=no-member
        get_device_by_device_id.assert_has_calls(
            [call("LVM-" + vg_name, hidden=True),
             call("LVM-" + vg_name),
             call("LVM-" + lv_name)])

        # Add parent devices, but the device is still not in the tree
        get_device_by_device_id.side_effect = None
        get_device_by_device_id.return_value = None
        self.assertEqual(helper.run(), None)
        get_device_by_device_id.assert_called_with("LVM-" + lv_name)


class OpticalDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = OpticalDevicePopulator

    @patch("blivet.udev.device_is_cdrom", return_value=True)
    def test_match(self, *args):
        """Test matching of optical device populator."""
        device_is_cdrom = args[0]
        self.assertTrue(self.helper_class.match(None))
        device_is_cdrom.return_value = False
        self.assertFalse(self.helper_class.match(None))

    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_dm_lvm", return_value=False)
    @patch("blivet.udev.device_is_dm_luks", return_value=False)
    @patch("blivet.udev.device_is_dm_integrity", return_value=False)
    @patch("blivet.udev.device_is_dm_bitlk", return_value=False)
    @patch("blivet.udev.device_is_dm_mpath", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_cdrom", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for optical devices."""
        device_is_cdrom = args[0]
        data = {'SYS_PATH': 'dummy'}
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_cdrom.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_cdrom.return_value = True

        # You can't be assured that setting any of the False return values to True will trigger
        # a failure because the ordering is not complete, meaning any of several device helpers
        # could be the first helper class checked.

    @patch("blivet.udev.device_get_major", return_value=99)
    @patch("blivet.udev.device_get_minor", return_value=17)
    @patch("blivet.udev.device_get_sysfs_path", return_value='')
    @patch("blivet.udev.device_get_name")
    def test_run(self, *args):
        """Test optical device populator."""
        device_get_name = args[0]

        devicetree = DeviceTree()
        data = Mock()

        helper = self.helper_class(devicetree, data)
        device_name = "sr0"
        device_get_name.return_value = device_name

        device = helper.run()
        self.assertIsInstance(device, OpticalDevice)
        self.assertTrue(device.exists)
        self.assertEqual(device.name, device_name)
        self.assertTrue(device in devicetree.devices)


class PartitionDevicePopulatorTestCase(PopulatorHelperTestCase):
    """Test partition device populator match method"""
    helper_class = PartitionDevicePopulator

    @patch("blivet.udev.device_is_dm_partition", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=True)
    def test_match(self, *args):
        """Test matching for partition device populator."""
        device_is_partition = args[0]
        device_is_dm_partition = args[1]
        self.assertTrue(self.helper_class.match(None))
        device_is_partition.return_value = False
        self.assertFalse(self.helper_class.match(None))

        device_is_dm_partition.return_value = True
        self.assertTrue(self.helper_class.match(None))

    @patch("blivet.udev.device_get_name")
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_dm_luks", return_value=False)
    @patch("blivet.udev.device_is_dm_integrity", return_value=False)
    @patch("blivet.udev.device_is_dm_bitlk", return_value=False)
    @patch("blivet.udev.device_is_dm_lvm", return_value=False)
    @patch("blivet.udev.device_is_dm_mpath", return_value=False)
    @patch("blivet.udev.device_is_dm_partition", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for partitions."""
        device_is_partition = args[0]
        device_is_loop = args[2]
        data = {'SYS_PATH': 'dummy'}
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_partition.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_partition.return_value = True

        # verify that setting one of the required False return values to True prevents success
        # as of now, loop is always checked before partition
        device_is_loop.return_value = True
        with patch("blivet.populator.helpers.loop.blockdev.loop.info", return_value=Mock(backing_file="foobar")):
            self.assertNotEqual(get_device_helper(data), self.helper_class)

        device_is_loop.return_value = False

    @patch.object(DiskDevice, "partitioned")
    @patch.object(DiskLabel, "parted_disk")
    @patch.object(DiskLabel, "parted_device")
    @patch.object(PartitionDevice, "probe")
    @patch("blivet.devicelibs.lvm.lvm_devices_add")
    @patch("blivet.udev.device_get_major", return_value=88)
    @patch("blivet.udev.device_get_minor", return_value=19)
    @patch.object(DeviceTree, "get_device_by_name")
    @patch("blivet.udev.device_get_name")
    @patch("blivet.udev.device_get_partition_disk")
    def test_run(self, *args):
        """Test partition device populator."""
        device_get_partition_disk = args[0]
        device_get_name = args[1]
        get_device_by_name = args[2]

        devicetree = DeviceTree()
        data = {'SYS_PATH': 'dummy'}

        # for every case:
        #   1. device(s) in tree
        #   2. lvm filter updated
        #   3. exceptions raised

        # base case: disk is already in the tree, normal disk
        fmt = get_format("disklabel", exists=True, device="/dev/xyz")
        disk = DiskDevice("xyz", fmt=fmt, exists=True)
        devicetree._add_device(disk)

        # pylint: disable=unused-argument
        def _get_device_by_name(name, **kwargs):
            if name == "xyz":
                return disk

        device_name = "xyz1"
        device_get_name.return_value = device_name
        get_device_by_name.side_effect = _get_device_by_name
        device_get_partition_disk.return_value = "xyz"
        helper = self.helper_class(devicetree, data)

        device = helper.run()
        self.assertIsInstance(device, PartitionDevice)
        self.assertTrue(device.exists)
        self.assertEqual(device.name, device_name)
        self.assertTrue(device in devicetree.devices)

        # TODO: disk not already in the tree

        # TODO: disk not already in tree and attempt to add it failed

        # TODO: md partition

        # TODO: corrupt disklabel


class DiskDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = DiskDevicePopulator

    @patch("os.path.join")
    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_disk", return_value=True)
    def test_match(self, *args):
        """Test matching of disk device populator."""
        device_is_disk = args[0]
        self.assertTrue(self.helper_class.match(None))
        device_is_disk.return_value = False
        self.assertFalse(self.helper_class.match(None))

    @patch("os.path.join")
    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_disk", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for disks."""
        device_is_disk = args[0]
        device_is_cdrom = args[5]
        data = {"DM_NAME": None}
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_disk.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_disk.return_value = True

        # verify that setting one of the required False return values to True prevents success
        # as of now, loop is always checked before partition
        device_is_cdrom.return_value = True
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_cdrom.return_value = False

    @patch("blivet.udev.device_get_major", return_value=99)
    @patch("blivet.udev.device_get_minor", return_value=222)
    @patch("blivet.udev.device_get_name")
    def test_run(self, *args):
        """Test disk device populator."""
        device_get_name = args[0]

        devicetree = DeviceTree()

        # set up some fake udev data to verify handling of specific entries
        data = {"SYS_PATH": "dummy", "ID_WWN_WITH_EXTENSION": "0x5000c50086fb75ca"}

        device_name = "nop"
        device_get_name.return_value = device_name
        helper = self.helper_class(devicetree, data)

        device = helper.run()
        self.assertIsInstance(device, DiskDevice)
        self.assertTrue(device.exists)
        self.assertTrue(device.is_disk)
        self.assertEqual(device.wwn, data["ID_WWN_WITH_EXTENSION"][2:])
        self.assertEqual(device.name, device_name)
        self.assertTrue(device in devicetree.devices)


class NVMeNamespaceDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = NVMeNamespaceDevicePopulator

    @patch("os.path.join")
    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_disk", return_value=True)
    @patch("blivet.udev.device_is_nvme_fabrics", return_value=False)
    @patch("blivet.udev.device_is_nvme_namespace", return_value=True)
    def test_match(self, *args):
        """Test matching of NVMe namespace device populator."""
        device_is_nvme_namespace = args[0]
        self.assertTrue(self.helper_class.match(None))
        device_is_nvme_namespace.return_value = False
        self.assertFalse(self.helper_class.match(None))

    @patch("os.path.join")
    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_disk", return_value=True)
    @patch("blivet.udev.device_is_nvme_fabrics", return_value=False)
    @patch("blivet.udev.device_is_nvme_namespace", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for NVMe namespaces."""
        device_is_nvme_namespace = args[0]
        data = {}
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_nvme_namespace.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_nvme_namespace.return_value = True

    @patch("blivet.udev.device_get_name")
    def test_run(self, *args):
        """Test disk device populator."""
        device_get_name = args[0]

        devicetree = DeviceTree()

        # set up some fake udev data to verify handling of specific entries
        data = {'SYS_PATH': 'dummy', 'DEVNAME': 'dummy', 'ID_PATH': 'dummy'}

        device_name = "nop"
        device_get_name.return_value = device_name
        helper = self.helper_class(devicetree, data)

        device = helper.run()

        self.assertIsInstance(device, NVMeNamespaceDevice)
        self.assertTrue(device.exists)
        self.assertTrue(device.is_disk)
        self.assertTrue(device in devicetree.devices)


class NVMeFabricsNamespaceDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = NVMeFabricsNamespaceDevicePopulator

    @patch("os.path.join")
    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_disk", return_value=True)
    @patch("blivet.udev.device_is_nvme_namespace", return_value=True)
    @patch("blivet.udev.device_is_nvme_fabrics", return_value=True)
    def test_match(self, *args):
        """Test matching of NVMe namespace device populator."""
        device_is_nvme_fabrics = args[0]
        self.assertTrue(self.helper_class.match(None))
        device_is_nvme_fabrics.return_value = False
        self.assertFalse(self.helper_class.match(None))

    @patch("os.path.join")
    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_disk", return_value=True)
    @patch("blivet.udev.device_is_nvme_namespace", return_value=True)
    @patch("blivet.udev.device_is_nvme_fabrics", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for NVMe namespaces."""
        device_is_nvme_fabrics = args[0]
        data = {}
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_nvme_fabrics.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_nvme_fabrics.return_value = True

    @patch("blivet.udev.device_get_name")
    def test_run(self, *args):
        """Test disk device populator."""
        device_get_name = args[0]

        devicetree = DeviceTree()

        # set up some fake udev data to verify handling of specific entries
        data = {'SYS_PATH': 'dummy', 'DEVNAME': 'dummy', 'ID_PATH': 'dummy'}

        device_name = "nop"
        device_get_name.return_value = device_name
        helper = self.helper_class(devicetree, data)

        device = helper.run()

        self.assertIsInstance(device, NVMeFabricsNamespaceDevice)
        self.assertTrue(device.exists)
        self.assertTrue(device.is_disk)
        self.assertTrue(device in devicetree.devices)


class MDDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = MDDevicePopulator

    @patch("blivet.udev.device_get_md_container", return_value=None)
    @patch("blivet.udev.device_is_md", return_value=True)
    def test_match(self, *args):
        """Test matching of md device populator."""
        device_is_md = args[0]
        device_get_md_container = args[1]

        self.assertEqual(self.helper_class.match(None), True)

        device_is_md.return_value = False
        device_get_md_container.return_value = None
        self.assertEqual(self.helper_class.match(None), False)

        device_is_md.return_value = True
        device_get_md_container.return_value = True
        self.assertEqual(self.helper_class.match(None), False)

        device_is_md.return_value = False
        device_get_md_container.return_value = True
        self.assertEqual(self.helper_class.match(None), False)

    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_disk", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_get_md_container", return_value=None)
    @patch("blivet.udev.device_is_md", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for md arrays."""
        device_is_md = args[0]

        data = dict()
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_md.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_md.return_value = True

        # You can't be assured that setting any of the False return values to True will trigger
        # a failure because the ordering is not complete, meaning any of several device helpers
        # could be the first helper class checked.

    @patch.object(DeviceTree, "get_device_by_device_id")
    @patch.object(DeviceTree, "_add_parent_devices")
    @patch("blivet.udev.device_get_name")
    @patch("blivet.udev.device_get_md_uuid")
    @patch("blivet.udev.device_get_md_name")
    def test_run(self, *args):
        """Test md device populator."""
        device_get_md_name = args[0]
        get_device_by_device_id = args[4]

        devicetree = DeviceTree()

        # base case: _add_parent_devices gets the array into the tree
        data = Mock()
        device = Mock()
        device.parents = []

        device_name = "mdtest"
        device_get_md_name.return_value = device_name
        get_device_by_device_id.return_value = device
        helper = self.helper_class(devicetree, data)

        self.assertEqual(helper.run(), device)


class MultipathDevicePopulatorTestCase(PopulatorHelperTestCase):
    helper_class = MultipathDevicePopulator
    match_auto_patches = ["blivet.udev.device_is_dm_mpath", "blivet.udev.device_is_dm_partition"]

    @patch("blivet.udev.device_is_dm_partition", return_value=False)
    @patch("blivet.udev.device_is_dm_mpath", return_value=True)
    def test_match(self, *args):
        """Test matching of multipath device populator."""
        device_is_dm_mpath = args[0]
        device_is_dm_partition = args[1]

        device_is_dm_partition.return_value = False
        self.assertEqual(MultipathDevicePopulator.match(None), True)

        device_is_dm_mpath.return_value = True
        device_is_dm_partition.return_value = True
        self.assertEqual(MultipathDevicePopulator.match(None), False)

        device_is_dm_mpath.return_value = False
        device_is_dm_partition.return_value = True
        self.assertEqual(MultipathDevicePopulator.match(None), False)

        device_is_dm_mpath.return_value = False
        device_is_dm_partition.return_value = False
        self.assertEqual(MultipathDevicePopulator.match(None), False)

    @patch("blivet.udev.device_is_cdrom", return_value=False)
    @patch("blivet.udev.device_is_loop", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_md", return_value=False)
    @patch("blivet.udev.device_is_dm_partition", return_value=False)
    @patch("blivet.udev.device_is_dm", return_value=True)
    @patch("blivet.udev.device_is_dm_mpath", return_value=True)
    def test_get_helper(self, *args):
        """Test get_device_helper for multipaths."""
        device_is_dm_mpath = args[0]

        data = dict()
        self.assertEqual(get_device_helper(data), self.helper_class)

        # verify that setting one of the required True return values to False prevents success
        device_is_dm_mpath.return_value = False
        self.assertNotEqual(get_device_helper(data), self.helper_class)
        device_is_dm_mpath.return_value = True

        # You can't be assured that setting any of the False return values to True will trigger
        # a failure because the ordering is not complete, meaning any of several device helpers
        # could be the first helper class checked.

    @patch("blivet.udev.device_get_sysfs_path")
    @patch.object(DeviceTree, "_add_parent_devices")
    @patch("blivet.udev.device_get_name")
    def test_run(self, *args):
        """Test multipath device populator."""
        device_get_name = args[0]
        add_parent_devices = args[1]

        devicetree = DeviceTree()
        # set up some fake udev data to verify handling of specific entries
        data = Mock()
        wwn = "0x5000c50086fb75ca"
        _data = {"DM_UUID": "1-2-3-4"}

        def _getitem_(key, extra=None):
            return _data.get(key, extra)
        data.get = Mock(side_effect=_getitem_)
        data.__getitem__ = Mock(side_effect=_getitem_)

        device_name = "mpathtest"
        device_get_name.return_value = device_name
        parent_1 = Mock(tags=set(), wwn=wwn[2:], id=0)
        parent_1.parents = []
        parent_2 = Mock(tags=set(), wwn=wwn[2:], id=0)
        parent_2.parents = []
        devicetree._add_device(parent_1)
        devicetree._add_device(parent_2)
        add_parent_devices.return_value = [parent_1, parent_2]

        helper = self.helper_class(devicetree, data)

        device = helper.run()
        self.assertIsInstance(device, MultipathDevice)
        self.assertTrue(device.exists)
        self.assertEqual(device.name, device_name)
        self.assertEqual(device.wwn, wwn[2:])
        self.assertTrue(device in devicetree.devices)


class FormatPopulatorTestCase(PopulatorHelperTestCase):
    """Format types that don't require special handling use FormatPopulator."""
    helper_class = FormatPopulator
    udev_type = None
    blivet_type = None

    @property
    def helper_name(self):
        return self.helper_class.__name__

    def test_match(self):
        if self.udev_type is None:
            return

        data = dict()
        device = Mock()

        with patch("blivet.udev.device_get_format", return_value=self.udev_type):
            self.assertTrue(self.helper_class.match(data, device),
                            msg="Failed to match %s against %s" % (self.udev_type, self.helper_name))

    @patch("blivet.static_data.mpath_members.is_mpath_member", return_value=False)
    @patch("blivet.udev.device_is_partition", return_value=False)
    @patch("blivet.udev.device_is_dm_partition", return_value=False)
    # pylint: disable=unused-argument
    def test_get_helper(self, *args):
        if self.udev_type is None:
            return

        data = dict()
        device = Mock()

        with patch("blivet.udev.device_get_format", return_value=self.udev_type):
            self.assertEqual(get_format_helper(data, device),
                             self.helper_class,
                             msg="get_format_helper failed for %s" % self.udev_type)

    # pylint: disable=unused-argument
    def test_run(self, *args):
        if self.udev_type is None:
            return

        devicetree = DeviceTree()
        data = dict()
        device = Mock()

        with patch("blivet.udev.device_get_format", return_value=self.udev_type):
            helper = self.helper_class(devicetree, data, device)
            helper.run()
            self.assertEqual(device.format.type,
                             self.blivet_type,
                             msg="FormatPopulator.run failed for %s" % self.udev_type)


class Ext4PopulatorTestCase(FormatPopulatorTestCase):
    """Test ext4 format populator."""
    udev_type = blivet_type = "ext4"


class XFSPopulatorTestCase(FormatPopulatorTestCase):
    udev_type = blivet_type = "xfs"


class SwapPopulatorTestCase(FormatPopulatorTestCase):
    udev_type = blivet_type = "swap"


class VFATPopulatorTestCase(FormatPopulatorTestCase):
    udev_type = blivet_type = "vfat"


class HFSPopulatorTestCase(FormatPopulatorTestCase):
    udev_type = blivet_type = "hfs"


class DiskLabelPopulatorTestCase(PopulatorHelperTestCase):
    helper_class = DiskLabelFormatPopulator

    @patch("blivet.udev.device_is_biosraid_member", return_value=False)
    @patch("blivet.udev.device_get_format", return_value=None)
    @patch("blivet.udev.device_get_disklabel_type", return_value="dos")
    def test_match(self, *args):
        """Test matching for disklabel format populator."""
        device_get_disklabel_type = args[0]
        device_get_format = args[1]
        device_is_biosraid_member = args[2]

        device = Mock()
        device.is_disk = True

        data = Mock()

        self.assertTrue(self.helper_class.match(data, device))

        # ID_PART_TABLE_TYPE is required in udev data
        device_get_disklabel_type.return_value = None
        self.assertFalse(self.helper_class.match(data, device))
        device_get_disklabel_type.return_value = "dos"

        # no match for whole-disk iso9660 filesystems (isohybrid media)
        device_get_format.return_value = "iso9660"
        self.assertFalse(self.helper_class.match(data, device))
        device_get_format.return_value = None

        # no match for whole-disk udf filesystem
        device_get_format.return_value = "udf"
        self.assertFalse(self.helper_class.match(data, device))
        device_get_format.return_value = None

        # no match for biosraid members
        device_is_biosraid_member.return_value = True
        self.assertFalse(self.helper_class.match(data, device))
        device_is_biosraid_member.return_value = False

        # no match for multipath members
        device_get_format.return_value = "mpath_member"
        self.assertFalse(self.helper_class.match(data, device))
        device_get_format.return_value = None

    @patch("blivet.static_data.mpath_members.is_mpath_member", return_value=False)
    @patch("blivet.udev.device_is_biosraid_member", return_value=False)
    @patch("blivet.udev.device_get_format", return_value=None)
    @patch("blivet.udev.device_get_disklabel_type", return_value="dos")
    def test_get_helper(self, *args):
        """Test get_format_helper for disklabels."""
        device_get_disklabel_type = args[0]

        device = Mock()
        device.is_disk = True

        data = Mock()

        self.assertEqual(get_format_helper(data, device), self.helper_class)

        # no disklabel type reported by udev/blkid -> get_format_helper does not return
        # disklabel helper
        device_get_disklabel_type.return_value = None
        self.assertNotEqual(get_format_helper(data, device), self.helper_class)
        device_get_disklabel_type.return_value = "dos"


class LVMFormatPopulatorTestCase(FormatPopulatorTestCase):
    helper_class = LVMFormatPopulator
    udev_type = "LVM2_member"
    blivet_type = "lvmpv"

    def _clean_up(self):
        blockdev.lvm.pvs = self._pvs
        blockdev.lvm.vgs = self._vgs
        blockdev.lvm.lvs = self._lvs

    @patch("blivet.udev.device_get_name")
    @patch.object(DeviceFormat, "_device_check", return_value=None)
    @patch.object(DeviceTree, "get_device_by_uuid")
    # XXX: the lvm_devices_* functions are decorated with needs_config_refresh decorator which
    #      at this point is already applied as a no-op because LVM libblockdev plugin is not available
    @patch("blivet.devicelibs.lvm.lvm_devices_add", new=lvm._lvm_devices.add)
    def test_run(self, *args):
        """Test lvm format populator."""
        get_device_by_uuid = args[0]

        devicetree = DeviceTree()
        data = dict()
        device = Mock()
        device.id = 0
        device.parents = []
        device.size = Size("10g")
        device.path = "/dev/sda1"
        devicetree._add_device(device)

        # pylint: disable=attribute-defined-outside-init
        self._pvs = blockdev.lvm.pvs
        self._vgs = blockdev.lvm.vgs
        self._lvs = blockdev.lvm.lvs
        blockdev.lvm.pvs = Mock(return_value=[])
        blockdev.lvm.vgs = Mock(return_value=[])
        blockdev.lvm.lvs = Mock(return_value=[])
        self.addCleanup(self._clean_up)

        # base case: pv format with no vg
        with patch("blivet.udev.device_get_format", return_value=self.udev_type):
            helper = self.helper_class(devicetree, data, device)
            helper.run()
            self.assertEqual(device.format.type,
                             self.blivet_type,
                             msg="Wrong format type after FormatPopulator.run on %s" % self.udev_type)

        # pv belongs to a valid vg which is already in the tree (no lvs)
        pv_info = Mock()

        pv_info.vg_name = "testvgname"
        pv_info.vg_uuid = sentinel.vg_uuid
        pv_info.pe_start = 0
        pv_info.pv_free = 0

        vg_device = Mock()
        vg_device.id = 0
        vg_device.parents = []
        vg_device.lvs = []
        get_device_by_uuid.return_value = vg_device

        with patch("blivet.static_data.lvm_info.PVsInfo.cache", new_callable=PropertyMock) as mock_pvs_cache:
            mock_pvs_cache.return_value = {device.path: pv_info}
            with patch("blivet.udev.device_get_format", return_value=self.udev_type):
                helper = self.helper_class(devicetree, data, device)
                self.assertFalse(device in vg_device.parents)
                helper.run()
                self.assertEqual(device.format.type,
                                 self.blivet_type,
                                 msg="Wrong format type after FormatPopulator.run on %s" % self.udev_type)

                self.assertEqual(get_device_by_uuid.call_count, 3)
                get_device_by_uuid.assert_called_with(pv_info.vg_uuid, incomplete=True)
                self.assertTrue(device in vg_device.parents)

        get_device_by_uuid.reset_mock()
        get_device_by_uuid.return_value = None

        # pv belongs to a valid vg which is not in the tree (no lvs, either)
        pv_info.vg_size = "10g"
        pv_info.vg_free = 0
        pv_info.vg_extent_size = "4m"
        pv_info.vg_extent_count = 2500
        pv_info.vg_free_count = 0
        pv_info.vg_pv_count = 1

        with patch("blivet.static_data.lvm_info.PVsInfo.cache", new_callable=PropertyMock) as mock_pvs_cache:
            mock_pvs_cache.return_value = {device.path: pv_info}
            with patch("blivet.static_data.lvm_info.VGsInfo.cache", new_callable=PropertyMock) as mock_vgs_cache:
                mock_vgs_cache.return_value = {pv_info.vg_uuid: Mock()}
                with patch("blivet.udev.device_get_format", return_value=self.udev_type):
                    helper = self.helper_class(devicetree, data, device)
                    helper.run()
                    self.assertEqual(device.format.type,
                                     self.blivet_type,
                                     msg="Wrong format type after FormatPopulator.run on %s" % self.udev_type)

                    self.assertEqual(get_device_by_uuid.call_count, 2)
                    get_device_by_uuid.assert_called_with(pv_info.vg_uuid, incomplete=True)
                    vg_device = devicetree.get_device_by_name(pv_info.vg_name)
                    self.assertTrue(vg_device is not None)
                    devicetree._remove_device(vg_device)

                    self.assertIn(device.path, lvm._lvm_devices)

        get_device_by_uuid.reset_mock()

        # pv belongs to a valid vg not in the tree with two lvs
        lv1 = Mock()
        lv1.id = 0
        lv1.vg_name = pv_info.vg_name
        lv1.lv_name = "testlv1"
        lv1.uuid = sentinel.lv1_uuid
        lv1.attr = "-wi-ao----"
        lv1.size = "2g"
        lv1.segtype = "linear"
        lv1_name = "%s-%s" % (pv_info.vg_name, lv1.lv_name)

        lv2 = Mock()
        lv2.id = 0
        lv2.vg_name = pv_info.vg_name
        lv2.lv_name = "testlv2"
        lv2.uuid = sentinel.lv2_uuid
        lv2.attr = "-wi-ao----"
        lv2.size = "7g"
        lv2.segtype = "linear"
        lv2_name = "%s-%s" % (pv_info.vg_name, lv2.lv_name)

        lv_info = {lv1_name: lv1,
                   lv2_name: lv2}

        device.format.container_uuid = pv_info.vg_uuid

        def gdbu(uuid, **kwargs):  # pylint: disable=unused-argument
            # This version doesn't check format UUIDs
            return next((d for d in devicetree.devices if d.uuid == uuid), None)
        get_device_by_uuid.side_effect = gdbu

        with patch("blivet.static_data.lvm_info.PVsInfo.cache", new_callable=PropertyMock) as mock_pvs_cache:
            mock_pvs_cache.return_value = {device.path: pv_info}
            with patch("blivet.static_data.lvm_info.VGsInfo.cache", new_callable=PropertyMock) as mock_vgs_cache:
                mock_vgs_cache.return_value = {pv_info.vg_uuid: Mock()}
                with patch("blivet.static_data.lvm_info.LVsInfo.cache", new_callable=PropertyMock) as mock_lvs_cache:
                    mock_lvs_cache.return_value = lv_info
                    with patch("blivet.udev.device_get_format", return_value=self.udev_type):
                        self.assertEqual(devicetree.get_device_by_name(pv_info.vg_name, incomplete=True), None)
                        helper = self.helper_class(devicetree, data, device)
                        helper.run()
                        self.assertEqual(device.format.type,
                                         self.blivet_type,
                                         msg="Wrong format type after FormatPopulator.run on %s" % self.udev_type)

                        self.assertEqual(get_device_by_uuid.call_count, 4,
                                         get_device_by_uuid.mock_calls)  # two for vg and one for each lv
                        get_device_by_uuid.assert_has_calls([call(pv_info.vg_uuid, incomplete=True),
                                                            call(lv1.uuid),
                                                            call(lv2.uuid)],
                                                            any_order=True)
                        vg_device = devicetree.get_device_by_name(pv_info.vg_name)
                        self.assertTrue(vg_device is not None)

                        lv1_device = devicetree.get_device_by_name(lv1_name)
                        self.assertEqual(lv1_device.uuid, lv1.uuid)
                        lv2_device = devicetree.get_device_by_name(lv2_name)
                        self.assertEqual(lv2_device.uuid, lv2.uuid)


class MDFormatPopulatorTestCase(FormatPopulatorTestCase):
    helper_class = MDFormatPopulator
    udev_type = "linux_raid_member"
    blivet_type = "mdmember"

    def _clean_up(self):
        blockdev.md.examine = self._examine

    @patch("blivet.udev.device_get_name")
    @patch("blivet.util.canonicalize_UUID", side_effect=lambda x: x)
    @patch.object(MDRaidArrayDevice, "mdadm_format_uuid", None)
    @patch("blivet.udev.device_is_md")
    @patch("blivet.udev.get_devices")
    @patch.object(DeviceTree, "get_device_by_uuid")
    def test_run(self, *args):
        """Test md format populator."""
        get_device_by_uuid = args[0]
        get_devices = args[1]
        device_is_md = args[2]

        devicetree = DeviceTree()
        data = dict()
        device = Mock()
        device.id = 0
        device.name = sentinel.dev1_name
        device.parents = []
        device.size = Size("10g")
        devicetree._add_device(device)

        # pylint: disable=attribute-defined-outside-init
        self._examine = blockdev.md.examine
        blockdev.md.examine = Mock()
        self.addCleanup(self._clean_up)

        # member belongs to a valid array which is already in the tree
        md_info = Mock()
        md_info.uuid = sentinel.md_uuid
        blockdev.md.examine.return_value = md_info

        md_device = Mock()
        md_device.id = 0
        get_device_by_uuid.return_value = md_device

        with patch("blivet.udev.device_get_format", return_value=self.udev_type):
            helper = self.helper_class(devicetree, data, device)
            helper.run()
            self.assertEqual(device.format.type,
                             self.blivet_type,
                             msg="Wrong format type after FormatPopulator.run on %s" % self.udev_type)

            self.assertEqual(get_device_by_uuid.call_count, 1)
            get_device_by_uuid.assert_called_with(md_info.uuid, incomplete=True)
            md_device.parents.append.assert_called_once_with(device)  # pylint: disable=no-member

        get_device_by_uuid.reset_mock()
        get_device_by_uuid.return_value = None

        # first of two members belonging to a valid array which is not in the tree
        array_name = "mdtest"
        md_info.level = "raid1"
        md_info.num_devices = 2
        md_info.metadata = "1.2"
        md_info.device = "/dev/md/" + array_name
        blockdev.md.examine.return_value = md_info

        device_is_md.return_value = True
        md_udev = {"MD_LEVEL": md_info.level, "MD_UUID": sentinel.md_uuid, "MD_DEVNAME": array_name}
        get_devices.return_value = [md_udev]

        with patch("blivet.udev.device_get_format", return_value=self.udev_type):
            helper = self.helper_class(devicetree, data, device)
            helper.run()
            self.assertEqual(device.format.type,
                             self.blivet_type,
                             msg="Wrong format type after FormatPopulator.run on %s" % self.udev_type)

            self.assertEqual(get_device_by_uuid.call_count, 1)
            get_device_by_uuid.assert_called_with(md_info.uuid, incomplete=True)
            array = devicetree.get_device_by_name(array_name)
            self.assertTrue(array is None)
            array = devicetree.get_device_by_name(array_name, incomplete=True)
            self.assertTrue(array is not None)
            self.assertFalse(array.complete)
            self.assertEqual(array.name, array_name)

        get_device_by_uuid.reset_mock()
        array = devicetree.get_device_by_name(array_name, incomplete=True)
        get_device_by_uuid.return_value = array

        # second of two members belonging to a valid array
        device2 = Mock()
        device2.id = 0
        device2.name = sentinel.dev2_name
        device2.parents = []
        device2.size = Size("10g")
        devicetree._add_device(device2)

        with patch("blivet.udev.device_get_format", return_value=self.udev_type):
            helper = self.helper_class(devicetree, data, device2)
            helper.run()
            self.assertEqual(device2.format.type,
                             self.blivet_type,
                             msg="Wrong format type after FormatPopulator.run on %s" % self.udev_type)

            self.assertEqual(get_device_by_uuid.call_count, 1)  # one for the array
            get_device_by_uuid.assert_called_with(md_info.uuid, incomplete=True)

            array = devicetree.get_device_by_name(array_name)
            self.assertTrue(array is not None)
            self.assertTrue(array.complete)
            self.assertEqual(array.name, array_name)


class FakePartedPart(object):
    """Fake parted_partition for testing the parted partition name
    matching stuff. Has to provide size also.
    """
    def __init__(self, partition, name):
        self.name = name
        self.partition = partition

    def getLength(self, unit):
        """This is circular, but works okay."""
        return self.partition._size.convert_to(unit)


class BootFormatPopulatorTestCase(PopulatorHelperTestCase):
    name_mismatch_ok = True

    def test_match(self):
        """Test boot format populator helper match method"""
        if self.helper_class is None:
            return

        partition = PartitionDevice("testpartitiondev")
        storagedev = StorageDevice("teststoragedev")
        storagedev.bootable = True
        data = dict()

        fmt_class = get_device_format_class(self.helper_class._type_specifier)
        if fmt_class is None:
            self.skipTest("failed to look up format class for %s" % self.helper_class._type_specifier)

        data["ID_FS_TYPE"] = self.helper_class._base_type_specifier
        partition._bootable = self.helper_class._bootable
        min_size = fmt_class._min_size
        max_size = fmt_class._max_size
        partition._size = min_size
        storagedev._size = min_size

        if fmt_class._name:
            partition._parted_partition = FakePartedPart(partition, fmt_class._name)
            partition.disk = Mock(format=Mock(supports_names=True))

        self.assertTrue(self.helper_class.match(data, partition))

        # These are only valid for partitions.
        self.assertFalse(self.helper_class.match(data, storagedev))

        data["ID_FS_TYPE"] += "x"
        self.assertFalse(self.helper_class.match(data, partition))
        data["ID_FS_TYPE"] = self.helper_class._base_type_specifier

        if self.helper_class._bootable:
            partition._bootable = False
            self.assertFalse(self.helper_class.match(data, partition))
            partition._bootable = True

        if max_size:
            partition._size = max_size + 1
        elif min_size:
            partition._size = min_size - 1

        self.assertFalse(self.helper_class.match(data, partition))
        partition._size = min_size

        # we don't always match on the parted partition name, so allow
        # subclasses to decide
        if not self.name_mismatch_ok:
            orig = partition._parted_partition
            partition._parted_partition = FakePartedPart(partition, 'dontmatchanything')
            self.assertFalse(self.helper_class.match(data, partition))

            # shouldn't crash
            partition._parted_partition = None
            self.assertFalse(self.helper_class.match(data, partition))
            partition._parted_partition = orig

    @patch("blivet.udev.device_get_disklabel_type", return_value=None)
    # pylint: disable=unused-argument
    def test_get_helper(self, *args):
        if self.helper_class is None:
            return

        partition = PartitionDevice("testpartitiondev")
        data = dict()

        fmt_class = get_device_format_class(self.helper_class._type_specifier)
        if fmt_class is None:
            self.skipTest("failed to look up format class for %s" % self.helper_class._type_specifier)

        data["ID_FS_TYPE"] = self.helper_class._base_type_specifier
        data["DEVTYPE"] = "partition"
        partition._bootable = self.helper_class._bootable
        partition._size = fmt_class._min_size
        if fmt_class._name:
            partition._parted_partition = FakePartedPart(partition, fmt_class._name)
            partition.disk = Mock(format=Mock(supports_names=True))
        self.assertEqual(get_format_helper(data, partition), self.helper_class)


class EFIFormatPopulatorTestCase(BootFormatPopulatorTestCase):
    helper_class = EFIFormatPopulator


class MacEFIFormatPopulatorTestCase(BootFormatPopulatorTestCase):
    helper_class = MacEFIFormatPopulator
    name_mismatch_ok = False


if __name__ == "__main__":
    unittest.main()
