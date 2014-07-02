#!/usr/bin/python
# vim:set fileencoding=utf-8

import unittest

from mock import Mock

import blivet

from blivet.errors import DeviceError
from blivet.errors import RaidError

from blivet.devices import BTRFSSnapShotDevice
from blivet.devices import BTRFSSubVolumeDevice
from blivet.devices import BTRFSVolumeDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import LVMSnapShotDevice
from blivet.devices import LVMThinPoolDevice
from blivet.devices import LVMThinLogicalVolumeDevice
from blivet.devices import LVMThinSnapShotDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import OpticalDevice
from blivet.devices import StorageDevice
from blivet.devices import ParentList
from blivet.devicelibs import btrfs
from blivet.size import Size

from blivet.formats import getFormat

class DeviceStateTestCase(unittest.TestCase):
    """A class which implements a simple method of checking the state
       of a device object.
    """

    def setUp(self):
        self._state_functions = {}

    def stateCheck(self, device, **kwargs):
        """Checks the current state of a device by means of its
           fields or properties.

           Every kwarg should be a key which is a field or property
           of a Device and a value which is a function of
           two parameters and should call the appropriate assert* functions.
           These values override those in the state_functions dict.

           If the value is None, then the test starts the debugger instead.
        """
        self.longMessage = True
        for k,v in self._state_functions.items():
            if k in kwargs:
                key = kwargs[k]
                if key is None:
                    import pdb
                    pdb.set_trace()
                    getattr(device, k)
                else:
                    kwargs[k](getattr(device, k), k)
            else:
                v(getattr(device, k), k)

class MDRaidArrayDeviceTestCase(DeviceStateTestCase):
    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or correct behavior. See the initial
       commit message for this file for further details.
    """

    def setUp(self):
        self._state_functions = {
           "createBitmap" : self.assertFalse,
           "currentSize" : lambda x, m: self.assertEqual(x, Size(0), m),
           "description" : self.assertIsNotNone,
           "devices" : lambda x, m: self.assertEqual(len(x), 0, m) and
                                    self.assertIsInstance(x, ParentList, m),
           "exists" : self.assertFalse,
           "format" : self.assertIsNotNone,
           "formatArgs" : lambda x, m: self.assertEqual(x, [], m),
           "formatClass" : self.assertIsNotNone,
           "isDisk" : self.assertFalse,
           "level" : self.assertIsNone,
           "major" : lambda x, m: self.assertEqual(x, 0, m),
           "maxSize" : lambda x, m: self.assertEqual(x, Size(0), m),
           "mediaPresent" : self.assertFalse,
           "metadataVersion" : lambda x, m: self.assertEqual(x, "default", m),
           "minor" : lambda x, m: self.assertEqual(x, 0, m),
           "parents" : lambda x, m: self.assertEqual(len(x), 0, m) and
                                    self.assertIsInstance(x, ParentList, m),
           "path" : lambda x, m: self.assertRegexpMatches(x, "^/dev", m),
           "partitionable" : self.assertFalse,
           "raw_device" : self.assertIsNotNone,
           "resizable" : self.assertFalse,
           "size" : lambda x, m: self.assertEqual(x, Size(0), m),
           "spares" : lambda x, m: self.assertEqual(x, 0, m),
           "status" : self.assertFalse,
           "sysfsPath" : lambda x, m: self.assertEqual(x, "", m),
           "targetSize" : lambda x, m: self.assertEqual(x, Size(0), m),
           "uuid" : self.assertIsNone,
           "memberDevices" : lambda x, m: self.assertEqual(x, 0, m),
           "totalDevices" : lambda x, m: self.assertEqual(x, 0, m),
           "type" : lambda x, m: self.assertEqual(x, "mdarray", m) }

        self.dev1 = MDRaidArrayDevice("dev1", level="container")
        self.dev2 = MDRaidArrayDevice("dev2", level="raid0")
        self.dev3 = MDRaidArrayDevice("dev3", level="raid1")
        self.dev4 = MDRaidArrayDevice("dev4", level="raid4")
        self.dev5 = MDRaidArrayDevice("dev5", level="raid5")
        self.dev6 = MDRaidArrayDevice("dev6", level="raid6")
        self.dev7 = MDRaidArrayDevice("dev7", level="raid10")

        self.dev8 = MDRaidArrayDevice("dev8", level=1, exists=True)
        self.dev9 = MDRaidArrayDevice(
           "dev9",
           level="raid0",
           memberDevices=2,
           parents=[
              MDRaidArrayDevice("parent", level="container",
                                fmt=getFormat("mdmember")),
              MDRaidArrayDevice("other", level=0,
                                fmt=getFormat("mdmember"))],
           totalDevices=2)

        self.dev10 = MDRaidArrayDevice(
           "dev10",
           level="raid0",
           size=Size("32 MiB"))

        self.dev11 = MDRaidArrayDevice(
           "dev11",
           level=1,
           memberDevices=2,
           parents=[
              MDRaidArrayDevice("parent", level="container",
                                fmt=getFormat("mdmember")),
              MDRaidArrayDevice("other", level="raid0",
                                fmt=getFormat("mdmember"))],
           size=Size("32 MiB"),
           totalDevices=2)

        self.dev12 = MDRaidArrayDevice(
           "dev12",
           level=1,
           memberDevices=2,
           parents=[
              Mock(**{"type": "mdcontainer",
                      "size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")})],
           size=Size("32 MiB"),
           totalDevices=2)

        self.dev13 = MDRaidArrayDevice(
           "dev13",
           level=0,
           memberDevices=3,
           parents=[
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")})],
           size=Size("32 MiB"),
           totalDevices=3)

        self.dev14 = MDRaidArrayDevice(
           "dev14",
           level=4,
           memberDevices=3,
           parents=[
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")})],
           totalDevices=3)

        self.dev15 = MDRaidArrayDevice(
           "dev15",
           level=5,
           memberDevices=3,
           parents=[
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")})],
           totalDevices=3)

        self.dev16 = MDRaidArrayDevice(
           "dev16",
           level=6,
           memberDevices=4,
           parents=[
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")})],
           totalDevices=4)

        self.dev17 = MDRaidArrayDevice(
           "dev17",
           level=10,
           memberDevices=4,
           parents=[
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")})],
           totalDevices=4)

        self.dev18 = MDRaidArrayDevice(
           "dev18",
           level=10,
           memberDevices=4,
           parents=[
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("4 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")}),
              Mock(**{"size": Size("2 MiB"),
                      "format": getFormat("mdmember")})],
           totalDevices=5)


    def testMDRaidArrayDeviceInit(self):
        """Tests the state of a MDRaidArrayDevice after initialization.
           For some combinations of arguments the initializer will throw
           an exception.
        """

        ##
        ## level tests
        ##
        self.stateCheck(self.dev1,
                        level=lambda x, m: self.assertEqual(x.name, "container", m),
                        type=lambda x, m: self.assertEqual(x, "mdcontainer", m))
        self.stateCheck(self.dev2,
                        createBitmap=self.assertFalse,
                        level=lambda x, m: self.assertEqual(x.number, 0, m))
        self.stateCheck(self.dev3,
                        level=lambda x, m: self.assertEqual(x.number, 1, m))
        self.stateCheck(self.dev4,
                        level=lambda x, m: self.assertEqual(x.number, 4, m))
        self.stateCheck(self.dev5,
                        level=lambda x, m: self.assertEqual(x.number, 5, m))
        self.stateCheck(self.dev6,
                        level=lambda x, m: self.assertEqual(x.number, 6, m))
        self.stateCheck(self.dev7,
                        level=lambda x, m: self.assertEqual(x.number, 10, m))

        ##
        ## existing device tests
        ##
        self.stateCheck(self.dev8,
                        exists=self.assertTrue,
                        level=lambda x, m: self.assertEqual(x.number, 1, m),
                        metadataVersion=self.assertIsNone)


        ##
        ## mdbiosraidarray tests
        ##
        self.stateCheck(self.dev9,
                        createBitmap=self.assertFalse,
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        isDisk=self.assertTrue,
                        level=lambda x, m: self.assertEqual(x.number, 0, m),
                        mediaPresent=self.assertTrue,
                        memberDevices=lambda x, m: self.assertEqual(x, 2, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        partitionable=self.assertTrue,
                        totalDevices=lambda x, m: self.assertEqual(x, 2, m),
                        type = lambda x, m: self.assertEqual(x, "mdbiosraidarray", m))

        ##
        ## size tests
        ##
        self.stateCheck(self.dev10,
                        createBitmap=self.assertFalse,
                        level=lambda x, m: self.assertEqual(x.number, 0, m),
                        targetSize=lambda x, m: self.assertEqual(x, Size("32 MiB"), m))

        self.stateCheck(self.dev11,
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        isDisk=self.assertTrue,
                        level=lambda x, m: self.assertEqual(x.number, 1, m),
                        mediaPresent=self.assertTrue,
                        memberDevices=lambda x, m: self.assertEqual(x, 2, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        partitionable=self.assertTrue,
                        targetSize=lambda x, m: self.assertEqual(x, Size("32 MiB"), m),
                        totalDevices=lambda x, m: self.assertEqual(x, 2, m),
                        type=lambda x, m: self.assertEqual(x, "mdbiosraidarray", m))

        self.stateCheck(self.dev12,
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        isDisk=self.assertTrue,
                        level=lambda x, m: self.assertEqual(x.number, 1, m),
                        mediaPresent=self.assertTrue,
                        memberDevices=lambda x, m: self.assertEqual(x, 2, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        partitionable=self.assertTrue,
                        targetSize=lambda x, m: self.assertEqual(x, Size("32 MiB"), m),
                        totalDevices=lambda x, m: self.assertEqual(x, 2, m),
                        type = lambda x, m: self.assertEqual(x, "mdbiosraidarray", m))

        self.stateCheck(self.dev13,
                        createBitmap=self.assertFalse,
                        devices=lambda x, m: self.assertEqual(len(x), 2, m),
                        level=lambda x, m: self.assertEqual(x.number, 0, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 3, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        size=lambda x, m: self.assertEqual(x, Size("3 MiB"), m),
                        targetSize=lambda x, m: self.assertEqual(x, Size("32 MiB"), m),
                        totalDevices=lambda x, m: self.assertEqual(x, 3, m))

        self.stateCheck(self.dev14,
                        createBitmap=self.assertTrue,
                        devices=lambda x, m: self.assertEqual(len(x), 3, m),
                        level=lambda x, m: self.assertEqual(x.number, 4, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 3, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        size=lambda x, m: self.assertEqual(x, Size("2 MiB"), m),
                        totalDevices=lambda x, m: self.assertEqual(x, 3, m))

        self.stateCheck(self.dev15,
                        createBitmap=self.assertTrue,
                        devices=lambda x, m: self.assertEqual(len(x), 3, m),
                        level=lambda x, m: self.assertEqual(x.number, 5, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 3, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        size=lambda x, m: self.assertEqual(x, Size("2 MiB"), m),
                        totalDevices=lambda x, m: self.assertEqual(x, 3, m))

        self.stateCheck(self.dev16,
                        createBitmap=self.assertTrue,
                        devices=lambda x, m: self.assertEqual(len(x), 4, m),
                        level=lambda x, m: self.assertEqual(x.number, 6, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 4, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        size=lambda x, m: self.assertEqual(x, Size("2 MiB"), m),
                        totalDevices=lambda x, m: self.assertEqual(x, 4, m))

        self.stateCheck(self.dev17,
                        createBitmap=self.assertTrue,
                        devices=lambda x, m: self.assertEqual(len(x), 4, m),
                        level=lambda x, m: self.assertEqual(x.number, 10, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 4, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        size=lambda x, m: self.assertEqual(x, Size("2 MiB"), m),
                        totalDevices=lambda x, m: self.assertEqual(x, 4, m))

        self.stateCheck(self.dev18,
                        createBitmap=self.assertTrue,
                        devices=lambda x, m: self.assertEqual(len(x), 4, m),
                        level=lambda x, m: self.assertEqual(x.number, 10, m),
                        memberDevices=lambda x, m: self.assertEqual(x, 4, m),
                        parents=lambda x, m: self.assertNotEqual(x, [], m),
                        size=lambda x, m: self.assertEqual(x, Size("2 MiB"), m),
                        spares=lambda x, m: self.assertEqual(x, 1, m),
                        totalDevices=lambda x, m: self.assertEqual(x, 5, m))

        self.assertRaisesRegexp(RaidError,
                                "invalid RAID level",
                                MDRaidArrayDevice,
                                "dev")

        self.assertRaisesRegexp(RaidError,
                                "invalid RAID level",
                                MDRaidArrayDevice,
                                "dev",
                                level="raid2")

        self.assertRaisesRegexp(RaidError,
                                "invalid RAID level",
                                MDRaidArrayDevice,
                                "dev",
                                parents=[StorageDevice("parent",
                                                fmt=getFormat("mdmember"))])

        self.assertRaisesRegexp(DeviceError,
                                "set requires at least 2 members",
                                MDRaidArrayDevice,
                                "dev",
                                level="raid0",
                                parents=[StorageDevice("parent",
                                                fmt=getFormat("mdmember"))])

        self.assertRaisesRegexp(RaidError,
                                "invalid RAID level descriptor junk",
                                MDRaidArrayDevice,
                                "dev",
                                level="junk")

        self.assertRaisesRegexp(ValueError,
                                "memberDevices cannot be greater than totalDevices",
                                MDRaidArrayDevice,
                                "dev",
                                level=0,
                                memberDevices=2)


    def testMDRaidArrayDeviceMethods(self):
        """Test for method calls on initialized MDRaidDevices."""
        with self.assertRaisesRegexp(RaidError, "invalid RAID level" ):
            self.dev7.level = "junk"

        with self.assertRaisesRegexp(RaidError, "invalid RAID level" ):
            self.dev7.level = None

class BTRFSDeviceTestCase(DeviceStateTestCase):
    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or correct behavior. See the initial
       commit message for this file for further details.
    """

    def setUp(self):
        self._state_functions = {
           "currentSize" : lambda x, m: self.assertEqual(x, Size(0), m),
           "exists" : self.assertFalse,
           "format" : self.assertIsNotNone,
           "formatArgs" : lambda x, m: self.assertEqual(x, [], m),
           "fstabSpec" : self.assertIsNotNone,
           "isDisk" : self.assertFalse,
           "major" : lambda x, m: self.assertEqual(x, 0, m),
           "maxSize" : lambda x, m: self.assertEqual(x, Size(0), m),
           "mediaPresent" : self.assertTrue,
           "minor" : lambda x, m: self.assertEqual(x, 0, m),
           "parents" : lambda x, m: self.assertEqual(len(x), 0, m) and
                                    self.assertIsInstance(x, ParentList, m),
           "partitionable" : self.assertFalse,
           "path" : lambda x, m: self.assertRegexpMatches(x, "^/dev", m),
           "resizable" : lambda x, m: self.assertFalse,
           "size" : lambda x, m: self.assertEqual(x, Size(0), m),
           "status" : self.assertFalse,
           "sysfsPath" : lambda x, m: self.assertEqual(x, "", m),
           "targetSize" : lambda x, m: self.assertEqual(x, Size(0), m),
           "type" : lambda x, m: self.assertEqual(x, "btrfs", m),
           "uuid" : self.assertIsNone,
           "vol_id" : lambda x, m: self.assertEqual(x, btrfs.MAIN_VOLUME_ID, m)}

        self.dev1 = BTRFSVolumeDevice("dev1",
           parents=[OpticalDevice("deva",
              fmt=blivet.formats.getFormat("btrfs"))])

        self.dev2 = BTRFSSubVolumeDevice("dev2", parents=[self.dev1])

        dev = StorageDevice("deva",
           fmt=blivet.formats.getFormat("btrfs"),
           size=Size("32 MiB"))
        self.dev3 = BTRFSVolumeDevice("dev3",
           parents=[dev])

    def testBTRFSDeviceInit(self):
        """Tests the state of a BTRFSDevice after initialization.
           For some combinations of arguments the initializer will throw
           an exception.
        """

        self.stateCheck(self.dev1,
           parents=lambda x, m: self.assertEqual(len(x), 1, m),
           type=lambda x, m: self.assertEqual(x, "btrfs volume", m))

        self.stateCheck(self.dev3,
           currentSize=lambda x, m: self.assertEqual(x, Size("32 MiB"), m),
           maxSize=lambda x, m: self.assertEqual(x, Size("32 MiB"), m),
           parents=lambda x, m: self.assertEqual(len(x), 1, m),
           size=lambda x, m: self.assertEqual(x, Size("32 MiB"), m),
           type=lambda x, m: self.assertEqual(x, "btrfs volume", m))

        self.assertRaisesRegexp(ValueError,
           "BTRFSDevice.*must have at least one parent",
           BTRFSVolumeDevice,
           "dev")

        self.assertRaisesRegexp(ValueError,
           "member has wrong format",
           BTRFSVolumeDevice,
           "dev", parents=[OpticalDevice("deva")])

        parents=[OpticalDevice("deva",
           fmt=blivet.formats.getFormat("btrfs"))]
        self.assertRaisesRegexp(DeviceError,
           "btrfs subvolume.*must be a BTRFSDevice",
           BTRFSSubVolumeDevice,
           "dev1", parents=parents)

        self.assertEqual(self.dev1.isleaf, False)
        self.assertEqual(self.dev1.direct, True)
        self.assertEqual(self.dev2.isleaf, True)
        self.assertEqual(self.dev2.direct, True)

        member = self.dev1.parents[0]
        self.assertEqual(member.isleaf, False)
        self.assertEqual(member.direct, False)

    def testBTRFSDeviceMethods(self):
        """Test for method calls on initialized BTRFS Devices."""
        # volumes do not have ancestor volumes
        with self.assertRaises(AttributeError):
            self.dev1.volume # pylint: disable=no-member,pointless-statement

        # subvolumes do not have default subvolumes
        with self.assertRaises(AttributeError):
            self.dev2.defaultSubVolume # pylint: disable=no-member,pointless-statement

        self.assertIsNotNone(self.dev2.volume)

        # size
        with self.assertRaisesRegexp(RuntimeError,
           "cannot directly set size of btrfs volume"):
            self.dev1.size = 32

    def testBTRFSSnapShotDeviceInit(self):
        parents = [StorageDevice("p1", fmt=blivet.formats.getFormat("btrfs"))]
        vol = BTRFSVolumeDevice("test", parents=parents)
        self.assertRaisesRegexp(ValueError,
                                "non-existent btrfs snapshots must have a source",
                                BTRFSSnapShotDevice,
                                "snap1", parents=[vol])

        self.assertRaisesRegexp(ValueError,
                                "btrfs snapshot source must already exist",
                                BTRFSSnapShotDevice,
                                "snap1", parents=[vol], source=vol)

        self.assertRaisesRegexp(ValueError,
                                "btrfs snapshot source must be a btrfs subvolume",
                                BTRFSSnapShotDevice,
                                "snap1", parents=[vol], source=parents[0])

        parents2 = [StorageDevice("p1", fmt=blivet.formats.getFormat("btrfs"))]
        vol2 = BTRFSVolumeDevice("test2", parents=parents2, exists=True)
        self.assertRaisesRegexp(ValueError,
                                ".*snapshot and source must be in the same volume",
                                BTRFSSnapShotDevice,
                                "snap1", parents=[vol], source=vol2)

        vol.exists = True
        snap = BTRFSSnapShotDevice("snap1", parents=[vol], source=vol)
        self.assertEqual(snap.isleaf, True)
        self.assertEqual(snap.direct, True)
        self.assertEqual(vol.isleaf, False)
        self.assertEqual(vol.direct, True)

        self.assertEqual(snap.dependsOn(vol), True)
        self.assertEqual(vol.dependsOn(snap), False)

class LVMDeviceTest(unittest.TestCase):
    def testLVMSnapShotDeviceInit(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.getFormat("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                    fmt=blivet.formats.getFormat("xfs"))

        self.assertRaisesRegexp(ValueError,
                                "lvm snapshot devices require an origin lv",
                                LVMSnapShotDevice,
                                "snap1", parents=[vg])

        self.assertRaisesRegexp(ValueError,
                                "lvm snapshot origin volume must already exist",
                                LVMSnapShotDevice,
                                "snap1", parents=[vg], origin=lv)

        self.assertRaisesRegexp(ValueError,
                                "lvm snapshot origin must be a logical volume",
                                LVMSnapShotDevice,
                                "snap1", parents=[vg], origin=pv)

        self.assertRaisesRegexp(ValueError,
                                "only existing vorigin snapshots are supported",
                                LVMSnapShotDevice,
                                "snap1", parents=[vg], vorigin=True)

        lv.exists = True
        snap1 = LVMSnapShotDevice("snap1", parents=[vg], origin=lv)

        self.assertEqual(snap1.format, lv.format)
        snap1.format = blivet.formats.getFormat("DM_snapshot_cow", exists=True)
        self.assertEqual(snap1.format, lv.format)

        self.assertEqual(snap1.isleaf, True)
        self.assertEqual(snap1.direct, True)
        self.assertEqual(lv.isleaf, False)
        self.assertEqual(lv.direct, True)

        self.assertEqual(snap1.dependsOn(lv), True)
        self.assertEqual(lv.dependsOn(snap1), False)

    def testLVMThinSnapShotDeviceInit(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.getFormat("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        pool = LVMThinPoolDevice("pool1", parents=[vg], size=Size("500 MiB"))
        thinlv = LVMThinLogicalVolumeDevice("thinlv", parents=[pool],
                                            size=Size("200 MiB"))

        self.assertRaisesRegexp(ValueError,
                                "lvm thin snapshots require an origin",
                                LVMThinSnapShotDevice,
                                "snap1", parents=[pool])

        self.assertRaisesRegexp(ValueError,
                                "lvm snapshot origin volume must already exist",
                                LVMThinSnapShotDevice,
                                "snap1", parents=[pool], origin=thinlv)

        self.assertRaisesRegexp(ValueError,
                                "lvm snapshot origin must be a logical volume",
                                LVMThinSnapShotDevice,
                                "snap1", parents=[pool], origin=pv)

        # now make the constructor succeed so we can test some properties
        thinlv.exists = True
        snap1 = LVMThinSnapShotDevice("snap1", parents=[pool], origin=thinlv)
        self.assertEqual(snap1.isleaf, True)
        self.assertEqual(snap1.direct, True)
        self.assertEqual(thinlv.isleaf, True)
        self.assertEqual(thinlv.direct, True)

        self.assertEqual(snap1.dependsOn(thinlv), True)
        self.assertEqual(thinlv.dependsOn(snap1), False)

        # existing thin snapshots do not depend on their origin
        snap1.exists = True
        self.assertEqual(snap1.dependsOn(thinlv), False)

class DeviceNameTestCase(unittest.TestCase):
    """Test device name validation"""

    def testStorageDevice(self):
        # Check that / and NUL are rejected along with . and ..
        good_names = ['sda1', '1sda', 'good-name', 'cciss/c0d0']
        bad_names = ['sda/1', 'sda\x00', '.', '..', 'cciss/..']

        for name in good_names:
            self.assertTrue(StorageDevice.isNameValid(name))

        for name in bad_names:
            self.assertFalse(StorageDevice.isNameValid(name))

    def testVolumeGroup(self):
        good_names = ['vg00', 'group-name', 'groupname-']
        bad_names = ['-leading-hyphen', 'únicode', 'sp aces']

        for name in good_names:
            self.assertTrue(LVMVolumeGroupDevice.isNameValid(name))

        for name in bad_names:
            self.assertFalse(LVMVolumeGroupDevice.isNameValid(name))

    def testLogicalVolume(self):
        good_names = ['lv00', 'volume-name', 'volumename-']
        bad_names = ['-leading-hyphen', 'únicode', 'sp aces',
                     'snapshot47', 'pvmove0', 'sub_tmetastring']

        for name in good_names:
            self.assertTrue(LVMLogicalVolumeDevice.isNameValid(name))

        for name in bad_names:
            self.assertFalse(LVMLogicalVolumeDevice.isNameValid(name))

if __name__ == "__main__":
    unittest.main()

