# pylint: disable=unused-import
import os

import unittest
from unittest.mock import patch, ANY

import blivet
import blivet.formats.fs as fs


class SELinuxContextTestCase(unittest.TestCase):
    """Testing SELinux contexts.
    """

    def setUp(self):
        if not blivet.flags.flags.selinux:
            self.skipTest("SELinux disabled.")
        self.selinux_reset_fcon = blivet.flags.flags.selinux_reset_fcon
        self.selinux = blivet.flags.flags.selinux
        super(SELinuxContextTestCase, self).setUp()
        self.addCleanup(self._clean_up)

    @patch("blivet.tasks.fsmount.BlockDev.fs.mount", return_value=True)
    @patch.object(fs.FS, "_pre_setup", return_value=True)
    @patch("os.access", return_value=True)
    @patch("os.path.isdir", return_value=True)
    # pylint: disable=unused-argument
    def exec_mount_selinux_format(self, formt, *args):
        """ Test of correct selinux context parameter value when mounting """

        lost_found_context = "system_u:object_r:lost_found_t:s0"
        blivet.flags.flags.selinux = True
        fmt = formt()

        import selinux
        # Patch selinux context setting
        with patch("selinux.lsetfilecon") as lsetfilecon:
            lsetfilecon.return_value = True

            blivet.flags.flags.selinux_reset_fcon = True
            fmt.setup(mountpoint="dummy")  # param needed to pass string check
            if isinstance(fmt, fs.Ext2FS):
                lsetfilecon.assert_called_with(ANY, lost_found_context)
            else:
                lsetfilecon.assert_not_called()

            lsetfilecon.reset_mock()

            blivet.flags.flags.selinux_reset_fcon = False
            fmt.setup(mountpoint="dummy")  # param needed to pass string check
            lsetfilecon.assert_not_called()

    def test_mount_selinux_ext2fs(self):
        """ Test of correct selinux context parameter value when mounting ext2"""
        self.exec_mount_selinux_format(fs.Ext2FS)

    def test_mount_selinux_xfs(self):
        """ Test of correct selinux context parameter value when mounting XFS"""
        self.exec_mount_selinux_format(fs.XFS)

    def _clean_up(self):
        blivet.flags.flags.selinux_reset_fcon = self.selinux_reset_fcon
        blivet.flags.flags.selinux = self.selinux
