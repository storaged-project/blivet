#!/usr/bin/python
import unittest
import glob

import blivet.devicelibs.lvm as lvm
from blivet.size import Size
from blivet.errors import LVMError

from tests import loopbackedtestcase

# TODO: test cases for lvorigin, lvsnapshot*, thin*

class LVMTestCase(unittest.TestCase):

    def testGetPossiblePhysicalExtents(self):
        # pass
        self.assertEqual(lvm.getPossiblePhysicalExtents(),
                         [Size("%d KiB" % 2**power) for power in xrange(0, 25)])

    def testClampSize(self):
        # pass
        self.assertEqual(lvm.clampSize(Size("10 MiB"), Size("4 MiB")),
                         Size("8 MiB"))
        self.assertEqual(lvm.clampSize(Size("10 MiB"), Size("4 MiB"),
 True),
                         Size("12 MiB"))

# FIXME: Some of these tests expect behavior that is not entirely correct.
#
# The following is a list of the known incorrect behaviors:
# *) All lvm methods that take a device should explicitly raise an exception
# when the device is non-existent. Currently, an exception is raised by the lvm
# call if the device is non-existant, and usually that exception is caught and
# an LVMError is then raised, but not always.

class LVMAsRootTestCaseBase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='runTest'):
        """Set up the structure of the volume group."""
        super(LVMAsRootTestCaseBase, self).__init__(methodName=methodName)
        self._vg_name = "test-vg"
        self._lv_name = "test-lv"

    def tearDown(self):
        """Destroy volume group."""
        try:
            lvm.lvdeactivate(self._vg_name, self._lv_name)
            lvm.lvremove(self._vg_name, self._lv_name)
        except LVMError:
            pass

        try:
            lvm.vgdeactivate(self._vg_name)
            lvm.vgreduce(self._vg_name, None, missing=True)
        except LVMError:
            pass

        try:
            lvm.vgremove(self._vg_name)
        except LVMError:
            pass

        for dev in self.loopDevices:
            try:
                lvm.pvremove(dev)
            except LVMError:
                pass

        super(LVMAsRootTestCaseBase, self).tearDown()

class LVM_Metadata_Backup_TestCase(LVMAsRootTestCaseBase):
    def _list_backups(self):
        return set(glob.glob("/etc/lvm/archive/%s_*" % self._vg_name))

    def setUp(self):
        super(LVM_Metadata_Backup_TestCase, self).setUp()
        self._old_backups = self._list_backups()
        for dev in self.loopDevices:
            lvm.pvcreate(dev)

    def test_backup_enabled(self):
        lvm.flags.lvm_metadata_backup = True
        lvm.vgcreate(self._vg_name, self.loopDevices, Size("4MiB"))

        current_backups = self._list_backups()
        self.assertTrue(current_backups.issuperset(self._old_backups),
                        "old backups disappeared??")
        self.assertTrue(current_backups.difference(self._old_backups),
                        "lvm_metadata_backup enabled but no backups created")

    def test_backup_disabled(self):
        lvm.flags.lvm_metadata_backup = False
        lvm.vgcreate(self._vg_name, self.loopDevices, Size("4MiB"))

        self.assertEqual(self._old_backups, self._list_backups(),
                         "lvm_metadata_backup disabled but backups created")


class LVMAsRootTestCase(LVMAsRootTestCaseBase):
    def testLVM(self):
        _LOOP_DEV0 = self.loopDevices[0]
        _LOOP_DEV1 = self.loopDevices[1]

        ##
        ## pvcreate
        ##
        # pass
        for dev in self.loopDevices:
            self.assertEqual(lvm.pvcreate(dev), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.pvcreate("/not/existing/device")

        ##
        ## pvresize
        ##
        # pass
        for dev in self.loopDevices:
            self.assertEqual(lvm.pvresize(dev, Size("50MiB")), None)
            self.assertEqual(lvm.pvresize(dev, Size("100MiB")), None)

        # fail
        with self.assertRaisesRegexp(LVMError, "pvresize failed"):
            lvm.pvresize("/not/existing/device", Size("50MiB"))

        ##
        ## vgcreate
        ##
        # pass
        self.assertEqual(lvm.vgcreate(self._vg_name, self.loopDevices, Size("4MiB")), None)

        # fail
        with self.assertRaisesRegexp(LVMError, "vgcreate failed"):
            lvm.vgcreate("another-vg", ["/not/existing/device"], Size("4MiB"))
        # vg already exists
        with self.assertRaisesRegexp(LVMError, "vgcreate failed"):
            lvm.vgcreate(self._vg_name, [_LOOP_DEV0], Size("4MiB"))
        # pe size must be power of 2
        with self.assertRaisesRegexp(LVMError, "vgcreate failed"):
            lvm.vgcreate("another-vg", [_LOOP_DEV0], Size("5MiB"))

        ##
        ## vgdeactivate
        ##
        # pass
        self.assertEqual(lvm.vgdeactivate(self._vg_name), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.vgdeactivate("wrong-vg-name")

        ##
        ## vgreduce
        ##
        # pass
        self.assertEqual(lvm.vgreduce(self._vg_name, _LOOP_DEV1), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.vgreduce("wrong-vg-name", _LOOP_DEV1)
        with self.assertRaises(LVMError):
            lvm.vgreduce(self._vg_name, "/not/existing/device")

        ##
        ## vgactivate
        ##
        # pass
        self.assertEqual(lvm.vgactivate(self._vg_name), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.vgactivate("wrong-vg-name")

        ##
        ## pvinfo
        ##
        # pass
        self.assertEqual(lvm.pvinfo(device=_LOOP_DEV0)[_LOOP_DEV0]["LVM2_VG_NAME"], self._vg_name)
        # no vg
        self.assertEqual(lvm.pvinfo(device=_LOOP_DEV1)[_LOOP_DEV1]["LVM2_VG_NAME"], "")

        self.assertEqual(lvm.pvinfo(device="/not/existing/device"), {})

        ##
        ## vginfo
        ##
        # pass
        self.assertEqual(lvm.vginfo(self._vg_name)['LVM2_PV_COUNT'], "1")

        # fail
        with self.assertRaises(LVMError):
            lvm.vginfo("wrong-vg-name")

        ##
        ## lvcreate
        ##
        # pass
        self.assertEqual(lvm.lvcreate(self._vg_name, self._lv_name, Size("10MiB")), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.lvcreate("wrong-vg-name", "another-lv", Size("10MiB"))

        ##
        ## lvdeactivate
        ##
        # pass
        self.assertEqual(lvm.lvdeactivate(self._vg_name, self._lv_name), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.lvdeactivate(self._vg_name, "wrong-lv-name")
        with self.assertRaises(LVMError):
            lvm.lvdeactivate("wrong-vg-name", self._lv_name)
        with self.assertRaises(LVMError):
            lvm.lvdeactivate("wrong-vg-name", "wrong-lv-name")

        ##
        ## lvresize
        ##
        # pass
        self.assertEqual(lvm.lvresize(self._vg_name, self._lv_name, Size("60MiB")), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.lvresize(self._vg_name, "wrong-lv-name", Size("80MiB"))
        with self.assertRaises(LVMError):
            lvm.lvresize("wrong-vg-name", self._lv_name, Size("80MiB"))
        with self.assertRaises(LVMError):
            lvm.lvresize("wrong-vg-name", "wrong-lv-name", Size("80MiB"))
        # changing to same size
        with self.assertRaises(LVMError):
            lvm.lvresize(self._vg_name, self._lv_name, Size("60MiB"))

        ##
        ## lvactivate
        ##
        # pass
        self.assertEqual(lvm.lvactivate(self._vg_name, self._lv_name), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.lvactivate(self._vg_name, "wrong-lv-name")
        with self.assertRaises(LVMError):
            lvm.lvactivate("wrong-vg-name", self._lv_name)
        with self.assertRaises(LVMError):
            lvm.lvactivate("wrong-vg-name", "wrong-lv-name")

        ##
        ## lvs
        ##
        # pass
        full_name = "%s-%s" % (self._vg_name, self._lv_name)
        info = lvm.lvs(vg_name=self._vg_name)
        self.assertEqual(info[full_name]["LVM2_LV_NAME"], self._lv_name)

        # fail
        self.assertEqual(lvm.lvs(vg_name="wrong-vg-name"), {})

        ##
        ## has_lvm
        ##
        # pass
        self.assertEqual(lvm.has_lvm(), True)

        # fail
        # TODO

        ##
        ## lvremove
        ##
        # pass
        self.assertEqual(lvm.lvdeactivate(self._vg_name, self._lv_name), None)      # is deactivation needed?
        self.assertEqual(lvm.lvremove(self._vg_name, self._lv_name), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.lvremove(self._vg_name, "wrong-lv-name")
        with self.assertRaises(LVMError):
            lvm.lvremove("wrong-vg-name", self._lv_name)
        with self.assertRaises(LVMError):
            lvm.lvremove("wrong-vg-name", "wrong-lv-name")
        # lv already removed
        with self.assertRaises(LVMError):
            lvm.lvremove(self._vg_name, self._lv_name)

        ##
        ## vgremove
        ##
        # pass
        self.assertEqual(lvm.vgremove(self._vg_name), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.vgremove("wrong-vg-name")
        # vg already removed
        with self.assertRaises(LVMError):
            lvm.vgremove(self._vg_name)

        ##
        ## pvremove
        ##
        # pass
        for dev in self.loopDevices:
            self.assertEqual(lvm.pvremove(dev), None)

        # fail
        with self.assertRaises(LVMError):
            lvm.pvremove("/not/existing/device")
        # pv already removed
        self.assertEqual(lvm.pvremove(_LOOP_DEV0), None)

class LVMAsNonRootTestCase(unittest.TestCase):
    # pylint: disable=unused-argument
    def lvm_passthrough_args(self, args, *other_args, **kwargs):
        """ Just return args as passed so tests can validate them. """
        # pylint: disable=attribute-defined-outside-init
        self.lvm_argv = args

    def setUp(self):
        self.orig_lvm_func = lvm.lvm
        lvm.lvm = self.lvm_passthrough_args

    def tearDown(self):
        lvm.lvm = self.orig_lvm_func

    def testLVM(self):
        #
        # verify we pass appropriate args for various data alignment values
        #

        # default => do not specify a data alignment
        lvm.pvcreate('/dev/placeholder')
        argv = self.lvm_argv
        self.assertEqual(any(a.startswith('--dataalignment') for a in argv),
                         False)

        # sizes get specified in KiB
        lvm.pvcreate('/dev/placeholder', data_alignment=Size('1 MiB'))
        argv = self.lvm_argv
        self.assertEqual("--dataalignment 1024k" in " ".join(argv), True)

        lvm.pvcreate('/dev/placeholder', data_alignment=Size(1023))
        argv = self.lvm_argv
        self.assertEqual("--dataalignment 0k" in " ".join(argv), True)

if __name__ == "__main__":
    unittest.main()
