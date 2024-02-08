import unittest
from unittest.mock import patch, Mock

import gi
gi.require_version("BlockDev", "3.0")

from gi.repository import BlockDev as blockdev

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
from blivet.devices import LVMVolumeGroupDevice, LVMLogicalVolumeDevice
from blivet.devices.lvm import LVMCacheRequest, LVMCache
from blivet.devicelibs import btrfs
from blivet.devicelibs import mdraid
from blivet.size import Size

from blivet.formats import get_format

BTRFS_MIN_MEMBER_SIZE = get_format("btrfs").min_size

# pylint: disable=unnecessary-lambda


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

    def __init__(self, methodName='run_test'):
        self._state_functions = {
            "current_size": xform(lambda x, m: self.assertEqual(x, Size(0), m)),
            "direct": xform(self.assertTrue),
            "exists": xform(self.assertFalse),
            "format": xform(self.assertIsNotNone),
            "format_args": xform(lambda x, m: self.assertEqual(x, [], m)),
            "is_disk": xform(self.assertFalse),
            "isleaf": xform(self.assertTrue),
            "major": xform(lambda x, m: self.assertEqual(x, 0, m)),
            "max_size": xform(lambda x, m: self.assertEqual(x, Size(0), m)),
            "media_present": xform(self.assertTrue),
            "minor": xform(lambda x, m: self.assertEqual(x, 0, m)),
            "parents": xform(lambda x, m: self.assertEqual(len(x), 0, m) and
                             self.assertIsInstance(x, ParentList, m)),
            "partitionable": xform(self.assertFalse),
            "path": xform(lambda x, m: self.assertRegex(x, "^/dev", m)),
            "raw_device": xform(self.assertIsNotNone),
            "resizable": xform(self.assertFalse),
            "size": xform(lambda x, m: self.assertEqual(x, Size(0), m)),
            "status": xform(self.assertFalse),
            "sysfs_path": xform(lambda x, m: self.assertEqual(x, "", m)),
            "target_size": xform(lambda x, m: self.assertEqual(x, Size(0), m)),
            "type": xform(lambda x, m: self.assertEqual(x, "mdarray", m)),
            "uuid": xform(self.assertIsNone)
        }
        super(DeviceStateTestCase, self).__init__(methodName=methodName)

    def state_check(self, device, **kwargs):
        """Checks the current state of a device by means of its
           fields or properties.

           Every kwarg should be a key which is a field or property
           of a Device and a value which is a function of
           two parameters and should call the appropriate assert* functions.
           These values override those in the state_functions dict.

           If the value is None, then the test starts the debugger instead.
        """
        self.longMessage = True
        for k, v in self._state_functions.items():
            if k in kwargs:
                test_func = kwargs[k]
                if test_func is None:
                    getattr(device, k)
                else:
                    test_func(device, k)
            else:
                v(device, k)

    def test_resizable(self):
        """ Test resizable property of unformatted devices. """
        # Devices with no (or unrecognized) formatting should not be resizable.
        device = StorageDevice("testdev1", exists=True, size=Size("100 G"), fmt=get_format("ext4", exists=True))
        device._resizable = True
        with patch.object(device, "_format", exists=True, resizable=True):
            self.assertTrue(device.resizable)

        device = StorageDevice("testdev1", exists=True, size=Size("100 G"))
        device._resizable = True
        self.assertFalse(device.resizable)


class MDRaidArrayDeviceTestCase(DeviceStateTestCase):

    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or correct behavior. See the initial
       commit message for this file for further details.
    """

    def __init__(self, methodName='run_test'):
        super(MDRaidArrayDeviceTestCase, self).__init__(methodName=methodName)
        state_functions = {
            "create_bitmap": xform(lambda d, a: self.assertFalse),
            "description": xform(self.assertIsNotNone),
            "format_class": xform(self.assertIsNotNone),
            "level": xform(self.assertIsNone),
            "mdadm_format_uuid": xform(self.assertIsNone),
            "member_devices": xform(lambda x, m: self.assertEqual(x, 0, m)),
            "members": xform(lambda x, m: self.assertEqual(len(x), 0, m) and
                             self.assertIsInstance(x, list, m)),
            "metadata_version": xform(lambda x, m: self.assertEqual(x, "default", m)),
            "spares": xform(lambda x, m: self.assertEqual(x, 0, m)),
            "total_devices": xform(lambda x, m: self.assertEqual(x, 0, m))
        }
        self._state_functions.update(state_functions)

    def setUp(self):
        self.md_chunk_size = mdraid.MD_CHUNK_SIZE
        mdraid.MD_CHUNK_SIZE = Size("1 MiB")
        self.get_superblock_size = MDRaidArrayDevice.get_superblock_size
        MDRaidArrayDevice.get_superblock_size = lambda a, s: Size(0)

        self.addCleanup(self._clean_up)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember"))
        ]
        self.dev1 = MDContainerDevice("dev1", level="container", parents=parents, total_devices=1, member_devices=1)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember"), size=Size("1 GiB")),
            DiskDevice("name2", fmt=get_format("mdmember"), size=Size("1 GiB"))
        ]
        self.dev2 = MDRaidArrayDevice("dev2", level="raid0", parents=parents,
                                      total_devices=2, member_devices=2)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember"))
        ]
        self.dev3 = MDRaidArrayDevice("dev3", level="raid1", parents=parents)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember")),
            DiskDevice("name3", fmt=get_format("mdmember"))
        ]
        self.dev4 = MDRaidArrayDevice("dev4", level="raid4", parents=parents)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember")),
            DiskDevice("name3", fmt=get_format("mdmember"))
        ]
        self.dev5 = MDRaidArrayDevice("dev5", level="raid5", parents=parents)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember")),
            DiskDevice("name3", fmt=get_format("mdmember")),
            DiskDevice("name4", fmt=get_format("mdmember"))
        ]
        self.dev6 = MDRaidArrayDevice("dev6", level="raid6", parents=parents)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember")),
            DiskDevice("name3", fmt=get_format("mdmember")),
            DiskDevice("name4", fmt=get_format("mdmember"))
        ]
        self.dev7 = MDRaidArrayDevice("dev7", level="raid10", parents=parents)

        self.dev8 = MDRaidArrayDevice("dev8", level=1, exists=True)

        parents_1 = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember"))
        ]
        dev_1 = MDContainerDevice(
            "parent",
            level="container",
            parents=parents_1,
            total_devices=2,
            member_devices=2,
            exists=True
        )
        self.dev9 = MDBiosRaidArrayDevice(
            "dev9",
            level="raid0",
            member_devices=1,
            parents=[dev_1],
            total_devices=1,
            exists=True
        )

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember"))
        ]
        self.dev10 = MDRaidArrayDevice(
            "dev10",
            level="raid0",
            parents=parents,
            size=Size("32 MiB"))

        parents_1 = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember"))
        ]
        dev_1 = MDContainerDevice(
            "parent",
            level="container",
            parents=parents,
            total_devices=2,
            member_devices=2
        )
        self.dev11 = MDBiosRaidArrayDevice(
            "dev11",
            level=1,
            exists=True,
            parents=[dev_1],
            size=Size("32 MiB"))

        self.dev13 = MDRaidArrayDevice(
            "dev13",
            level=0,
            member_devices=2,
            parents=[
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")})],
            size=Size("32 MiB"),
            total_devices=2)

        self.dev14 = MDRaidArrayDevice(
            "dev14",
            level=4,
            member_devices=3,
            parents=[
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")})],
            total_devices=3)

        self.dev15 = MDRaidArrayDevice(
            "dev15",
            level=5,
            member_devices=3,
            parents=[
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")})],
            total_devices=3)

        self.dev16 = MDRaidArrayDevice(
            "dev16",
            level=6,
            member_devices=4,
            parents=[
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")})],
            total_devices=4)

        self.dev17 = MDRaidArrayDevice(
            "dev17",
            level=10,
            member_devices=4,
            parents=[
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")})],
            total_devices=4)

        self.dev18 = MDRaidArrayDevice(
            "dev18",
            level=10,
            member_devices=4,
            parents=[
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("4 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")}),
                Mock(**{"size": Size("2 MiB"),
                        "format": get_format("mdmember")})],
            total_devices=5)

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember"))
        ]
        self.dev19 = MDRaidArrayDevice(
            "dev19",
            level="raid1",
            parents=parents,
            uuid='3386ff85-f501-2621-4a43-5f061eb47236'
        )

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember"))
        ]
        self.dev20 = MDRaidArrayDevice(
            "dev20",
            level="raid1",
            parents=parents,
            uuid='Just-pretending'
        )

    def _clean_up(self):
        mdraid.MD_CHUNK_SIZE = self.md_chunk_size
        MDRaidArrayDevice.get_superblock_size = self.get_superblock_size

    def test_mdraid_array_device_init(self):
        """Tests the state of a MDRaidArrayDevice after initialization.
           For some combinations of arguments the initializer will throw
           an exception.
        """

        ##
        # level tests
        ##
        self.state_check(self.dev1,
                         level=xform(lambda x, m: self.assertEqual(x.name, "container", m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 1, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         media_present=xform(self.assertFalse),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 1, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "mdcontainer", m)))
        self.state_check(self.dev2,
                         create_bitmap=xform(self.assertFalse),
                         level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("2 GiB"), m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 2, m)))
        self.state_check(self.dev3,
                         level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)))
        self.state_check(self.dev4,
                         level=xform(lambda x, m: self.assertEqual(x.number, 4, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 3, m)))
        self.state_check(self.dev5,
                         level=xform(lambda x, m: self.assertEqual(x.number, 5, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 3, m)))
        self.state_check(self.dev6,
                         level=xform(lambda x, m: self.assertEqual(x.number, 6, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 4, m)))
        self.state_check(self.dev7,
                         level=xform(lambda x, m: self.assertEqual(x.number, 10, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 4, m)))

        ##
        # existing device tests
        ##
        self.state_check(self.dev8,
                         exists=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
                         metadata_version=xform(self.assertIsNone))

        ##
        # mdbiosraidarray tests
        ##
        self.state_check(self.dev9,
                         create_bitmap=xform(self.assertFalse),
                         is_disk=xform(self.assertTrue),
                         exists=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         metadata_version=xform(lambda x, m: self.assertEqual(x, None, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         partitionable=xform(self.assertTrue),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "mdbiosraidarray", m)))

        ##
        # mdcontainer tests
        ##
        dev9_container = self.dev9.parents[0]
        self.state_check(dev9_container,
                         create_bitmap=xform(self.assertFalse),
                         direct=xform(self.assertFalse),
                         is_disk=xform(self.assertFalse),
                         isleaf=xform(self.assertFalse),
                         exists=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.name, "container", m)),
                         media_present=xform(self.assertFalse),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         metadata_version=xform(lambda x, m: self.assertEqual(x, None, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         partitionable=xform(self.assertFalse),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "mdcontainer", m)))

        ##
        # size tests
        ##
        self.state_check(self.dev10,
                         create_bitmap=xform(self.assertFalse),
                         level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         target_size=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)))

        self.state_check(self.dev11,
                         is_disk=xform(self.assertTrue),
                         exists=xform(lambda x, m: self.assertEqual(x, True, m)),
                         level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
                         current_size=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
                         max_size=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         metadata_version=xform(lambda x, m: self.assertEqual(x, None, m)),
                         parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
                         partitionable=xform(self.assertTrue),
                         size=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
                         target_size=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "mdbiosraidarray", m)))

        self.state_check(self.dev13,
                         create_bitmap=xform(self.assertFalse),
                         level=xform(lambda x, m: self.assertEqual(x.number, 0, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 2, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("4 MiB"), m)),
                         target_size=xform(lambda x, m: self.assertEqual(x, Size("32 MiB"), m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 2, m)))

        self.state_check(self.dev14,
                         create_bitmap=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.number, 4, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 3, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
                         parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("4 MiB"), m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 3, m)))

        self.state_check(self.dev15,
                         create_bitmap=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.number, 5, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 3, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 3, m)),
                         parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("4 MiB"), m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 3, m)))

        self.state_check(self.dev16,
                         create_bitmap=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.number, 6, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 4, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
                         parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("4 MiB"), m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 4, m)))

        self.state_check(self.dev17,
                         create_bitmap=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.number, 10, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 4, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
                         parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("4 MiB"), m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 4, m)))

        self.state_check(self.dev18,
                         create_bitmap=xform(self.assertTrue),
                         level=xform(lambda x, m: self.assertEqual(x.number, 10, m)),
                         member_devices=xform(lambda x, m: self.assertEqual(x, 4, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 4, m)),
                         parents=xform(lambda x, m: self.assertNotEqual(x, [], m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("4 MiB"), m)),
                         spares=xform(lambda x, m: self.assertEqual(x, 1, m)),
                         total_devices=xform(lambda x, m: self.assertEqual(x, 5, m)))

        self.state_check(self.dev19,
                         level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
                         mdadm_format_uuid=xform(lambda x, m: self.assertEqual(x, blockdev.md.get_md_uuid(self.dev19.uuid), m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         uuid=xform(lambda x, m: self.assertEqual(x, self.dev19.uuid, m)))

        self.state_check(self.dev20,
                         level=xform(lambda x, m: self.assertEqual(x.number, 1, m)),
                         members=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 2, m)),
                         uuid=xform(lambda x, m: self.assertEqual(x, self.dev20.uuid, m)))

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice("dev")

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice("dev", level="raid2")

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice(
                "dev",
                parents=[StorageDevice("parent", fmt=get_format("mdmember"))])

        with self.assertRaisesRegex(DeviceError, "at least 2 members"):
            MDRaidArrayDevice(
                "dev",
                level="raid0",
                parents=[StorageDevice("parent", fmt=get_format("mdmember"))])

        with self.assertRaisesRegex(DeviceError, "invalid"):
            MDRaidArrayDevice("dev", level="junk")

        with self.assertRaisesRegex(DeviceError, "at least 2 members"):
            MDRaidArrayDevice("dev", level=0, member_devices=2)

    def test_mdraid_array_device_methods(self):
        """Test for method calls on initialized MDRaidDevices."""
        with self.assertRaisesRegex(DeviceError, "invalid"):
            self.dev7.level = "junk"

        with self.assertRaisesRegex(DeviceError, "invalid"):
            self.dev7.level = None


class BTRFSDeviceTestCase(DeviceStateTestCase):

    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or correct behavior. See the initial
       commit message for this file for further details.
    """

    def __init__(self, methodName='run_test'):
        super(BTRFSDeviceTestCase, self).__init__(methodName=methodName)
        state_functions = {
            "data_level": lambda d, a: self.assertFalse(hasattr(d, a)),
            "fstab_spec": xform(self.assertIsNotNone),
            "media_present": xform(self.assertTrue),
            "metadata_level": lambda d, a: self.assertFalse(hasattr(d, a)),
            "type": xform(lambda x, m: self.assertEqual(x, "btrfs", m)),
            "vol_id": xform(lambda x, m: self.assertEqual(x, btrfs.MAIN_VOLUME_ID, m))
        }
        self._state_functions.update(state_functions)

    def setUp(self):
        self.dev1 = BTRFSVolumeDevice("dev1",
                                      parents=[StorageDevice("deva",
                                                             fmt=blivet.formats.get_format("btrfs"),
                                                             size=BTRFS_MIN_MEMBER_SIZE)])

        self.dev2 = BTRFSSubVolumeDevice("dev2",
                                         parents=[self.dev1],
                                         fmt=blivet.formats.get_format("btrfs"))

        dev = StorageDevice("deva",
                            fmt=blivet.formats.get_format("btrfs"),
                            size=Size("500 MiB"))
        self.dev3 = BTRFSVolumeDevice("dev3",
                                      parents=[dev])

    def test_btrfsdevice_init(self):
        """Tests the state of a BTRFSDevice after initialization.
           For some combinations of arguments the initializer will throw
           an exception.
        """

        self.state_check(self.dev1,
                         current_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         data_level=xform(self.assertIsNone),
                         isleaf=xform(self.assertFalse),
                         max_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         metadata_level=xform(self.assertIsNone),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "btrfs volume", m)),
                         uuid=xform(self.assertIsNotNone))

        self.state_check(self.dev2,
                         target_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         current_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         max_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "btrfs subvolume", m)),
                         vol_id=xform(self.assertIsNone))

        self.state_check(self.dev3,
                         current_size=xform(lambda x, m: self.assertEqual(x, Size("500 MiB"), m)),
                         data_level=xform(self.assertIsNone),
                         max_size=xform(lambda x, m: self.assertEqual(x, Size("500 MiB"), m)),
                         metadata_level=xform(self.assertIsNone),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         size=xform(lambda x, m: self.assertEqual(x, Size("500 MiB"), m)),
                         type=xform(lambda x, m: self.assertEqual(x, "btrfs volume", m)),
                         uuid=xform(self.assertIsNotNone))

        with self.assertRaisesRegex(ValueError, "BTRFSDevice.*must have at least one parent"):
            BTRFSVolumeDevice("dev")

        with self.assertRaisesRegex(ValueError, "format"):
            BTRFSVolumeDevice("dev", parents=[StorageDevice("deva", size=BTRFS_MIN_MEMBER_SIZE)])

        with self.assertRaisesRegex(DeviceError, "btrfs subvolume.*must be a btrfs volume"):
            fmt = blivet.formats.get_format("btrfs")
            device = StorageDevice("deva", fmt=fmt, size=BTRFS_MIN_MEMBER_SIZE)
            BTRFSSubVolumeDevice("dev1", parents=[device])

        deva = OpticalDevice("deva", fmt=blivet.formats.get_format("btrfs", exists=True),
                             exists=True)
        with self.assertRaisesRegex(BTRFSValueError, "at least"):
            BTRFSVolumeDevice("dev1", data_level="raid1", parents=[deva])

        deva = StorageDevice("deva", fmt=blivet.formats.get_format("btrfs"), size=BTRFS_MIN_MEMBER_SIZE)
        self.assertIsNotNone(BTRFSVolumeDevice("dev1", metadata_level="dup", parents=[deva]))

        deva = StorageDevice("deva", fmt=blivet.formats.get_format("btrfs"), size=BTRFS_MIN_MEMBER_SIZE)
        with self.assertRaisesRegex(BTRFSValueError, "invalid"):
            BTRFSVolumeDevice("dev1", data_level="dup", parents=[deva])

        self.assertEqual(self.dev1.isleaf, False)
        self.assertEqual(self.dev1.direct, True)
        self.assertEqual(self.dev2.isleaf, True)
        self.assertEqual(self.dev2.direct, True)

        member = self.dev1.parents[0]
        self.assertEqual(member.isleaf, False)
        self.assertEqual(member.direct, False)

    def test_btrfsdevice_methods(self):
        """Test for method calls on initialized BTRFS Devices."""
        # volumes do not have ancestor volumes
        with self.assertRaises(AttributeError):
            self.dev1.volume  # pylint: disable=no-member,pointless-statement

        # subvolumes do not have default subvolumes
        with self.assertRaises(AttributeError):
            self.dev2.default_sub_volume  # pylint: disable=no-member,pointless-statement

        self.assertIsNotNone(self.dev2.volume)

        # size
        with self.assertRaisesRegex(RuntimeError, "cannot directly set size of btrfs volume"):
            self.dev1.size = Size("500 MiB")

    def test_btrfssnap_shot_device_init(self):
        parents = [StorageDevice("p1", fmt=blivet.formats.get_format("btrfs"), size=BTRFS_MIN_MEMBER_SIZE)]
        vol = BTRFSVolumeDevice("test", parents=parents)
        with self.assertRaisesRegex(ValueError, "non-existent btrfs snapshots must have a source"):
            BTRFSSnapShotDevice("snap1", parents=[vol])

        with self.assertRaisesRegex(ValueError, "btrfs snapshot source must already exist"):
            BTRFSSnapShotDevice("snap1", parents=[vol], source=vol)

        with self.assertRaisesRegex(ValueError, "btrfs snapshot source must be a btrfs subvolume"):
            BTRFSSnapShotDevice("snap1", parents=[vol], source=parents[0])

        parents2 = [StorageDevice("p1", fmt=blivet.formats.get_format("btrfs"), size=BTRFS_MIN_MEMBER_SIZE, exists=True)]
        vol2 = BTRFSVolumeDevice("test2", parents=parents2, exists=True)
        with self.assertRaisesRegex(ValueError, ".*snapshot and source must be in the same volume"):
            BTRFSSnapShotDevice("snap1", parents=[vol], source=vol2)

        vol.exists = True
        snap = BTRFSSnapShotDevice("snap1",
                                   fmt=blivet.formats.get_format("btrfs"),
                                   parents=[vol],
                                   source=vol)
        self.state_check(snap,
                         current_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         target_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         max_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "btrfs snapshot", m)),
                         vol_id=xform(self.assertIsNone))
        self.state_check(vol,
                         current_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         data_level=xform(self.assertIsNone),
                         exists=xform(self.assertTrue),
                         isleaf=xform(self.assertFalse),
                         max_size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         metadata_level=xform(self.assertIsNone),
                         parents=xform(lambda x, m: self.assertEqual(len(x), 1, m)),
                         size=xform(lambda x, m: self.assertEqual(x, BTRFS_MIN_MEMBER_SIZE, m)),
                         type=xform(lambda x, m: self.assertEqual(x, "btrfs volume", m)),
                         uuid=xform(self.assertIsNotNone))

        self.assertEqual(snap.isleaf, True)
        self.assertEqual(snap.direct, True)
        self.assertEqual(vol.isleaf, False)
        self.assertEqual(vol.direct, True)

        self.assertEqual(snap.depends_on(vol), True)
        self.assertEqual(vol.depends_on(snap), False)


class LVMLogicalVolumeDeviceTestCase(DeviceStateTestCase):

    def __init__(self, methodName="run_test"):
        super(LVMLogicalVolumeDeviceTestCase, self).__init__(methodName=methodName)
        state_functions = {
            "type": xform(lambda x, m: self.assertEqual(x, "lvmlv", m)),
            "parents": xform(lambda x, m: self.assertEqual(len(x), 1, m) and
                             self.assertIsInstance(x, ParentList) and
                             self.assertIsInstance(x[0], LVMVolumeGroupDevice)),
            "size": xform(lambda x, m: self.assertEqual(x, self.fmt._min_size, m)),
            "target_size": xform(lambda x, m: self.assertEqual(x, self.fmt._min_size, m))
        }

        self._state_functions.update(state_functions)

    def setUp(self):
        pv = StorageDevice("pv1", fmt=blivet.formats.get_format("lvmpv"),
                           size=Size("1 GiB"))
        vg = LVMVolumeGroupDevice("testvg", parents=[pv])
        self.fmt = blivet.formats.get_format("xfs")
        self.lv = LVMLogicalVolumeDevice("testlv", parents=[vg],
                                         fmt=self.fmt)

        pv2 = StorageDevice("pv2", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("1 GiB"))
        pv3 = StorageDevice("pv3", fmt=blivet.formats.get_format("lvmpv"),
                            size=Size("1 GiB"))
        vg2 = LVMVolumeGroupDevice("testvg2", parents=[pv2, pv3])
        cache_req = LVMCacheRequest(Size("512 MiB"), [pv3], "writethrough")
        self.cached_lv = LVMLogicalVolumeDevice("testcachedlv", parents=[vg2],
                                                fmt=blivet.formats.get_format("xfs"),
                                                exists=False, cache_request=cache_req)

    def test_lvmlogical_volume_device_init(self):
        self.state_check(self.lv,
                         # 1 GiB - one extent
                         max_size=xform(lambda x, m: self.assertEqual(x, Size("1020 MiB"), m) and
                                        self.assertIsInstance(x, Size, m)),
                         snapshots=xform(lambda x, m: self.assertEqual(x, [], m)),
                         seg_type=xform(lambda x, m: self.assertEqual(x, "linear", m)),
                         req_grow=xform(lambda x, m: self.assertEqual(x, None, m)),
                         req_max_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                            self.assertIsInstance(x, Size, m)),
                         req_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                        self.assertIsInstance(x, Size, m)),
                         req_percent=xform(lambda x, m: self.assertEqual(x, Size(0), m)),
                         copies=xform(lambda x, m: self.assertEqual(x, 1, m)),
                         log_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                        self.assertIsInstance(x, Size, m)),
                         metadata_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                             self.assertIsInstance(x, Size, m)),
                         mirrored=xform(lambda x, m: self.assertFalse(x, m)),
                         vg_space_used=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                             self.assertIsInstance(x, Size, m)),
                         vg=xform(lambda x, m: self.assertIsInstance(x, LVMVolumeGroupDevice)),
                         container=xform(lambda x, m: self.assertIsInstance(x, LVMVolumeGroupDevice)),
                         map_name=xform(lambda x, m: self.assertEqual(x, "testvg-testlv", m)),
                         path=xform(lambda x, m: self.assertEqual(x, "/dev/mapper/testvg-testlv", m)),
                         lvname=xform(lambda x, m: self.assertEqual(x, "testlv", m)),
                         complete=xform(lambda x, m: self.assertTrue(x, m)),
                         isleaf=xform(lambda x, m: self.assertTrue(x, m)),
                         direct=xform(lambda x, m: self.assertTrue(x, m)),
                         cached=xform(lambda x, m: self.assertFalse(x, m)),
                         )

    def test_lvmlogical_volume_device_init_cached(self):
        self.state_check(self.cached_lv,
                         # 2 * (1 GiB - one extent) - 504 MiB - 8 MiB
                         #       PVfree               cache     pmspare
                         # NOTE: cache reserves space for the pmspare LV
                         max_size=xform(lambda x, m: self.assertEqual(x, Size("1528 MiB"), m) and
                                        self.assertIsInstance(x, Size, m)),
                         snapshots=xform(lambda x, m: self.assertEqual(x, [], m)),
                         seg_type=xform(lambda x, m: self.assertEqual(x, "linear", m)),
                         req_grow=xform(lambda x, m: self.assertEqual(x, None, m)),
                         req_max_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                            self.assertIsInstance(x, Size, m)),
                         req_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                        self.assertIsInstance(x, Size, m)),
                         req_percent=xform(lambda x, m: self.assertEqual(x, Size(0), m)),
                         copies=xform(lambda x, m: self.assertEqual(x, 1, m)),
                         log_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                        self.assertIsInstance(x, Size, m)),
                         metadata_size=xform(lambda x, m: self.assertEqual(x, Size(0), m) and
                                             self.assertIsInstance(x, Size, m)),
                         mirrored=xform(lambda x, m: self.assertFalse(x, m)),
                         vg_space_used=xform(lambda x, m: self.assertEqual(x, Size("512 MiB"), m) and
                                             self.assertIsInstance(x, Size, m)),
                         vg=xform(lambda x, m: self.assertIsInstance(x, LVMVolumeGroupDevice)),
                         container=xform(lambda x, m: self.assertIsInstance(x, LVMVolumeGroupDevice)),
                         map_name=xform(lambda x, m: self.assertEqual(x, "testvg2-testcachedlv", m)),
                         path=xform(lambda x, m: self.assertEqual(x, "/dev/mapper/testvg2-testcachedlv", m)),
                         lvname=xform(lambda x, m: self.assertEqual(x, "testcachedlv", m)),
                         complete=xform(lambda x, m: self.assertTrue(x, m)),
                         isleaf=xform(lambda x, m: self.assertTrue(x, m)),
                         direct=xform(lambda x, m: self.assertTrue(x, m)),
                         cached=xform(lambda x, m: self.assertTrue(x, m)),
                         cache=xform(lambda x, m: self.assertIsInstance(x, LVMCache, m)),
                         )
