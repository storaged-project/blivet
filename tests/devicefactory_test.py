#!/usr/bin/python

import unittest

import blivet

from blivet import devicefactory
from blivet import devices
from blivet.devicelibs import mdraid

class MDFactoryTestCase(unittest.TestCase):
    """Note that these tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or its correct behavior. See the
       initial commit message for this file for further details.
    """
    def setUp(self):
        self.b = blivet.Blivet()
        self.factory1 = devicefactory.get_device_factory(self.b,
           devicefactory.DEVICE_TYPE_MD,
           1024)

        self.factory2 = devicefactory.get_device_factory(self.b,
           devicefactory.DEVICE_TYPE_MD,
           1024,
           raid_level=0)

    def testMDFactory(self):
        self.assertRaisesRegexp(mdraid.MDRaidError,
           "invalid raid level",
           self.factory1._get_device_space)

        self.assertRaisesRegexp(mdraid.MDRaidError,
           "invalid raid level",
           self.factory1._set_raid_level)

        self.assertEqual(self.factory1.container_list, [])

        self.assertIsNone(self.factory1.get_container())

        self.assertRaisesRegexp(mdraid.MDRaidError,
           "invalid raid level",
           self.factory1._get_new_device,
           parents=[])

        self.assertRaisesRegexp(mdraid.MDRaidError,
           "requires at least",
           self.factory2._get_device_space)

        self.assertEqual(self.factory2.container_list, [])

        self.assertIsNone(self.factory2.get_container())

def suite():
    return unittest.TestLoader().loadTestsFromTestCase(MDFactoryTestCase)


if __name__ == "__main__":
    unittest.main()
