import unittest

import blivet

from blivet.devices import StorageDevice
from blivet.devices import MDRaidArrayDevice
from blivet.size import Size
from blivet.devicelibs import mdraid

DEVICE_CLASSES = [
    MDRaidArrayDevice,
    StorageDevice
]


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class MDRaidArrayDeviceTest(unittest.TestCase):

    def test_chunk_size1(self):

        member1 = StorageDevice("member1", fmt=blivet.formats.get_format("mdmember"),
                                size=Size("1 GiB"))
        member2 = StorageDevice("member2", fmt=blivet.formats.get_format("mdmember"),
                                size=Size("1 GiB"))

        raid_array = MDRaidArrayDevice(name="raid", level="raid0", member_devices=2,
                                       total_devices=2, parents=[member1, member2])

        # no chunk_size specified -- default value
        self.assertEqual(raid_array.chunk_size, mdraid.MD_CHUNK_SIZE)

    def test_chunk_size2(self):

        member1 = StorageDevice("member1", fmt=blivet.formats.get_format("mdmember"),
                                size=Size("1 GiB"))
        member2 = StorageDevice("member2", fmt=blivet.formats.get_format("mdmember"),
                                size=Size("1 GiB"))

        raid_array = MDRaidArrayDevice(name="raid", level="raid0", member_devices=2,
                                       total_devices=2, parents=[member1, member2],
                                       chunk_size=Size("1024 KiB"))

        self.assertEqual(raid_array.chunk_size, Size("1024 KiB"))

        with self.assertRaisesRegex(ValueError, "new chunk size must be of type Size"):
            raid_array.chunk_size = 1

        with self.assertRaisesRegex(ValueError, "new chunk size must be multiple of 4 KiB"):
            raid_array.chunk_size = Size("5 KiB")
