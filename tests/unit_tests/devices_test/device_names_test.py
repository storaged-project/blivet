import unittest
from unittest.mock import patch

from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import StorageDevice
from blivet.devicelibs import lvm
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

    def test_lvm_name_length(self):
        # a single VG/LV name may be up to LVM_MAX_NAME_LEN characters long
        self.assertTrue(lvm.is_lvm_name_valid("n" * lvm.LVM_MAX_NAME_LEN))
        self.assertFalse(lvm.is_lvm_name_valid("n" * (lvm.LVM_MAX_NAME_LEN + 1)))

        # names longer than the old 55 character limit are now accepted
        self.assertTrue(lvm.is_lvm_name_valid("n" * 96))

    def test_lvm_full_name(self):
        # the customer use case: 32 char VG name + 32 char LV name is fine
        self.assertTrue(lvm.is_lvm_full_name_valid("v" * 32, "l" * 32))

        # both parts still have to be valid on their own
        self.assertFalse(lvm.is_lvm_full_name_valid("-badvg", "goodlv"))
        self.assertFalse(lvm.is_lvm_full_name_valid("goodvg", "bad lv"))

        # the combined device-mapper name must fit (with headroom for the
        # suffixes LVM appends to internal LVs)
        budget = lvm.LVM_MAX_NAME_LEN - lvm.LVM_INTERNAL_LV_SUFFIX_LEN
        vg_name = "v" * 10
        max_lv = budget - len(vg_name) - 1  # -1 for the '-' separator
        self.assertTrue(lvm.is_lvm_full_name_valid(vg_name, "l" * max_lv))
        self.assertFalse(lvm.is_lvm_full_name_valid(vg_name, "l" * (max_lv + 1)))

        # hyphens in the names are doubled in the device-mapper name
        self.assertFalse(lvm.is_lvm_full_name_valid("v" * 10, "-".join("l" * budget)))

    @patch("blivet.formats.fs.Ext4FS.supported", return_value=True)
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    def test_safe_device_name_not_truncated(self, *args):  # pylint: disable=unused-argument,arguments-differ
        # a user-specified LVM name well within the LVM limits must not be
        # silently truncated (regression test for the customer report of
        # unexpectedly truncated LV names during Kickstart installation)
        b = blivet.Blivet()

        # 32 characters used to be truncated when max_len was lowered to 55
        # (as part of the vgname-lvname pair); it must survive unchanged now
        self.assertEqual(b.safe_device_name("l" * 32, blivet.devicefactory.DeviceTypes.LVM),
                         "l" * 32)

        # names longer than the old 55 character limit are no longer truncated
        self.assertEqual(b.safe_device_name("l" * 96, blivet.devicefactory.DeviceTypes.LVM),
                         "l" * 96)
