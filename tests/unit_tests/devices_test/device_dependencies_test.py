import os
import unittest
from unittest.mock import patch, PropertyMock

import blivet
import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev as blockdev

from blivet.errors import DependencyError

from blivet.deviceaction import ActionCreateDevice
from blivet.deviceaction import ActionDestroyDevice
from blivet.deviceaction import ActionResizeDevice

from blivet.deviceaction import ActionCreateFormat
from blivet.deviceaction import ActionDestroyFormat

from blivet.devices import DiskDevice
from blivet.devices import DiskFile
from blivet.devices import LUKSDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import PartitionDevice
from blivet.devices import StorageDevice

from blivet.formats import get_format

from blivet.size import Size

from blivet.tasks import availability

from blivet.util import create_sparse_tempfile


class DeviceDependenciesTestCase(unittest.TestCase):

    """Test external device dependencies. """

    def test_dependencies(self):
        dev1 = DiskDevice("name", fmt=get_format("mdmember"))
        dev2 = DiskDevice("other", fmt=get_format("mdmember"))
        dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, dev2])
        luks = LUKSDevice("luks", parents=[dev])

        # a parent's dependencies are a subset of its child's.
        for d in dev.external_dependencies:
            self.assertIn(d, luks.external_dependencies)

        # make sure that there's at least something in these dependencies
        self.assertGreater(len(luks.external_dependencies), 0)


class MockingDeviceDependenciesTestCase1(unittest.TestCase):

    """Test availability of external device dependencies. """

    def setUp(self):
        dev1 = DiskDevice("name", fmt=get_format("mdmember"), size=Size("1 GiB"))
        dev2 = DiskDevice("other")
        self.part = PartitionDevice("part", fmt=get_format("mdmember"), parents=[dev2])
        self.dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, self.part], fmt=get_format("luks"), total_devices=2, member_devices=2)
        self.luks = LUKSDevice("luks", parents=[self.dev], fmt=get_format("ext4"))

        self.mdraid_method = availability.BLOCKDEV_MDRAID_PLUGIN._method
        self.dm_method = availability.BLOCKDEV_DM_PLUGIN._method
        self.hfsplus_method = availability.MKFS_HFSPLUS_APP._method
        self.cache_availability = availability.CACHE_AVAILABILITY

        self.addCleanup(self._clean_up)

    def test_availability_mdraidplugin(self):

        availability.CACHE_AVAILABILITY = False
        availability.BLOCKDEV_DM_PLUGIN._method = availability.AvailableMethod

        # if the plugin is not in, there's nothing to test
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.external_dependencies)

        # dev is not among its unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = availability.AvailableMethod
        availability.MKFS_HFSPLUS_APP._method = availability.AvailableMethod  # macefi
        availability.BLOCKDEV_CRYPTO_PLUGIN._method = availability.AvailableMethod  # luks
        availability.KPARTX_APP._method = availability.AvailableMethod  # luks
        self.assertNotIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailable_dependencies)
        self.assertIsNotNone(ActionCreateDevice(self.luks))
        self.assertIsNotNone(ActionDestroyDevice(self.luks))
        self.assertIsNotNone(ActionCreateFormat(self.luks, fmt=get_format("macefi")))
        self.assertIsNotNone(ActionDestroyFormat(self.luks))

        # dev is among the unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = availability.UnavailableMethod
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailable_dependencies)
        with self.assertRaises(DependencyError):
            ActionDestroyDevice(self.dev)

    def _clean_up(self):
        availability.BLOCKDEV_MDRAID_PLUGIN._method = self.mdraid_method
        availability.BLOCKDEV_DM_PLUGIN._method = self.dm_method
        availability.MKFS_HFSPLUS_APP._method = self.hfsplus_method

        availability.CACHE_AVAILABILITY = False
        availability.BLOCKDEV_MDRAID_PLUGIN.available  # pylint: disable=pointless-statement
        availability.BLOCKDEV_DM_PLUGIN.available  # pylint: disable=pointless-statement
        availability.MKFS_HFSPLUS_APP.available  # pylint: disable=pointless-statement

        availability.CACHE_AVAILABILITY = self.cache_availability


class MockingDeviceDependenciesTestCase2(unittest.TestCase):
    def test_dependencies_handling(self):
        device = StorageDevice("testdev1")
        self.assertTrue(device.controllable)
        self.assertIsNotNone(ActionCreateDevice(device))
        device.exists = True
        self.assertIsNotNone(ActionDestroyDevice(device))
        with patch.object(StorageDevice, "resizable", new_callable=PropertyMock(return_value=True)):
            self.assertIsNotNone(ActionResizeDevice(device, Size("1 GiB")))

        # if any external dependency is missing, it should be impossible to create, destroy, setup,
        # teardown, or resize the device (controllable encompasses setup & teardown)
        with patch.object(StorageDevice, "_external_dependencies",
                          new_callable=PropertyMock(return_value=[availability.unavailable_resource("testing")])):
            device = StorageDevice("testdev1")
            self.assertFalse(device.controllable)
            self.assertRaises(DependencyError, ActionCreateDevice, device)
            device.exists = True
            self.assertRaises(DependencyError, ActionDestroyDevice, device)
            self.assertRaises(ValueError, ActionResizeDevice, device, Size("1 GiB"))

        # same goes for formats, except that the properties they affect vary by format class
        fmt = get_format("lvmpv")
        fmt._plugin = availability.available_resource("lvm-testing")
        self.assertTrue(fmt.supported)
        self.assertTrue(fmt.formattable)
        self.assertTrue(fmt.destroyable)

        fmt._plugin = availability.unavailable_resource("lvm-testing")
        self.assertFalse(fmt.supported)
        self.assertFalse(fmt.formattable)
        self.assertFalse(fmt.destroyable)


class MissingWeakDependenciesTestCase(unittest.TestCase):

    def setUp(self):
        self.addCleanup(self._clean_up)
        self.disk1_file = create_sparse_tempfile("disk1", Size("2GiB"))
        self.plugins = blockdev.plugin_specs_from_names(blockdev.get_available_plugin_names())  # pylint: disable=no-value-for-parameter

        loaded_plugins = self.load_all_plugins()
        if not all(p in loaded_plugins for p in ("btrfs", "crypto", "lvm", "md")):
            # we don't have all plugins needed for this test case
            self.skipTest("Missing libblockdev plugins needed from weak dependencies test.")

    def _clean_up(self):
        # reload all libblockdev plugins
        self.load_all_plugins()

        if os.path.exists(self.disk1_file):
            os.unlink(self.disk1_file)

        availability.CACHE_AVAILABILITY = True

    def load_all_plugins(self):
        result, plugins = blockdev.try_reinit(require_plugins=self.plugins, reload=True)
        if not result:
            self.fail("Could not reload libblockdev plugins")
        return plugins

    def unload_all_plugins(self):
        result, _ = blockdev.try_reinit(require_plugins=[], reload=True)
        if not result:
            self.fail("Could not reload libblockdev plugins")

    def test_weak_dependencies(self):
        self.bvt = blivet.Blivet()  # pylint: disable=attribute-defined-outside-init
        availability.CACHE_AVAILABILITY = False

        # reinitialize blockdev without the plugins
        # TODO: uncomment (workaround (1/2) for blivet.reset fail)
        # self.unload_all_plugins()
        disk1 = DiskFile(self.disk1_file)

        self.bvt.exclusive_disks = [disk1.name]
        if os.geteuid() == 0:
            try:
                self.bvt.reset()
            except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
                self.fail("Improper handling of missing libblockdev plugin")
        # TODO: remove line (workaround (2/2) for blivet.reset fail)
        self.unload_all_plugins()

        self.bvt.devicetree._add_device(disk1)
        self.bvt.initialize_disk(disk1)

        pv = self.bvt.new_partition(size=Size("8GiB"), fmt_type="lvmpv")
        pv_fail = self.bvt.new_partition(size=Size("8GiB"), fmt_type="lvmpv")
        btrfs = self.bvt.new_partition(size=Size("1GiB"), fmt_type="btrfs")
        raid1 = self.bvt.new_partition(size=Size("1GiB"), fmt_type="mdmember")
        raid2 = self.bvt.new_partition(size=Size("1GiB"), fmt_type="mdmember")

        with self.assertRaisesRegex(ValueError, "resource to create this format.*unavailable"):
            self.bvt.create_device(pv_fail)

        # to be able to test functions like destroy_device it is necessary to have some
        # testing devices actually created - hence loading libblockdev plugins...
        self.load_all_plugins()
        self.bvt.create_device(pv)
        self.bvt.create_device(btrfs)
        # ... and unloading again when tests can continue
        self.unload_all_plugins()

        try:
            vg = self.bvt.new_vg(parents=[pv])
        except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
            self.fail("Improper handling of missing libblockdev plugin")

        self.load_all_plugins()
        self.bvt.create_device(vg)
        self.unload_all_plugins()

        try:
            lv1 = self.bvt.new_lv(fmt_type="ext4", size=Size("1GiB"), parents=[vg])
            lv2 = self.bvt.new_lv(fmt_type="ext4", size=Size("1GiB"), parents=[vg])
            lv3 = self.bvt.new_lv(fmt_type="luks", size=Size("1GiB"), parents=[vg])
        except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
            self.fail("Improper handling of missing libblockdev plugin")

        self.load_all_plugins()
        self.bvt.create_device(lv1)
        self.bvt.create_device(lv2)
        self.bvt.create_device(lv3)
        self.unload_all_plugins()

        try:
            pool = self.bvt.new_lv_from_lvs(vg, name='pool', seg_type="thin-pool", from_lvs=[lv1, lv2])
        except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
            self.fail("Improper handling of missing libblockdev plugin")

        self.load_all_plugins()
        self.bvt.create_device(pool)
        self.unload_all_plugins()

        with self.assertRaisesRegex(DependencyError, "requires unavailable_dependencies"):
            self.bvt.destroy_device(pool)

        try:
            self.bvt.new_btrfs(parents=[btrfs])
        except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
            self.fail("Improper handling of missing libblockdev plugin")

        with self.assertRaisesRegex(ValueError, "device cannot be resized"):
            self.bvt.resize_device(lv3, Size("2GiB"))

        try:
            self.bvt.new_tmp_fs(fmt=disk1.format, size=Size("500MiB"))
        except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
            self.fail("Improper handling of missing libblockdev plugin")

        try:
            self.bvt.new_mdarray(level='raid0', parents=[raid1, raid2])
        except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
            self.fail("Improper handling of missing libblockdev plugin")
