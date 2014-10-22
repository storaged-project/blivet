#!/usr/bin/python
import unittest
import time

import blivet.devicelibs.raid as raid
import blivet.devicelibs.mdraid as mdraid
from blivet.errors import MDRaidError
from blivet.size import Size

from tests import loopbackedtestcase

class MDRaidTestCase(unittest.TestCase):

    def testMDRaid(self):

        ##
        ## level lookup
        ##
        self.assertEqual(mdraid.RAID_levels.raidLevel("container").name, "container")
        self.assertEqual(mdraid.RAID_levels.raidLevel("stripe").name, "raid0")
        self.assertEqual(mdraid.RAID_levels.raidLevel("mirror").name, "raid1")
        self.assertEqual(mdraid.RAID_levels.raidLevel("4").name, "raid4")
        self.assertEqual(mdraid.RAID_levels.raidLevel(5).name, "raid5")
        self.assertEqual(mdraid.RAID_levels.raidLevel("RAID6").name, "raid6")
        self.assertEqual(mdraid.RAID_levels.raidLevel("raid10").name, "raid10")

        ##
        ## get_raid_superblock_size
        ##
        self.assertEqual(mdraid.get_raid_superblock_size(Size("256 GiB")),
                         Size("128 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size("128 GiB")),
                         Size("128 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size("64 GiB")),
                         Size("64 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size("63 GiB")),
                         Size("32 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size("10 GiB")),
                         Size("8 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size("1 GiB")),
                         Size("1 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size("1023 MiB")),
                         Size("1 MiB"))
        self.assertEqual(mdraid.get_raid_superblock_size(Size("512 MiB")),
                         Size("1 MiB"))

        self.assertEqual(mdraid.get_raid_superblock_size(Size("257 MiB"),
                                                         version="version"),
                         mdraid.MD_SUPERBLOCK_SIZE)

    def testMisc(self):
        """ Miscellaneous testing. """
        self.assertEqual(
           mdraid.mduuid_from_canonical('3386ff85-f501-2621-4a43-5f061eb47236'),
          '3386ff85:f5012621:4a435f06:1eb47236'
        )

class MDRaidAsRootTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='runTest', deviceSpec=None):
        super(MDRaidAsRootTestCase, self).__init__(methodName=methodName, deviceSpec=deviceSpec)
        self._dev_name = "/dev/md0"

    def tearDown(self):
        try:
            mdraid.mddeactivate(self._dev_name)
        except MDRaidError:
            pass
        for dev in self.loopDevices:
            try:
                mdraid.mdremove(self._dev_name, dev, fail=True)
            except MDRaidError:
                pass
            try:
                mdraid.mddestroy(dev)
            except MDRaidError:
                pass

        super(MDRaidAsRootTestCase, self).tearDown()

class RAID0Test(MDRaidAsRootTestCase):

    def __init__(self, methodName='runTest'):
        super(RAID0Test, self).__init__(methodName=methodName, deviceSpec=[102400, 102400, 102400])

    def testGrow(self):
        self.assertIsNone(mdraid.mdcreate(self._dev_name, raid.RAID0, self.loopDevices[:2]))
        time.sleep(2) # wait for raid to settle

        # it is not possible to add a managed device to a non-redundant array,
        # but it can be grown, by specifying the desired number of members
        self.assertIsNone(mdraid.mdadd(self._dev_name, self.loopDevices[2], raid_devices=3))

    def testGrowRAID1(self):
        self.assertIsNone(mdraid.mdcreate(self._dev_name, raid.RAID1, self.loopDevices[:2]))
        time.sleep(2) # wait for raid to settle

        # a RAID1 array can be grown as well as a RAID0 array
        self.assertIsNone(mdraid.mdadd(self._dev_name, self.loopDevices[2], raid_devices=3))

    def testGrowTooBig(self):
        self.assertIsNone(mdraid.mdcreate(self._dev_name, raid.RAID0, self.loopDevices[:2]))
        time.sleep(2) # wait for raid to settle

        # if more devices are specified than are available after the
        # addition an error is raised
        with self.assertRaises(MDRaidError):
            mdraid.mdadd(self._dev_name, self.loopDevices[2], raid_devices=4)

    def testGrowSmaller(self):
        self.assertIsNone(mdraid.mdcreate(self._dev_name, raid.RAID0, self.loopDevices[:2]))
        time.sleep(2) # wait for raid to settle

        # it is ok to grow an array smaller than its devices
        self.assertIsNone(mdraid.mdadd(self._dev_name, self.loopDevices[2], raid_devices=2))

    def testGrowSimple(self):
        self.assertIsNone(mdraid.mdcreate(self._dev_name, raid.RAID0, self.loopDevices[:2]))
        time.sleep(2) # wait for raid to settle

        # try to simply add a device and things go wrong
        with self.assertRaises(MDRaidError):
            mdraid.mdadd(self._dev_name, self.loopDevices[2])

class SimpleRaidTest(MDRaidAsRootTestCase):

    def __init__(self, methodName='runTest'):
        super(SimpleRaidTest, self).__init__(methodName=methodName, deviceSpec=[102400, 102400, 102400])
        self.longMessage = True

    def testMDRaidAsRoot(self):
        ##
        ## mdcreate
        ##
        # pass
        self.assertIsNone(mdraid.mdcreate(self._dev_name, raid.RAID1, self.loopDevices))
        time.sleep(2) # wait for raid to settle

        # fail
        with self.assertRaises(MDRaidError):
            mdraid.mdcreate("/dev/md1", "raid1", ["/not/existing/dev0", "/not/existing/dev1"])

        # fail
        with self.assertRaises(MDRaidError):
            mdraid.mdadd(self._dev_name, "/not/existing/device")
        time.sleep(2) # wait for raid to settle

        # removing and re-adding a component device should succeed
        self.assertIsNone(mdraid.mdremove(self._dev_name, self.loopDevices[2], fail=True))
        time.sleep(2) # wait for raid to settle
        self.assertIsNone(mdraid.mdadd(self._dev_name, self.loopDevices[2]))
        time.sleep(3) # wait for raid to settle

        # it is not possible to add a device that has already been added
        with self.assertRaises(MDRaidError):
            mdraid.mdadd(self._dev_name, self.loopDevices[2])

        self.assertIsNone(mdraid.mdremove(self._dev_name, self.loopDevices[2], fail=True))
        time.sleep(2) # wait for raid to settle

        # can not re-add in incremental mode because the array is active
        with self.assertRaises(MDRaidError):
            mdraid.mdnominate(self.loopDevices[2])

        info_pre = mdraid.mddetail(self._dev_name)

        ##
        ## mddeactivate
        ##
        # pass
        self.assertIsNone(mdraid.mddeactivate(self._dev_name))

        # once the array is deactivated, can add in incremental mode
        self.assertIsNone(mdraid.mdnominate(self.loopDevices[2]))

        # but cannot re-add twice
        with self.assertRaises(MDRaidError):
            mdraid.mdnominate(self.loopDevices[2])

        # fail
        with self.assertRaises(MDRaidError):
            mdraid.mddeactivate("/not/existing/md")


        ##
        ## mdactivate
        ##
        with self.assertRaises(MDRaidError):
            mdraid.mdactivate("/not/existing/md", array_uuid=32)
        # requires uuid
        with self.assertRaises(MDRaidError):
            mdraid.mdactivate("/dev/md1")

        self.assertIsNone(mdraid.mdactivate(self._dev_name, array_uuid=mdraid.mduuid_from_canonical(info_pre['UUID'])))
        time.sleep(2)
        info_post = mdraid.mddetail(self._dev_name)

        # the array should remain mostly the same across activations
        changeable_values = (
           'ACTIVE DEVICES',
           'STATE',
           'TOTAL DEVICES',
           'WORKING DEVICES'
        )
        for k in (k for k in info_pre.keys() if k not in changeable_values):
            self.assertEqual(info_pre[k], info_post[k], msg="key: %s" % k)

        # deactivating the array one more time
        self.assertIsNone(mdraid.mddeactivate(self._dev_name))

        ##
        ## mddestroy
        ##
        # pass
        for dev in self.loopDevices:
            self.assertIsNone(mdraid.mddestroy(dev))

        # pass
        # Note that these should fail because mdadm is unable to locate the
        # device. The mdadm Kill function does return 2, but the mdadm process
        # returns 0 for both tests.
        self.assertIsNone(mdraid.mddestroy(self._dev_name))
        self.assertIsNone(mdraid.mddestroy("/not/existing/device"))

if __name__ == "__main__":
    unittest.main()
