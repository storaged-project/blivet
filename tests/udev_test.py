
import unittest
import mock

import blivet3.udev as udev


class UdevTest(unittest.TestCase):

    def setUp(self):
        self._blivet_os = udev.os
        self._blivet_log = udev.log
        self._blivet_util = udev.util
        udev.os = mock.Mock()
        udev.log = mock.Mock()
        udev.util = mock.Mock()

    def tearDown(self):
        udev.log = self._blivet_log
        udev.os = self._blivet_os
        udev.util = self._blivet_util

    def test_udev_get_device(self):
        devices = udev.global_udev.list_devices(subsystem="block")
        for device in devices:
            self.assertNotEqual(udev.get_device(device.sys_path), None)

    def udev_settle_test(self):
        udev.settle()
        self.assertTrue(udev.util.run_program.called)

    def udev_trigger_test(self):
        udev.trigger()
        self.assertTrue(udev.util.run_program.called)
