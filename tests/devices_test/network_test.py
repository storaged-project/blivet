# vim:set fileencoding=utf-8

import unittest

from blivet.devices import NetworkStorageDevice
from blivet.devices import StorageDevice

from blivet.formats import getFormat

class FakeNetDev(StorageDevice, NetworkStorageDevice):
    _type = "fakenetdev"

class NetDevMountOptionTestCase(unittest.TestCase):
    def testNetDevSetting(self):
        """ Verify netdev mount option setting after format assignment. """
        netdev = FakeNetDev("net1")
        dev = StorageDevice("dev1", fmt=getFormat("ext4"))
        self.assertFalse("_netdev" in dev.format.options.split(","))

        dev.parents.append(netdev)
        dev.format = getFormat("ext4")
        self.assertTrue("_netdev" in dev.format.options.split(","))

    def testNetDevUpdate(self):
        """ Verify netdev mount option setting after device creation. """
        netdev = FakeNetDev("net1")
        dev = StorageDevice("dev1", fmt=getFormat("ext4"))
        self.assertFalse("_netdev" in dev.format.options.split(","))

        dev.parents.append(netdev)

        # these create methods shouldn't write anything to disk
        netdev.create()
        dev.create()

        self.assertTrue("_netdev" in dev.format.options.split(","))

