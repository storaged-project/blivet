# vim:set fileencoding=utf-8
from six import PY3
if PY3:
    from unittest.mock import patch, PropertyMock
else:
    from mock import patch, PropertyMock

import unittest

from blivet.deviceaction import ActionCreateDevice
from blivet.deviceaction import ActionDestroyDevice
from blivet.deviceaction import ActionResizeDevice

from blivet.deviceaction import ActionCreateFormat
from blivet.deviceaction import ActionDestroyFormat

from blivet.devices import DiskDevice
from blivet.devices import LUKSDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import PartitionDevice
from blivet.devices import StorageDevice

from blivet.formats import get_format

from blivet.size import Size

from blivet.tasks import availability


class DeviceDependenciesTestCase(unittest.TestCase):

    """Test external device dependencies. """

    def test_dependencies(self):
        dev1 = DiskDevice("name", fmt=get_format("mdmember"))
        dev2 = DiskDevice("other", fmt=get_format("mdmember"))
        dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, dev2])
        luks = LUKSDevice("luks", parents=[dev])

        # a parent's dependencies are a subset of its child's.
        for d in dev.external_dependencies:
            self.assertIn(d, luks.external_dependencies)

        # make sure that there's at least something in these dependencies
        self.assertGreater(len(luks.external_dependencies), 0)


class MockingDeviceDependenciesTestCase1(unittest.TestCase):

    """Test availability of external device dependencies. """

    def setUp(self):
        dev1 = DiskDevice("name", fmt=get_format("mdmember"), size=Size("1 GiB"))
        dev2 = DiskDevice("other")
        self.part = PartitionDevice("part", fmt=get_format("mdmember"), parents=[dev2])
        self.dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, self.part], fmt=get_format("luks"), total_devices=2, member_devices=2)
        self.luks = LUKSDevice("luks", parents=[self.dev], fmt=get_format("ext4"))

        self.mdraid_method = availability.BLOCKDEV_MDRAID_PLUGIN._method
        self.dm_method = availability.BLOCKDEV_DM_PLUGIN._method
        self.cache_availability = availability.CACHE_AVAILABILITY

        self.addCleanup(self._clean_up)

    def test_availability_mdraidplugin(self):

        availability.CACHE_AVAILABILITY = False
        availability.BLOCKDEV_DM_PLUGIN._method = availability.AvailableMethod

        # if the plugin is not in, there's nothing to test
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.external_dependencies)

        # dev is not among its unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = availability.AvailableMethod
        availability.MKFS_HFSPLUS_APP._method = availability.AvailableMethod  # macefi
        self.assertNotIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailable_dependencies)
        self.assertIsNotNone(ActionCreateDevice(self.luks))
        self.assertIsNotNone(ActionDestroyDevice(self.luks))
        self.assertIsNotNone(ActionCreateFormat(self.luks, fmt=get_format("macefi")))
        self.assertIsNotNone(ActionDestroyFormat(self.luks))

        # dev is among the unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = availability.UnavailableMethod
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailable_dependencies)
        with self.assertRaises(ValueError):
            ActionCreateDevice(self.luks)
        with self.assertRaises(ValueError):
            ActionDestroyDevice(self.dev)
        with self.assertRaises(ValueError):
            ActionCreateFormat(self.dev)
        with self.assertRaises(ValueError):
            ActionDestroyFormat(self.dev)

    def _clean_up(self):
        availability.BLOCKDEV_MDRAID_PLUGIN._method = self.mdraid_method
        availability.BLOCKDEV_DM_PLUGIN._method = self.dm_method

        availability.CACHE_AVAILABILITY = False
        availability.BLOCKDEV_MDRAID_PLUGIN.available  # pylint: disable=pointless-statement
        availability.BLOCKDEV_DM_PLUGIN.available  # pylint: disable=pointless-statement

        availability.CACHE_AVAILABILITY = self.cache_availability


class MockingDeviceDependenciesTestCase2(unittest.TestCase):
    def test_dependencies_handling(self):
        device = StorageDevice("testdev1")
        self.assertTrue(device.controllable)
        self.assertIsNotNone(ActionCreateDevice(device))
        device.exists = True
        self.assertIsNotNone(ActionDestroyDevice(device))
        with patch.object(StorageDevice, "resizable", new_callable=PropertyMock(return_value=True)):
            self.assertIsNotNone(ActionResizeDevice(device, Size("1 GiB")))

        # if any external dependency is missing, it should be impossible to create, destroy, setup,
        # teardown, or resize the device (controllable encompasses setup & teardown)
        with patch.object(StorageDevice, "_external_dependencies",
                          new_callable=PropertyMock(return_value=[availability.unavailable_resource("testing")])):
            device = StorageDevice("testdev1")
            self.assertFalse(device.controllable)
            self.assertRaises(ValueError, ActionCreateDevice, device)
            device.exists = True
            self.assertRaises(ValueError, ActionDestroyDevice, device)
            self.assertRaises(ValueError, ActionResizeDevice, device, Size("1 GiB"))

        # same goes for formats, except that the properties they affect vary by format class
        fmt = get_format("lvmpv")
        fmt._plugin = availability.available_resource("lvm-testing")
        self.assertTrue(fmt.supported)
        self.assertTrue(fmt.formattable)
        self.assertTrue(fmt.destroyable)

        fmt._plugin = availability.unavailable_resource("lvm-testing")
        self.assertFalse(fmt.supported)
        self.assertFalse(fmt.formattable)
        self.assertFalse(fmt.destroyable)
