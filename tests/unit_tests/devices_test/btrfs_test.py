import unittest

try:
    from unittest.mock import patch
except ImportError:
    from mock import patch

import blivet

from blivet.devices import StorageDevice
from blivet.devices import BTRFSVolumeDevice
from blivet.devices import BTRFSSubVolumeDevice
from blivet.size import Size


DEVICE_CLASSES = [
    BTRFSVolumeDevice,
    BTRFSSubVolumeDevice,
    StorageDevice
]


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class BlivetNewBtrfsVolumeDeviceTest(unittest.TestCase):
    def test_new_btrfs(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=False)

        b.devicetree._add_device(bd)

        with patch("blivet.devicetree.DeviceTree.names", []):
            vol = b.new_btrfs(name="testvolume", parents=[bd])
        self.assertEqual(vol.name, "testvolume")
        self.assertEqual(vol.size, bd.size)
        self.assertIsNotNone(vol.format)
        self.assertEqual(vol.format.type, "btrfs")

        b.create_device(vol)

        with patch("blivet.devices.btrfs.blockdev.btrfs") as blockdev:
            with patch.object(vol, "_pre_create"):
                with patch.object(vol, "_post_create"):
                    vol.create()
                    blockdev.create_volume.assert_called_with(['/dev/bd1'],
                                                              label='testvolume',
                                                              data_level=None,
                                                              md_level=None,
                                                              extra={'-U': vol.uuid})

        with patch("blivet.devicetree.DeviceTree.names", []):
            sub = b.new_btrfs_sub_volume(name="testsub", parents=[vol])

        self.assertIsNotNone(sub.format)
        self.assertEqual(sub.format.type, "btrfs")
        self.assertEqual(sub.size, vol.size)
        self.assertEqual(sub.volume, vol)

    def test_device_id(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=False)

        vol = BTRFSVolumeDevice("testvolume", parents=[bd])
        self.assertEqual(vol.device_id, "BTRFS-" + vol.uuid)

        sub = BTRFSSubVolumeDevice("testsub", parents=[vol])
        self.assertEqual(sub.device_id, "BTRFS-" + vol.uuid + "-testsub")
