# vim:set fileencoding=utf-8

import unittest

from blivet.deviceaction import ActionCreateDevice
from blivet.deviceaction import ActionDestroyDevice

from blivet.deviceaction import ActionCreateFormat
from blivet.deviceaction import ActionDestroyFormat

from blivet.devices import DiskDevice
from blivet.devices import LUKSDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import PartitionDevice

from blivet.formats import getFormat

from blivet.size import Size

from blivet.tasks import availability

class DeviceDependenciesTestCase(unittest.TestCase):
    """Test external device dependencies. """

    def testDependencies(self):
        dev1 = DiskDevice("name", fmt=getFormat("mdmember"))
        dev2 = DiskDevice("other", fmt=getFormat("mdmember"))
        dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1,dev2])
        luks = LUKSDevice("luks", parents=[dev])

        # a parent's dependencies are a subset of its child's.
        for d in dev.externalDependencies:
            self.assertIn(d, luks.externalDependencies)

        # make sure that there's at least something in these dependencies
        self.assertGreater(len(luks.externalDependencies), 0)

class MockingDeviceDependenciesTestCase(unittest.TestCase):
    """Test availability of external device dependencies. """

    def setUp(self):
        dev1 = DiskDevice("name", fmt=getFormat("mdmember"), size=Size("1 GiB"))
        dev2 = DiskDevice("other")
        self.part = PartitionDevice("part", fmt=getFormat("mdmember"), parents=[dev2])
        self.dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, self.part], fmt=getFormat("luks"), totalDevices=2, memberDevices=2)
        self.luks = LUKSDevice("luks", parents=[self.dev], fmt=getFormat("ext4"))

        self.mdraid_method = availability.BLOCKDEV_MDRAID_PLUGIN._method
        self.dm_method = availability.BLOCKDEV_DM_PLUGIN._method
        self.cache_availability = availability.CACHE_AVAILABILITY

    def testAvailabilityMDRAIDplugin(self):

        availability.CACHE_AVAILABILITY = False
        availability.BLOCKDEV_DM_PLUGIN._method = availability.AvailableMethod

        # if the plugin is not in, there's nothing to test
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.externalDependencies)

        # dev is not among its unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = availability.AvailableMethod
        self.assertNotIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailableDependencies)
        self.assertIsNotNone(ActionCreateDevice(self.luks))
        self.assertIsNotNone(ActionDestroyDevice(self.luks))
        self.assertIsNotNone(ActionCreateFormat(self.luks, fmt=getFormat("macefi")))
        self.assertIsNotNone(ActionDestroyFormat(self.luks))

        # dev is among the unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = availability.UnavailableMethod
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailableDependencies)
        with self.assertRaises(ValueError):
            ActionCreateDevice(self.luks)
        with self.assertRaises(ValueError):
            ActionDestroyDevice(self.dev)
        with self.assertRaises(ValueError):
            ActionCreateFormat(self.dev)
        with self.assertRaises(ValueError):
            ActionDestroyFormat(self.dev)

    def tearDown(self):
        availability.BLOCKDEV_MDRAID_PLUGIN._method = self.mdraid_method
        availability.BLOCKDEV_DM_PLUGIN._method = self.dm_method

        availability.CACHE_AVAILABILITY = False
        availability.BLOCKDEV_MDRAID_PLUGIN.available # pylint: disable=pointless-statement
        availability.BLOCKDEV_DM_PLUGIN.available # pylint: disable=pointless-statement

        availability.CACHE_AVAILABILITY = self.cache_availability
