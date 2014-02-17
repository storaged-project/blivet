#!/usr/bin/python

import unittest
import mock
import os

class UdevTest(unittest.TestCase):

    def setUp(self):
        import blivet.udev
        blivet.udev.os = mock.Mock()
        blivet.udev.log = mock.Mock()

    def test_udev_enumerate_devices(self):
        import blivet.udev
        ENUMERATE_LIST = [
            '/sys/devices/pci0000:00/0000:00:1f.2/host0/target0:0:0/0:0:0:0/block/sda',
            '/sys/devices/virtual/block/loop0',
            '/sys/devices/virtual/block/loop1',
            '/sys/devices/virtual/block/ram0',
            '/sys/devices/virtual/block/ram1',
            '/sys/devices/virtual/block/dm-0',
        ]
        blivet.udev.global_udev.enumerate_devices = mock.Mock(return_value=ENUMERATE_LIST)
        ret = blivet.udev.udev_enumerate_devices()
        self.assertEqual(set(ret),
            set(['/devices/pci0000:00/0000:00:1f.2/host0/target0:0:0/0:0:0:0/block/sda',
            '/devices/virtual/block/loop0', '/devices/virtual/block/loop1',
            '/devices/virtual/block/ram0', '/devices/virtual/block/ram1',
            '/devices/virtual/block/dm-0'])
        )

    def test_udev_get_device_1(self):
        import blivet.udev

        class Device(object):
            def __init__(self):
                self.sysname = 'loop1'
                self.dict = {'symlinks': ['/dev/block/7:1'],
                    'SUBSYSTEM': 'block',
                    'MAJOR': '7',
                    'DEVPATH': '/devices/virtual/block/loop1',
                    'UDISKS_PRESENTATION_NOPOLICY': '1',
                    'UDEV_LOG': '3',
                    'DEVNAME': '/dev/loop1',
                    'DEVTYPE': 'disk',
                    'DEVLINKS': '/dev/block/7:1',
                    'MINOR': '1'
                }

            def __getitem__(self, key):
                return self.dict[key]

            def __setitem__(self, key, value):
                self.dict[key] = value

        blivet.udev.os.path.exists.return_value = True
        DEV_PATH = '/devices/virtual/block/loop1'
        dev = Device()
        blivet.udev.global_udev = mock.Mock()
        blivet.udev.global_udev.create_device.return_value = dev

        saved = blivet.udev.udev_parse_uevent_file
        blivet.udev.udev_parse_uevent_file = mock.Mock(return_value=dev)

        ret = blivet.udev.udev_get_device(DEV_PATH)
        self.assertTrue(isinstance(ret, Device))
        self.assertEqual(ret['name'], ret.sysname)
        self.assertEqual(ret['sysfs_path'], DEV_PATH)
        self.assertTrue(blivet.udev.udev_parse_uevent_file.called)

        blivet.udev.udev_parse_uevent_file = saved

    def test_udev_get_device_2(self):
        import blivet.udev
        blivet.udev.os.path.exists.return_value = False
        ret = blivet.udev.udev_get_device('')
        self.assertEqual(ret, None)

    def test_udev_get_device_3(self):
        import blivet.udev
        blivet.udev.os.path.exists.return_value = True
        blivet.udev.global_udev = mock.Mock()
        blivet.udev.global_udev.create_device.return_value = None
        ret = blivet.udev.udev_get_device('')
        self.assertEqual(ret, None)

    def test_udev_get_devices(self):
        import blivet.udev
        saved = blivet.udev.udev_settle
        blivet.udev.udev_settle = mock.Mock()
        DEVS = \
            ['/devices/pci0000:00/0000:00:1f.2/host0/target0:0:0/0:0:0:0/block/sda',
            '/devices/virtual/block/loop0', '/devices/virtual/block/loop1',
            '/devices/virtual/block/ram0', '/devices/virtual/block/ram1',
            '/devices/virtual/block/dm-0']
        blivet.udev.udev_enumerate_devices = mock.Mock(return_value=DEVS)
        blivet.udev.udev_get_device = lambda x: x
        ret = blivet.udev.udev_get_devices()
        self.assertEqual(ret, DEVS)
        blivet.udev.udev_settle = saved

    def test_udev_parse_uevent_file_1(self):
        import blivet.udev
        # For this one we're accessing the real uevent file (twice).
        path = '/devices/virtual/block/loop1'
        if not os.path.exists("/sys" + path):
            self.skipTest("this test requires the presence of /dev/loop1")

        info = {'sysfs_path': path}
        for line in open('/sys' + path + '/uevent').readlines():
            (name, equals, value) = line.strip().partition("=")
            if not equals:
                continue

            info[name] = value

        dev = {'sysfs_path': path}
        blivet.udev.os.path.normpath = os.path.normpath
        blivet.udev.os.access = os.access
        blivet.udev.os.R_OK = os.R_OK
        ret = blivet.udev.udev_parse_uevent_file(dev)
        self.assertEqual(ret, info)
        blivet.udev.os.path.normpath = mock.Mock()
        blivet.udev.os.access = mock.Mock()
        blivet.udev.os.R_OK = mock.Mock()

    def test_udev_parse_uevent_file_2(self):
        import blivet.udev
        blivet.udev.os.path.normpath = os.path.normpath
        blivet.udev.os.access.return_value = False
        path = '/devices/virtual/block/loop1'
        if not os.path.exists("/sys" + path):
            self.skipTest("this test requires the presence of /dev/loop1")

        dev = {'sysfs_path': path}

        ret = blivet.udev.udev_parse_uevent_file(dev)
        self.assertEqual(ret, {'sysfs_path': '/devices/virtual/block/loop1'})

    def udev_settle_test(self):
        import blivet.udev
        blivet.udev.util = mock.Mock()
        blivet.udev.udev_settle()
        self.assertTrue(blivet.udev.util.run_program.called)

    def udev_trigger_test(self):
        import blivet.udev
        blivet.udev.util = mock.Mock()
        blivet.udev.udev_trigger()
        self.assertTrue(blivet.udev.util.run_program.called)


if __name__ == "__main__":
    unittest.main()
