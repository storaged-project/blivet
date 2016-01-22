# vim:set fileencoding=utf-8

import unittest

from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import StorageDevice
from blivet.size import Size
import blivet


class DeviceNameTestCase(unittest.TestCase):

    """Test device name validation"""

    def test_storage_device(self):
        # Check that / and NUL are rejected along with . and ..
        good_names = ['sda1', '1sda', 'good-name', 'cciss/c0d0']
        bad_names = ['sda/1', 'sda\x00', '.', '..', 'cciss/..']

        sd = StorageDevice("tester")

        for name in good_names:
            self.assertTrue(sd.is_name_valid(name))

        for name in bad_names:
            self.assertFalse(sd.is_name_valid(name))

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
