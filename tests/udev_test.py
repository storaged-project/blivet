#!/usr/bin/python

import unittest

try:
    import mock
except ImportError:
    has_mock = False
else:
    has_mock = True

@unittest.skipUnless(has_mock, "Python mock module not available.")
class UdevTest(unittest.TestCase):

    def setUp(self):
        import blivet.udev
        blivet.udev.os = mock.Mock()
        blivet.udev.log = mock.Mock()

    def test_udev_get_device(self):
        import blivet.udev
        devices = blivet.udev.global_udev.list_devices(subsystem="block")
        for device in devices:
            self.assertNotEqual(blivet.udev.get_device(device.sys_path), None)

    def udev_settle_test(self):
        import blivet.udev
        blivet.udev.util = mock.Mock()
        blivet.udev.settle()
        self.assertTrue(blivet.udev.util.run_program.called)

    def udev_trigger_test(self):
        import blivet.udev
        blivet.udev.util = mock.Mock()
        blivet.udev.trigger()
        self.assertTrue(blivet.udev.util.run_program.called)


if __name__ == "__main__":
    unittest.main()
