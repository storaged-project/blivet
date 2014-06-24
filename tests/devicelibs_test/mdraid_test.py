#!/usr/bin/python
import unittest
import time
import uuid

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


class MDRaidAsRootTestCase(loopbackedtestcase.LoopBackedTestCase):

    names_0 = [
      'DEVICE',
      'MD_DEVICES',
      'MD_EVENTS',
      'MD_LEVEL',
      'MD_UPDATE_TIME',
      'MD_UUID'
    ]

    names_1 = [
       'DEVICE',
       'MD_ARRAY_SIZE',
       'MD_DEV_UUID',
       'MD_DEVICES',
       'MD_EVENTS',
       'MD_LEVEL',
       'MD_METADATA',
       'MD_NAME',
       'MD_UPDATE_TIME',
       'MD_UUID'
    ]

    names_container = [
       'MD_DEVICES',
       'MD_LEVEL',
       'MD_METADATA',
       'MD_UUID'
    ]

    def __init__(self, methodName='runTest'):
        """Set up the structure of the mdraid array."""
        super(MDRaidAsRootTestCase, self).__init__(methodName=methodName)
        self._dev_name = "/dev/md0"

    def tearDown(self):
        try:
            mdraid.mddeactivate(self._dev_name)
            for dev in self.loopDevices:
                mdraid.mddestroy(dev)
        except MDRaidError:
            pass

        super(MDRaidAsRootTestCase, self).tearDown()

    def testMDExamineMDRaidArray(self):
        mdraid.mdcreate(self._dev_name, raid.RAID1, self.loopDevices)
        # wait for raid to settle
        time.sleep(2)

        # examining the array itself yield no data
        info = mdraid.mdexamine(self._dev_name)
        self.assertEqual(info, {})

    def testMDExamineNonMDRaid(self):
        # invoking mdexamine on a device that is not an array member yields {}
        info = mdraid.mdexamine(self.loopDevices[0])
        self.assertEqual(info, {})

    def _testMDExamine(self, names, metadataVersion=None, level=None):
        """ Test mdexamine for a specified metadataVersion.

            :param list names: mdexamine's expected list of names to return
            :param str metadataVersion: the metadata version for the array
            :param object level: any valid RAID level descriptor

            Verifies that:
              - exactly the predicted names are returned by mdexamine
              - RAID level and number of devices are correct
              - UUIDs have canonical form
        """
        level = mdraid.RAID_levels.raidLevel(level or raid.RAID1)
        mdraid.mdcreate(self._dev_name, level, self.loopDevices, metadataVer=metadataVersion)
        # wait for raid to settle
        time.sleep(2)

        info = mdraid.mdexamine(self.loopDevices[0])

        # info contains values for exactly names
        for n in names:
            self.assertIn(n, info, msg="name '%s' not in info" % n)

        for n in info.keys():
            self.assertIn(n, names, msg="unexpected name '%s' in info" % n)

        # check names with predictable values
        self.assertEqual(info['MD_DEVICES'], '2')
        self.assertEqual(info['MD_LEVEL'], str(level))

        # verify that uuids are in canonical form
        for name in (k for k in iter(info.keys()) if k.endswith('UUID')):
            self.assertTrue(str(uuid.UUID(info[name])) == info[name])

    def testMDExamineContainerDefault(self):
        self._testMDExamine(self.names_container, level="container")

    def testMDExamineDefault(self):
        self._testMDExamine(self.names_1)

    def testMDExamine0(self):
        self._testMDExamine(self.names_0, metadataVersion='0')

    def testMDExamine0_90(self):
        self._testMDExamine(self.names_0, metadataVersion='0.90')

    def testMDExamine1(self):
        self._testMDExamine(self.names_1, metadataVersion='1')

    def testMDExamine1_2(self):
        self._testMDExamine(self.names_1, metadataVersion='1.2')

    def testMDRaidAsRoot(self):
        ##
        ## mdcreate
        ##
        # pass
        self.assertEqual(mdraid.mdcreate(self._dev_name, raid.RAID1, self.loopDevices), None)

        # fail
        with self.assertRaises(MDRaidError):
            mdraid.mdcreate("/dev/md1", "raid1", ["/not/existing/dev0", "/not/existing/dev1"])

        ##
        ## mddeactivate
        ##
        # pass
        self.assertEqual(mdraid.mddeactivate(self._dev_name), None)

        # fail
        with self.assertRaises(MDRaidError):
            mdraid.mddeactivate("/not/existing/md")

        ##
        ## mdadd
        ##
        # pass
        # TODO

        # fail
        with self.assertRaises(MDRaidError):
            mdraid.mdadd(self._dev_name, "/not/existing/device")

        ##
        ## mdactivate
        ##
        with self.assertRaises(MDRaidError):
            mdraid.mdactivate("/not/existing/md", array_uuid=32)
        # requires uuid
        with self.assertRaises(MDRaidError):
            mdraid.mdactivate("/dev/md1")

        ##
        ## mddestroy
        ##
        # pass
        for dev in self.loopDevices:
            self.assertEqual(mdraid.mddestroy(dev), None)

        # pass
        # Note that these should fail because mdadm is unable to locate the
        # device. The mdadm Kill function does return 2, but the mdadm process
        # returns 0 for both tests.
        self.assertIsNone(mdraid.mddestroy(self._dev_name))
        self.assertIsNone(mdraid.mddestroy("/not/existing/device"))

if __name__ == "__main__":
    unittest.main()
