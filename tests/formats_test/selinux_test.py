#!/usr/bin/python
import os
import selinux
import tempfile
import unittest

import blivet
from devicelibs_test import baseclass
from blivet.formats import device_formats
import blivet.formats.fs as fs

class SELinuxContextTestCase(baseclass.DevicelibsTestCase):
    """Testing SELinux contexts.
    """

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testMountingExt2FS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.Ext2FS(device=_LOOP_DEV0, label="test")
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

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testMountingXFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.XFS(device=_LOOP_DEV0, label="test")
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

def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(SELinuxContextTestCase)
    return unittest.TestSuite([suite1])


if __name__ == "__main__":
    unittest.main()
