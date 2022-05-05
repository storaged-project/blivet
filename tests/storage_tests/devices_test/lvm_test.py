import os

from ..storagetestcase import StorageTestCase

import blivet


class LVMTestCase(StorageTestCase):

    def setUp(self):
        super().setUp()

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

        return super()._clean_up()

    def test_lvm_basic(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                        parents=[disk])
        self.storage.create_device(pv)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name="blivetTestVG", parents=[pv])
        self.storage.create_device(vg)

        lv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                 parents=[vg], name="blivetTestLV")
        self.storage.create_device(lv)

        self.storage.do_it()
        self.storage.reset()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        pv = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "1")
        self.assertIsNotNone(pv)
        self.assertIsInstance(pv, blivet.devices.PartitionDevice)
        self.assertIsNotNone(pv.format)
        self.assertEqual(pv.format.type, "lvmpv")

        vg = self.storage.devicetree.get_device_by_name("blivetTestVG")
        self.assertIsNotNone(vg)
        self.assertIsInstance(vg, blivet.devices.LVMVolumeGroupDevice)
        self.assertIsNotNone(vg.format)
        self.assertIsNone(vg.format.type)
        self.assertEqual(pv.format.vg_name, vg.name)
        self.assertEqual(len(vg.parents), 1)
        self.assertEqual(vg.parents[0], pv)

        lv = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestLV")
        self.assertIsNotNone(lv)
        self.assertIsInstance(lv, blivet.devices.LVMLogicalVolumeDevice)
        self.assertIsNotNone(lv.format)
        self.assertEqual(lv.format.type, "ext4")
        self.assertEqual(lv.vg, vg)
        self.assertEqual(len(lv.parents), 1)
        self.assertEqual(lv.parents[0], vg)

    def test_lvm_thin(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                        parents=[disk])
        self.storage.create_device(pv)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name="blivetTestVG", parents=[pv])
        self.storage.create_device(vg)

        pool = self.storage.new_lv(thin_pool=True, size=blivet.size.Size("50 MiB"),
                                   parents=[vg], name="blivetTestPool")
        self.storage.create_device(pool)

        thinlv = self.storage.new_lv(thin_volume=True, fmt_type="ext4", size=blivet.size.Size("25 MiB"),
                                     parents=[pool], name="blivetTestThinLV")
        self.storage.create_device(thinlv)

        snap = self.storage.new_lv(name=thinlv.lvname + "_snapshot", parents=[pool], origin=thinlv,
                                   seg_type="thin")
        self.storage.create_device(snap)

        self.storage.do_it()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertTrue(pool.is_thin_pool)

        thinlv = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestThinLV")
        self.assertIsNotNone(thinlv)
        self.assertTrue(thinlv.is_thin_lv)
        self.assertEqual(len(thinlv.parents), 1)
        self.assertEqual(thinlv.parents[0], pool)
        self.assertEqual(thinlv.pool, pool)

        snap = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestThinLV_snapshot")
        self.assertIsNotNone(snap)
        self.assertTrue(snap.is_snapshot_lv)
        self.assertEqual(snap.origin, thinlv)

    def test_lvm_raid(self):
        disk1 = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk1)
        self.storage.initialize_disk(disk1)

        disk2 = self.storage.devicetree.get_device_by_path(self.vdevs[1])
        self.assertIsNotNone(disk2)
        self.storage.initialize_disk(disk2)

        pv1 = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                         parents=[disk1])
        self.storage.create_device(pv1)

        pv2 = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                         parents=[disk2])
        self.storage.create_device(pv2)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name="blivetTestVG", parents=[pv1, pv2])
        self.storage.create_device(vg)

        raidlv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                     parents=[vg], name="blivetTestRAIDLV",
                                     seg_type="raid1", pvs=[pv1, pv2])
        self.storage.create_device(raidlv)

        self.storage.do_it()
        self.storage.reset()

        raidlv = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestRAIDLV")
        self.assertIsNotNone(raidlv)
        self.assertTrue(raidlv.is_raid_lv)
        self.assertEqual(raidlv.raid_level, blivet.devicelibs.raid.RAID1)

    def test_lvm_cache(self):
        disk1 = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk1)
        self.storage.initialize_disk(disk1)

        disk2 = self.storage.devicetree.get_device_by_path(self.vdevs[1])
        self.assertIsNotNone(disk2)
        self.storage.initialize_disk(disk2)

        pv1 = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                         parents=[disk1])
        self.storage.create_device(pv1)

        pv2 = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                         parents=[disk2])
        self.storage.create_device(pv2)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name="blivetTestVG", parents=[pv1, pv2])
        self.storage.create_device(vg)

        cache_spec = blivet.devices.lvm.LVMCacheRequest(size=blivet.size.Size("50 MiB"), pvs=[pv2])
        cachedlv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                       parents=[vg], name="blivetTestCachedLV",
                                       cache_request=cache_spec)
        self.storage.create_device(cachedlv)

        self.storage.do_it()
        self.storage.reset()

        cachedlv = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestCachedLV")
        self.assertIsNotNone(cachedlv)
        self.assertTrue(cachedlv.cached)
        self.assertIsNotNone(cachedlv.cache)
