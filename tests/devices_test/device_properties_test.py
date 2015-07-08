# vim:set fileencoding=utf-8

import unittest

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

from mock import Mock

import blivet

from blivet.errors import BTRFSValueError
from blivet.errors import DeviceError

from blivet.devices import BTRFSSnapShotDevice
from blivet.devices import BTRFSSubVolumeDevice
from blivet.devices import BTRFSVolumeDevice
from blivet.devices import DiskDevice
from blivet.devices import MDBiosRaidArrayDevice
from blivet.devices import MDContainerDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import OpticalDevice
from blivet.devices import StorageDevice
from blivet.devices import ParentList
from blivet.devicelibs import btrfs
from blivet.size import Size

from blivet.formats import getFormat

def xform(func):
    """ Simple wrapper function that transforms a function that takes
        a precalculated value and a message to a function that takes
        a device and an attribute name, evaluates the attribute, and
        passes the value and the attribute name as the message to the
        original function.

        :param func: The function to be transformed.
        :type func: (object * str) -> None
        :returns: a function that gets the attribute and passes it to func
        :rtype: (object * str) -> None
    """
    return lambda d, a: func(getattr(d, a), a)

class DeviceStateTestCase(unittest.TestCase):
    """A class which implements a simple method of checking the state
       of a device object.
    """

    def __init__(self, methodName='runTest'):
        self._state_functions = {
           "currentSize" : xform(lambda x, m: self.assertEqual(x, Size(0), m)),
           "direct" : xform(self.assertTrue),
           "exists" : xform(self.assertFalse),
           "format" : xform(self.assertIsNotNone),
           "formatArgs" : xform(lambda x, m: self.assertEqual(x, [], m)),
           "isDisk" : xform(self.assertFalse),
           "isleaf" : xform(self.assertTrue),
           "major" : xform(lambda x, m: self.assertEqual(x, 0, m)),
           "maxSize" : xform(lambda x, m: self.assertEqual(x, Size(0), m)),
           "mediaPresent" : xform(self.assertTrue),
           "minor" : xform(lambda x, m: self.assertEqual(x, 0, m)),
           "parents" : xform(lambda x, m: self.assertEqual(len(x), 0, m) and
                                    self.assertIsInstance(x, ParentList, m)),
           "partitionable" : xform(self.assertFalse),
           "path" : xform(lambda x, m: self.assertRegex(x, "^/dev", m)),
           "raw_device" : xform(self.assertIsNotNone),
           "resizable" : xform(self.assertFalse),
           "size" : xform(lambda x, m: self.assertEqual(x, Size(0), m)),
           "status" : xform(self.assertFalse),
           "sysfsPath" : xform(lambda x, m: self.assertEqual(x, "", m)),
           "targetSize" : xform(lambda x, m: self.assertEqual(x, Size(0), m)),
           "type" : xform(lambda x, m: self.assertEqual(x, "mdarray", m)),
           "uuid" : xform(self.assertIsNone)
        }
        super(DeviceStateTestCase, self).__init__(methodName=methodName)

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
                test_func = kwargs[k]
                if test_func is None:
                    import pdb
                    pdb.set_trace()
                    getattr(device, k)
                else:
                    test_func(device, k)
            else:
                v(device, k)

class MDRaidArrayDeviceTestCase(DeviceStateTestCase):
    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or correct behavior. See the initial
       commit message for this file for further details.
    """

    def __init__(self, methodName='runTest'):
        super(MDRaidArrayDeviceTestCase, self).__init__(methodName=methodName)
        state_functions = {
           "createBitmap" : xform(lambda d, a: self.assertFalse),
           "description" : xform(self.assertIsNotNone),
           "devices" : xform(lambda x, m: self.assertEqual(len(x), 0, m) and
                                    self.assertIsInstance(x, ParentList, m)),
           "formatClass" : xform(self.assertIsNotNone),
           "level" : xform(self.assertIsNone),
           "mdadmFormatUUID" : xform(self.assertIsNone),
           "memberDevices" : xform(lambda x, m: self.assertEqual(x, 0, m)),
           "metadataVersion" : xform(lambda x, m: self.assertEqual(x, "default", m)),
           "spares" : xform(lambda x, m: self.assertEqual(x, 0, m)),
           "totalDevices" : xform(lambda x, m: self.assertEqual(x, 0, m))
        }
        self._state_functions.update(state_functions)

    def setUp(self):
        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember"))
        ]
        self.dev1 = MDContainerDevice("dev1", level="container", parents=parents)

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember"))
        ]
        self.dev2 = MDRaidArrayDevice("dev2", level="raid0", parents=parents)

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember"))
        ]
        self.dev3 = MDRaidArrayDevice("dev3", level="raid1", parents=parents)

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember")),
           DiskDevice("name3", fmt=getFormat("mdmember"))
        ]
        self.dev4 = MDRaidArrayDevice("dev4", level="raid4", parents=parents)

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember")),
           DiskDevice("name3", fmt=getFormat("mdmember"))
        ]
        self.dev5 = MDRaidArrayDevice("dev5", level="raid5", parents=parents)

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember")),
           DiskDevice("name3", fmt=getFormat("mdmember")),
           DiskDevice("name4", fmt=getFormat("mdmember"))
        ]
        self.dev6 = MDRaidArrayDevice("dev6", level="raid6", parents=parents)

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember")),
           DiskDevice("name3", fmt=getFormat("mdmember")),
           DiskDevice("name4", fmt=getFormat("mdmember"))
        ]
        self.dev7 = MDRaidArrayDevice("dev7", level="raid10", parents=parents)

        self.dev8 = MDRaidArrayDevice("dev8", level=1, exists=True)


        parents_1 = [
           DiskDevice("name1", fmt=getFormat("mdmember"))
        ]
        dev_1 = MDContainerDevice(
           "parent",
           level="container",
           parents=parents_1
        )
        parents_2 = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember"))
        ]
        dev_2 = MDRaidArrayDevice(
           "other",
           level=0,
           fmt=getFormat("mdmember"),
           parents=parents_2
        )
        self.dev9 = MDBiosRaidArrayDevice(
           "dev9",
           level="raid0",
           memberDevices=2,
           parents=[dev_1, dev_2],
           totalDevices=2
        )

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember"))
        ]
        self.dev10 = MDRaidArrayDevice(
           "dev10",
           level="raid0",
           parents=parents,
           size=Size("32 MiB"))

        parents_1 = [
           DiskDevice("name1", fmt=getFormat("mdmember"))
        ]
        dev_1 = MDContainerDevice(
           "parent",
           level="container",
           parents=parents
        )
        parents_2 = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember"))
        ]
        dev_2 = MDRaidArrayDevice(
           "other",
           level=0,
           fmt=getFormat("mdmember"),
           parents=parents_2
        )
        self.dev11 = MDBiosRaidArrayDevice(
           "dev11",
           level=1,
           memberDevices=2,
           parents=[dev_1, dev_2],
           size=Size("32 MiB"),
           totalDevices=2)

        self.dev12 = MDBiosRaidArrayDevice(
           "dev12",
           level=1,
           memberDevices=2,
           parents=[
              Mock(**{"type": "mdcontainer",
                      "size": Size("4 MiB"),
                      "format": getFormat(None)}),
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

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember"))
        ]
        self.dev19 = MDRaidArrayDevice(
           "dev19",
           level="raid1",
           parents=parents,
           uuid='3386ff85-f501-2621-4a43-5f061eb47236'
        )

        parents = [
           DiskDevice("name1", fmt=getFormat("mdmember")),
           DiskDevice("name2", fmt=getFormat("mdmember"))
        ]
        self.dev20 = MDRaidArrayDevice(
           "dev20",
           level="raid1",
           parents=parents,
           uuid='Just-pretending'
        )

    def testMDRaidArrayDeviceInit(self):
        """Tests the state of a MDRaidArrayDevice after initialization.
           For some combinations of arguments the initializer will throw
           an exception.
        """

        ##
        ## level tests
        ##
        self.stateCheck(self.dev1,
           devices=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
           level=xform(lambda x, m: self.assertEqual(x.name, "container", m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
           mediaPresent=xform(self.assertFalse),
           type=xform(lambda x, m: self.assertEqual(x, "mdcontainer", m)))
        self.stateCheck(self.dev2,
           createBitmap=xform(self.assertFalse),
           devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)))
        self.stateCheck(self.dev3,
           devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)))
        self.stateCheck(self.dev4,
           devices=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 4, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 3, m)))
        self.stateCheck(self.dev5,
           devices=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 5, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 3, m)))
        self.stateCheck(self.dev6,
           devices=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 6, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 4, m)))
        self.stateCheck(self.dev7,
           devices=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 10, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 4, m)))

        ##
        ## existing device tests
        ##
        self.stateCheck(self.dev8,
           exists=xform(self.assertTrue),
           level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
           metadataVersion=xform(self.assertIsNone))


        ##
        ## mdbiosraidarray tests
        ##
        self.stateCheck(self.dev9,
           createBitmap=xform(self.assertFalse),
           devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           isDisk=xform(self.assertTrue),
           level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 2, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           partitionable=xform(self.assertTrue),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 2, m)),
           type = xform(lambda x, m: self.assertEqual(x, "mdbiosraidarray", m)))

        ##
        ## size tests
        ##
        self.stateCheck(self.dev10,
           createBitmap=xform(self.assertFalse),
           devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           targetSize=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)))

        self.stateCheck(self.dev11,
           devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           isDisk=xform(self.assertTrue),
           level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 2, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           partitionable=xform(self.assertTrue),
           targetSize=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 2, m)),
           type=xform(lambda x, m: self.assertEqual(x, "mdbiosraidarray", m)))

        self.stateCheck(self.dev12,
           devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           isDisk=xform(self.assertTrue),
           level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 2, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           partitionable=xform(self.assertTrue),
           targetSize=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 2, m)),
           type = xform(lambda x, m: self.assertEqual(x, "mdbiosraidarray", m)))

        self.stateCheck(self.dev13,
           createBitmap=xform(self.assertFalse),
           devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 3, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           size=xform(lambda x, m: self.assertEqual(x, Size("3 MiB"), m)),
           targetSize=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 3, m)))

        self.stateCheck(self.dev14,
           createBitmap=xform(self.assertTrue),
           devices=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 4, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 3, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           size=xform(lambda x, m: self.assertEqual(x, Size("2 MiB"), m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 3, m)))

        self.stateCheck(self.dev15,
           createBitmap=xform(self.assertTrue),
           devices=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 5, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 3, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           size=xform(lambda x, m: self.assertEqual(x, Size("2 MiB"), m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 3, m)))

        self.stateCheck(self.dev16,
           createBitmap=xform(self.assertTrue),
           devices=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 6, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 4, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           size=xform(lambda x, m: self.assertEqual(x, Size("2 MiB"), m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 4, m)))

        self.stateCheck(self.dev17,
           createBitmap=xform(self.assertTrue),
           devices=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 10, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 4, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           size=xform(lambda x, m: self.assertEqual(x, Size("2 MiB"), m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 4, m)))

        self.stateCheck(self.dev18,
           createBitmap=xform(self.assertTrue),
           devices=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
           level=xform(lambda x, m: self.assertEqual(x.number, 10, m)),
           memberDevices=xform(lambda x, m: self.assertEqual(x, 4, m)),
           parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
           size=xform(lambda x, m: self.assertEqual(x, Size("2 MiB"), m)),
           spares=xform(lambda x, m: self.assertEqual(x, 1, m)),
           totalDevices=xform(lambda x, m: self.assertEqual(x, 5, m)))

        self.stateCheck(self.dev19,
                        devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                        level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
                        mdadmFormatUUID=xform(lambda x, m: self.assertEqual(x, blockdev.md.get_md_uuid(self.dev19.uuid), m)),
                        parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                        uuid=xform(lambda x, m: self.assertEqual(x, self.dev19.uuid, m)))

        self.stateCheck(self.dev20,
                        devices=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                        level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
                        parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                        uuid=xform(lambda x, m: self.assertEqual(x, self.dev20.uuid, m)))

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice("dev")

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice("dev", level="raid2")

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice(
               "dev",
               parents=[StorageDevice("parent", fmt=getFormat("mdmember"))])

        with self.assertRaisesRegex(DeviceError, "at least 2 members"):
            MDRaidArrayDevice(
               "dev",
               level="raid0",
               parents=[StorageDevice("parent", fmt=getFormat("mdmember"))])

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice("dev", level="junk")

        with self.assertRaisesRegex(DeviceError, "at least 2 members"):
            MDRaidArrayDevice("dev", level=0, memberDevices=2)

    def testMDRaidArrayDeviceMethods(self):
        """Test for method calls on initialized MDRaidDevices."""
        with self.assertRaisesRegex(DeviceError, "invalid" ):
            self.dev7.level = "junk"

        with self.assertRaisesRegex(DeviceError, "invalid" ):
            self.dev7.level = None

class BTRFSDeviceTestCase(DeviceStateTestCase):
    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or correct behavior. See the initial
       commit message for this file for further details.
    """

    def __init__(self, methodName='runTest'):
        super(BTRFSDeviceTestCase, self).__init__(methodName=methodName)
        state_functions = {
           "dataLevel" : lambda d, a: self.assertFalse(hasattr(d,a)),
           "fstabSpec" : xform(self.assertIsNotNone),
           "mediaPresent" : xform(self.assertTrue),
           "metaDataLevel" : lambda d, a: self.assertFalse(hasattr(d, a)),
           "type" : xform(lambda x, m: self.assertEqual(x, "btrfs", m)),
           "vol_id" : xform(lambda x, m: self.assertEqual(x, btrfs.MAIN_VOLUME_ID, m))}
        self._state_functions.update(state_functions)

    def setUp(self):
        self.dev1 = BTRFSVolumeDevice("dev1",
           parents=[StorageDevice("deva",
              fmt=blivet.formats.getFormat("btrfs"),
              size=btrfs.MIN_MEMBER_SIZE)])

        self.dev2 = BTRFSSubVolumeDevice("dev2",
           parents=[self.dev1],
           fmt=blivet.formats.getFormat("btrfs"))

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
           currentSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           dataLevel=xform(self.assertIsNone),
           isleaf=xform(self.assertFalse),
           maxSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           metaDataLevel=xform(self.assertIsNone),
           parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
           size=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           type=xform(lambda x, m: self.assertEqual(x, "btrfs volume", m)))

        self.stateCheck(self.dev2,
           currentSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           maxSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
           size=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           type=xform(lambda x, m: self.assertEqual(x, "btrfs subvolume", m)),
           vol_id=xform(self.assertIsNone))

        self.stateCheck(self.dev3,
           currentSize=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
           dataLevel=xform(self.assertIsNone),
           maxSize=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
           metaDataLevel=xform(self.assertIsNone),
           parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
           size=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
           type=xform(lambda x, m: self.assertEqual(x, "btrfs volume", m)))

        with self.assertRaisesRegex(ValueError, "BTRFSDevice.*must have at least one parent"):
            BTRFSVolumeDevice("dev")

        with self.assertRaisesRegex(ValueError, "format"):
            BTRFSVolumeDevice("dev", parents=[StorageDevice("deva", size=btrfs.MIN_MEMBER_SIZE)])

        with self.assertRaisesRegex(DeviceError, "btrfs subvolume.*must be a btrfs volume"):
            fmt = blivet.formats.getFormat("btrfs")
            device = StorageDevice("deva", fmt=fmt, size=btrfs.MIN_MEMBER_SIZE)
            BTRFSSubVolumeDevice("dev1", parents=[device])

        deva = OpticalDevice("deva", fmt=blivet.formats.getFormat("btrfs"))
        with self.assertRaisesRegex(BTRFSValueError, "at least"):
            BTRFSVolumeDevice("dev1", dataLevel="raid1", parents=[deva])

        deva = StorageDevice("deva", fmt=blivet.formats.getFormat("btrfs"), size=btrfs.MIN_MEMBER_SIZE)
        self.assertIsNotNone(BTRFSVolumeDevice("dev1", metaDataLevel="dup", parents=[deva]))

        deva = StorageDevice("deva", fmt=blivet.formats.getFormat("btrfs"), size=btrfs.MIN_MEMBER_SIZE)
        with self.assertRaisesRegex(BTRFSValueError, "invalid"):
            BTRFSVolumeDevice("dev1", dataLevel="dup", parents=[deva])

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
        with self.assertRaisesRegex(RuntimeError, "cannot directly set size of btrfs volume"):
            self.dev1.size = 32

    def testBTRFSSnapShotDeviceInit(self):
        parents = [StorageDevice("p1", fmt=blivet.formats.getFormat("btrfs"), size=btrfs.MIN_MEMBER_SIZE)]
        vol = BTRFSVolumeDevice("test", parents=parents)
        with self.assertRaisesRegex(ValueError, "non-existent btrfs snapshots must have a source"):
            BTRFSSnapShotDevice("snap1", parents=[vol])

        with self.assertRaisesRegex(ValueError, "btrfs snapshot source must already exist"):
            BTRFSSnapShotDevice("snap1", parents=[vol], source=vol)

        with self.assertRaisesRegex(ValueError, "btrfs snapshot source must be a btrfs subvolume"):
            BTRFSSnapShotDevice("snap1", parents=[vol], source=parents[0])

        parents2 = [StorageDevice("p1", fmt=blivet.formats.getFormat("btrfs"), size=btrfs.MIN_MEMBER_SIZE)]
        vol2 = BTRFSVolumeDevice("test2", parents=parents2, exists=True)
        with self.assertRaisesRegex(ValueError, ".*snapshot and source must be in the same volume"):
            BTRFSSnapShotDevice("snap1", parents=[vol], source=vol2)

        vol.exists = True
        snap = BTRFSSnapShotDevice("snap1",
           fmt=blivet.formats.getFormat("btrfs"),
           parents=[vol],
           source=vol)
        self.stateCheck(snap,
           currentSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           maxSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
           size=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           type=xform(lambda x, m: self.assertEqual(x, "btrfs snapshot", m)),
           vol_id=xform(self.assertIsNone))
        self.stateCheck(vol,
           currentSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           dataLevel=xform(self.assertIsNone),
           exists=xform(self.assertTrue),
           isleaf=xform(self.assertFalse),
           maxSize=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           metaDataLevel=xform(self.assertIsNone),
           parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
           size=xform(lambda x, m: self.assertEqual(x, btrfs.MIN_MEMBER_SIZE, m)),
           type=xform(lambda x, m: self.assertEqual(x, "btrfs volume", m)))

        self.assertEqual(snap.isleaf, True)
        self.assertEqual(snap.direct, True)
        self.assertEqual(vol.isleaf, False)
        self.assertEqual(vol.direct, True)

        self.assertEqual(snap.dependsOn(vol), True)
        self.assertEqual(vol.dependsOn(snap), False)
