import unittest

import blivet.devicelibs.mdraid as mdraid

class MDRaidTestCase(unittest.TestCase):

    def testMDRaid(self):

        ##
        ## level lookup
        ##
        self.assertEqual(mdraid.RAID_levels.raidLevel("stripe").name, "raid0")
        self.assertEqual(mdraid.RAID_levels.raidLevel("mirror").name, "raid1")
        self.assertEqual(mdraid.RAID_levels.raidLevel("4").name, "raid4")
        self.assertEqual(mdraid.RAID_levels.raidLevel(5).name, "raid5")
        self.assertEqual(mdraid.RAID_levels.raidLevel("RAID6").name, "raid6")
        self.assertEqual(mdraid.RAID_levels.raidLevel("raid10").name, "raid10")

