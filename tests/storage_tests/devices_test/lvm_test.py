import os
import shutil
import subprocess
import tempfile

from ..storagetestcase import StorageTestCase

import blivet


class LVMTestCase(StorageTestCase):

    vgname = "blivetTestVG"

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

    def _get_pv_size(self, pv):
        out = subprocess.check_output(["pvs", "-o", "pv_size", "--noheadings", "--nosuffix", "--units=b", pv])
        return blivet.size.Size(out.decode().strip())

    def _get_vg_size(self, vg):
        out = subprocess.check_output(["vgs", "-o", "vg_size", "--noheadings", "--nosuffix", "--units=b", vg])
        return blivet.size.Size(out.decode().strip())

    def _get_vg_free(self, vg):
        out = subprocess.check_output(["vgs", "-o", "vg_free", "--noheadings", "--nosuffix", "--units=b", vg])
        return blivet.size.Size(out.decode().strip())

    def _clean_up(self):
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        ret = os.system("vgs blivetTestVG >/dev/null 2>&1")
        if ret == 0:
            raise RuntimeError("blivetTestVG not removed by recursive remove")
        else:
            # XXX sometimes vgremove doesn't remove the /dev/<vgname> folder on Debian
            if os.path.exists("/dev/%s" % self.vgname):
                shutil.rmtree("/dev/%s" % self.vgname, ignore_errors=True)

        return super()._clean_up()

    def test_lvm_basic(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                        parents=[disk])
        self.storage.create_device(pv)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name=self.vgname, parents=[pv])
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
        pv_size = self._get_pv_size(pv.path)
        self.assertEqual(pv.format.size, pv_size)

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        self.assertIsInstance(vg, blivet.devices.LVMVolumeGroupDevice)
        self.assertIsNotNone(vg.format)
        self.assertIsNone(vg.format.type)
        self.assertEqual(pv.format.vg_name, vg.name)
        self.assertEqual(pv.format.vg_uuid, vg.uuid)
        self.assertEqual(len(vg.parents), 1)
        self.assertEqual(vg.parents[0], pv)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        lv = self.storage.devicetree.get_device_by_name("%s-blivetTestLV" % self.vgname)
        self.assertIsNotNone(lv)
        self.assertIsInstance(lv, blivet.devices.LVMLogicalVolumeDevice)
        self.assertIsNotNone(lv.format)
        self.assertEqual(lv.format.type, "ext4")
        self.assertEqual(lv.vg, vg)
        self.assertEqual(len(lv.parents), 1)
        self.assertEqual(lv.parents[0], vg)

        self.storage.destroy_device(lv)
        self.storage.destroy_device(vg)

        pv = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "1")
        self.assertIsNone(pv.format.vg_name)
        self.assertIsNone(pv.format.vg_uuid)

    def test_lvm_thin(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                        parents=[disk])
        self.storage.create_device(pv)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name=self.vgname, parents=[pv])
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

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        pool = self.storage.devicetree.get_device_by_name("%s-blivetTestPool" % self.vgname)
        self.assertIsNotNone(pool)
        self.assertTrue(pool.is_thin_pool)

        thinlv = self.storage.devicetree.get_device_by_name("%s-blivetTestThinLV" % self.vgname)
        self.assertIsNotNone(thinlv)
        self.assertTrue(thinlv.is_thin_lv)
        self.assertEqual(len(thinlv.parents), 1)
        self.assertEqual(thinlv.parents[0], pool)
        self.assertEqual(thinlv.pool, pool)

        snap = self.storage.devicetree.get_device_by_name("%s-blivetTestThinLV_snapshot" % self.vgname)
        self.assertIsNotNone(snap)
        self.assertTrue(snap.is_snapshot_lv)
        self.assertEqual(snap.origin, thinlv)

    def _test_lvm_raid(self, seg_type, raid_level, stripe_size=0):
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

        vg = self.storage.new_vg(name=self.vgname, parents=[pv1, pv2])
        self.storage.create_device(vg)

        raidlv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                     parents=[vg], name="blivetTestRAIDLV",
                                     seg_type=seg_type, pvs=[pv1, pv2], stripe_size=stripe_size)
        self.storage.create_device(raidlv)

        self.storage.do_it()
        self.storage.reset()

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)

        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space + vg.reserved_space)

        raidlv = self.storage.devicetree.get_device_by_name("%s-blivetTestRAIDLV" % self.vgname)
        self.assertIsNotNone(raidlv)
        self.assertTrue(raidlv.is_raid_lv)
        self.assertEqual(raidlv.raid_level, raid_level)
        self.assertEqual(raidlv.seg_type, seg_type)

        if stripe_size:
            out = subprocess.check_output(["lvs", "-o", "stripe_size", "--noheadings", "--nosuffix", "--units=b", raidlv.vg.name + "/" + raidlv.lvname])
            self.assertEqual(out.decode().strip(), str(int(stripe_size.convert_to())))

    def test_lvm_raid_raid0(self):
        self._test_lvm_raid("raid0", blivet.devicelibs.raid.RAID0)

    def test_lvm_raid_raid0_stripe_size(self):
        self._test_lvm_raid("raid0", blivet.devicelibs.raid.RAID0, stripe_size=blivet.size.Size("1 MiB"))

    def test_lvm_raid_striped(self):
        self._test_lvm_raid("striped", blivet.devicelibs.raid.Striped)

    def test_lvm_raid_raid1(self):
        self._test_lvm_raid("raid1", blivet.devicelibs.raid.RAID1)

    def test_lvm_raid_mirror(self):
        self._test_lvm_raid("mirror", blivet.devicelibs.raid.RAID1)

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

        vg = self.storage.new_vg(name=self.vgname, parents=[pv1, pv2])
        self.storage.create_device(vg)

        cache_spec = blivet.devices.lvm.LVMCacheRequest(size=blivet.size.Size("50 MiB"), pvs=[pv2])
        cachedlv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                       parents=[vg], name="blivetTestCachedLV",
                                       cache_request=cache_spec)
        self.storage.create_device(cachedlv)

        self.storage.do_it()
        self.storage.reset()

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        cachedlv = self.storage.devicetree.get_device_by_name("%s-blivetTestCachedLV" % self.vgname)
        self.assertIsNotNone(cachedlv)
        self.assertTrue(cachedlv.cached)
        self.assertIsNotNone(cachedlv.cache)

    def test_lvm_cache_attach(self):
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

        vg = self.storage.new_vg(name=self.vgname, parents=[pv1, pv2])
        self.storage.create_device(vg)

        cachedlv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                       parents=[vg], name="blivetTestCachedLV")
        self.storage.create_device(cachedlv)

        # create the cache pool
        cachepool = self.storage.new_lv(size=blivet.size.Size("50 MiB"), parents=[vg],
                                        pvs=[pv2], cache_pool=True, name="blivetTestFastLV")
        self.storage.create_device(cachepool)

        self.storage.do_it()
        self.storage.reset()

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        cachedlv = self.storage.devicetree.get_device_by_name("%s-blivetTestCachedLV" % self.vgname)
        self.assertIsNotNone(cachedlv)
        cachepool = self.storage.devicetree.get_device_by_name("%s-blivetTestFastLV" % self.vgname)
        self.assertIsNotNone(cachepool)

        # attach the cache pool to the LV
        cachedlv.attach_cache(cachepool)

        self.storage.reset()
        cachedlv = self.storage.devicetree.get_device_by_name("%s-blivetTestCachedLV" % self.vgname)
        self.assertIsNotNone(cachedlv)
        self.assertTrue(cachedlv.cached)
        self.assertIsNotNone(cachedlv.cache)

        # detach the cache again
        cachedlv.cache.detach()

        self.storage.reset()
        cachedlv = self.storage.devicetree.get_device_by_name("%s-blivetTestCachedLV" % self.vgname)
        self.assertIsNotNone(cachedlv)
        self.assertFalse(cachedlv.cached)
        self.assertIsNone(cachedlv.cache)
        cachepool = self.storage.devicetree.get_device_by_name("%s-blivetTestFastLV" % self.vgname)
        self.assertIsNotNone(cachepool)

    def test_lvm_cache_create_and_attach(self):
        blivet.util.set_up_logging()
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

        vg = self.storage.new_vg(name=self.vgname, parents=[pv1, pv2])
        self.storage.create_device(vg)

        cachedlv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                       parents=[vg], name="blivetTestCachedLV")
        self.storage.create_device(cachedlv)

        self.storage.do_it()
        self.storage.reset()

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        cachedlv = self.storage.devicetree.get_device_by_name("%s-blivetTestCachedLV" % self.vgname)
        self.assertIsNotNone(cachedlv)

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        pv2 = self.storage.devicetree.get_device_by_name(pv2.name)

        # create the cache pool and attach it to the LV
        cachepool = self.storage.new_lv(size=blivet.size.Size("50 MiB"), parents=[vg],
                                        pvs=[pv2], cache_pool=True, name="blivetTestFastLV",
                                        attach_to=cachedlv)
        self.storage.create_device(cachepool)

        self.storage.do_it()
        self.storage.reset()

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        cachedlv = self.storage.devicetree.get_device_by_name("%s-blivetTestCachedLV" % self.vgname)
        self.assertIsNotNone(cachedlv)
        self.assertTrue(cachedlv.cached)
        self.assertIsNotNone(cachedlv.cache)

        # the cachepool shouldn't be in the devicetree now
        cachepool = self.storage.devicetree.get_device_by_name("%s-blivetTestFastLV" % self.vgname)
        self.assertIsNone(cachepool)

    def test_lvm_pvs_add_remove(self):
        disk1 = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk1)
        self.storage.initialize_disk(disk1)

        pv1 = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                         parents=[disk1])
        self.storage.create_device(pv1)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name=self.vgname, parents=[pv1])
        self.storage.create_device(vg)

        lv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                 parents=[vg], name="blivetTestLV")
        self.storage.create_device(lv)

        self.storage.do_it()

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        # create a second PV
        disk2 = self.storage.devicetree.get_device_by_path(self.vdevs[1])
        self.assertIsNotNone(disk2)
        self.storage.initialize_disk(disk2)

        pv2 = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                         parents=[disk2])
        self.storage.create_device(pv2)

        blivet.partitioning.do_partitioning(self.storage)

        self.storage.do_it()
        self.storage.reset()

        pv1 = self.storage.devicetree.get_device_by_name(pv1.name)
        pv1_size = self._get_pv_size(pv1.path)
        self.assertEqual(pv1.format.size, pv1_size)

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        # add the PV to the existing VG
        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        pv2 = self.storage.devicetree.get_device_by_name(pv2.name)

        ac = blivet.deviceaction.ActionAddMember(vg, pv2)
        self.storage.devicetree.actions.add(ac)
        self.storage.do_it()

        pv2 = self.storage.devicetree.get_device_by_name(pv2.name)
        pv2_size = self._get_pv_size(pv2.path)
        self.assertEqual(pv2.format.size, pv2_size)

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        self.assertEqual(pv2.format.vg_name, vg.name)

        self.storage.reset()
        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        self.assertEqual(len(vg.pvs), 2)

        # remove the first PV from the VG
        pv1 = self.storage.devicetree.get_device_by_name(pv1.name)
        ac = blivet.deviceaction.ActionRemoveMember(vg, pv1)
        self.storage.devicetree.actions.add(ac)

        self.assertIsNone(pv1.format.vg_name)
        self.assertIsNone(pv1.format.vg_uuid)

        # schedule also removing the lvmpv format from the PV
        ac = blivet.deviceaction.ActionDestroyFormat(pv1)
        self.storage.devicetree.actions.add(ac)

        self.storage.do_it()

        pv2 = self.storage.devicetree.get_device_by_name(pv2.name)
        pv2_size = self._get_pv_size(pv2.path)
        self.assertEqual(pv2.format.size, pv2_size)

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

        self.assertIsNone(pv1.format.type)

        self.storage.reset()

        self.storage.reset()
        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        self.assertEqual(len(vg.pvs), 1)
        self.assertEqual(vg.pvs[0].name, pv2.name)

    def test_lvm_pv_size(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                        parents=[disk])
        self.storage.create_device(pv)

        blivet.partitioning.do_partitioning(self.storage)

        self.storage.do_it()
        self.storage.reset()

        pv = self.storage.devicetree.get_device_by_name(pv.name)
        self.assertIsNotNone(pv)

        pv.format.update_size_info()
        self.assertTrue(pv.format.resizable)

        ac = blivet.deviceaction.ActionResizeFormat(pv, blivet.size.Size("50 MiB"))
        self.storage.devicetree.actions.add(ac)

        self.storage.do_it()
        self.storage.reset()

        pv = self.storage.devicetree.get_device_by_name(pv.name)
        self.assertIsNotNone(pv)
        self.assertEqual(pv.format.size, blivet.size.Size("50 MiB"))
        pv_size = self._get_pv_size(pv.path)
        self.assertEqual(pv_size, pv.format.size)

        vg = self.storage.new_vg(name=self.vgname, parents=[pv])
        self.storage.create_device(vg)

        self.storage.do_it()
        self.storage.reset()

        pv = self.storage.devicetree.get_device_by_name(pv.name)
        self.assertIsNotNone(pv)
        pv_size = self._get_pv_size(pv.path)
        self.assertEqual(pv_size, pv.format.size)

        vg = self.storage.devicetree.get_device_by_name(self.vgname)
        self.assertIsNotNone(vg)
        vg_size = self._get_vg_size(vg.name)
        self.assertEqual(vg_size, vg.size)
        vg_free = self._get_vg_free(vg.name)
        self.assertEqual(vg_free, vg.free_space)

    def _break_thin_pool(self):
        os.system("vgchange -an %s >/dev/null 2>&1" % self.vgname)

        # changing transaction_id for the pool prevents it from being activated
        with tempfile.NamedTemporaryFile(prefix="blivet_test") as temp:
            os.system("vgcfgbackup -f %s %s >/dev/null 2>&1" % (temp.name, self.vgname))
            os.system("sed -i 's/transaction_id =.*/transaction_id = 123456/' %s >/dev/null 2>&1" % temp.name)
            os.system("vgcfgrestore -f %s %s --force >/dev/null 2>&1" % (temp.name, self.vgname))

    def test_lvm_broken_thin(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.initialize_disk(disk)

        pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                        parents=[disk])
        self.storage.create_device(pv)

        blivet.partitioning.do_partitioning(self.storage)

        vg = self.storage.new_vg(name=self.vgname, parents=[pv])
        self.storage.create_device(vg)

        pool = self.storage.new_lv(thin_pool=True, size=blivet.size.Size("50 MiB"),
                                   parents=[vg], name="blivetTestPool")
        self.storage.create_device(pool)

        self.storage.do_it()

        # intentionally break the thin pool created above
        self._break_thin_pool()

        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("%s-blivetTestPool" % self.vgname)
        self.assertIsNotNone(pool)

        # check that the pool cannot be activated
        try:
            pool.setup()
        except Exception:  # pylint: disable=broad-except
            pass
        else:
            self.fail("Failed to break thinpool for tests")

        # verify that the pool can be destroyed even if it cannot be activated
        self.storage.recursive_remove(pool)
        self.storage.do_it()
