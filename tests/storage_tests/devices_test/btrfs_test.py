import os
import tempfile
import unittest

from ..storagetestcase import StorageTestCase

import blivet
from blivet.devices.btrfs import BTRFSVolumeDevice


class BtrfsTestCase(StorageTestCase):

    volname = "blivetTestBtrfsVolume"

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

    def test_btrfs_basic(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        part = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="btrfs",
                                          parents=[disk])
        self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        vol = self.storage.new_btrfs(name=self.volname, parents=[part])
        self.storage.create_device(vol)

        self.assertIsNotNone(vol.uuid)
        pre_uuid = vol.uuid

        sub = self.storage.new_btrfs_sub_volume(parents=[vol], name="blivetTestSubVol")
        self.storage.create_device(sub)

        self.storage.do_it()
        self.storage.reset()
        self.storage.reset()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        part = self.storage.devicetree.get_device_by_name(os.path.basename(self.vdevs[0]) + "1")
        self.assertIsNotNone(part)
        self.assertIsInstance(part, blivet.devices.PartitionDevice)
        self.assertIsNotNone(part.format)
        self.assertEqual(part.format.type, "btrfs")

        vol = self.storage.devicetree.get_device_by_name(self.volname)
        self.assertIsNotNone(vol)
        self.assertIsInstance(vol, blivet.devices.BTRFSVolumeDevice)
        self.assertIsNotNone(vol.format)
        self.assertEqual(vol.format.type, "btrfs")
        self.assertEqual(vol.format.container_uuid, vol.uuid)
        self.assertEqual(len(vol.parents), 1)
        self.assertEqual(vol.parents[0].name, part.name)
        self.assertEqual(vol.uuid, pre_uuid)

        sub = self.storage.devicetree.get_device_by_name("blivetTestSubVol")
        self.assertIsNotNone(sub)
        self.assertIsInstance(sub, blivet.devices.BTRFSSubVolumeDevice)
        self.assertIsNotNone(sub.format)
        self.assertEqual(sub.format.type, "btrfs")
        self.assertEqual(sub.volume, vol)
        self.assertEqual(len(sub.parents), 1)
        self.assertEqual(sub.parents[0], vol)
        self.assertEqual(sub.size, vol.size)
        self.assertEqual(sub.format.container_uuid, vol.uuid)
        self.assertEqual(sub.format.subvolspec, sub.name)

    def _test_btrfs_raid(self, raid_level):
        disk1 = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk1)
        self.storage.initialize_disk(disk1)

        disk2 = self.storage.devicetree.get_device_by_path(self.vdevs[1])
        self.assertIsNotNone(disk2)
        self.storage.initialize_disk(disk2)

        part1 = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="btrfs",
                                           parents=[disk1])
        self.storage.create_device(part1)

        part2 = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="btrfs",
                                           parents=[disk2])
        self.storage.create_device(part2)

        blivet.partitioning.do_partitioning(self.storage)

        vol = self.storage.new_btrfs(name=self.volname, parents=[part1, part2],
                                     data_level=raid_level, metadata_level=raid_level)
        self.storage.create_device(vol)

        sub = self.storage.new_btrfs_sub_volume(parents=[vol], name="blivetTestSubVol")
        self.storage.create_device(sub)

        self.storage.do_it()
        self.storage.reset()
        self.storage.reset()

        vol = self.storage.devicetree.get_device_by_name(self.volname)
        self.assertIsNotNone(vol)
        self.assertIsInstance(vol, blivet.devices.BTRFSVolumeDevice)
        self.assertIsNotNone(vol.format)
        self.assertEqual(vol.format.type, "btrfs")
        self.assertEqual(vol.format.container_uuid, vol.uuid)
        self.assertEqual(len(vol.parents), 2)
        self.assertCountEqual([p.name for p in vol.parents], [part1.name, part2.name])

    def test_btrfs_raid_single(self):
        self._test_btrfs_raid(blivet.devicelibs.raid.Single)

    def test_btrfs_raid_raid0(self):
        self._test_btrfs_raid(blivet.devicelibs.raid.RAID0)

    def test_btrfs_raid_raid1(self):
        self._test_btrfs_raid(blivet.devicelibs.raid.RAID1)

    def test_btrfs_fs_is_empty(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        part = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="btrfs",
                                          parents=[disk])
        self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        vol = self.storage.new_btrfs(name=self.volname, parents=[part])
        self.storage.create_device(vol)

        self.assertIsNotNone(vol.uuid)

        sub1 = self.storage.new_btrfs_sub_volume(parents=[vol], name="blivetTestSubVol1")
        self.storage.create_device(sub1)

        sub2 = self.storage.new_btrfs_sub_volume(parents=[vol], name="blivetTestSubVol2")
        self.storage.create_device(sub2)

        sub3 = self.storage.new_btrfs_sub_volume(parents=[sub2], name="blivetTestSubVol2/blivetTestSubVol3")
        self.storage.create_device(sub3)

        self.storage.do_it()
        self.storage.reset()
        self.storage.reset()

        vol = self.storage.devicetree.get_device_by_name(self.volname)
        self.assertIsNotNone(vol)

        self.assertTrue(vol.format.is_empty)
        for sub in vol.subvolumes:
            self.assertTrue(sub.format.is_empty)

        # create a new directory in the second subvolume
        with tempfile.TemporaryDirectory() as mountpoint:
            vol.format.mount(mountpoint=mountpoint)
            os.makedirs(os.path.join(mountpoint, "blivetTestSubVol2/test"))
            vol.format.unmount()

        self.assertTrue(vol.format.is_empty)

        # first subvolume is empty
        sub1 = self.storage.devicetree.get_device_by_name("blivetTestSubVol1")
        self.assertIsNotNone(sub1)
        self.assertTrue(sub1.format.is_empty)

        # second subvolume is NOT empty
        sub2 = self.storage.devicetree.get_device_by_name("blivetTestSubVol2")
        self.assertIsNotNone(sub2)
        self.assertFalse(sub2.format.is_empty)

        # third subvolume is also empty
        sub3 = self.storage.devicetree.get_device_by_name("blivetTestSubVol2/blivetTestSubVol3")
        self.assertIsNotNone(sub3)
        self.assertTrue(sub3.format.is_empty)
