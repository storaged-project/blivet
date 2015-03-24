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
        for d in dev.externalDependencies:
            self.assertIn(d, luks.externalDependencies)

        # make sure that there's at least something in these dependencies
        self.assertTrue(len(luks.externalDependencies) > 0)

class MockingDeviceDependenciesTestCase(unittest.TestCase):
    """Test availability of external device dependencies. """

    def setUp(self):
        dev1 = DiskDevice("name", fmt=getFormat("mdmember"))
        dev2 = DiskDevice("other")
        self.part = PartitionDevice("part", fmt=getFormat("mdmember"), parents=[dev2])
        self.dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, self.part], fmt=getFormat("ext4"))
        self.luks = LUKSDevice("luks", parents=[self.dev], fmt=getFormat("luks"))

        self.mdraid_method = availability.BLOCKDEV_MDRAID_PLUGIN._method
        self.mount_method = self.dev.format._mount._app._method

    def testAvailabilityMDRAIDplugin(self):

        # if the plugin is not in, there's nothing to test
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.externalDependencies)

        # dev is not among its unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = TrueMethod()
        self.assertNotIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailableDependencies)
        self.assertIsNotNone(ActionCreateDevice(self.dev))
        self.assertIsNotNone(ActionDestroyDevice(self.dev))
        self.assertIsNotNone(ActionCreateFormat(self.dev, fmt=getFormat("macefi")))
        self.assertIsNotNone(ActionDestroyFormat(self.dev))

        # dev is among the unavailable dependencies
        availability.BLOCKDEV_MDRAID_PLUGIN._method = FalseMethod()
        self.assertIn(availability.BLOCKDEV_MDRAID_PLUGIN, self.luks.unavailableDependencies)
        with self.assertRaises(ValueError):
            ActionCreateDevice(self.dev)
        with self.assertRaises(ValueError):
            ActionDestroyDevice(self.dev)
        with self.assertRaises(ValueError):
            ActionCreateFormat(self.dev)
        with self.assertRaises(ValueError):
            ActionDestroyFormat(self.dev)

    def testFormatAvailability(self):
        self.dev.format._mount._app._method = TrueMethod()
        self.assertIsNotNone(ActionCreateDevice(self.luks))
        self.assertIsNotNone(ActionDestroyDevice(self.luks))
        self.assertIsNotNone(ActionCreateFormat(self.luks, fmt=getFormat("macefi")))
        self.assertIsNotNone(ActionDestroyFormat(self.luks))

        self.dev.format._mount._app._method = FalseMethod()
        with self.assertRaises(ValueError):
            ActionCreateDevice(self.luks)
        with self.assertRaises(ValueError):
            ActionDestroyDevice(self.luks)
        with self.assertRaises(ValueError):
            ActionCreateFormat(self.luks, fmt=getFormat("macefi"))
        with self.assertRaises(ValueError):
            ActionDestroyFormat(self.luks)

    def tearDown(self):
        availability.BLOCKDEV_MDRAID_PLUGIN._method = self.mdraid_method
        self.dev.format._mount._app._method = self.mount_method

if __name__ == "__main__":
    unittest.main()
