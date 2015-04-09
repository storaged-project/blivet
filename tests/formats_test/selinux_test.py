#!/usr/bin/python
import os
import selinux
import tempfile
import unittest

import blivet
from tests import loopbackedtestcase
import blivet.formats.fs as fs
from blivet.size import Size

@unittest.skipUnless(selinux.is_selinux_enabled() == 1, "SELinux is disabled")
class SELinuxContextTestCase(loopbackedtestcase.LoopBackedTestCase):
    """Testing SELinux contexts.
    """

    def __init__(self, methodName='runTest'):
        super(SELinuxContextTestCase, self).__init__(methodName=methodName, deviceSpec=[Size("100 MiB")])

    def setUp(self):
        self.installer_mode = blivet.flags.installer_mode
        super(SELinuxContextTestCase, self).setUp()

    def testMountingExt2FS(self):
        """ Test that lost+found directory gets assigned correct SELinux
            context if installer_mode is True, and retains some random old
            context if installer_mode is False.
        """
        LOST_AND_FOUND_CONTEXT = 'system_u:object_r:lost_found_t:s0'
        an_fs = fs.Ext2FS(device=self.loopDevices[0], label="test")
        self.assertIsNone(an_fs.create())

        blivet.flags.installer_mode = False
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertTrue(os.path.exists(lost_and_found))

        lost_and_found_selinux_context = selinux.getfilecon(lost_and_found)

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertNotEqual(lost_and_found_selinux_context[1], LOST_AND_FOUND_CONTEXT)

        blivet.flags.installer_mode = True
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertTrue(os.path.exists(lost_and_found))

        lost_and_found_selinux_context = selinux.getfilecon(lost_and_found)

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertEqual(lost_and_found_selinux_context[1], LOST_AND_FOUND_CONTEXT)

    def testMountingXFS(self):
        """ XFS does not have a lost+found directory. """
        an_fs = fs.XFS(device=self.loopDevices[0], label="test")
        self.assertIsNone(an_fs.create())

        blivet.flags.installer_mode = False
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertFalse(os.path.exists(lost_and_found))

        an_fs.unmount()
        os.rmdir(mountpoint)

        blivet.flags.installer_mode = True
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertFalse(os.path.exists(lost_and_found))

        an_fs.unmount()
        os.rmdir(mountpoint)

    def tearDown(self):
        super(SELinuxContextTestCase, self).tearDown()
        blivet.flags.installer_mode = self.installer_mode

if __name__ == "__main__":
    unittest.main()
