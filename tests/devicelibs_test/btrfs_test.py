#!/usr/bin/python
import baseclass
import os
import os.path
import subprocess
import tempfile
import unittest

import blivet.devicelibs.btrfs as btrfs
import blivet.util as util

class BTRFSMountDevice(baseclass.DevicelibsTestCase):
    """A superclass that mounts and unmounts the filesystem.
       It must create the filesystem on its chosen devices before mounting.
       It always mounts the filesystem using self.device at self.mountpoint.
    """
    def __init__(self, *args, **kwargs):
        baseclass.DevicelibsTestCase.__init__(self, *args, **kwargs)
        self.device = None
        self.mountpoint = None

    def setUp(self):
        """After the DevicelibsTestCase setup, creates the filesystem on both
           devices and mounts on a tmp directory.

           Chooses the device to specify to mount command arbitrarily.
        """
        baseclass.DevicelibsTestCase.setUp(self)

        btrfs.create_volume(self._loopMap.values())
        self.device = self._loopMap.values()[0]

        self.mountpoint = tempfile.mkdtemp()
        rc = subprocess.call(["mount", self.device, self.mountpoint])
        if rc:
            raise OSError, "mount failed to mount device %s" % device

    def tearDown(self):
        """Before the DevicelibsTestCase cleanup unmount the device and
           remove the temporary mountpoint.
        """
        proc = subprocess.Popen(["umount", self.device])
        while True:
            (out, err) = proc.communicate()
            if proc.returncode is not None:
                rc = proc.returncode
                break
        if rc:
            raise OSError, "failed to unmount device %s" % self.device

        os.rmdir(self.mountpoint)
        baseclass.DevicelibsTestCase.tearDown(self)

class BTRFSAsRootTestCase1(baseclass.DevicelibsTestCase):

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

class BTRFSAsRootTestCase2(BTRFSMountDevice):
    """Tests which require mounting the device."""

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testSubvolume(self):
        """Tests which focus on subvolumes."""
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        # no subvolumes yet
        self.assertEqual(btrfs.list_subvolumes(self.mountpoint), [])

        # the default subvolume is the root subvolume
        self.assertEqual(btrfs.get_default_subvolume(self.mountpoint),
           btrfs.MAIN_VOLUME_ID)

        # a new subvolume can be added succesfully below the mountpoint
        self.assertEqual(btrfs.create_subvolume(self.mountpoint, "SV1"), 0)

        # expect one subvolume
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertEqual(len(subvolumes), 1)
        self.assertEqual(subvolumes[0]['path'], 'SV1')
        self.assertEqual(subvolumes[0]['parent'], btrfs.MAIN_VOLUME_ID)

        # the same subvolume can be deleted
        self.assertEqual(btrfs.delete_subvolume(self.mountpoint, "SV1"), 0)

        # deleted subvolume is no longer present
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertNotIn("SV1", [v['path'] for v in subvolumes])

        # two distinct subvolumes, so both should be present
        self.assertEqual(btrfs.create_subvolume(self.mountpoint, "SV1"), 0)
        self.assertEqual(btrfs.create_subvolume(self.mountpoint, "SV2"), 0)
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertIn("SV1", [v['path'] for v in subvolumes])
        self.assertIn("SV2", [v['path'] for v in subvolumes])

        # we can remove one subvolume
        self.assertEqual(btrfs.delete_subvolume(self.mountpoint, "SV1"), 0)
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertNotIn("SV1", [v['path'] for v in subvolumes])

        # if the subvolume is already gone,  an error is raised by btrfs
        self.assertRaisesRegexp(btrfs.BTRFSError,
           "1",
           btrfs.delete_subvolume,
           self.mountpoint, "SV1")

        # if the subvolume is already there, an error is raise by btrfs
        self.assertRaisesRegexp(btrfs.BTRFSError,
           "1",
           btrfs.create_subvolume,
           self.mountpoint, "SV2")

        # if we create SV1 once again it's back
        self.assertEqual(btrfs.create_subvolume(self.mountpoint, "SV1"), 0)
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertIn("SV1", [v['path'] for v in subvolumes])

        # we can create an additional subvolume beneath SV1
        self.assertEqual(btrfs.create_subvolume(os.path.join(self.mountpoint, "SV1"), "SV1.1"), 0)
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertEqual(len([v for v in subvolumes if v['path'].find("SV1.1") != -1]), 1)


def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(BTRFSAsRootTestCase1)
    suite1 = unittest.TestLoader().loadTestsFromTestCase(BTRFSAsRootTestCase2)
    return unittest.TestSuite([suite1, suite2])


if __name__ == "__main__":
    unittest.main()
