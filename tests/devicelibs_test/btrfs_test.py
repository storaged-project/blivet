#!/usr/bin/python
import baseclass
import os
import unittest

import blivet.devicelibs.btrfs as btrfs

class BTRFSAsRootTestCase(baseclass.DevicelibsTestCase):

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testUnmountedBTRFS(self):
        """A series of simple tests on an unmounted file system.

           These tests are limited to simple creating and scanning.
        """
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        ##
        ## create_volume
        ##
        # no devices specified
        self.assertRaisesRegexp(ValueError,
           "no devices specified",
           btrfs.create_volume, [], data=0)

        # non-existant device
        self.assertRaisesRegexp(ValueError,
           "one or more specified devices not present",
           btrfs.create_volume,
           ["/not/existing/device"])

        # bad data
        self.assertRaisesRegexp(btrfs.BTRFSError,
           "1",
           btrfs.create_volume,
           [_LOOP_DEV0], data="RaID7")

        # bad metadata
        self.assertRaisesRegexp(btrfs.BTRFSError,
           "1",
           btrfs.create_volume,
           [_LOOP_DEV0], metadata="RaID7")

        # pass
        self.assertEqual(btrfs.create_volume(self._loopMap.values()), 0)

        # already created
        self.assertRaisesRegexp(btrfs.BTRFSError,
           "1",
           btrfs.create_volume,
           [_LOOP_DEV0], metadata="RaID7")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testMkfsDefaults(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        btrfs.create_volume(self._loopMap.values())

        self.assertEqual(btrfs.summarize_filesystem(_LOOP_DEV0)["label"], "none")
        self.assertEqual(btrfs.summarize_filesystem(_LOOP_DEV0)["num_devices"], "2")


        self.assertEqual(len(btrfs.list_devices(_LOOP_DEV0)), 2)
        self.assertIn(_LOOP_DEV1,
           [ dev["path"] for dev in btrfs.list_devices(_LOOP_DEV0) ])
        self.assertIn(_LOOP_DEV0,
           [ dev["path"] for dev in btrfs.list_devices(_LOOP_DEV1) ])

def suite():
    return unittest.TestSuite(
       unittest.TestLoader().loadTestsFromTestCase(BTRFSAsRootTestCase))


if __name__ == "__main__":
    unittest.main()
