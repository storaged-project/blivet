import unittest
from unittest.mock import patch

from blivet.devices import DiskDevice
from blivet.devicelibs import disk as disklib
from blivet.devicelibs import raid
from blivet.size import Size


class DiskDeviceRAIDPropertiesTestCase(unittest.TestCase):
    def test_disk_raid_properties(self):
        volumes = {"/dev/test1": disklib.LSMInfo("Test 1",
                                                 ["/dev/test1"],
                                                 raid.get_raid_level("raid0"),
                                                 Size("512 KiB"),
                                                 4),
                   "/dev/test2": disklib.LSMInfo("Test 2",
                                                 ["/dev/test2"],
                                                 None,
                                                 None,
                                                 None)}

        test1 = DiskDevice("test1")
        test2 = DiskDevice("test2")
        test3 = DiskDevice("test3")
        # DiskDevice attributes should have the same values as the corresponding LSMInfo, or None
        with patch("blivet.devices.disk.disklib") as _disklib:
            _disklib.volumes = volumes

            test1_volume = volumes[test1.path]
            self.assertEqual(test1._volume, volumes[test1.path])
            self.assertEqual(test1.raid_system, test1_volume.system)
            self.assertEqual(test1.raid_level, test1_volume.raid_type)
            self.assertEqual(test1.raid_stripe_size, test1_volume.raid_stripe_size)
            self.assertEqual(test1.raid_disk_count, test1_volume.raid_disk_count)

            test2_volume = volumes[test2.path]
            self.assertEqual(test2._volume, volumes[test2.path])
            self.assertEqual(test2._volume, test2_volume)
            self.assertEqual(test2.raid_system, test2_volume.system)
            self.assertEqual(test2.raid_level, test2_volume.raid_type)
            self.assertEqual(test2.raid_stripe_size, test2_volume.raid_stripe_size)
            self.assertEqual(test2.raid_disk_count, test2_volume.raid_disk_count)

            self.assertIsNone(test3._volume)
            self.assertIsNone(test3.raid_system)
            self.assertIsNone(test3.raid_level)
            self.assertIsNone(test3.raid_stripe_size)
            self.assertIsNone(test3.raid_disk_count)
