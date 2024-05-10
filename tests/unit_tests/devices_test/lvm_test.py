import unittest
from unittest.mock import patch, PropertyMock

import blivet

from blivet.devices import StorageDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices.lvm import LVMCache, LVMWriteCache, LVMVDOPoolMixin
from blivet.devices.lvm import LVMVDOLogicalVolumeMixin
from blivet.devices.lvm import LVMCacheRequest
from blivet.devices.lvm import LVPVSpec, LVMInternalLVtype, LVMCacheType
from blivet.size import Size
from blivet.devicelibs import raid
from blivet import devicefactory
from blivet import errors


@patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[])
class LVMDeviceTest(unittest.TestCase):

    def test_lvmsnap_shot_device_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.get_format("xfs"))

        with self.assertRaisesRegex(errors.DeviceError, "lvm snapshot origin must be a logical volume"):
            LVMLogicalVolumeDevice("snap1", parents=[vg], origin=pv)

        with self.assertRaisesRegex(errors.DeviceError, "only existing vorigin snapshots are supported"):
            LVMLogicalVolumeDevice("snap1", parents=[vg], vorigin=True)

        lv.exists = True
        snap1 = LVMLogicalVolumeDevice("snap1", parents=[vg], origin=lv)

        self.assertEqual(snap1.format.type, lv.format.type)
        lv.format = blivet.formats.get_format("DM_snapshot_cow", exists=True)
        self.assertEqual(snap1.format.type, lv.format.type)

        self.assertEqual(snap1.isleaf, True)
        self.assertEqual(snap1.direct, True)
        self.assertEqual(lv.isleaf, False)
        self.assertEqual(lv.direct, True)

        self.assertEqual(snap1.depends_on(lv), True)
        self.assertEqual(lv.depends_on(snap1), False)

    def test_lvmthin_snap_shot_device_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        pool = LVMLogicalVolumeDevice("pool1", parents=[vg], size=Size("500 MiB"), seg_type="thin-pool")
        thinlv = LVMLogicalVolumeDevice("thinlv", parents=[pool], size=Size("200 MiB"), seg_type="thin")

        with self.assertRaisesRegex(errors.DeviceError, "lvm snapshot origin must be a logical volume"):
            LVMLogicalVolumeDevice("snap1", parents=[pool], origin=pv, seg_type="thin")

        # now make the constructor succeed so we can test some properties
        thinlv.exists = True
        snap1 = LVMLogicalVolumeDevice("snap1", parents=[pool], origin=thinlv, seg_type="thin")
        self.assertEqual(snap1.isleaf, True)
        self.assertEqual(snap1.direct, True)
        self.assertEqual(thinlv.isleaf, True)
        self.assertEqual(thinlv.direct, True)

        self.assertEqual(snap1.depends_on(thinlv), True)
        self.assertEqual(thinlv.depends_on(snap1), False)

        # existing thin snapshots do not depend on their origin
        snap1.exists = True
        self.assertEqual(snap1.depends_on(thinlv), False)

    def test_lvmcached_logical_volume_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("512 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        cache_req = LVMCacheRequest(Size("512 MiB"), [pv2], "writethrough")
        xfs_fmt = blivet.formats.get_format("xfs")
        lv = LVMLogicalVolumeDevice("testlv",
                                    parents=[vg],
                                    fmt=xfs_fmt,
                                    size=Size(xfs_fmt.min_size),
                                    exists=False,
                                    cache_request=cache_req)
        self.assertEqual(lv.size, xfs_fmt.min_size)

        # check that the LV behaves like a cached LV
        self.assertTrue(lv.cached)
        cache = lv.cache
        self.assertIsNotNone(cache)
        self.assertIsInstance(cache, LVMCache)

        # the cache reserves space for its metadata from the requested size, but
        # it may require (and does in this case) a pmspare LV to be allocated
        self.assertEqual(lv.vg_space_used, lv.cache.size + lv.cache.md_size + lv.size)

        # check parameters reported by the (non-existing) cache
        # 512 MiB - 8 MiB (metadata) - 8 MiB (pmspare)
        self.assertEqual(cache.size, Size("496 MiB"))
        self.assertEqual(cache.md_size, Size("8 MiB"))
        self.assertEqual(cache.vg_space_used, Size("504 MiB"))
        self.assertIsInstance(cache.size, Size)
        self.assertIsInstance(cache.md_size, Size)
        self.assertIsInstance(cache.vg_space_used, Size)
        self.assertFalse(cache.exists)
        self.assertIsNone(cache.stats)
        self.assertEqual(cache.mode, "writethrough")
        self.assertIsNone(cache.backing_device_name)
        self.assertIsNone(cache.cache_device_name)
        self.assertEqual(set(cache.fast_pvs), set([pv2]))

    def test_lvmcached_two_logical_volume_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("512 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        cache_req = LVMCacheRequest(Size("256 MiB"), [pv2], "writethrough")
        lv1 = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                     fmt=blivet.formats.get_format("xfs"),
                                     exists=False, cache_request=cache_req)

        cache_req = LVMCacheRequest(Size("256 MiB"), [pv2], "writethrough")
        lv2 = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                     fmt=blivet.formats.get_format("xfs"),
                                     exists=False, cache_request=cache_req)

        cache = lv1.cache
        self.assertIsNotNone(cache)
        # 256 MiB - 8 MiB (metadata) - 8 MiB (pmspare)
        self.assertEqual(cache.size, Size("240 MiB"))

        cache = lv2.cache
        self.assertIsNotNone(cache)
        # already have pmspare space reserved for lv1's cache (and shared)
        # 256 MiB - 8 MiB (metadata) [no pmspare]
        self.assertEqual(cache.size, Size("248 MiB"))

    def test_lvmwritecached_logical_volume_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("512 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        req_size = pv2.format.free
        cache_req = LVMCacheRequest(req_size, [pv2], cache_type=LVMCacheType.lvmwritecache)
        xfs_fmt = blivet.formats.get_format("xfs")
        lv = LVMLogicalVolumeDevice("testlv",
                                    parents=[vg],
                                    fmt=xfs_fmt,
                                    size=Size(xfs_fmt.min_size),
                                    exists=False,
                                    cache_request=cache_req)
        self.assertEqual(lv.size, xfs_fmt.min_size)

        # check that the LV behaves like a cached LV
        self.assertTrue(lv.cached)
        cache = lv.cache
        self.assertIsNotNone(cache)
        self.assertIsInstance(cache, LVMWriteCache)

        # the cache reserves space for its metadata from the requested size, but
        # it may require (and does in this case) a pmspare LV to be allocated
        self.assertEqual(lv.vg_space_used, lv.cache.size + lv.cache.md_size + lv.size)

        self.assertEqual(cache.size, req_size)
        self.assertEqual(cache.vg_space_used, req_size)
        self.assertIsInstance(cache.size, Size)
        self.assertIsInstance(cache.vg_space_used, Size)
        self.assertFalse(cache.exists)
        self.assertIsNone(cache.backing_device_name)
        self.assertIsNone(cache.cache_device_name)
        self.assertEqual(set(cache.fast_pvs), set([pv2]))

    def test_lvm_logical_volume_with_pvs_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("512 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        pv_spec = LVPVSpec(pv, Size("1 GiB"))
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("1 GiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, pvs=[pv_spec])

        self.assertEqual([spec.pv for spec in lv._pv_specs], [pv])

    def test_lvm_logical_volume_segtype_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        with self.assertRaises(ValueError):
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("1 GiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, seg_type="raid8", pvs=[pv, pv2])

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("1 GiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, seg_type="striped", pvs=[pv, pv2])

        self.assertEqual(lv.seg_type, "striped")

    def test_lvm_logical_volume_segtype_pv_free(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("1 GiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, seg_type="striped", pvs=[pv, pv2])

        self.assertEqual(lv.seg_type, "striped")
        self.assertEqual(pv.format.free, Size("512 MiB"))
        self.assertEqual(pv2.format.free, 0)

    def test_lvm_logical_volume_pv_free_linear(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])
        pv_spec = LVPVSpec(pv, Size("256 MiB"))
        pv_spec2 = LVPVSpec(pv2, Size("256 MiB"))
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, pvs=[pv_spec, pv_spec2])
        self.assertEqual(lv.seg_type, "linear")
        self.assertEqual(pv.format.free, Size("768 MiB"))
        self.assertEqual(pv2.format.free, Size("256 MiB"))

    def test_lvm_logical_volume_raid_level(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, seg_type="raid1", pvs=[pv, pv2])

        self.assertEqual(lv.seg_type, "raid1")
        # 512 MiB - 4 MiB (metadata)
        self.assertEqual(lv.size, Size("508 MiB"))
        self.assertEqual(lv._raid_level, raid.RAID1)
        self.assertTrue(lv.is_raid_lv)
        self.assertEqual(lv.num_raid_pvs, 2)

    def test_lvm_logical_volume_mirror(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, seg_type="mirror", pvs=[pv, pv2])

        self.assertEqual(lv.seg_type, "mirror")
        # 512 MiB - 4 MiB (metadata)
        self.assertEqual(lv.size, Size("508 MiB"))
        self.assertEqual(lv._raid_level, raid.RAID1)
        self.assertTrue(lv.is_raid_lv)
        self.assertEqual(lv.num_raid_pvs, 2)

    def test_lvm_logical_volume_raid0(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, seg_type="raid0", pvs=[pv, pv2])

        self.assertEqual(lv.seg_type, "raid0")
        # 512 MiB - 4 MiB (metadata)
        self.assertEqual(lv.size, Size("508 MiB"))
        self.assertEqual(lv._raid_level, raid.RAID0)
        self.assertTrue(lv.is_raid_lv)
        self.assertEqual(lv.num_raid_pvs, 2)

    def test_lvm_logical_volume_insuf_seg_type(self):
        # pylint: disable=unused-variable
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        # pvs have to be specified for non-linear LVs
        with self.assertRaises(errors.DeviceError):
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, seg_type="raid1")
        with self.assertRaises(errors.DeviceError):
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, seg_type="striped")

        # no or complete specification has to be given for linear LVs
        with self.assertRaises(errors.DeviceError):
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, pvs=[pv])
        with self.assertRaises(errors.DeviceError):
            pv_spec = LVPVSpec(pv, Size("256 MiB"))
            pv_spec2 = LVPVSpec(pv2, Size("250 MiB"))
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, pvs=[pv_spec, pv_spec2])

    def test_lvm_logical_volume_metadata_size(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, seg_type="raid1", pvs=[pv, pv2])
        self.assertEqual(lv.metadata_size, Size("4 MiB"))
        # two copies of metadata
        self.assertEqual(lv.metadata_vg_space_used, Size("8 MiB"))

    def test_lvm_logical_volume_pv_free_cached(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])
        pv_spec = LVPVSpec(pv, Size("256 MiB"))
        pv_spec2 = LVPVSpec(pv2, Size("256 MiB"))
        cache_req = LVMCacheRequest(Size("512 MiB"), [pv], "writethrough")
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, cache_request=cache_req,
                                    pvs=[pv_spec, pv_spec2])
        self.assertEqual(lv.seg_type, "linear")
        # 1024 MiB (free) - 256 MiB (LV part) - 504 MiB (cache shrank for pmspare space)
        self.assertEqual(pv.format.free, Size("264 MiB"))
        self.assertEqual(pv2.format.free, Size("256 MiB"))

    def test_lvm_logical_volume_raid_stripe_size(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        with self.assertRaises(blivet.errors.DeviceError):
            # non-raid LV
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("1 GiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, stripe_size=Size("1 MiB"))

        with self.assertRaises(blivet.errors.DeviceError):
            # raid1 LV
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("1 GiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, seg_type="raid1", pvs=[pv, pv2],
                                        stripe_size=Size("1 MiB"))

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("1 GiB"),
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, seg_type="raid0", pvs=[pv, pv2],
                                    stripe_size=Size("1 MiB"))

        self.assertEqual(lv._stripe_size, Size("1 MiB"))

    @patch("blivet.formats.fs.Ext4FS.resizable", return_value=True)
    def test_target_size(self, *args):  # pylint: disable=unused-argument
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        orig_size = Size("800 MiB")
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=orig_size,
                                    fmt=blivet.formats.get_format("ext4"),
                                    exists=True)

        min_size = Size("200 MiB")
        lv.format.exists = True
        lv.format._min_instance_size = min_size
        lv.format._resizable = True

        # Make sure things are as expected to begin with.
        self.assertEqual(lv.min_size, min_size)
        self.assertEqual(lv.max_size, Size("1020 MiB"))
        self.assertEqual(lv.size, orig_size)

        # ValueError if size smaller than min_size
        with self.assertRaisesRegex(ValueError,
                                    "size.*smaller than the minimum"):
            lv.target_size = Size("1 MiB")

        # target size should be unchanged
        self.assertEqual(lv.target_size, orig_size)

        # ValueError if size larger than max_size
        with self.assertRaisesRegex(ValueError,
                                    "size.*larger than the maximum"):
            lv.target_size = Size("1 GiB")

        # target size should be unchanged
        self.assertEqual(lv.target_size, orig_size)

        # successful set of target size should also be reflected in size attr
        new_target = Size("900 MiB")
        lv.target_size = new_target
        self.assertEqual(lv.target_size, new_target)
        self.assertEqual(lv.size, new_target)

        # reset target size to original size
        lv.target_size = orig_size
        self.assertEqual(lv.target_size, orig_size)
        self.assertEqual(lv.size, orig_size)

    def test_lvm_inconsistent_sector_size(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1024 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("1024 MiB"))

        with patch("blivet.devices.StorageDevice.sector_size", new_callable=PropertyMock) as mock_property:
            mock_property.__get__ = lambda _mock, pv, _class: 512 if pv.name == "pv1" else 4096
            with self.assertRaisesRegex(errors.InconsistentParentSectorSize, "Cannot create volume group"):
                LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

    def test_skip_activate(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv = LVMLogicalVolumeDevice("data_lv", parents=[vg], size=Size("500 MiB"), exists=True)

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                lvm.lvactivate.assert_called_with(vg.name, lv.lvname, ignore_skip=False)

        lv.ignore_skip_activation += 1
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                lvm.lvactivate.assert_called_with(vg.name, lv.lvname, ignore_skip=True)

        lv.ignore_skip_activation += 1
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                lvm.lvactivate.assert_called_with(vg.name, lv.lvname, ignore_skip=True)

        lv.ignore_skip_activation -= 2
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                lvm.lvactivate.assert_called_with(vg.name, lv.lvname, ignore_skip=False)

    @patch("blivet.tasks.availability.BLOCKDEV_LVM_PLUGIN_SHARED",
           new=blivet.tasks.availability.ExternalResource(blivet.tasks.availability.AvailableMethod, ""))
    def test_lv_activate_shared(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv = LVMLogicalVolumeDevice("data_lv", parents=[vg], size=Size("500 MiB"), exists=True, shared=True)

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                lvm.lvactivate.assert_called_with(vg.name, lv.lvname, ignore_skip=False, shared=True)

    @patch("blivet.tasks.availability.BLOCKDEV_LVM_PLUGIN_SHARED",
           new=blivet.tasks.availability.ExternalResource(blivet.tasks.availability.AvailableMethod, ""))
    def test_vg_create_shared(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], shared=True)

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            vg._create()
            lvm.vgcreate.assert_called_with(vg.name, [pv.path], Size("4 MiB"), shared="")
            lvm.vglock_start.assert_called_with(vg.name)

    def test_vg_is_empty(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1024 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        self.assertTrue(vg.is_empty)

        LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                               fmt=blivet.formats.get_format("xfs"),
                               exists=False)
        self.assertFalse(vg.is_empty)

    def test_lvm_vdo_pool(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        pool = LVMLogicalVolumeDevice("testpool", parents=[vg], size=Size("512 MiB"),
                                      seg_type="vdo-pool", exists=True)
        self.assertTrue(pool.is_vdo_pool)

        free = vg.free_space
        lv = LVMLogicalVolumeDevice("testlv", parents=[pool], size=Size("2 GiB"),
                                    seg_type="vdo", exists=True)
        self.assertTrue(lv.is_vdo_lv)
        self.assertEqual(lv.vg, vg)
        self.assertEqual(lv.pool, pool)

        # free space in the vg shouldn't be affected by the vdo lv
        self.assertEqual(lv.vg_space_used, 0)
        self.assertEqual(free, vg.free_space)

        self.assertListEqual(pool.lvs, [lv])

        # now try to destroy both the pool and the vdo lv
        # for the lv this should be a no-op, destroying the pool should destroy both
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            lv.destroy()
            lv.remove_hook()
            self.assertFalse(lv.exists)
            self.assertFalse(lvm.lvremove.called)
            self.assertListEqual(pool.lvs, [])

            pool.destroy()
            self.assertFalse(pool.exists)
            self.assertTrue(lvm.lvremove.called)

    def test_lvmthinpool_chunk_size(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("100 TiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        pool = LVMLogicalVolumeDevice("pool1", parents=[vg], size=Size("500 MiB"), seg_type="thin-pool")
        self.assertEqual(pool.chunk_size, Size("64 KiB"))

        pool.size = Size("16 TiB")
        pool.autoset_md_size(enforced=True)
        self.assertEqual(pool.chunk_size, Size("128 KiB"))

    def test_add_remove_pv(self):
        pv1 = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("1024 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("1024 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv1], uuid="b0bf62ba-2a96-437e-8299-b0c5fffc43bb")

        vg._add_parent(pv2)
        self.assertEqual(pv2.format.vg_name, vg.name)

        vg._remove_parent(pv2)
        self.assertEqual(pv2.format.vg_name, None)
        self.assertEqual(pv2.format.vg_uuid, None)

    def test_device_id(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        self.assertEqual(vg.device_id, "LVM-testvg")

        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.get_format("xfs"))
        self.assertEqual(lv.device_id, "LVM-testvg-testlv")


class TypeSpecificCallsTest(unittest.TestCase):
    def test_type_specific_calls(self):
        class A(object):
            def __init__(self, a):
                self._a = a

            @property
            def is_a(self):
                return self._a == "A"

            def say_hello(self):
                return "Hello from A"

            @property
            def greeting(self):
                return self._greet or "Hi, this is A"

            @greeting.setter
            def greeting(self, val):
                self._greet = "Set by A: %s" % val  # pylint: disable=attribute-defined-outside-init

        class B(object):
            def __init__(self, b):
                self._b = b

            @property
            def is_b(self):
                return self._b == "B"

            def say_hello(self):
                return "Hello from B"

            @property
            def greeting(self):
                return self._greet or "Hi, this is B"

            @greeting.setter
            def greeting(self, val):
                self._greet = "Set by B: %s" % val  # pylint: disable=attribute-defined-outside-init

        class C(A, B):
            def __init__(self, a, b):
                A.__init__(self, a)
                B.__init__(self, b)
                self._greet = None

            def _get_type_classes(self):
                """Method to get type classes for this particular instance"""
                ret = []
                if self.is_a:
                    ret.append(A)
                if self.is_b:
                    ret.append(B)
                return ret

            def _try_specific_call(self, method, *args, **kwargs):
                """Try to call a type-specific method for this particular instance"""
                clss = self._get_type_classes()
                for cls in clss:
                    if hasattr(cls, method):
                        # found, get the specific property
                        if isinstance(vars(cls)[method], property):
                            if len(args) == 0 and len(kwargs.keys()) == 0:
                                # this is how you call the getter method of the property object
                                ret = getattr(cls, method).__get__(self)
                            else:
                                # this is how you call the setter method of the property object
                                ret = getattr(cls, method).__set__(self, *args, **kwargs)
                        else:
                            # or call the type-specific method
                            ret = getattr(cls, method)(self, *args, **kwargs)
                        return (True, ret)
                # not found, let the caller know
                return (False, None)

            # decorator
            def type_specific(meth):  # pylint: disable=no-self-argument
                """Decorator that makes sure the type-specific code is executed if available"""
                def decorated(self, *args, **kwargs):
                    found, ret = self._try_specific_call(meth.__name__, *args, **kwargs)  # pylint: disable=no-member
                    if found:
                        # nothing more to do here
                        return ret
                    else:
                        return meth(self, *args, **kwargs)  # pylint: disable=not-callable

                return decorated

            @type_specific
            def say_hello(self):
                return "Hello from C"

            @property
            @type_specific
            def greeting(self):
                return self._greet or "Hi, this is C"

            @greeting.setter
            @type_specific
            def greeting(self, val):  # pylint: disable=arguments-differ
                self._greet = val  # pylint: disable=attribute-defined-outside-init

        # a non-specific instance
        c = C(a="x", b="y")
        self.assertEqual(c.say_hello(), "Hello from C")
        self.assertEqual(c.greeting, "Hi, this is C")
        c.greeting = "Welcome"
        self.assertEqual(c.greeting, "Welcome")

        # an A-specific instance
        c = C(a="A", b="y")
        self.assertEqual(c.say_hello(), "Hello from A")
        self.assertEqual(c.greeting, "Hi, this is A")
        c.greeting = "Welcome"
        self.assertEqual(c.greeting, "Set by A: Welcome")

        # a B-specific instance
        c = C(a="x", b="B")
        self.assertEqual(c.say_hello(), "Hello from B")
        self.assertEqual(c.greeting, "Hi, this is B")
        c.greeting = "Welcome"
        self.assertEqual(c.greeting, "Set by B: Welcome")

        # both A-B-specific instance
        # A is listed first so it should win
        c = C(a="A", b="B")
        self.assertEqual(c.say_hello(), "Hello from A")
        self.assertEqual(c.greeting, "Hi, this is A")
        c.greeting = "Welcome"
        self.assertEqual(c.greeting, "Set by A: Welcome")


class BlivetLVMUnitTest(unittest.TestCase):

    @patch("blivet.formats.fs.Ext4FS.supported", return_value=True)
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    def setUp(self, *args):  # pylint: disable=unused-argument,arguments-differ
        self.b = blivet.Blivet()


@patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[])
@patch("blivet.devices.dm.DMDevice._external_dependencies", new=[])
class BlivetNewLVMDeviceTest(BlivetLVMUnitTest):
    def test_new_lv_from_lvs(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv1 = LVMLogicalVolumeDevice("data_lv", parents=[vg], size=Size("500 MiB"), exists=True)
        lv2 = LVMLogicalVolumeDevice("metadata_lv", parents=[vg], size=Size("50 MiB"), exists=True)

        for dev in (pv, vg, lv1, lv2):
            self.b.devicetree._add_device(dev)

        # check that all the above devices are in the expected places
        self.assertEqual(set(self.b.devices), {pv, vg, lv1, lv2})
        self.assertEqual(set(self.b.vgs), {vg})
        self.assertEqual(set(self.b.lvs), {lv1, lv2})
        self.assertEqual(set(self.b.vgs[0].lvs), {lv1, lv2})

        self.assertEqual(vg.size, Size("1020 MiB"))
        self.assertEqual(lv1.size, Size("500 MiB"))
        self.assertEqual(lv2.size, Size("50 MiB"))

        # combine the two LVs into a thin pool (the LVs should become its internal LVs)
        pool = self.b.new_lv_from_lvs(vg, name="pool", seg_type="thin-pool", from_lvs=(lv1, lv2))

        # add the pool LV into the devicetree
        self.b.devicetree._add_device(pool)

        self.assertEqual(set(self.b.devices), {pv, vg, pool})
        self.assertEqual(set(self.b.vgs), {vg})
        self.assertEqual(set(self.b.lvs), {pool})
        self.assertEqual(set(self.b.vgs[0].lvs), {pool})
        self.assertEqual(set(self.b.vgs[0].lvs[0]._internal_lvs), {lv1, lv2})

        self.assertTrue(lv1.is_internal_lv)
        self.assertEqual(lv1.int_lv_type, LVMInternalLVtype.data)
        self.assertEqual(lv1.size, Size("500 MiB"))
        self.assertTrue(lv2.is_internal_lv)
        self.assertEqual(lv2.int_lv_type, LVMInternalLVtype.meta)
        self.assertEqual(lv2.size, Size("50 MiB"))

        self.assertEqual(pool.name, "testvg-pool")
        self.assertEqual(pool.size, Size("500 MiB"))
        self.assertEqual(pool.metadata_size, Size("50 MiB"))
        self.assertIs(pool.vg, vg)

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(pool, "_pre_create"):
                pool.create()
                self.assertTrue(lvm.thpool_convert.called)

    def test_new_lv_from_non_existing_lvs(self):
        # same test as above, just with non-existing LVs used to create the new one
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv1 = LVMLogicalVolumeDevice("data_lv", parents=[vg], size=Size("500 MiB"), exists=False)
        lv2 = LVMLogicalVolumeDevice("metadata_lv", parents=[vg], size=Size("50 MiB"), exists=False)

        for dev in (pv, vg, lv1, lv2):
            self.b.devicetree._add_device(dev)

        # check that all the above devices are in the expected places
        self.assertEqual(set(self.b.devices), {pv, vg, lv1, lv2})
        self.assertEqual(set(self.b.vgs), {vg})
        self.assertEqual(set(self.b.lvs), {lv1, lv2})
        self.assertEqual(set(self.b.vgs[0].lvs), {lv1, lv2})

        self.assertEqual(vg.size, Size("1020 MiB"))
        self.assertEqual(lv1.size, Size("500 MiB"))
        self.assertEqual(lv2.size, Size("50 MiB"))

        # combine the two LVs into a thin pool (the LVs should become its internal LVs)
        pool = self.b.new_lv_from_lvs(vg, name="pool", seg_type="thin-pool", from_lvs=(lv1, lv2))

        # add the pool LV into the devicetree
        self.b.devicetree._add_device(pool)

        self.assertEqual(set(self.b.devices), {pv, vg, pool})
        self.assertEqual(set(self.b.vgs), {vg})
        self.assertEqual(set(self.b.lvs), {pool})
        self.assertEqual(set(self.b.vgs[0].lvs), {pool})
        self.assertEqual(set(self.b.vgs[0].lvs[0]._internal_lvs), {lv1, lv2})

        self.assertTrue(lv1.is_internal_lv)
        self.assertEqual(lv1.int_lv_type, LVMInternalLVtype.data)
        self.assertEqual(lv1.size, Size("500 MiB"))
        self.assertTrue(lv2.is_internal_lv)
        self.assertEqual(lv2.int_lv_type, LVMInternalLVtype.meta)
        self.assertEqual(lv2.size, Size("50 MiB"))
        self.assertTrue(pool.depends_on(lv1))
        self.assertTrue(pool.depends_on(lv2))

        self.assertEqual(pool.name, "testvg-pool")
        self.assertEqual(pool.size, Size("500 MiB"))
        self.assertEqual(pool.metadata_size, Size("50 MiB"))
        self.assertIs(pool.vg, vg)

        # both component LVs don't exist
        with self.assertRaises(errors.DeviceError):
            with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
                pool.create()

        # lv2 will still not exist
        lv1.exists = True
        with self.assertRaises(errors.DeviceError):
            with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
                pool.create()

        # both component LVs exist, should just work
        lv2.exists = True
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(pool, "_pre_create"):
                pool.create()
                self.assertTrue(lvm.thpool_convert.called)


@patch("blivet.devices.lvm.LVMVDOPoolMixin._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[])
@patch("blivet.devices.dm.DMDevice._external_dependencies", new=[])
class BlivetNewLVMVDODeviceTest(BlivetLVMUnitTest):

    def test_new_vdo_pool(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("10 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)

        for dev in (pv, vg):
            self.b.devicetree._add_device(dev)

        # check that all the above devices are in the expected places
        self.assertEqual(set(self.b.devices), {pv, vg})
        self.assertEqual(set(self.b.vgs), {vg})

        self.assertEqual(vg.size, Size("10236 MiB"))

        with patch("blivet.devices.lvm.blockdev.lvm"):
            with self.assertRaises(ValueError):
                vdopool = self.b.new_lv(name="vdopool", vdo_pool=True,
                                        parents=[vg], compression=True,
                                        deduplication=True,
                                        size=blivet.size.Size("1 GiB"))

            vdopool = self.b.new_lv(name="vdopool", vdo_pool=True,
                                    parents=[vg], compression=True,
                                    deduplication=True,
                                    size=blivet.size.Size("8 GiB"))

            vdolv = self.b.new_lv(name="vdolv", vdo_lv=True,
                                  parents=[vdopool],
                                  size=blivet.size.Size("40 GiB"))

        self.b.create_device(vdopool)
        self.b.create_device(vdolv)

        self.assertEqual(vdopool.children[0], vdolv)
        self.assertEqual(vdolv.parents[0], vdopool)
        self.assertListEqual(vg.lvs, [vdopool, vdolv])


class BlivetLVMVDODependenciesTest(BlivetLVMUnitTest):
    def test_vdo_dependencies(self):
        blivet.tasks.availability.CACHE_AVAILABILITY = False

        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("10 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)

        for dev in (pv, vg):
            self.b.devicetree._add_device(dev)

        # check that all the above devices are in the expected places
        self.assertEqual(set(self.b.devices), {pv, vg})
        self.assertEqual(set(self.b.vgs), {vg})

        self.assertEqual(vg.size, Size("10236 MiB"))

        with patch("blivet.blivet.Blivet.names", new=[]):
            vdopool = self.b.new_lv(name="vdopool", vdo_pool=True,
                                    parents=[vg], compression=True,
                                    deduplication=True,
                                    size=blivet.size.Size("8 GiB"))

            vdolv = self.b.new_lv(name="vdolv", vdo_lv=True,
                                  parents=[vdopool],
                                  size=blivet.size.Size("40 GiB"))

        # Dependencies check: for VDO types these should be combination of "normal"
        # LVM dependencies (LVM libblockdev plugin and DM plugin from DMDevice)
        # and LVM VDO technology from the LVM plugin
        lvm_vdo_dependencies = ["libblockdev dm plugin",
                                "libblockdev lvm plugin",
                                "libblockdev lvm plugin (vdo technology)"]
        pool_deps = [d.name for d in vdopool.external_dependencies]
        self.assertCountEqual(pool_deps, lvm_vdo_dependencies)

        vdolv_deps = [d.name for d in vdolv.external_dependencies]
        self.assertCountEqual(vdolv_deps, lvm_vdo_dependencies)

        # same dependencies should be returned when checking with class not instance
        pool_type_deps = [d.name for d in LVMVDOPoolMixin.type_external_dependencies()]
        self.assertCountEqual(pool_type_deps, lvm_vdo_dependencies)

        vdolv_type_deps = [d.name for d in LVMVDOLogicalVolumeMixin.type_external_dependencies()]
        self.assertCountEqual(vdolv_type_deps, lvm_vdo_dependencies)

        with patch("blivet.blivet.Blivet.names", new=[]):
            # just to be sure LVM VDO specific code didn't break "normal" LVs
            normallv = self.b.new_lv(name="lvol0",
                                     parents=[vg],
                                     size=blivet.size.Size("1 GiB"))

        normalvl_deps = [d.name for d in normallv.external_dependencies]
        self.assertCountEqual(normalvl_deps, ["libblockdev dm plugin", "libblockdev lvm plugin"])

        with patch("blivet.devices.lvm.LVMVDOPoolMixin._external_dependencies",
                   new=[blivet.tasks.availability.unavailable_resource("VDO unavailability test")]):
            with patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin._external_dependencies",
                       new=[blivet.tasks.availability.unavailable_resource("VDO unavailability test")]):

                # if LVM plugin is not available it will show in the LVM VDO deps too
                lvm_type_deps = [d.name for d in LVMLogicalVolumeDevice.unavailable_type_dependencies()]

                pool_deps = [d.name for d in vdopool.unavailable_dependencies]
                self.assertCountEqual(pool_deps, ["VDO unavailability test"] + lvm_type_deps)

                vdolv_deps = [d.name for d in vdolv.unavailable_dependencies]
                self.assertCountEqual(vdolv_deps, ["VDO unavailability test"] + lvm_type_deps)

                # same dependencies should be returned when checking with class not instance
                pool_type_deps = [d.name for d in LVMVDOPoolMixin.unavailable_type_dependencies()]
                self.assertCountEqual(pool_type_deps,
                                      ["VDO unavailability test"] + lvm_type_deps)

                vdolv_type_deps = [d.name for d in LVMVDOLogicalVolumeMixin.unavailable_type_dependencies()]
                self.assertCountEqual(vdolv_type_deps,
                                      ["VDO unavailability test"] + lvm_type_deps)

                normallv_deps = [d.name for d in normallv.unavailable_dependencies]
                self.assertCountEqual(normallv_deps, lvm_type_deps)

                with self.assertRaises(errors.DependencyError):
                    self.b.create_device(vdopool)
                    self.b.create_device(vdolv)

                with patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[]):
                    with patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[]):
                        with patch("blivet.devices.dm.DMDevice._external_dependencies", new=[]):
                            self.b.create_device(normallv)

        with patch("blivet.devices.lvm.LVMVDOPoolMixin._external_dependencies", new=[]):
            with patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin._external_dependencies", new=[]):
                with patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[]):
                    with patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[]):
                        with patch("blivet.devices.dm.DMDevice._external_dependencies", new=[]):
                            self.b.create_device(vdopool)
                            self.b.create_device(vdolv)

        with patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[]):
            with patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[]):
                with patch("blivet.devices.dm.DMDevice._external_dependencies", new=[]):
                    # LVM VDO specific dependencies shouldn't be needed for removing, "normal" LVM and DM is enough
                    self.b.destroy_device(vdolv)
                    self.b.destroy_device(vdopool)

    @patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[])
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[])
    @patch("blivet.devices.dm.DMDevice._external_dependencies", new=[])
    def test_vdo_dependencies_devicefactory(self):
        with patch("blivet.devices.lvm.LVMVDOPoolMixin._external_dependencies",
                   new=[blivet.tasks.availability.unavailable_resource("VDO unavailability test")]):
            with patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin._external_dependencies",
                       new=[blivet.tasks.availability.unavailable_resource("VDO unavailability test")]):

                # shouldn't affect "normal" LVM
                lvm_supported = devicefactory.is_supported_device_type(devicefactory.DEVICE_TYPE_LVM)
                self.assertTrue(lvm_supported)

                vdo_supported = devicefactory.is_supported_device_type(devicefactory.DEVICE_TYPE_LVM_VDO)
                self.assertFalse(vdo_supported)


@patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[])
@patch("blivet.devices.dm.DMDevice._external_dependencies", new=[])
class BlivetNewLVMCachePoolDeviceTest(BlivetLVMUnitTest):

    def test_new_cache_pool(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("10 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)

        for dev in (pv, vg):
            self.b.devicetree._add_device(dev)

        # check that all the above devices are in the expected places
        self.assertEqual(set(self.b.devices), {pv, vg})
        self.assertEqual(set(self.b.vgs), {vg})

        self.assertEqual(vg.size, Size("10236 MiB"))

        with patch("blivet.devices.lvm.blockdev.lvm"):
            cachepool = self.b.new_lv(name="cachepool", cache_pool=True,
                                      parents=[vg], pvs=[pv])

        self.b.create_device(cachepool)

        self.assertEqual(cachepool.type, "lvmcachepool")


@patch("blivet.devices.lvm.LVMVDOPoolMixin._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMLogicalVolumeDevice._external_dependencies", new=[])
@patch("blivet.devices.lvm.LVMLogicalVolumeBase._external_dependencies", new=[])
@patch("blivet.devices.dm.DMDevice._external_dependencies", new=[])
class BlivetLVMConfigureActionsTest(BlivetLVMUnitTest):

    def test_vg_rename(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("10 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], exists=True)

        for dev in (pv, vg, lv):
            self.b.devicetree._add_device(dev)

        ac = blivet.deviceaction.ActionConfigureDevice(device=vg, attr="name", new_value="newname")
        self.b.devicetree.actions.add(ac)
        self.assertEqual(vg.name, "newname")
        self.assertEqual(lv.name, "newname-%s" % lv.lvname)
        with patch("blivet.devices.lvm.blockdev.lvm"):
            self.assertIn(vg.name, self.b.devicetree.names)
            self.assertIn(lv.name, self.b.devicetree.names)

        # try to remove the action and make sure the name is changed back
        self.b.devicetree.actions.remove(ac)
        self.assertEqual(vg.name, "testvg")
        self.assertEqual(lv.name, "testvg-%s" % lv.lvname)

        # re-add the action and make the change
        self.b.devicetree.actions.add(ac)
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.b.do_it()
            lvm.vgrename.assert_called_with("testvg", "newname")

        self.assertEqual(pv.format.vg_name, "newname")

    def test_lv_rename(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("10 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], exists=True)

        for dev in (pv, vg, lv):
            self.b.devicetree._add_device(dev)

        ac = blivet.deviceaction.ActionConfigureDevice(device=lv, attr="name", new_value="newname")
        self.b.devicetree.actions.add(ac)
        self.assertEqual(lv.name, "%s-newname" % vg.name)
        self.assertEqual(lv.lvname, "newname")
        with patch("blivet.devices.lvm.blockdev.lvm"):
            self.assertIn(lv.name, self.b.devicetree.names)

        # try to remove the action and make sure the name is changed back
        self.b.devicetree.actions.remove(ac)
        self.assertEqual(lv.name, "%s-testlv" % vg.name)
        self.assertEqual(lv.lvname, "testlv")

        # re-add the action and make the change
        self.b.devicetree.actions.add(ac)
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.b.do_it()
            lvm.lvrename.assert_called_with(vg.name, "testlv", "newname")

    def test_vdo_compression_deduplication_change(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("10 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        vdopool = LVMLogicalVolumeDevice("testvdopool", seg_type="vdo-pool", parents=[vg], exists=True,
                                         deduplication=True, compression=True)
        vdolv = LVMLogicalVolumeDevice("testvdolv", seg_type="vdo", parents=[vdopool], exists=True)

        for dev in (pv, vg, vdopool, vdolv):
            self.b.devicetree._add_device(dev)

        # compression/deduplication must be set on the pool, not the volume
        with self.assertRaises(ValueError):
            ac = blivet.deviceaction.ActionConfigureDevice(device=vdolv, attr="compression", new_value=True)
            self.b.devicetree.actions.add(ac)
        with self.assertRaises(ValueError):
            ac = blivet.deviceaction.ActionConfigureDevice(device=vdolv, attr="deduplication", new_value=True)
            self.b.devicetree.actions.add(ac)

        # compression/deduplication already enabled
        with self.assertRaisesRegex(ValueError, "compression is already enabled"):
            ac = blivet.deviceaction.ActionConfigureDevice(device=vdopool, attr="compression", new_value=True)
            self.b.devicetree.actions.add(ac)
        with self.assertRaisesRegex(ValueError, "deduplication is already enabled"):
            ac = blivet.deviceaction.ActionConfigureDevice(device=vdopool, attr="deduplication", new_value=True)
            self.b.devicetree.actions.add(ac)

        # disable compression
        ac = blivet.deviceaction.ActionConfigureDevice(device=vdopool, attr="compression", new_value=False)
        self.b.devicetree.actions.add(ac)
        self.assertFalse(vdopool.compression)

        # cancel the action, compression should be enabled
        self.b.devicetree.actions.remove(ac)
        self.assertTrue(vdopool.compression)

        # re-add the action and make the change
        self.b.devicetree.actions.add(ac)
        self.assertFalse(vdopool.compression)
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.b.do_it()
            lvm.vdo_disable_compression.assert_called_with(vg.name, vdopool.lvname)

        # enable compression back
        ac = blivet.deviceaction.ActionConfigureDevice(device=vdopool, attr="compression", new_value=True)
        self.b.devicetree.actions.add(ac)
        self.assertTrue(vdopool.compression)

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.b.do_it()
            lvm.vdo_enable_compression.assert_called_with(vg.name, vdopool.lvname)

        # disable deduplication
        ac = blivet.deviceaction.ActionConfigureDevice(device=vdopool, attr="deduplication", new_value=False)
        self.b.devicetree.actions.add(ac)
        self.assertFalse(vdopool.deduplication)

        # cancel the action, deduplication should be enabled
        self.b.devicetree.actions.remove(ac)
        self.assertTrue(vdopool.deduplication)

        # re-add the action and make the change
        self.b.devicetree.actions.add(ac)
        self.assertFalse(vdopool.deduplication)
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.b.do_it()
            lvm.vdo_disable_deduplication.assert_called_with(vg.name, vdopool.lvname)

        # enable deduplication back
        ac = blivet.deviceaction.ActionConfigureDevice(device=vdopool, attr="deduplication", new_value=True)
        self.b.devicetree.actions.add(ac)
        self.assertTrue(vdopool.deduplication)

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.b.do_it()
            lvm.vdo_enable_deduplication.assert_called_with(vg.name, vdopool.lvname)
