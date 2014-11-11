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

class TestCaseFactory(object):

    @staticmethod
    def _minMembersForCreation(level):
        min_members = level.min_members
        return min_members if min_members > 1 else 2

class JustAddTestCaseFactory(TestCaseFactory):

    @staticmethod
    def makeClass(name, level):

        def __init__(self, methodName='runTest'):
            super(self.__class__, self).__init__(methodName=methodName, deviceSpec=[Size("100 MiB") for _ in range(5)])
            self.longMessage = True

        def testAdd(self):
            """ Tests adding, not growing, a device. """
            initial_members = TestCaseFactory._minMembersForCreation(level)
            self.assertIsNone(mdraid.mdcreate(self._dev_name, level, self.loopDevices[:initial_members]))
            time.sleep(2) # wait for raid to settle

            new_member = self.loopDevices[initial_members]

            if level is raid.Container or level.has_redundancy():
                info_pre = mdraid.mddetail(self._dev_name)
                self.assertIsNone(mdraid.mdadd(self._dev_name, new_member))
                info_post = mdraid.mddetail(self._dev_name)
                keys = ['TOTAL DEVICES', 'WORKING DEVICES']
                for k in keys:
                    self.assertEqual(int(info_pre[k]) + 1, int(info_post[k]), msg="key: %s" % k)
                if level is not raid.Container:
                    keys = ['ACTIVE DEVICES', 'SPARE DEVICES']
                    self.assertEqual(sum(int(info_pre[k]) for k in keys) + 1,
                       sum(int(info_post[k]) for k in keys))
                    self.assertEqual(info_pre['RAID DEVICES'], info_post['RAID DEVICES'])
                    dev_info = mdraid.mdexamine(new_member)
                    self.assertEqual(info_post['UUID'], dev_info['MD_UUID'])
            else:
                with self.assertRaises(MDRaidError):
                    mdraid.mdadd(self._dev_name, new_member)

        return type(
           name,
           (MDRaidAsRootTestCase,),
           {
              '__init__': __init__,
              'testAdd': testAdd,
           })

class GrowTestCaseFactory(object):

    @staticmethod
    def makeClass(name, level):

        def __init__(self, methodName='runTest'):
            super(self.__class__, self).__init__(methodName=methodName, deviceSpec=[Size("100 MiB") for _ in range(6)])
            self.longMessage = True

        def testGrow(self):
            """ Tests growing a device by exactly 1. """
            initial_members = TestCaseFactory._minMembersForCreation(level)
            self.assertIsNone(mdraid.mdcreate(self._dev_name, level, self.loopDevices[:initial_members]))
            time.sleep(3) # wait for raid to settle

            new_member = self.loopDevices[initial_members]
            info_pre = mdraid.mddetail(self._dev_name)

            # for linear RAID the new number of devices must not be specified
            # for all other levels the new number of devices must be specified
            if level is raid.Linear:
                with self.assertRaises(MDRaidError):
                    mdraid.mdadd(self._dev_name, new_member, grow_mode=True, raid_devices=initial_members + 1)
                self.assertIsNone(mdraid.mdadd(self._dev_name, new_member, grow_mode=True))
            else:
                with self.assertRaises(MDRaidError):
                    mdraid.mdadd(self._dev_name, new_member, grow_mode=True)
                self.assertIsNone(mdraid.mdadd(self._dev_name, new_member, grow_mode=True, raid_devices=initial_members + 1))

            info_post = mdraid.mddetail(self._dev_name)
            keys = ['RAID DEVICES', 'TOTAL DEVICES', 'WORKING DEVICES']
            for k in keys:
                self.assertEqual(int(info_pre[k]) + 1, int(info_post[k]), msg="key: %s" % k)
            if level is not raid.Container:
                keys = ['ACTIVE DEVICES', 'SPARE DEVICES']
                self.assertEqual(sum(int(info_pre[k]) for k in keys) + 1,
                   sum(int(info_post[k]) for k in keys),
                   msg="%s" % " + ".join(keys))
                dev_info = mdraid.mdexamine(new_member)
                self.assertEqual(info_post['UUID'], dev_info['MD_UUID'], msg="key: UUID")

        def testGrowBig(self):
            """ Test growing a device beyond its size. """
            initial_members = TestCaseFactory._minMembersForCreation(level)
            self.assertIsNone(mdraid.mdcreate(self._dev_name, level, self.loopDevices[:initial_members]))
            time.sleep(3) # wait for raid to settle

            new_member = self.loopDevices[initial_members]
            if level is raid.Linear:
                self.assertIsNone(mdraid.mdadd(self._dev_name, new_member, grow_mode=True))
            else:
                with self.assertRaises(MDRaidError):
                    mdraid.mdadd(self._dev_name, new_member, grow_mode=True, raid_devices=initial_members + 2)

        def testGrowSmall(self):
            """ Test decreasing size of device. """
            initial_members = TestCaseFactory._minMembersForCreation(level) + 1
            self.assertIsNone(mdraid.mdcreate(self._dev_name, level, self.loopDevices[:initial_members]))
            time.sleep(2) # wait for raid to settle

            new_member = self.loopDevices[initial_members]

            with self.assertRaises(MDRaidError):
                mdraid.mdadd(self._dev_name, new_member, grow_mode=True, raid_devices=initial_members - 1)

        return type(
           name,
           (MDRaidAsRootTestCase,),
           {
              '__init__': __init__,
              'testGrow': testGrow,
              'testGrowBig' : testGrowBig,
              'testGrowSmall': testGrowSmall
           })


# make some test cases for every RAID level
levels = sorted(mdraid.RAID_levels, cmp=lambda x, y: cmp(x.name, y.name))
for l in levels:
    classname = "%sJustAddTestCase" % l
    globals()[classname] = JustAddTestCaseFactory.makeClass(classname, l)

    if l is not raid.Container:
        classname = "%sGrowTestCase" % l
        globals()[classname] = GrowTestCaseFactory.makeClass(classname, l)

@unittest.skip("temporarily disabled due to bug 1162823")
class SimpleRaidTest(MDRaidAsRootTestCase):

    def __init__(self, methodName='runTest'):
        super(SimpleRaidTest, self).__init__(methodName=methodName, deviceSpec=[Size("100 MiB") for _ in range(3)])
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
