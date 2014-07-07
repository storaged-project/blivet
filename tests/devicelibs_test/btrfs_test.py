#!/usr/bin/python
import os
import os.path
import subprocess
import tempfile
import unittest

import blivet.devicelibs.btrfs as btrfs
from blivet.errors import BTRFSError

from tests import loopbackedtestcase

class BTRFSMountDevice(loopbackedtestcase.LoopBackedTestCase):
    """A superclass that mounts and unmounts the filesystem.
       It must create the filesystem on its chosen devices before mounting.
       It always mounts the filesystem using self.device at self.mountpoint.
    """
    def __init__(self, methodName='runTest'):
        super(BTRFSMountDevice, self).__init__(methodName=methodName)
        self.device = None
        self.mountpoint = None

    def setUp(self):
        """After the DevicelibsTestCase setup, creates the filesystem on both
           devices and mounts on a tmp directory.

           Chooses the device to specify to mount command arbitrarily.
        """
        super(BTRFSMountDevice, self).setUp()

        btrfs.create_volume(self.loopDevices)
        self.device = self.loopDevices[0]

        self.mountpoint = tempfile.mkdtemp()
        rc = subprocess.call(["mount", self.device, self.mountpoint])
        if rc:
            raise OSError("mount failed to mount device %s" % self.device)

    def tearDown(self):
        """Before the DevicelibsTestCase cleanup unmount the device and
           remove the temporary mountpoint.
        """
        proc = subprocess.Popen(["umount", self.device])
        while True:
            proc.communicate()
            if proc.returncode is not None:
                rc = proc.returncode
                break
        if rc:
            raise OSError("failed to unmount device %s" % self.device)

        os.rmdir(self.mountpoint)
        super(BTRFSMountDevice, self).tearDown()

class BTRFSAsRootTestCase1(loopbackedtestcase.LoopBackedTestCase):

    def testUnmountedBTRFS(self):
        """A series of simple tests on an unmounted file system.

           These tests are limited to simple creating and scanning.
        """
        _LOOP_DEV0 = self.loopDevices[0]
        _LOOP_DEV1 = self.loopDevices[1]

        ##
        ## create_volume
        ##
        # no devices specified
        with self.assertRaisesRegexp(ValueError, "no devices specified"):
            btrfs.create_volume([], data=0)

        # non-existant device
        with self.assertRaisesRegexp(ValueError, "one or more specified devices not present"):
            btrfs.create_volume(["/not/existing/device"])

        # bad data
        with self.assertRaisesRegexp(BTRFSError, "1"):
            btrfs.create_volume([_LOOP_DEV0], data="RaID7")

        # bad metadata
        with self.assertRaisesRegexp(BTRFSError, "1"):
            btrfs.create_volume([_LOOP_DEV0], metadata="RaID7")

        # pass
        self.assertEqual(btrfs.create_volume(self.loopDevices), 0)

        # already created
        with self.assertRaisesRegexp(BTRFSError, "1"):
            btrfs.create_volume([_LOOP_DEV0], metadata="RaID7")

    def testMkfsDefaults(self):
        _LOOP_DEV0 = self.loopDevices[0]
        _LOOP_DEV1 = self.loopDevices[1]

        btrfs.create_volume(self.loopDevices)

        self.assertEqual(btrfs.summarize_filesystem(_LOOP_DEV0)["label"], "none")
        self.assertEqual(btrfs.summarize_filesystem(_LOOP_DEV0)["num_devices"], "2")

        self.assertEqual(len(btrfs.list_devices(_LOOP_DEV0)), 2)
        self.assertIn(_LOOP_DEV1,
           [ dev["path"] for dev in btrfs.list_devices(_LOOP_DEV0) ])
        self.assertIn(_LOOP_DEV0,
           [ dev["path"] for dev in btrfs.list_devices(_LOOP_DEV1) ])

class BTRFSAsRootTestCase2(BTRFSMountDevice):
    """Tests which require mounting the device."""

    def testSubvolume(self):
        """Tests which focus on subvolumes."""
        _LOOP_DEV0 = self.loopDevices[0]
        _LOOP_DEV1 = self.loopDevices[1]

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
        with self.assertRaisesRegexp(BTRFSError, "1"):
            btrfs.delete_subvolume(self.mountpoint, "SV1")

        # if the subvolume is already there, an error is raise by btrfs
        with self.assertRaisesRegexp(BTRFSError, "1"):
            btrfs.create_subvolume(self.mountpoint, "SV2")

        # if we create SV1 once again it's back
        self.assertEqual(btrfs.create_subvolume(self.mountpoint, "SV1"), 0)
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertIn("SV1", [v['path'] for v in subvolumes])

        # we can create an additional subvolume beneath SV1
        self.assertEqual(btrfs.create_subvolume(os.path.join(self.mountpoint, "SV1"), "SV1.1"), 0)
        subvolumes = btrfs.list_subvolumes(self.mountpoint)
        self.assertEqual(len([v for v in subvolumes if v['path'].find("SV1.1") != -1]), 1)

class BTRFSAsRootTestCase3(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='runTest'):
        super(BTRFSAsRootTestCase3, self).__init__(methodName=methodName, deviceSpec=[8192])

    def testSmallDevice(self):
        """ Creation of a smallish device will result in an error if the
            data and metadata levels are specified differently, but not if
            they are unspecified.
        """
        with self.assertRaises(BTRFSError):
            btrfs.create_volume(self.loopDevices, data="single", metadata="dup")
        self.assertEqual(btrfs.create_volume(self.loopDevices), 0)

if __name__ == "__main__":
    unittest.main()
