import unittest
from unittest.mock import patch

from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import StorageDevice
from blivet.size import Size
import blivet


class DeviceNameTestCase(unittest.TestCase):
    """Test device name validation"""
    @patch.object(StorageDevice, "status", return_value=True)
    @patch.object(StorageDevice, "update_sysfs_path", return_value=None)
    @patch.object(StorageDevice, "read_current_size", return_value=None)
    def test_storage_device(self, *patches):  # pylint: disable=unused-argument
        # Check that / and NUL are rejected along with . and ..
        good_names = ['sda1', '1sda', 'good-name', 'cciss/c0d0']
        bad_names = ['sda/1', 'sda\x00', '.', '..', 'cciss/..']

        sd = StorageDevice("tester")

        for name in good_names:
            self.assertTrue(sd.is_name_valid(name))

        for name in bad_names:
            self.assertFalse(sd.is_name_valid(name))

        # Check that name validity check is omitted (only) when
        # device already exists
        # This test was added to prevent regression (see #1379145)
        for name in good_names:
            try:
                StorageDevice(name, exists=True)
            except ValueError:
                self.fail("Name check should not be performed nor failing")

            try:
                StorageDevice(name, exists=False)
            except ValueError:
                self.fail("Device name check failed when it shouldn't")

        for name in bad_names:
            try:
                StorageDevice(name, exists=True)
            except ValueError as e:
                if ' is not a valid name for this device' in str(e):
                    self.fail("Device name checked on already existing device")

            with self.assertRaisesRegex(ValueError, ' is not a valid name for this device'):
                StorageDevice(name, exists=False)

    def test_volume_group(self):
        good_names = ['vg00', 'group-name', 'groupname-']
        bad_names = ['-leading-hyphen', 'únicode', 'sp aces']

        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])

        for name in good_names:
            self.assertTrue(vg.is_name_valid(name))

        for name in bad_names:
            self.assertFalse(vg.is_name_valid(name))

    def test_logical_volume(self):
        good_names = ['lv00', 'volume-name', 'volumename-']
        bad_names = ['-leading-hyphen', 'únicode', 'sp aces',
                     'snapshot47', 'pvmove0', 'sub_tmetastring']

        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.get_format("xfs"))

        for name in good_names:
            self.assertTrue(lv.is_name_valid(name))

        for name in bad_names:
            self.assertFalse(lv.is_name_valid(name))
