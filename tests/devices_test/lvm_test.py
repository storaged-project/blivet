# vim:set fileencoding=utf-8

import unittest

import blivet

from blivet.devices import StorageDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices.lvm import LVMCacheRequest
from blivet.devices.lvm import LVPVSpec
from blivet.size import Size
from blivet.devicelibs import raid

DEVICE_CLASSES = [
    LVMLogicalVolumeDevice,
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

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin volume must already exist"):
            LVMLogicalVolumeDevice("snap1", parents=[vg], origin=lv)

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin must be a logical volume"):
            LVMLogicalVolumeDevice("snap1", parents=[vg], origin=pv)

        with self.assertRaisesRegex(ValueError, "only existing vorigin snapshots are supported"):
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

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin volume must already exist"):
            LVMLogicalVolumeDevice("snap1", parents=[pool], origin=thinlv, seg_type="thin")

        with self.assertRaisesRegex(ValueError, "lvm snapshot origin must be a logical volume"):
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
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.get_format("xfs"),
                                    exists=False, cache_request=cache_req)

        # the cache reserves space for the 8MiB pmspare internal LV
        self.assertEqual(lv.vg_space_used, Size("504 MiB"))

        # check that the LV behaves like a cached LV
        self.assertTrue(lv.cached)
        cache = lv.cache
        self.assertIsNotNone(cache)

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
        self.assertEqual(lv._num_raid_pvs, 2)

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
        self.assertEqual(lv._num_raid_pvs, 2)

    def test_lvm_logical_volume_insuf_seg_type(self):
        # pylint: disable=unused-variable
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1025 MiB"))
        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("513 MiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

        # pvs have to be specified for non-linear LVs
        with self.assertRaises(ValueError):
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, seg_type="raid1")
        with self.assertRaises(ValueError):
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, seg_type="striped")

        # no or complete specification has to be given for linear LVs
        with self.assertRaises(ValueError):
            lv = LVMLogicalVolumeDevice("testlv", parents=[vg], size=Size("512 MiB"),
                                        fmt=blivet.formats.get_format("xfs"),
                                        exists=False, pvs=[pv])
        with self.assertRaises(ValueError):
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
