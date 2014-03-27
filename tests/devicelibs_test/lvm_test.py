#!/usr/bin/python
import baseclass
import os
import unittest

import blivet.devicelibs.lvm as lvm
from blivet.size import Size

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
        except lvm.LVMError:
            pass

        try:
            lvm.vgdeactivate(self._vg_name)
            lvm.vgreduce(self._vg_name, None, missing=True)
        except lvm.LVMError:
            pass

        try:
            lvm.vgremove(self._vg_name)
        except lvm.LVMError:
            pass

        try:
            for dev in self._loopMap.keys():
                lvm.pvremove(dev)
        except lvm.LVMError:
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
        for _file, dev in self._loopMap.iteritems():
            self.assertEqual(lvm.pvcreate(dev), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.pvcreate, "/not/existing/device")

        ##
        ## pvresize
        ##
        # pass
        for _file, dev in self._loopMap.iteritems():
            self.assertEqual(lvm.pvresize(dev, Size(spec="50MiB")), None)
            self.assertEqual(lvm.pvresize(dev, Size(spec="100MiB")), None)

        # fail
        self.assertRaisesRegexp(lvm.LVMError,
           "pvresize failed",
           lvm.pvresize,
           "/not/existing/device", Size(spec="50MiB"))

        ##
        ## vgcreate
        ##
        # pass
        self.assertEqual(lvm.vgcreate(self._vg_name, [_LOOP_DEV0, _LOOP_DEV1], Size(spec="4MiB")), None)

        # fail
        self.assertRaisesRegexp(lvm.LVMError,
           "vgcreate failed",
           lvm.vgcreate,
           "another-vg", ["/not/existing/device"], Size(spec="4MiB"))
        # vg already exists
        self.assertRaisesRegexp(lvm.LVMError,
           "vgcreate failed",
           lvm.vgcreate,
           self._vg_name, [_LOOP_DEV0], Size(spec="4MiB"))
        # pe size must be power of 2
        self.assertRaisesRegexp(lvm.LVMError,
           "vgcreate failed",
           lvm.vgcreate,
           "another-vg", [_LOOP_DEV0], Size(spec="5MiB"))

        ##
        ## vgdeactivate
        ##
        # pass
        self.assertEqual(lvm.vgdeactivate(self._vg_name), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.vgdeactivate, "wrong-vg-name")

        ##
        ## vgreduce
        ##
        # pass
        self.assertEqual(lvm.vgreduce(self._vg_name, _LOOP_DEV1), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.vgreduce, "wrong-vg-name", _LOOP_DEV1)
        self.assertRaises(lvm.LVMError, lvm.vgreduce, self._vg_name, "/not/existing/device")

        ##
        ## vgactivate
        ##
        # pass
        self.assertEqual(lvm.vgactivate(self._vg_name), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.vgactivate, "wrong-vg-name")

        ##
        ## pvinfo
        ##
        # pass
        self.assertEqual(lvm.pvinfo(_LOOP_DEV0)["LVM2_VG_NAME"], self._vg_name) 
        # no vg
        self.assertEqual(lvm.pvinfo(_LOOP_DEV1)["LVM2_VG_NAME"], "")

        self.assertEqual(lvm.pvinfo("/not/existing/device"), {})

        ##
        ## vginfo
        ##
        # pass
        self.assertEqual(lvm.vginfo(self._vg_name)['LVM2_PV_COUNT'], "1")

        # fail
        self.assertRaises(lvm.LVMError, lvm.vginfo, "wrong-vg-name")

        ##
        ## lvcreate
        ##
        # pass
        self.assertEqual(lvm.lvcreate(self._vg_name, self._lv_name, Size(spec="10MiB")), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.lvcreate, "wrong-vg-name", "another-lv", Size(spec="10MiB"))

        ##
        ## lvdeactivate
        ##
        # pass
        self.assertEqual(lvm.lvdeactivate(self._vg_name, self._lv_name), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.lvdeactivate, self._vg_name, "wrong-lv-name")
        self.assertRaises(lvm.LVMError, lvm.lvdeactivate, "wrong-vg-name", self._lv_name)
        self.assertRaises(lvm.LVMError, lvm.lvdeactivate, "wrong-vg-name", "wrong-lv-name")

        ##
        ## lvresize
        ##
        # pass
        self.assertEqual(lvm.lvresize(self._vg_name, self._lv_name, Size(spec="60MiB")), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.lvresize, self._vg_name, "wrong-lv-name", Size(spec="80MiB"))
        self.assertRaises(lvm.LVMError, lvm.lvresize, "wrong-vg-name", self._lv_name, Size(spec="80MiB"))
        self.assertRaises(lvm.LVMError, lvm.lvresize, "wrong-vg-name", "wrong-lv-name", Size(spec="80MiB"))
        # changing to same size
        self.assertRaises(lvm.LVMError, lvm.lvresize, self._vg_name, self._lv_name, Size(spec="60MiB"))

        ##
        ## lvactivate
        ##
        # pass
        self.assertEqual(lvm.lvactivate(self._vg_name, self._lv_name), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.lvactivate, self._vg_name, "wrong-lv-name")
        self.assertRaises(lvm.LVMError, lvm.lvactivate, "wrong-vg-name", self._lv_name)
        self.assertRaises(lvm.LVMError, lvm.lvactivate, "wrong-vg-name", "wrong-lv-name")

        ##
        ## lvs
        ##
        # pass
        self.assertEqual(lvm.lvs(self._vg_name)["LVM2_LV_NAME"], [self._lv_name])

        # fail
        self.assertEqual(lvm.lvs("wrong-vg-name"), {})

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
        self.assertRaises(lvm.LVMError, lvm.lvremove, self._vg_name, "wrong-lv-name")
        self.assertRaises(lvm.LVMError, lvm.lvremove, "wrong-vg-name", self._lv_name)
        self.assertRaises(lvm.LVMError, lvm.lvremove, "wrong-vg-name", "wrong-lv-name")
        # lv already removed
        self.assertRaises(lvm.LVMError, lvm.lvremove, self._vg_name, self._lv_name)

        ##
        ## vgremove
        ##
        # pass
        self.assertEqual(lvm.vgremove(self._vg_name), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.vgremove, "wrong-vg-name")
        # vg already removed
        self.assertRaises(lvm.LVMError, lvm.vgremove, self._vg_name)

        ##
        ## pvremove
        ##
        # pass
        for _file, dev in self._loopMap.iteritems():
            self.assertEqual(lvm.pvremove(dev), None)

        # fail
        self.assertRaises(lvm.LVMError, lvm.pvremove, "/not/existing/device")
        # pv already removed
        self.assertEqual(lvm.pvremove(_LOOP_DEV0), None)

def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(LVMTestCase)
    suite2 = unittest.TestLoader().loadTestsFromTestCase(LVMAsRootTestCase)
    return unittest.TestSuite([suite1, suite2])


if __name__ == "__main__":
    unittest.main()
