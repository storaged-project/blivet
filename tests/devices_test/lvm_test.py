# vim:set fileencoding=utf-8

import unittest

import blivet

from blivet.devices import StorageDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import LVMSnapShotDevice
from blivet.devices import LVMThinLogicalVolumeDevice
from blivet.devices import LVMThinPoolDevice
from blivet.devices import LVMThinSnapShotDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices.lvm import LVMCacheRequest
from blivet.size import Size

DEVICE_CLASSES = [
    LVMLogicalVolumeDevice,
    LVMSnapShotDevice,
    LVMThinLogicalVolumeDevice,
    LVMThinPoolDevice,
    LVMThinSnapShotDevice,
    LVMVolumeGroupDevice,
    StorageDevice
]


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class LVMDeviceTest(unittest.TestCase):

    def test_lvmsnap_shot_device_init(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.get_format("xfs"))

        with self.assertRaisesRegex(ValueError, "lvm snapshot devices require an origin lv"):
            LVMSnapShotDevice("snap1", parents=[vg])

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin volume must already exist"):
            LVMSnapShotDevice("snap1", parents=[vg], origin=lv)

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin must be a logical volume"):
            LVMSnapShotDevice("snap1", parents=[vg], origin=pv)

        with self.assertRaisesRegex(ValueError, "only existing vorigin snapshots are supported"):
            LVMSnapShotDevice("snap1", parents=[vg], vorigin=True)

        lv.exists = True
        snap1 = LVMSnapShotDevice("snap1", parents=[vg], origin=lv)

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
        pool = LVMThinPoolDevice("pool1", parents=[vg], size=Size("500 MiB"))
        thinlv = LVMThinLogicalVolumeDevice("thinlv", parents=[pool],
                                            size=Size("200 MiB"))

        with self.assertRaisesRegex(ValueError, "lvm thin snapshots require an origin"):
            LVMThinSnapShotDevice("snap1", parents=[pool])

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin volume must already exist"):
            LVMThinSnapShotDevice("snap1", parents=[pool], origin=thinlv)

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin must be a logical volume"):
            LVMThinSnapShotDevice("snap1", parents=[pool], origin=pv)

        # now make the constructor succeed so we can test some properties
        thinlv.exists = True
        snap1 = LVMThinSnapShotDevice("snap1", parents=[pool], origin=thinlv)
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
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, cache_request=cache_req)
        self.assertEqual(lv.vg_space_used, Size("512 MiB"))

        # check that the LV behaves like a cached LV
        self.assertTrue(lv.cached)
        cache = lv.cache
        self.assertIsNotNone(cache)

        # check parameters reported by the (non-existing) cache
        self.assertEqual(cache.size, Size("504 MiB"))
        self.assertEqual(cache.md_size, Size("8 MiB"))
        self.assertEqual(cache.vg_space_used, Size("512 MiB"))
        self.assertIsInstance(cache.size, Size)
        self.assertIsInstance(cache.md_size, Size)
        self.assertIsInstance(cache.vg_space_used, Size)
        self.assertFalse(cache.exists)
        self.assertIsNone(cache.stats)
        self.assertEqual(cache.mode, "writethrough")
        self.assertIsNone(cache.backing_device_name)
        self.assertIsNone(cache.cache_device_name)
        self.assertEqual(set(cache.fast_pvs), set([pv2]))

    def test_target_size(self):
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
