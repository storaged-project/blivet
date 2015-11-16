import unittest

import blivet.devicelibs.mdraid as mdraid


class MDRaidTestCase(unittest.TestCase):

    def test_mdraid(self):

        ##
        # level lookup
        ##
        self.assertEqual(mdraid.raid_levels.raid_level("stripe").name, "raid0")
        self.assertEqual(mdraid.raid_levels.raid_level("mirror").name, "raid1")
        self.assertEqual(mdraid.raid_levels.raid_level("4").name, "raid4")
        self.assertEqual(mdraid.raid_levels.raid_level(5).name, "raid5")
        self.assertEqual(mdraid.raid_levels.raid_level("RAID6").name, "raid6")
        self.assertEqual(mdraid.raid_levels.raid_level("raid10").name, "raid10")
