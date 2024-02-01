import os
import unittest

from unittest.mock import patch

from ..storagetestcase import StorageTestCase

import blivet
from blivet.devices.btrfs import BTRFSVolumeDevice


class DeviceIDTestCase(StorageTestCase):

    vgname = "blivetTestVG"

    @classmethod
    def setUpClass(cls):
        unavailable_deps = BTRFSVolumeDevice.unavailable_type_dependencies()
        if unavailable_deps:
            dep_str = ", ".join([d.name for d in unavailable_deps])
            raise unittest.SkipTest("some unavailable dependencies required for this test: %s" % dep_str)

    def setUp(self):
        super().setUp()

        # allow automounting to get btrfs information
        blivet.flags.flags.auto_dev_updates = True

        disks = [os.path.basename(vdev) for vdev in self.vdevs]
        self.storage = blivet.Blivet()
        self.storage.exclusive_disks = disks
        self.storage.reset()

        # make sure only the targetcli disks are in the devicetree
        for disk in self.storage.disks:
            self.assertTrue(disk.path in self.vdevs)
            self.assertIsNone(disk.format.type)
            self.assertFalse(disk.children)

    def _clean_up(self):
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        # reset back to default
        blivet.flags.flags.auto_dev_updates = False

        return super()._clean_up()

    def test_same_name_devices(self):
        """ Test that we can handle multiple devices with the same name

            This test cases creates three devices named "test": two btrfs
            volumes and one VG and checks that reset() and get_device_by_device_id()
            work as expected.
        """

        # BTRFS volume named "test"
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        part = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="btrfs",
                                          parents=[disk])
        self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        vol = self.storage.new_btrfs(name="test", parents=[part])
        btrfs1_uuid = vol.uuid
        self.storage.create_device(vol)
        self.storage.do_it()
        self.storage.reset()

        # second BTRFS volume also named "test"
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[1])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        part = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="btrfs",
                                          parents=[disk])
        self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        # XXX we actually cannot create another device with the same name
        with patch("blivet.devicetree.DeviceTree.names", []):
            vol = self.storage.new_btrfs(name="test", parents=[part])
            btrfs2_uuid = vol.uuid
            self.storage.create_device(vol)
            self.storage.do_it()
            self.storage.reset()

        # LVM VG named "test"
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[2])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                        parents=[disk])
        self.storage.create_device(pv)

        blivet.partitioning.do_partitioning(self.storage)

        # XXX we actually cannot create another device with the same name
        with patch("blivet.devicetree.DeviceTree.names", []):
            vg = self.storage.new_vg(name="test", parents=[pv])
            self.storage.create_device(vg)
            self.storage.do_it()
            self.storage.reset()

        # we should now have three devices named test
        test_devs = [dev for dev in self.storage.devices if dev.name == "test"]
        self.assertEqual(len(test_devs), 3)

        vol1 = self.storage.devicetree.get_device_by_device_id("BTRFS-" + btrfs1_uuid)
        self.assertIsNotNone(vol1)
        self.assertEqual(vol1.type, "btrfs volume")
        self.assertEqual(vol1.name, "test")
        self.assertEqual(vol1.parents[0].path, self.vdevs[0] + "1")

        vol2 = self.storage.devicetree.get_device_by_device_id("BTRFS-" + btrfs2_uuid)
        self.assertIsNotNone(vol2)
        self.assertEqual(vol2.type, "btrfs volume")
        self.assertEqual(vol2.name, "test")
        self.assertEqual(vol2.parents[0].path, self.vdevs[1] + "1")

        vg = self.storage.devicetree.get_device_by_device_id("LVM-test")
        self.assertIsNotNone(vg)
        self.assertEqual(vg.type, "lvmvg")
        self.assertEqual(vg.name, "test")
        self.assertEqual(vg.parents[0].path, self.vdevs[2] + "1")
