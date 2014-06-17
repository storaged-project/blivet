#!/usr/bin/python
import os
import selinux
import tempfile
import unittest

import blivet
from tests import loopbackedtestcase
import blivet.formats.fs as fs

class SELinuxContextTestCase(loopbackedtestcase.LoopBackedTestCase):
    """Testing SELinux contexts.
    """

    def __init__(self, methodName='runTest'):
        super(SELinuxContextTestCase, self).__init__(methodName=methodName, deviceSpec=[102400])

    def testMountingExt2FS(self):
        an_fs = fs.Ext2FS(device=self.loopDevices[0], label="test")
        self.assertIsNone(an_fs.create())

        blivet.flags.installer_mode = False
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        root_selinux_context = selinux.getfilecon(mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertTrue(os.path.exists(lost_and_found))

        lost_and_found_selinux_context = selinux.getfilecon(lost_and_found)

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertEqual(root_selinux_context[1], 'system_u:object_r:file_t:s0')

        self.assertEqual(lost_and_found_selinux_context[1],
           'system_u:object_r:file_t:s0')

        blivet.flags.installer_mode = True
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        root_selinux_context = selinux.getfilecon(mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertTrue(os.path.exists(lost_and_found))

        lost_and_found_selinux_context = selinux.getfilecon(lost_and_found)

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertEqual(root_selinux_context[1], 'system_u:object_r:file_t:s0')

        self.assertEqual(lost_and_found_selinux_context[1],
           'system_u:object_r:lost_found_t:s0')

    def testMountingXFS(self):
        an_fs = fs.XFS(device=self.loopDevices[0], label="test")
        self.assertIsNone(an_fs.create())

        blivet.flags.installer_mode = False
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        root_selinux_context = selinux.getfilecon(mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertFalse(os.path.exists(lost_and_found))

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertEqual(root_selinux_context[1], 'system_u:object_r:file_t:s0')

        blivet.flags.installer_mode = True
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        root_selinux_context = selinux.getfilecon(mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertFalse(os.path.exists(lost_and_found))

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertEqual(root_selinux_context[1], 'system_u:object_r:file_t:s0')

if __name__ == "__main__":
    unittest.main()
