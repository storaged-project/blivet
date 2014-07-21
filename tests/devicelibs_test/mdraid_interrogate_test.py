#!/usr/bin/python
import unittest
import time
import uuid

import blivet.devicelibs.raid as raid
import blivet.devicelibs.mdraid as mdraid

from . import mdraid_test
from blivet.errors import MDRaidError

class MDRaidInterrogateTestCase(mdraid_test.MDRaidAsRootTestCase):

    def _matchNames(self, found, expected, transient=None):
        """ Match names found against expected names.

            :param found: a list of names found in result
            :type found: list of str
            :param expected: a list of expected names
            :type expected: list of str
            :param transient: a list of names that only sometimes appear
            :type transient: list of str
        """
        transient = transient or []

        for n in (n for n in expected if n not in transient):
            self.assertIn(n, found, msg="name '%s' not in info" % n)

        for n in (n for n in found if n not in transient):
            self.assertIn(n, expected, msg="unexpected name '%s' in info" % n)


class MDExamineTestCase(MDRaidInterrogateTestCase):

    def __init__(self, methodName='runTest'):
        super(MDExamineTestCase, self).__init__(methodName=methodName, deviceSpec=[102400, 102400, 102400])

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

    def testMDExamineMDRaidArray(self):
        mdraid.mdcreate(self._dev_name, raid.RAID1, self.loopDevices)
        time.sleep(2) # wait for raid to settle

        # invoking mdexamine on the array itself raises an error
        with self.assertRaisesRegexp(MDRaidError, "mdexamine failed"):
            mdraid.mdexamine(self._dev_name)

    def testMDExamineNonMDRaid(self):
        # invoking mdexamine on any non-array member raises an error
        with self.assertRaisesRegexp(MDRaidError, "mdexamine failed"):
            mdraid.mdexamine(self.loopDevices[0])

    def _testMDExamine(self, names, metadataVersion=None, level=None, spares=0):
        """ Test mdexamine for a specified metadataVersion.

            :param list names: mdexamine's expected list of names to return
            :param str metadataVersion: the metadata version for the array
            :param object level: any valid RAID level descriptor
            :param int spares: the number of spares in this array

            Verifies that:
              - exactly the predicted names are returned by mdexamine
              - RAID level and number of devices are correct
              - UUIDs have canonical form
        """
        level = mdraid.RAID_levels.raidLevel(level or raid.RAID1)
        mdraid.mdcreate(self._dev_name, level, self.loopDevices, metadataVer=metadataVersion, spares=spares)
        time.sleep(2) # wait for raid to settle

        info = mdraid.mdexamine(self.loopDevices[0])

        self._matchNames(info.keys(), names)

        # check names with predictable values
        self.assertEqual(info['MD_DEVICES'], str(len(self.loopDevices) - spares))
        self.assertEqual(info['MD_LEVEL'], str(level))

        # verify that uuids are in canonical form
        for name in (k for k in iter(info.keys()) if k.endswith('UUID')):
            self.assertEqual(str(uuid.UUID(info[name])), info[name])

    def testMDExamineContainerDefault(self):
        self._testMDExamine(self.names_container, level="container")

    def testMDExamineDefault(self):
        self._testMDExamine(self.names_1)

    def testMDExamineSpares(self):
        self._testMDExamine(self.names_1, spares=1)

    def testMDExamine0(self):
        self._testMDExamine(self.names_0, metadataVersion='0')

    def testMDExamine0_90(self):
        self._testMDExamine(self.names_0, metadataVersion='0.90')

    def testMDExamine1(self):
        self._testMDExamine(self.names_1, metadataVersion='1')

    def testMDExamine1_2(self):
        self._testMDExamine(self.names_1, metadataVersion='1.2')

class MDDetailTestCase(MDRaidInterrogateTestCase):

    def __init__(self, methodName='runTest'):
        super(MDDetailTestCase, self).__init__(methodName=methodName, deviceSpec=[102400, 102400, 102400])

    names = [
        'ACTIVE DEVICES',
        'ARRAY SIZE',
        'CREATION TIME',
        'EVENTS',
        'FAILED DEVICES',
        'NAME',
        'PERSISTENCE',
        'RAID DEVICES',
        'RAID LEVEL',
        'RESYNC STATUS',
        'SPARE DEVICES',
        'STATE',
        'TOTAL DEVICES',
        'UPDATE TIME',
        'USED DEV SIZE',
        'UUID',
        'VERSION',
        'WORKING DEVICES'
    ]

    names_0 = [
        'ACTIVE DEVICES',
        'ARRAY SIZE',
        'CREATION TIME',
        'EVENTS',
        'FAILED DEVICES',
        'PERSISTENCE',
        'PREFERRED MINOR',
        'RAID DEVICES',
        'RAID LEVEL',
        'RESYNC STATUS',
        'SPARE DEVICES',
        'STATE',
        'TOTAL DEVICES',
        'UPDATE TIME',
        'USED DEV SIZE',
        'UUID',
        'VERSION',
        'WORKING DEVICES'
    ]

    names_container = [
        'RAID LEVEL',
        'WORKING DEVICES',
        'VERSION',
        'TOTAL DEVICES'
    ]

    def _testMDDetail(self, names, metadataVersion=None, level=None, spares=0):
        """ Test mddetail for a specified metadataVersion.

            :param list names: mdexamine's expected list of names to return
            :param str metadataVersion: the metadata version for the array
            :param object level: any valid RAID level descriptor
            :param int spares: the number of spares for this array

            Verifies that:
              - exactly the predicted names are returned by mddetail
              - UUIDs have canonical form
        """
        level = mdraid.RAID_levels.raidLevel(level) if level is not None else raid.RAID1

        mdraid.mdcreate(self._dev_name, level, self.loopDevices, metadataVer=metadataVersion, spares=spares)
        time.sleep(2) # wait for raid to settle

        info = mdraid.mddetail(self._dev_name)

        # info contains values for exactly names
        self._matchNames(info.keys(), names, ['RESYNC STATUS'])

        # check names with predictable values
        self.assertEqual(info['RAID LEVEL'], str(level))
        self.assertEqual(info['TOTAL DEVICES'], str(len(self.loopDevices)))
        self.assertEqual(info['WORKING DEVICES'], str(len(self.loopDevices)))

        if level is not raid.Container:
            self.assertEqual(info['ACTIVE DEVICES'], str(len(self.loopDevices) - spares))
            self.assertEqual(info['FAILED DEVICES'], '0')
            self.assertEqual(info['SPARE DEVICES'], str(spares))

            # verify that uuid is in canonical form
            self.assertEqual(str(uuid.UUID(info['UUID'])), info['UUID'])

    def testMDDetail(self):
        self._testMDDetail(self.names)

    def testMDDetailSpares(self):
        self._testMDDetail(self.names, spares=1)

    def testMDDetail0_90(self):
        self._testMDDetail(self.names_0, metadataVersion='0.90')

    def testMDDetailMDDevice(self):
        mdraid.mdcreate(self._dev_name, raid.RAID1, self.loopDevices)
        time.sleep(2) # wait for raid to settle

        # invoking mddetail on a device raises an error
        with self.assertRaisesRegexp(MDRaidError, "mddetail failed"):
            mdraid.mddetail(self.loopDevices[0])

    def testMDDetailContainerDefault(self):
        self._testMDDetail(self.names_container, level="container")

if __name__ == "__main__":
    unittest.main()
