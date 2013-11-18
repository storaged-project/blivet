#!/usr/bin/python

import unittest

from mock import Mock

import blivet

from blivet.errors import DeviceError

from blivet.devices import Device
from blivet.devices import MDRaidArrayDevice
from blivet.devices import mdraid

class MDRaidArrayDeviceTestCase(unittest.TestCase):
    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or correct behavior. See the initial
       commit message for this file for further details.
    """

    def stateCheck(self, device, **kwargs):
        """Checks the current state of an mdraid device by means of its
           fields or properties.

           Every kwarg should be a key which is a field or property
           of an MDRaidArrayDevice and a value which is a function of
           two parameters and should call the appropriate assert* functions.
           These values override those in the state_functions dict.

           If the value is None, then the test starts the debugger instead.
        """
        self.longMessage = True
        state_functions = {
           "createBitmap" : lambda x,m: self.assertTrue(x, m),
           "currentSize" : lambda x, m: self.assertEqual(x, 0, m),
           "description" : lambda x, m: self.assertEqual(x, "MDRAID set (unknown level)", m),
           "devices" : lambda x, m: self.assertEqual(x, [], m),
           "exists" : self.assertFalse,
           "format" : self.assertIsNotNone,
           "formatArgs" : lambda x, m: self.assertEqual(x, [], m),
           "formatClass" : self.assertIsNotNone,
           "isDisk" : self.assertFalse,
           "level" : self.assertIsNone,
           "major" : lambda x, m: self.assertEqual(x, 0, m),
           "mediaPresent" : self.assertFalse,
           "metadataVersion" : lambda x, m: self.assertEqual(x, "default", m),
           "minor" : lambda x, m: self.assertEqual(x, 0, m),
           "parents" : lambda x, m: self.assertEqual(x, [], m),
           "partitionable" : self.assertFalse,
           "rawArraySize" : lambda x, m: self.assertEqual(x, 0, m),
           "size" : lambda x, m: self.assertEqual(x, 0, m),
           "smallestMember" : lambda x, m: self.assertIsNone(x, m),
           "spares" : lambda x, m: self.assertEqual(x, 0, m),
           "superBlockSize" : lambda x, m: self.assertEqual(x, 0, m),
           "sysfsPath" : lambda x, m: self.assertEqual(x, "", m),
           "uuid" : self.assertIsNone,
           "memberDevices" : lambda x, m: self.assertEqual(x, 0, m),
           "totalDevices" : lambda x, m: self.assertEqual(x, 0, m),
           "type" : lambda x, m: self.assertEqual(x, "mdarray", m) }
        for k,v in state_functions.items():
            if kwargs.has_key(k):
                key = kwargs[k]
                if key is None:
                    import pdb
                    pdb.set_trace()
                    getattr(device, k)
                else:
                    kwargs[k](getattr(device, k), k)
            else:
                v(getattr(device, k), k)

    def setUp(self):
        self.dev0 = MDRaidArrayDevice("dev0")

        self.dev1 = MDRaidArrayDevice("dev1", level="container")
        self.dev2 = MDRaidArrayDevice("dev2", level="raid0")
        self.dev3 = MDRaidArrayDevice("dev3", level="raid1")
        self.dev4 = MDRaidArrayDevice("dev4", level="raid4")
        self.dev5 = MDRaidArrayDevice("dev5", level="raid5")
        self.dev6 = MDRaidArrayDevice("dev6", level="raid6")
        self.dev7 = MDRaidArrayDevice("dev7", level="raid10")

        self.dev8 = MDRaidArrayDevice("dev8", exists=True)
        self.dev9 = MDRaidArrayDevice(
           "dev9",
           level="raid0",
           parents=[
              MDRaidArrayDevice("parent", level="container"),
              MDRaidArrayDevice("other")])

        self.dev10 = MDRaidArrayDevice(
           "dev10",
           level="raid0",
           size=32)

        self.dev11 = MDRaidArrayDevice(
           "dev11",
           level=1,
           parents=[
              MDRaidArrayDevice("parent", level="container"),
              MDRaidArrayDevice("other")],
           size=32)

        self.dev12 = MDRaidArrayDevice(
           "dev12",
           level=1,
           memberDevices=2,
           parents=[
              Mock(**{"type": "mdcontainer",
                      "size": 4}),
              Mock(**{"size": 2})],
           size=32,
           totalDevices=2)

        self.dev13 = MDRaidArrayDevice(
           "dev13",
           level=0,
           memberDevices=3,
           parents=[
              Mock(**{"size": 4}),
              Mock(**{"size": 2})],
           size=32,
           totalDevices=3)

        self.dev14 = MDRaidArrayDevice(
           "dev14",
           level=4,
           memberDevices=3,
           parents=[
              Mock(**{"size": 4}),
              Mock(**{"size": 2}),
              Mock(**{"size": 2})],
           totalDevices=3)

        self.dev15 = MDRaidArrayDevice(
           "dev15",
           level=5,
           memberDevices=3,
           parents=[
              Mock(**{"size": 4}),
              Mock(**{"size": 2}),
              Mock(**{"size": 2})],
           totalDevices=3)

        self.dev16 = MDRaidArrayDevice(
           "dev16",
           level=6,
           memberDevices=4,
           parents=[
              Mock(**{"size": 4}),
              Mock(**{"size": 4}),
              Mock(**{"size": 2}),
              Mock(**{"size": 2})],
           totalDevices=4)

        self.dev17 = MDRaidArrayDevice(
           "dev17",
           level=10,
           memberDevices=4,
           parents=[
              Mock(**{"size": 4}),
              Mock(**{"size": 4}),
              Mock(**{"size": 2}),
              Mock(**{"size": 2})],
           totalDevices=4)

        self.dev18 = MDRaidArrayDevice(
           "dev18",
           level=10,
           memberDevices=4,
           parents=[
              Mock(**{"size": 4}),
              Mock(**{"size": 4}),
              Mock(**{"size": 2}),
              Mock(**{"size": 2})],
           totalDevices=5)


    def testMDRaidArrayDeviceInit(self, *args, **kwargs):
        """Tests the state of a MDRaidArrayDevice after initialization.
           For some combinations of arguments the initializer will throw
           an exception.
        """
        self.stateCheck(self.dev0)


        ##
        ## level tests
        ##
        self.stateCheck(self.dev1,
                        description=lambda x, m: self.assertEqual(x, "BIOS RAID container", m),
                        level=lambda x, m: self.assertEqual(x, "container", m),
                        type=lambda x, m: self.assertEqual(x, "mdcontainer", m))
        self.stateCheck(self.dev2,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (stripe)", m),
                        createBitmap=self.assertFalse,
                        level=lambda x, m: self.assertEqual(x, 0, m))
        self.stateCheck(self.dev3,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (mirror)", m),
                        level=lambda x, m: self.assertEqual(x, 1, m))
        self.stateCheck(self.dev4,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid4)", m),
                        level=lambda x, m: self.assertEqual(x, 4, m))
        self.stateCheck(self.dev5,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid5)", m),
                        level=lambda x, m: self.assertEqual(x, 5, m))
        self.stateCheck(self.dev6,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid6)", m),
                        level=lambda x, m: self.assertEqual(x, 6, m))
        self.stateCheck(self.dev7,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid10)", m),
                        level=lambda x, m: self.assertEqual(x, 10, m))

        ##
        ## existing device tests
        ##
        self.stateCheck(self.dev8,
                        exists=self.assertTrue,
                        metadataVersion=self.assertIsNone)


        ##
        ## mdbiosraidarray tests
        ##
        self.stateCheck(self.dev9,
                        createBitmap=self.assertFalse,
                        description=lambda x, m: self.assertEqual(x, "BIOS RAID set (stripe)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        isDisk=self.assertTrue,
                        level=lambda x, m: self.assertEqual(x, 0, m),
                        mediaPresent=self.assertTrue,
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        partitionable=self.assertTrue,
                        smallestMember=self.assertIsNotNone,
                        type = lambda x, m: self.assertEqual(x, "mdbiosraidarray", m))

        ##
        ## size tests
        ##
        self.stateCheck(self.dev10,
                        createBitmap=self.assertFalse,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (stripe)", m),
                        level=lambda x, m: self.assertEqual(x, 0, m))

        self.stateCheck(self.dev11,
                        description=lambda x, m: self.assertEqual(x, "BIOS RAID set (mirror)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        isDisk=self.assertTrue,
                        level=lambda x, m: self.assertEqual(x, 1, m),
                        mediaPresent=self.assertTrue,
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        partitionable=self.assertTrue,
                        smallestMember=self.assertIsNotNone,
                        type=lambda x, m: self.assertEqual(x, "mdbiosraidarray", m))

        ##
        ## rawArraySize tests
        ##
        self.stateCheck(self.dev12,
                        description=lambda x, m: self.assertEqual(x, "BIOS RAID set (mirror)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        isDisk=self.assertTrue,
                        level=lambda x, m: self.assertEqual(x, 1, m),
                        mediaPresent=self.assertTrue,
                        memberDevices=lambda x, m: self.assertEqual(x, 2, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        partitionable=self.assertTrue,
                        rawArraySize=lambda x, m: self.assertEqual(x, 2, m),
                        smallestMember=self.assertIsNotNone,
                        totalDevices=lambda x, m: self.assertEqual(x, 2, m),
                        type = lambda x, m: self.assertEqual(x, "mdbiosraidarray", m))

        self.stateCheck(self.dev13,
                        createBitmap=self.assertFalse,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (stripe)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        level=lambda x, m: self.assertEqual(x, 0, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 3, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        rawArraySize=lambda x, m: self.assertEqual(x, 6, m),
                        size=lambda x, m: self.assertEqual(x, 6, m),
                        smallestMember=self.assertIsNotNone,
                        totalDevices=lambda x, m: self.assertEqual(x, 3, m))

        self.stateCheck(self.dev14,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid4)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 3, m),
                        level=lambda x, m: self.assertEqual(x, 4, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 3, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        rawArraySize=lambda x, m: self.assertEqual(x, 4, m),
                        size=lambda x, m: self.assertEqual(x, 4, m),
                        smallestMember=self.assertIsNotNone,
                        totalDevices=lambda x, m: self.assertEqual(x, 3, m))

        self.stateCheck(self.dev15,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid5)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 3, m),
                        level=lambda x, m: self.assertEqual(x, 5, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 3, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        rawArraySize=lambda x, m: self.assertEqual(x, 4, m),
                        size=lambda x, m: self.assertEqual(x, 4, m),
                        smallestMember=self.assertIsNotNone,
                        totalDevices=lambda x, m: self.assertEqual(x, 3, m))

        self.stateCheck(self.dev16,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid6)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 4, m),
                        level=lambda x, m: self.assertEqual(x, 6, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 4, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        rawArraySize=lambda x, m: self.assertEqual(x, 4, m),
                        size=lambda x, m: self.assertEqual(x, 4, m),
                        smallestMember=self.assertIsNotNone,
                        totalDevices=lambda x, m: self.assertEqual(x, 4, m))

        self.stateCheck(self.dev17,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid10)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 4, m),
                        level=lambda x, m: self.assertEqual(x, 10, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 4, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        rawArraySize=lambda x, m: self.assertEqual(x, 4, m),
                        size=lambda x, m: self.assertEqual(x, 4, m),
                        smallestMember=self.assertIsNotNone,
                        totalDevices=lambda x, m: self.assertEqual(x, 4, m))

        self.stateCheck(self.dev18,
                        description=lambda x, m: self.assertEqual(x, "MDRAID set (raid10)", m),
                        devices=lambda x, m: self.assertEqual(len(x), 4, m),
                        level=lambda x, m: self.assertEqual(x, 10, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 4, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        rawArraySize=lambda x, m: self.assertEqual(x, 4, m),
                        size=lambda x, m: self.assertEqual(x, 4, m),
                        smallestMember=self.assertIsNotNone,
                        spares=lambda x, m: self.assertEqual(x, 1, m),
                        totalDevices=lambda x, m: self.assertEqual(x, 5, m))

        self.assertRaisesRegexp(mdraid.MDRaidError,
                                "invalid raid level",
                                MDRaidArrayDevice,
                                "dev",
                                level="raid2")

        self.assertRaisesRegexp(mdraid.MDRaidError,
                                "invalid raid level",
                                MDRaidArrayDevice,
                                "dev",
                                parents=[Device("parent")])

        self.assertRaisesRegexp(DeviceError,
                                "A RAID0 set requires at least 2 members",
                                MDRaidArrayDevice,
                                "dev",
                                level="raid0",
                                parents=[Device("parent")])

        self.assertRaisesRegexp(mdraid.MDRaidError,
                                "invalid raid level descriptor junk",
                                MDRaidArrayDevice,
                                "dev",
                                level="junk")

        self.assertRaisesRegexp(ValueError,
                                "memberDevices cannot be greater than totalDevices",
                                MDRaidArrayDevice,
                                "dev",
                                memberDevices=2)


    def testMDRaidArrayDeviceMethods(self, *args, **kwargs):
        """Test for method calls on initialized MDRaidDevices."""
        with self.assertRaisesRegexp(mdraid.MDRaidError, "invalid raid level" ):
            self.dev7.level = "junk"


def suite():
    return unittest.TestLoader().loadTestsFromTestCase(MDRaidArrayDeviceTestCase)


if __name__ == "__main__":
    unittest.main()

