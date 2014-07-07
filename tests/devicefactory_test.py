#!/usr/bin/python

import unittest

import blivet

from blivet import devicefactory
from blivet.devicelibs import raid
from blivet.errors import RaidError
from blivet.size import Size

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
           Size("1 GiB"),
           raid_level=raid.RAID1)

        self.factory2 = devicefactory.get_device_factory(self.b,
           devicefactory.DEVICE_TYPE_MD,
           Size("1 GiB"),
           raid_level=0)

    def testMDFactory(self):
        with self.assertRaisesRegexp(devicefactory.DeviceFactoryError, "must have some RAID level"):
            devicefactory.get_device_factory(
               self.b,
               devicefactory.DEVICE_TYPE_MD,
               Size("1 GiB"))

        with self.assertRaisesRegexp(RaidError, "requires at least"):
            self.factory1._get_device_space()

        with self.assertRaisesRegexp(RaidError, "requires at least"):
            self.factory1._configure()

        self.assertEqual(self.factory1.container_list, [])

        self.assertIsNone(self.factory1.get_container())

        self.assertIsNotNone(self.factory1._get_new_device(parents=[]))

        with self.assertRaisesRegexp(RaidError, "requires at least"):
            self.factory2._get_device_space()

        self.assertEqual(self.factory2.container_list, [])

        self.assertIsNone(self.factory2.get_container())

if __name__ == "__main__":
    unittest.main()
