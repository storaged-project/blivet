#!/usr/bin/python
import os
import unittest
import time

import blivet.devicelibs.mdraid as mdraid
from blivet.errors import MDRaidError
from blivet.size import Size

from tests.devicelibs_test import baseclass

class MDRaidTestCase(unittest.TestCase):

    def testMDRaid(self):

        ##
        ## getRaidLevel
        ##
        self.assertEqual(mdraid.getRaidLevel("container").name, "container")
        self.assertEqual(mdraid.getRaidLevel("stripe").name, "raid0")
        self.assertEqual(mdraid.getRaidLevel("mirror").name, "raid1")
        self.assertEqual(mdraid.getRaidLevel("4").name, "raid4")
        self.assertEqual(mdraid.getRaidLevel(5).name, "raid5")
        self.assertEqual(mdraid.getRaidLevel("RAID6").name, "raid6")
        self.assertEqual(mdraid.getRaidLevel("raid10").name, "raid10")

        ##
        ## get_raid_superblock_size
        ##
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="256 GiB")),
                         Size(spec="128 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="128 GiB")),
                         Size(spec="128 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="64 GiB")),
                         Size(spec="64 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="63 GiB")),
                         Size(spec="32 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="10 GiB")),
                         Size(spec="8 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="1 GiB")),
                         Size(spec="1 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="1023 MiB")),
                         Size(spec="1 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="512 MiB")),
                         Size(spec="1 MiB"))

        self.assertEqual(mdraid.get_raid_superblock_size(Size(spec="257 MiB"),
                                                         version="version"),
                         mdraid.MD_SUPERBLOCK_SIZE)


class MDRaidAsRootTestCase(baseclass.DevicelibsTestCase):

    def __init__(self, *args, **kwargs):
        """Set up the structure of the mdraid array."""
        super(MDRaidAsRootTestCase, self).__init__(*args, **kwargs)
        self._dev_name = "/dev/md0"

    def tearDown(self):
        try:
            mdraid.mddeactivate(self._dev_name)
            for dev in self._loopMap.values():
                mdraid.mddestroy(dev)
        except MDRaidError:
            pass

        super(MDRaidAsRootTestCase, self).tearDown()

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testMDRaidAsRoot(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        ##
        ## mdcreate
        ##
        # pass
        self.assertEqual(mdraid.mdcreate(self._dev_name, 1, [_LOOP_DEV0, _LOOP_DEV1]), None)
        # wait for raid to settle
        time.sleep(2)

        # fail
        self.assertRaises(MDRaidError, mdraid.mdcreate, "/dev/md1", 1, ["/not/existing/dev0", "/not/existing/dev1"])

        ##
        ## mddeactivate
        ##
        # pass
        self.assertEqual(mdraid.mddeactivate(self._dev_name), None)

        # fail
        self.assertRaises(MDRaidError, mdraid.mddeactivate, "/not/existing/md")

        ##
        ## mdadd
        ##
        # pass
        # TODO

        # fail
        self.assertRaises(MDRaidError, mdraid.mdadd, self._dev_name, "/not/existing/device")

        ##
        ## mdactivate
        ##
        self.assertRaises(MDRaidError, mdraid.mdactivate, "/not/existing/md", uuid=32)
        # requires uuid
        self.assertRaises(MDRaidError, mdraid.mdactivate, "/dev/md1")

        ##
        ## mddestroy
        ##
        # pass
        self.assertEqual(mdraid.mddestroy(_LOOP_DEV0), None)
        self.assertEqual(mdraid.mddestroy(_LOOP_DEV1), None)

        # pass
        # Note that these should fail because mdadm is unable to locate the
        # device. The mdadm Kill function does return 2, but the mdadm process
        # returns 0 for both tests.
        self.assertIsNone(mdraid.mddestroy(self._dev_name))
        self.assertIsNone(mdraid.mddestroy("/not/existing/device"))


def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(MDRaidTestCase)
    suite2 = unittest.TestLoader().loadTestsFromTestCase(MDRaidAsRootTestCase)
    return unittest.TestSuite([suite1, suite2])


if __name__ == "__main__":
    unittest.main()
