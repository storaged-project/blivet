# vim:set fileencoding=utf-8
import test_compat  # pylint: disable=unused-import

import six
from six.moves.mock import patch, PropertyMock  # pylint: disable=no-name-in-module,import-error
import unittest

import blivet

from blivet.devices import StorageDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices.lvm import LVMCacheRequest
from blivet.devices.lvm import LVPVSpec, LVMInternalLVtype
from blivet.size import Size
from blivet.devicelibs import raid
from blivet import errors

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

        with six.assertRaisesRegex(self, ValueError, "lvm snapshot origin must be a logical volume"):
            LVMLogicalVolumeDevice("snap1", parents=[vg], origin=pv)

        with six.assertRaisesRegex(self, ValueError, "only existing vorigin snapshots are supported"):
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

        with six.assertRaisesRegex(self, ValueError, "lvm snapshot origin must be a logical volume"):
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
        lv = LVMLogicalVolumeDevice("testlv",
                                    parents=[vg],
                                    fmt=blivet.formats.get_format("xfs"),
                                    size=Size(blivet.formats.get_format("xfs").min_size),
                                    exists=False,
                                    cache_request=cache_req)

        # the cache reserves space for its metadata from the requested size, but
        # it may require (and does in this case) a pmspare LV to be allocated
        self.assertEqual(lv.vg_space_used, Size("508 MiB"))

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
        with six.assertRaisesRegex(self, ValueError,
                                   "size.*smaller than the minimum"):
            lv.target_size = Size("1 MiB")

        # target size should be unchanged
        self.assertEqual(lv.target_size, orig_size)

        # ValueError if size larger than max_size
        with six.assertRaisesRegex(self, ValueError,
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
            with six.assertRaisesRegex(self, ValueError, "The volume group testvg cannot be created."):
                LVMVolumeGroupDevice("testvg", parents=[pv, pv2])

    def test_skip_activate(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv = LVMLogicalVolumeDevice("data_lv", parents=[vg], size=Size("500 MiB"), exists=True)

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                self.assertTrue(lvm.lvactivate.called_with(vg.name, lv.lvname, ignore_skip=False))

        lv.ignore_skip_activation += 1
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                self.assertTrue(lvm.lvactivate.called_with(vg.name, lv.lvname, ignore_skip=True))

        lv.ignore_skip_activation += 1
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                self.assertTrue(lvm.lvactivate.called_with(vg.name, lv.lvname, ignore_skip=True))

        lv.ignore_skip_activation -= 2
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            with patch.object(lv, "_pre_setup"):
                lv.setup()
                self.assertTrue(lvm.lvactivate.called_with(vg.name, lv.lvname, ignore_skip=False))


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


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class BlivetNewLVMDeviceTest(unittest.TestCase):
    def test_new_lv_from_lvs(self):
        b = blivet.Blivet()
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv1 = LVMLogicalVolumeDevice("data_lv", parents=[vg], size=Size("500 MiB"), exists=True)
        lv2 = LVMLogicalVolumeDevice("metadata_lv", parents=[vg], size=Size("50 MiB"), exists=True)

        for dev in (pv, vg, lv1, lv2):
            b.devicetree._add_device(dev)

        # check that all the above devices are in the expected places
        self.assertEqual(set(b.devices), {pv, vg, lv1, lv2})
        self.assertEqual(set(b.vgs), {vg})
        self.assertEqual(set(b.lvs), {lv1, lv2})
        self.assertEqual(set(b.vgs[0].lvs), {lv1, lv2})

        self.assertEqual(vg.size, Size("1020 MiB"))
        self.assertEqual(lv1.size, Size("500 MiB"))
        self.assertEqual(lv2.size, Size("50 MiB"))

        # combine the two LVs into a thin pool (the LVs should become its internal LVs)
        pool = b.new_lv_from_lvs(vg, name="pool", seg_type="thin-pool", from_lvs=(lv1, lv2))

        # add the pool LV into the devicetree
        b.devicetree._add_device(pool)

        self.assertEqual(set(b.devices), {pv, vg, pool})
        self.assertEqual(set(b.vgs), {vg})
        self.assertEqual(set(b.lvs), {pool})
        self.assertEqual(set(b.vgs[0].lvs), {pool})
        self.assertEqual(set(b.vgs[0].lvs[0]._internal_lvs), {lv1, lv2})

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
        b = blivet.Blivet()
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"), exists=True)
        vg = LVMVolumeGroupDevice("testvg", parents=[pv], exists=True)
        lv1 = LVMLogicalVolumeDevice("data_lv", parents=[vg], size=Size("500 MiB"), exists=False)
        lv2 = LVMLogicalVolumeDevice("metadata_lv", parents=[vg], size=Size("50 MiB"), exists=False)

        for dev in (pv, vg, lv1, lv2):
            b.devicetree._add_device(dev)

        # check that all the above devices are in the expected places
        self.assertEqual(set(b.devices), {pv, vg, lv1, lv2})
        self.assertEqual(set(b.vgs), {vg})
        self.assertEqual(set(b.lvs), {lv1, lv2})
        self.assertEqual(set(b.vgs[0].lvs), {lv1, lv2})

        self.assertEqual(vg.size, Size("1020 MiB"))
        self.assertEqual(lv1.size, Size("500 MiB"))
        self.assertEqual(lv2.size, Size("50 MiB"))

        # combine the two LVs into a thin pool (the LVs should become its internal LVs)
        pool = b.new_lv_from_lvs(vg, name="pool", seg_type="thin-pool", from_lvs=(lv1, lv2))

        # add the pool LV into the devicetree
        b.devicetree._add_device(pool)

        self.assertEqual(set(b.devices), {pv, vg, pool})
        self.assertEqual(set(b.vgs), {vg})
        self.assertEqual(set(b.lvs), {pool})
        self.assertEqual(set(b.vgs[0].lvs), {pool})
        self.assertEqual(set(b.vgs[0].lvs[0]._internal_lvs), {lv1, lv2})

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
