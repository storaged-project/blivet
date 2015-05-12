#!/usr/bin/python
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

@unittest.skipUnless(all(not x.unavailableTypeDependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class LVMDeviceTest(unittest.TestCase):
    def testLVMSnapShotDeviceInit(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.getFormat("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.getFormat("xfs"))

        with self.assertRaisesRegexp(ValueError, "lvm snapshot devices require an origin lv"):
            LVMSnapShotDevice("snap1", parents=[vg])

        with self.assertRaisesRegexp(ValueError, "lvm snapshot origin volume must already exist"):
            LVMSnapShotDevice("snap1", parents=[vg], origin=lv)

        with self.assertRaisesRegexp(ValueError, "lvm snapshot origin must be a logical volume"):
            LVMSnapShotDevice("snap1", parents=[vg], origin=pv)

        with self.assertRaisesRegexp(ValueError, "only existing vorigin snapshots are supported"):
            LVMSnapShotDevice("snap1", parents=[vg], vorigin=True)

        lv.exists = True
        snap1 = LVMSnapShotDevice("snap1", parents=[vg], origin=lv)

        self.assertEqual(snap1.format, lv.format)
        snap1.format = blivet.formats.getFormat("DM_snapshot_cow", exists=True)
        self.assertEqual(snap1.format, lv.format)

        self.assertEqual(snap1.isleaf, True)
        self.assertEqual(snap1.direct, True)
        self.assertEqual(lv.isleaf, False)
        self.assertEqual(lv.direct, True)

        self.assertEqual(snap1.dependsOn(lv), True)
        self.assertEqual(lv.dependsOn(snap1), False)

    def testLVMThinSnapShotDeviceInit(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.getFormat("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        pool = LVMThinPoolDevice("pool1", parents=[vg], size=Size("500 MiB"))
        thinlv = LVMThinLogicalVolumeDevice("thinlv", parents=[pool],
                                            size=Size("200 MiB"))

        with self.assertRaisesRegexp(ValueError, "lvm thin snapshots require an origin"):
            LVMThinSnapShotDevice("snap1", parents=[pool])

        with self.assertRaisesRegexp(ValueError, "lvm snapshot origin volume must already exist"):
            LVMThinSnapShotDevice("snap1", parents=[pool], origin=thinlv)

        with self.assertRaisesRegexp(ValueError, "lvm snapshot origin must be a logical volume"):
            LVMThinSnapShotDevice("snap1", parents=[pool], origin=pv)

        # now make the constructor succeed so we can test some properties
        thinlv.exists = True
        snap1 = LVMThinSnapShotDevice("snap1", parents=[pool], origin=thinlv)
        self.assertEqual(snap1.isleaf, True)
        self.assertEqual(snap1.direct, True)
        self.assertEqual(thinlv.isleaf, True)
        self.assertEqual(thinlv.direct, True)

        self.assertEqual(snap1.dependsOn(thinlv), True)
        self.assertEqual(thinlv.dependsOn(snap1), False)

        # existing thin snapshots do not depend on their origin
        snap1.exists = True
        self.assertEqual(snap1.dependsOn(thinlv), False)

    def testTargetSize(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.getFormat("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        orig_size = Size("800 MiB")
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=orig_size,
                                    fmt=blivet.formats.getFormat("ext4"),
                                    exists=True)

        min_size = Size("200 MiB")
        lv.format.exists = True
        lv.format._minInstanceSize = min_size
        lv.format._resizable = True

        # Make sure things are as expected to begin with.
        self.assertEqual(lv.minSize, min_size)
        self.assertEqual(lv.maxSize, Size("1020 MiB"))
        self.assertEqual(lv.size, orig_size)

        # ValueError if size smaller than minSize
        with self.assertRaisesRegexp(ValueError,
                                     "size.*smaller than the minimum"):
            lv.targetSize = Size("1 MiB")

        # target size should be unchanged
        self.assertEqual(lv.targetSize, orig_size)

        # ValueError if size larger than maxSize
        with self.assertRaisesRegexp(ValueError,
                                     "size.*larger than the maximum"):
            lv.targetSize = Size("1 GiB")

        # target size should be unchanged
        self.assertEqual(lv.targetSize, orig_size)

        # successful set of target size should also be reflected in size attr
        new_target = Size("900 MiB")
        lv.targetSize = new_target
        self.assertEqual(lv.targetSize, new_target)
        self.assertEqual(lv.size, new_target)

        # reset target size to original size
        lv.targetSize = orig_size
        self.assertEqual(lv.targetSize, orig_size)
        self.assertEqual(lv.size, orig_size)

if __name__ == "__main__":
    unittest.main()
