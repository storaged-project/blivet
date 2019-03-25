
import unittest
import mock


class UdevTest(unittest.TestCase):

    def setUp(self):
        import blivet3.udev
        self._blivet_os = blivet.udev.os
        self._blivet_log = blivet.udev.log
        self._blivet_util = blivet.udev.util
        blivet.udev.os = mock.Mock()
        blivet.udev.log = mock.Mock()
        blivet.udev.util = mock.Mock()

    def tearDown(self):
        import blivet3.udev
        blivet.udev.log = self._blivet_log
        blivet.udev.os = self._blivet_os
        blivet.udev.util = self._blivet_util

    def test_udev_get_device(self):
        import blivet3.udev
        devices = blivet.udev.global_udev.list_devices(subsystem="block")
        for device in devices:
            self.assertNotEqual(blivet.udev.get_device(device.sys_path), None)

    def udev_settle_test(self):
        import blivet3.udev
        blivet.udev.settle()
        self.assertTrue(blivet.udev.util.run_program.called)

    def udev_trigger_test(self):
        import blivet3.udev
        blivet.udev.trigger()
        self.assertTrue(blivet.udev.util.run_program.called)
