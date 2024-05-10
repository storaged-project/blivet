import unittest

import blivet.devicelibs.raid as raid
import blivet.errors as errors
from blivet.size import Size


class RaidTestCase(unittest.TestCase):

    def setUp(self):
        self.levels = raid.RAIDLevels(["raid0", "raid1", "raid4", "raid5", "raid6", "raid10", "striped"])
        self.levels_none = raid.RAIDLevels([])
        self.levels_some = raid.RAIDLevels(["mirror", 6])

    def test_raid(self):

        with self.assertRaisesRegex(TypeError, "Can't instantiate abstract class"):
            raid.ErsatzRAID()

        ##
        # get_min_members
        ##
        # pass
        self.assertEqual(raid.RAID0.min_members, 2)
        self.assertEqual(raid.RAID1.min_members, 2)
        self.assertEqual(raid.RAID5.min_members, 3)
        self.assertEqual(raid.RAID6.min_members, 4)
        self.assertEqual(raid.RAID10.min_members, 4)
        self.assertEqual(raid.Linear.min_members, 1)
        self.assertEqual(raid.Striped.min_members, 2)

        ##
        # get_max_spares
        ##
        # pass
        self.assertEqual(raid.RAID0.get_max_spares(5), 0)
        self.assertEqual(raid.RAID1.get_max_spares(5), 3)
        self.assertEqual(raid.RAID5.get_max_spares(5), 2)
        self.assertEqual(raid.RAID6.get_max_spares(5), 1)
        self.assertEqual(raid.RAID10.get_max_spares(5), 1)
        self.assertEqual(raid.Linear.get_max_spares(5), 4)
        self.assertEqual(raid.Striped.get_max_spares(5), 0)
        self.assertEqual(raid.Single.get_max_spares(5), 4)

        ##
        # raid_level
        ##
        # pass
        self.assertIs(self.levels.raid_level(10), raid.RAID10)
        self.assertIs(self.levels.raid_level("6"), raid.RAID6)
        self.assertIs(self.levels.raid_level("RAID5"), raid.RAID5)
        self.assertIs(self.levels.raid_level("raid4"), raid.RAID4)
        self.assertIs(self.levels.raid_level("mirror"), raid.RAID1)
        self.assertIs(self.levels.raid_level("stripe"), raid.RAID0)
        self.assertIs(self.levels.raid_level(raid.RAID0), raid.RAID0)
        self.assertIs(self.levels.raid_level(raid.Striped), raid.Striped)

        with self.assertRaises(errors.RaidError):
            self.levels.raid_level("bogus")
        with self.assertRaises(errors.RaidError):
            self.levels.raid_level(None)

        ##
        # get_max_spares
        ##
        self.assertEqual(raid.RAID0.get_max_spares(1000), 0)
        self.assertEqual(raid.RAID1.get_max_spares(2), 0)

        with self.assertRaises(errors.RaidError):
            raid.RAID0.get_max_spares(0)

        ##
        # get_base_member_size
        ##
        self.assertEqual(raid.RAID0.get_base_member_size(4, 2), 2)
        self.assertEqual(raid.RAID1.get_base_member_size(4, 2), 4)
        self.assertEqual(raid.RAID4.get_base_member_size(4, 4), 2)
        self.assertEqual(raid.RAID5.get_base_member_size(4, 4), 2)
        self.assertEqual(raid.RAID6.get_base_member_size(4, 4), 2)
        self.assertEqual(raid.RAID10.get_base_member_size(4, 4), 2)
        self.assertEqual(raid.RAID10.get_base_member_size(4, 5), 2)
        self.assertEqual(raid.RAID10.get_base_member_size(5, 5), 3)
        self.assertEqual(raid.Striped.get_base_member_size(4, 2), 2)

        with self.assertRaises(errors.RaidError):
            raid.RAID10.get_base_member_size(4, 3)
        with self.assertRaises(errors.RaidError):
            raid.RAID10.get_base_member_size(-4, 4)

        ##
        # get_net_array_size
        ##
        self.assertEqual(raid.RAID0.get_net_array_size(4, Size(2)), Size(8))
        self.assertEqual(raid.RAID1.get_net_array_size(4, Size(2)), Size(2))
        self.assertEqual(raid.RAID4.get_net_array_size(4, Size(2)), Size(6))
        self.assertEqual(raid.RAID5.get_net_array_size(4, Size(2)), Size(6))
        self.assertEqual(raid.RAID6.get_net_array_size(4, Size(2)), Size(4))
        self.assertEqual(raid.RAID10.get_net_array_size(4, Size(2)), Size(4))
        self.assertEqual(raid.RAID10.get_net_array_size(5, Size(2)), Size(4))
        self.assertEqual(raid.Striped.get_net_array_size(4, Size(2)), Size(8))

        ##
        # get_recommended_stride
        ##
        self.assertIsNone(raid.RAID1.get_recommended_stride(32))
        self.assertIsNone(raid.RAID6.get_recommended_stride(32))
        self.assertIsNone(raid.RAID10.get_recommended_stride(32))

        self.assertEqual(raid.RAID0.get_recommended_stride(4), 64)
        self.assertEqual(raid.RAID4.get_recommended_stride(4), 48)
        self.assertEqual(raid.RAID5.get_recommended_stride(4), 48)
        self.assertIsNone(raid.Linear.get_recommended_stride(4))
        self.assertEqual(raid.Striped.get_recommended_stride(4), 64)

        with self.assertRaises(errors.RaidError):
            raid.RAID10.get_recommended_stride(1)

        ##
        # size
        ##
        sizes = [Size("32MiB"), Size("128MiB"), Size("128MiB"), Size("64MiB")]
        for r in (l for l in raid.ALL_LEVELS if l not in (raid.Container, raid.Dup)):
            self.assertEqual(r.get_size(sizes, 4, Size("1MiB"), lambda x: Size(0)),
                             r.get_net_array_size(4, Size("32MiB")) if isinstance(r, raid.RAIDn) else sum(sizes, Size(0)))

        for r in (l for l in raid.ALL_LEVELS if l not in (raid.Container, raid.Dup)):
            self.assertEqual(r.get_size(sizes, 5, Size("1MiB"), lambda x: Size(0)),
                             r.get_net_array_size(5, Size("32MiB")) if isinstance(r, raid.RAIDn) else sum(sizes, Size(0)))

        for r in (l for l in raid.ALL_LEVELS if l not in (raid.Container, raid.Dup)):
            self.assertEqual(r.get_size(sizes, 4, Size("1MiB"), lambda x: Size("32MiB")),
                             Size(0) if isinstance(r, raid.RAIDn) else (sum(sizes, Size(0)) - 4 * Size("32MiB")))

        for r in (l for l in raid.ALL_LEVELS if l not in (raid.Container, raid.Dup)):
            if isinstance(r, raid.RAIDn):
                if r not in (raid.RAID1, raid.RAID10):
                    self.assertEqual(r.get_size(sizes, 4, Size("2MiB"), lambda x: Size("31MiB")), Size(0))
                else:
                    self.assertEqual(r.get_size(sizes, 4, Size("2MiB"), lambda x: Size("31MiB")), r.get_net_array_size(4, Size("1MiB")))
            else:
                self.assertEqual(r.get_size(sizes, 4, Size("2MiB"), lambda x: Size("31MiB")), sum(sizes, Size(0)) - 4 * Size("31MiB"))

        ##
        # names
        ##
        self.assertListEqual(raid.RAID0.names,
                             ["raid0", "stripe", "RAID0", "0", 0])
        self.assertListEqual(raid.RAID10.names,
                             ["raid10", "RAID10", "10", 10])

        ##
        # __init__
        ##
        with self.assertRaisesRegex(errors.RaidError, "invalid RAID level"):
            self.levels_none.raid_level(10)

        with self.assertRaisesRegex(errors.RaidError, "invalid RAID level"):
            self.levels_some.raid_level(10)

        with self.assertRaisesRegex(errors.RaidError, "invalid standard RAID level descriptor"):
            raid.RAIDLevels(["raid3.1415"])
