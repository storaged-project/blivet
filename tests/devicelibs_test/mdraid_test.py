#!/usr/bin/python
import baseclass
import os
import unittest
import time

import blivet.devicelibs.mdraid as mdraid
import blivet.errors as errors

class MDRaidTestCase(unittest.TestCase):

    def testMDRaid(self):

        ##
        ## get_raid_min_members
        ##
        # pass
        self.assertEqual(mdraid.get_raid_min_members(mdraid.RAID0), 2)
        self.assertEqual(mdraid.get_raid_min_members(mdraid.RAID1), 2)
        self.assertEqual(mdraid.get_raid_min_members(mdraid.RAID5), 3)
        self.assertEqual(mdraid.get_raid_min_members(mdraid.RAID6), 4)
        self.assertEqual(mdraid.get_raid_min_members(mdraid.RAID10), 4)

        # fail
        # unsupported raid
        self.assertRaisesRegexp(errors.MDRaidError,
           "invalid raid level",
           mdraid.get_raid_min_members, 8)

        ##
        ## get_raid_max_spares
        ##
        # pass
        self.assertEqual(mdraid.get_raid_max_spares(mdraid.RAID0, 5), 0)
        self.assertEqual(mdraid.get_raid_max_spares(mdraid.RAID1, 5), 3)
        self.assertEqual(mdraid.get_raid_max_spares(mdraid.RAID5, 5), 2)
        self.assertEqual(mdraid.get_raid_max_spares(mdraid.RAID6, 5), 1)
        self.assertEqual(mdraid.get_raid_max_spares(mdraid.RAID10, 5), 1)

        # fail
        # unsupported raid
        self.assertRaisesRegexp(errors.MDRaidError,
           "invalid raid level",
           mdraid.get_raid_max_spares, 8, 5)

        ##
        ## get_raid_superblock_size
        ##
        self.assertEqual(mdraid.get_raid_superblock_size(256 * 1024), 128)
        self.assertEqual(mdraid.get_raid_superblock_size(128 * 1024), 128)
        self.assertEqual(mdraid.get_raid_superblock_size(64 * 1024), 64)
        self.assertEqual(mdraid.get_raid_superblock_size(63 * 1024), 32)
        self.assertEqual(mdraid.get_raid_superblock_size(10 * 1024), 8)
        self.assertEqual(mdraid.get_raid_superblock_size(1024), 1)
        self.assertEqual(mdraid.get_raid_superblock_size(1023), 0)
        self.assertEqual(mdraid.get_raid_superblock_size(512), 0)

        self.assertEqual(mdraid.get_raid_superblock_size(257, "version"),
           mdraid.MD_SUPERBLOCK_SIZE)

        ##
        ## get_member_space
        ##
        self.assertEqual(mdraid.get_member_space(1024, 2, 0), 513 * 2)
        self.assertEqual(mdraid.get_member_space(1024, 2, 1), 1025 * 2)
        self.assertEqual(mdraid.get_member_space(1024, 3, 4), 513 * 3)
        self.assertEqual(mdraid.get_member_space(1024, 3, 5), 513 * 3)
        self.assertEqual(mdraid.get_member_space(1024, 4, 6), 513 * 4)
        self.assertEqual(mdraid.get_member_space(1024, 5, 10), 513 * 5)

        # fail
        # unsupported raid
        self.assertRaisesRegexp(errors.MDRaidError,
           "invalid raid level",
           mdraid.get_member_space, 1024, 0)

        # fail
        # not enough disks
        self.assertRaisesRegexp(errors.MDRaidError,
           "requires at least",
           mdraid.get_member_space, 1024, 0, 0)

        ##
        ## isRaid
        ##
        self.assertTrue(mdraid.isRaid(0, "RAID0"))
        self.assertFalse(mdraid.isRaid(6, "RAID0"))

        # fail
        # invalid raid
        self.assertRaisesRegexp(errors.MDRaidError,
           "invalid raid level",
           mdraid.isRaid, 7, "RAID")

        ##
        ## raidLevel
        ##
        self.assertEqual(mdraid.raidLevel("RAID0"), 0)

        # fail
        # invalid raid
        self.assertRaisesRegexp(errors.MDRaidError,
           "invalid raid level",
           mdraid.raidLevel, "RAID")

        ##
        ## raidLevelString
        ##
        self.assertEqual(mdraid.raidLevelString(0), "raid0")

        # fail
        # invalid constant
        self.assertRaisesRegexp(errors.MDRaidError,
           "invalid raid level constant",
          mdraid.raidLevelString, -1)

class MDRaidAsRootTestCase(baseclass.DevicelibsTestCase):

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testMDRaidAsRoot(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        ##
        ## mdcreate
        ##
        # pass
        self.assertEqual(mdraid.mdcreate("/dev/md0", 1, [_LOOP_DEV0, _LOOP_DEV1]), None)
        # wait for raid to settle
        time.sleep(2)

        # fail
        self.assertRaises(mdraid.MDRaidError, mdraid.mdcreate, "/dev/md1", 1, ["/not/existing/dev0", "/not/existing/dev1"])

        ##
        ## mddeactivate
        ##
        # pass
        self.assertEqual(mdraid.mddeactivate("/dev/md0"), None)

        # fail
        self.assertRaises(mdraid.MDRaidError, mdraid.mddeactivate, "/not/existing/md")

        ##
        ## mdadd
        ##
        # pass
        # TODO

        # fail
        self.assertRaises(mdraid.MDRaidError, mdraid.mdadd, "/not/existing/device")

        ##
        ## mdactivate
        ##
        # pass
        self.assertEqual(mdraid.mdactivate("/dev/md0", [_LOOP_DEV0, _LOOP_DEV1], super_minor=0), None)
        # wait for raid to settle
        time.sleep(2)

        # fail
        self.assertRaises(mdraid.MDRaidError, mdraid.mdactivate, "/not/existing/md", super_minor=1)
        # requires super_minor or uuid
        self.assertRaises(ValueError, mdraid.mdactivate, "/dev/md1")

        ##
        ## mddestroy
        ##
        # pass
        # deactivate first
        self.assertEqual(mdraid.mddeactivate("/dev/md0"), None)

        self.assertEqual(mdraid.mddestroy(_LOOP_DEV0), None)
        self.assertEqual(mdraid.mddestroy(_LOOP_DEV1), None)

        # fail
        # not a component
        self.assertRaises(mdraid.MDRaidError, mdraid.mddestroy, "/dev/md0")
        self.assertRaises(mdraid.MDRaidError, mdraid.mddestroy, "/not/existing/device")


def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(MDRaidTestCase)
    suite2 = unittest.TestLoader().loadTestsFromTestCase(MDRaidAsRootTestCase)
    return unittest.TestSuite([suite1, suite2])


if __name__ == "__main__":
    unittest.main()
