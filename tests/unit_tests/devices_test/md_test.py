import six
import unittest

try:
    from unittest.mock import patch
except ImportError:
    from mock import patch

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

        # no chunk_size specified and RAID0 -- default value
        self.assertEqual(raid_array.chunk_size, mdraid.MD_CHUNK_SIZE)

        with patch("blivet.devices.md.blockdev.md.create") as md_create:
            raid_array._create()
            md_create.assert_called_with("/dev/md/raid", "raid0", ["/dev/member1", "/dev/member2"],
                                         0, version="default", bitmap=None,
                                         chunk_size=mdraid.MD_CHUNK_SIZE)

        raid_array = MDRaidArrayDevice(name="raid", level="raid1", member_devices=2,
                                       total_devices=2, parents=[member1, member2])

        # no chunk_size specified and RAID1 -- no chunk size set (0)
        self.assertEqual(raid_array.chunk_size, Size(0))

        with patch("blivet.devices.md.blockdev.md.create") as md_create:
            raid_array._create()
            md_create.assert_called_with("/dev/md/raid", "raid1", ["/dev/member1", "/dev/member2"],
                                         0, version="default", bitmap="internal",
                                         chunk_size=0)

    def test_chunk_size2(self):

        member1 = StorageDevice("member1", fmt=blivet.formats.get_format("mdmember"),
                                size=Size("1 GiB"))
        member2 = StorageDevice("member2", fmt=blivet.formats.get_format("mdmember"),
                                size=Size("1 GiB"))

        raid_array = MDRaidArrayDevice(name="raid", level="raid0", member_devices=2,
                                       total_devices=2, parents=[member1, member2],
                                       chunk_size=Size("1024 KiB"))
        self.assertEqual(raid_array.chunk_size, Size("1024 KiB"))

        # for raid0 setting chunk_size = 0 means "default"
        raid_array.chunk_size = Size(0)
        self.assertEqual(raid_array.chunk_size, mdraid.MD_CHUNK_SIZE)

        with six.assertRaisesRegex(self, ValueError, "new chunk size must be of type Size"):
            raid_array.chunk_size = 1

        with six.assertRaisesRegex(self, ValueError, "new chunk size must be multiple of 4 KiB"):
            raid_array.chunk_size = Size("5 KiB")

        with six.assertRaisesRegex(self, ValueError, "specifying chunk size is not allowed for raid1"):
            MDRaidArrayDevice(name="raid", level="raid1", member_devices=2,
                              total_devices=2, parents=[member1, member2],
                              chunk_size=Size("1024 KiB"))

        raid_array = MDRaidArrayDevice(name="raid", level="raid1", member_devices=2,
                                       total_devices=2, parents=[member1, member2])

        with six.assertRaisesRegex(self, ValueError, "specifying chunk size is not allowed for raid1"):
            raid_array.chunk_size = Size("512 KiB")
