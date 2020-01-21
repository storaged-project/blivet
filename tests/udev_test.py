
import unittest
import mock


class UdevTest(unittest.TestCase):

    def setUp(self):
        import blivet.udev
        self._blivet_os = blivet.udev.os
        self._blivet_log = blivet.udev.log
        self._blivet_util = blivet.udev.util
        blivet.udev.os = mock.Mock()
        blivet.udev.log = mock.Mock()
        blivet.udev.util = mock.Mock()

    def tearDown(self):
        import blivet.udev
        blivet.udev.log = self._blivet_log
        blivet.udev.os = self._blivet_os
        blivet.udev.util = self._blivet_util

    def test_udev_get_device(self):
        import blivet.udev
        devices = blivet.udev.global_udev.list_devices(subsystem="block")
        for device in devices:
            self.assertNotEqual(blivet.udev.get_device(device.sys_path), None)

    def test_udev_settle(self):
        import blivet.udev
        blivet.udev.settle()
        self.assertTrue(blivet.udev.util.run_program.called)

    def test_udev_trigger(self):
        import blivet.udev
        blivet.udev.trigger()
        self.assertTrue(blivet.udev.util.run_program.called)

    @mock.patch('blivet.udev.device_is_cdrom', return_value=False)
    @mock.patch('blivet.udev.device_is_partition', return_value=False)
    @mock.patch('blivet.udev.device_is_dm_partition', return_value=False)
    @mock.patch('blivet.udev.device_is_dm_lvm', return_value=False)
    @mock.patch('blivet.udev.device_is_dm_crypt', return_value=False)
    @mock.patch('blivet.udev.device_is_md')
    @mock.patch('blivet.udev.device_get_md_container')
    @mock.patch('blivet.udev.device_get_slaves')
    def test_udev_device_is_disk_md(self, *args):
        import blivet.udev
        info = dict(DEVTYPE='disk', SYS_PATH=mock.sentinel.md_path)
        (device_get_slaves, device_get_md_container, device_is_md) = args[:3]  # pylint: disable=unbalanced-tuple-unpacking

        disk_parents = [dict(DEVTYPE="disk", SYS_PATH='/fake/path/2'),
                        dict(DEVTYPE="disk", SYS_PATH='/fake/path/3')]
        partition_parents = [dict(DEVTYPE="partition", SYS_PATH='/fake/path/2'),
                             dict(DEVTYPE="partition", SYS_PATH='/fake/path/3')]
        mixed_parents = [dict(DEVTYPE="partition", SYS_PATH='/fake/path/2'),
                         dict(DEVTYPE="partition", SYS_PATH='/fake/path/3')]

        blivet.udev.os.path.exists.return_value = False  # has_range checked in device_is_disk
        device_is_md.return_value = True

        # Intel FW RAID (MD RAID w/ container layer)
        # device_get_container will return some mock value which will evaluate to True
        device_get_md_container.return_value = mock.sentinel.md_container
        device_get_slaves.side_effect = lambda info: list()
        self.assertTrue(blivet.udev.device_is_disk(info))

        # Normal MD RAID
        device_get_slaves.side_effect = lambda info: partition_parents if info['SYS_PATH'] == mock.sentinel.md_path else list()
        device_get_md_container.return_value = None
        self.assertFalse(blivet.udev.device_is_disk(info))

        # Dell FW RAID (MD RAID whose members are all whole disks)
        device_get_slaves.side_effect = lambda info: disk_parents if info['SYS_PATH'] == mock.sentinel.md_path else list()
        self.assertTrue(blivet.udev.device_is_disk(info))

        # Normal MD RAID (w/ at least one non-disk member)
        device_get_slaves.side_effect = lambda info: mixed_parents if info['SYS_PATH'] == mock.sentinel.md_path else list()
        self.assertFalse(blivet.udev.device_is_disk(info))
