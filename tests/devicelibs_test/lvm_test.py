#!/usr/bin/python
import os
import unittest

import blivet.devicelibs.lvm as lvm
from blivet.size import Size
from blivet.errors import LVMError

from tests.devicelibs_test import baseclass

class LVMTestCase(unittest.TestCase):

    def testGetPossiblePhysicalExtents(self):
        # pass
        self.assertEqual(lvm.getPossiblePhysicalExtents(),
                         map(lambda power: Size(spec="%d KiB" % 2**power),
                             xrange(0, 25)))

    def testClampSize(self):
        # pass
        self.assertEqual(lvm.clampSize(Size(spec="10 MiB"), Size(spec="4 MiB")),
                         Size(spec="8 MiB"))
        self.assertEqual(lvm.clampSize(Size(spec="10 MiB"), Size(spec="4 MiB"),
 True),
                         Size(spec="12 MiB"))

# FIXME: Some of these tests expect behavior that is not entirely correct.
#
# The following is a list of the known incorrect behaviors:
# *) All lvm methods that take a device should explicitly raise an exception
# when the device is non-existent. Currently, an exception is raised by the lvm
# call if the device is non-existant, and usually that exception is caught and
# an LVMError is then raised, but not always.

class LVMAsRootTestCase(baseclass.DevicelibsTestCase):

    def __init__(self, *args, **kwargs):
        """Set up the structure of the volume group."""
        super(LVMAsRootTestCase, self).__init__(*args, **kwargs)
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

        try:
            for dev in self._loopMap.values():
                lvm.pvremove(dev)
        except LVMError:
            pass

        super(LVMAsRootTestCase, self).tearDown()

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLVM(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        ##
        ## pvcreate
        ##
        # pass
        for dev in self._loopMap.values():
            self.assertEqual(lvm.pvcreate(dev), None)

        # fail
        self.assertRaises(LVMError, lvm.pvcreate, "/not/existing/device")

        ##
        ## pvresize
        ##
        # pass
        for dev in self._loopMap.values():
            self.assertEqual(lvm.pvresize(dev, Size(spec="50MiB")), None)
            self.assertEqual(lvm.pvresize(dev, Size(spec="100MiB")), None)

        # fail
        self.assertRaisesRegexp(LVMError,
           "pvresize failed",
           lvm.pvresize,
           "/not/existing/device", Size(spec="50MiB"))

        ##
        ## vgcreate
        ##
        # pass
        self.assertEqual(lvm.vgcreate(self._vg_name, [_LOOP_DEV0, _LOOP_DEV1], Size(spec="4MiB")), None)

        # fail
        self.assertRaisesRegexp(LVMError,
           "vgcreate failed",
           lvm.vgcreate,
           "another-vg", ["/not/existing/device"], Size(spec="4MiB"))
        # vg already exists
        self.assertRaisesRegexp(LVMError,
           "vgcreate failed",
           lvm.vgcreate,
           self._vg_name, [_LOOP_DEV0], Size(spec="4MiB"))
        # pe size must be power of 2
        self.assertRaisesRegexp(LVMError,
           "vgcreate failed",
           lvm.vgcreate,
           "another-vg", [_LOOP_DEV0], Size(spec="5MiB"))

        ##
        ## vgdeactivate
        ##
        # pass
        self.assertEqual(lvm.vgdeactivate(self._vg_name), None)

        # fail
        self.assertRaises(LVMError, lvm.vgdeactivate, "wrong-vg-name")

        ##
        ## vgreduce
        ##
        # pass
        self.assertEqual(lvm.vgreduce(self._vg_name, _LOOP_DEV1), None)

        # fail
        self.assertRaises(LVMError, lvm.vgreduce, "wrong-vg-name", _LOOP_DEV1)
        self.assertRaises(LVMError, lvm.vgreduce, self._vg_name, "/not/existing/device")

        ##
        ## vgactivate
        ##
        # pass
        self.assertEqual(lvm.vgactivate(self._vg_name), None)

        # fail
        self.assertRaises(LVMError, lvm.vgactivate, "wrong-vg-name")

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
        self.assertRaises(LVMError, lvm.vginfo, "wrong-vg-name")

        ##
        ## lvcreate
        ##
        # pass
        self.assertEqual(lvm.lvcreate(self._vg_name, self._lv_name, Size(spec="10MiB")), None)

        # fail
        self.assertRaises(LVMError, lvm.lvcreate, "wrong-vg-name", "another-lv", Size(spec="10MiB"))

        ##
        ## lvdeactivate
        ##
        # pass
        self.assertEqual(lvm.lvdeactivate(self._vg_name, self._lv_name), None)

        # fail
        self.assertRaises(LVMError, lvm.lvdeactivate, self._vg_name, "wrong-lv-name")
        self.assertRaises(LVMError, lvm.lvdeactivate, "wrong-vg-name", self._lv_name)
        self.assertRaises(LVMError, lvm.lvdeactivate, "wrong-vg-name", "wrong-lv-name")

        ##
        ## lvresize
        ##
        # pass
        self.assertEqual(lvm.lvresize(self._vg_name, self._lv_name, Size(spec="60MiB")), None)

        # fail
        self.assertRaises(LVMError, lvm.lvresize, self._vg_name, "wrong-lv-name", Size(spec="80MiB"))
        self.assertRaises(LVMError, lvm.lvresize, "wrong-vg-name", self._lv_name, Size(spec="80MiB"))
        self.assertRaises(LVMError, lvm.lvresize, "wrong-vg-name", "wrong-lv-name", Size(spec="80MiB"))
        # changing to same size
        self.assertRaises(LVMError, lvm.lvresize, self._vg_name, self._lv_name, Size(spec="60MiB"))

        ##
        ## lvactivate
        ##
        # pass
        self.assertEqual(lvm.lvactivate(self._vg_name, self._lv_name), None)

        # fail
        self.assertRaises(LVMError, lvm.lvactivate, self._vg_name, "wrong-lv-name")
        self.assertRaises(LVMError, lvm.lvactivate, "wrong-vg-name", self._lv_name)
        self.assertRaises(LVMError, lvm.lvactivate, "wrong-vg-name", "wrong-lv-name")

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
        self.assertRaises(LVMError, lvm.lvremove, self._vg_name, "wrong-lv-name")
        self.assertRaises(LVMError, lvm.lvremove, "wrong-vg-name", self._lv_name)
        self.assertRaises(LVMError, lvm.lvremove, "wrong-vg-name", "wrong-lv-name")
        # lv already removed
        self.assertRaises(LVMError, lvm.lvremove, self._vg_name, self._lv_name)

        ##
        ## vgremove
        ##
        # pass
        self.assertEqual(lvm.vgremove(self._vg_name), None)

        # fail
        self.assertRaises(LVMError, lvm.vgremove, "wrong-vg-name")
        # vg already removed
        self.assertRaises(LVMError, lvm.vgremove, self._vg_name)

        ##
        ## pvremove
        ##
        # pass
        for dev in self._loopMap.values():
            self.assertEqual(lvm.pvremove(dev), None)

        # fail
        self.assertRaises(LVMError, lvm.pvremove, "/not/existing/device")
        # pv already removed
        self.assertEqual(lvm.pvremove(_LOOP_DEV0), None)

def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(LVMTestCase)
    suite2 = unittest.TestLoader().loadTestsFromTestCase(LVMAsRootTestCase)
    return unittest.TestSuite([suite1, suite2])


if __name__ == "__main__":
    unittest.main()
