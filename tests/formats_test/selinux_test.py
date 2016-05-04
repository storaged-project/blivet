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

    def __init__(self, methodName='run_test'):
        super(SELinuxContextTestCase, self).__init__(methodName=methodName, device_spec=[Size("100 MiB")])

    def setUp(self):
        self.selinux_reset_fcon = blivet.flags.selinux_reset_fcon
        super(SELinuxContextTestCase, self).setUp()

    def test_mounting_ext2fs(self):
        """ Test that lost+found directory gets assigned correct SELinux
            context if selinux_set_fcon is True, and retains some random old
            context if selinux_set_fcon is False.
        """
        LOST_AND_FOUND_CONTEXT = 'system_u:object_r:lost_found_t:s0'
        an_fs = fs.Ext2FS(device=self.loop_devices[0], label="test")

        if not an_fs.formattable or not an_fs.mountable:
            self.skipTest("can not create or mount filesystem %s" % an_fs.name)

        self.assertIsNone(an_fs.create())

        blivet.flags.selinux_reset_fcon = False
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertTrue(os.path.exists(lost_and_found))

        lost_and_found_selinux_context = selinux.getfilecon(lost_and_found)

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertNotEqual(lost_and_found_selinux_context[1], LOST_AND_FOUND_CONTEXT)

        blivet.flags.selinux_reset_fcon = True
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertTrue(os.path.exists(lost_and_found))

        lost_and_found_selinux_context = selinux.getfilecon(lost_and_found)

        an_fs.unmount()
        os.rmdir(mountpoint)

        self.assertEqual(lost_and_found_selinux_context[1], LOST_AND_FOUND_CONTEXT)

    def test_mounting_xfs(self):
        """ XFS does not have a lost+found directory. """
        an_fs = fs.XFS(device=self.loop_devices[0], label="test")

        if not an_fs.formattable or not an_fs.mountable:
            self.skipTest("can not create or mount filesystem %s" % an_fs.name)

        self.assertIsNone(an_fs.create())

        blivet.flags.selinux_reset_fcon = False
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertFalse(os.path.exists(lost_and_found))

        an_fs.unmount()
        os.rmdir(mountpoint)

        blivet.flags.selinux_reset_fcon = True
        mountpoint = tempfile.mkdtemp("test.selinux")
        an_fs.mount(mountpoint=mountpoint)

        lost_and_found = os.path.join(mountpoint, "lost+found")
        self.assertFalse(os.path.exists(lost_and_found))

        an_fs.unmount()
        os.rmdir(mountpoint)

    def tearDown(self):
        super(SELinuxContextTestCase, self).tearDown()
        blivet.flags.selinux_reset_fcon = self.selinux_reset_fcon
