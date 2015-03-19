#!/usr/bin/python
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

from blivet.devices.external import DestroyMode, DefaultMode

from blivet.formats import getFormat

from blivet.tasks import availability

class FalseMethod(availability.Method):
    def available(self, resource):
        return False

class TrueMethod(availability.Method):
    def available(self, resource):
        return True

class DeviceDependenciesTestCase(unittest.TestCase):
    """Test external device dependencies. """

    def testDependencies(self):
        dev1 = DiskDevice("name", fmt=getFormat("mdmember"))
        dev2 = DiskDevice("other", fmt=getFormat("mdmember"))
        dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1,dev2])
        luks = LUKSDevice("luks", parents=[dev])

        # a parent's dependencies are a subset of its child's.
        for d in dev.allExternalDependencies():
            self.assertIn(d, luks.allExternalDependencies())

        # make sure that there's at least something in these dependencies
        self.assertTrue(len(luks.allExternalDependencies()) > 0)

class MockingDeviceDependenciesTestCase(unittest.TestCase):
    """Test availability of external device dependencies. """

    def setUp(self):
        dev1 = DiskDevice("name", fmt=getFormat("mdmember"))
        dev2 = DiskDevice("other")
        self.part = PartitionDevice("part", fmt=getFormat("mdmember"), parents=[dev2])
        self.dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, self.part], fmt=getFormat("ext4"))
        self.luks = LUKSDevice("luks", parents=[self.dev])

        self.mdraid_method = availability.BLOCKDEV_MDRAID_PLUGIN._method
        self.dm_method = availability.BLOCKDEV_DM_PLUGIN._method

    def testAvailabilityMDRAIDplugin(self):

        # if the plugin is not in, there's nothing to test
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.allExternalDependencies())

        # dev is not among its unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = TrueMethod()
        self.assertNotIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailableDependencies())
        self.assertIsNotNone(ActionCreateDevice(self.dev))
        self.assertIsNotNone(ActionDestroyDevice(self.dev))
        self.assertIsNotNone(ActionCreateFormat(self.dev))
        self.assertIsNotNone(ActionDestroyFormat(self.dev))

        # dev is among the unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = FalseMethod()
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailableDependencies())
        with self.assertRaises(ValueError):
            ActionCreateDevice(self.dev)
        with self.assertRaises(ValueError):
            ActionDestroyDevice(self.dev)
        with self.assertRaises(ValueError):
            ActionCreateFormat(self.dev)
        with self.assertRaises(ValueError):
            ActionDestroyFormat(self.dev)

    def testAvailabilityDestroyMode(self):
        # if the plugin is not in destroy category, there's nothing to test
        self.assertIn(availability.BLOCKDEV_DM_PLUGIN, self.part.allExternalDependencies(DestroyMode))

        # if the plugin is in general category, there's nothing to testDMPlugin
        self.assertNotIn(availability.BLOCKDEV_DM_PLUGIN, self.part.allExternalDependencies(DefaultMode))

        # if dm plugin is available, possible to do all actions w/ a partition
        availability.BLOCKDEV_DM_PLUGIN._method = TrueMethod()
        self.assertNotIn(availability.BLOCKDEV_DM_PLUGIN, self.part.unavailableDependencies(DefaultMode))
        self.assertNotIn(availability.BLOCKDEV_DM_PLUGIN, self.part.unavailableDependencies(DefaultMode))
        self.assertIsNotNone(ActionCreateDevice(self.dev))
        self.assertIsNotNone(ActionDestroyDevice(self.dev))
        self.assertIsNotNone(ActionCreateFormat(self.dev))
        self.assertIsNotNone(ActionDestroyFormat(self.dev))

        # if dm plugin is available, possible to do all actions w/ a partition
        availability.BLOCKDEV_DM_PLUGIN._method = FalseMethod()
        self.assertNotIn(availability.BLOCKDEV_DM_PLUGIN, self.part.unavailableDependencies(DefaultMode))
        self.assertIn(availability.BLOCKDEV_DM_PLUGIN, self.part.unavailableDependencies(DestroyMode))
        self.assertIsNotNone(ActionCreateDevice(self.dev))
        self.assertIsNotNone(ActionCreateFormat(self.dev))
        self.assertIsNotNone(ActionDestroyFormat(self.dev))
        with self.assertRaises(ValueError):
            ActionDestroyDevice(self.dev)


    def tearDown(self):
        availability.BLOCKDEV_MDRAID_PLUGIN._method = self.mdraid_method
        availability.BLOCKDEV_DM_PLUGIN._method = self.dm_method

if __name__ == "__main__":
    unittest.main()
