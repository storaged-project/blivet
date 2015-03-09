#!/usr/bin/python
# vim:set fileencoding=utf-8

import unittest

from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import StorageDevice

class DeviceNameTestCase(unittest.TestCase):
    """Test device name validation"""

    def testStorageDevice(self):
        # Check that / and NUL are rejected along with . and ..
        good_names = ['sda1', '1sda', 'good-name', 'cciss/c0d0']
        bad_names = ['sda/1', 'sda\x00', '.', '..', 'cciss/..']

        for name in good_names:
            self.assertTrue(StorageDevice.isNameValid(name))

        for name in bad_names:
            self.assertFalse(StorageDevice.isNameValid(name))

    def testVolumeGroup(self):
        good_names = ['vg00', 'group-name', 'groupname-']
        bad_names = ['-leading-hyphen', 'únicode', 'sp aces']

        for name in good_names:
            self.assertTrue(LVMVolumeGroupDevice.isNameValid(name))

        for name in bad_names:
            self.assertFalse(LVMVolumeGroupDevice.isNameValid(name))

    def testLogicalVolume(self):
        good_names = ['lv00', 'volume-name', 'volumename-']
        bad_names = ['-leading-hyphen', 'únicode', 'sp aces',
                     'snapshot47', 'pvmove0', 'sub_tmetastring']

        for name in good_names:
            self.assertTrue(LVMLogicalVolumeDevice.isNameValid(name))

        for name in bad_names:
            self.assertFalse(LVMLogicalVolumeDevice.isNameValid(name))

if __name__ == "__main__":
    unittest.main()
