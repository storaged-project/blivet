# vim:set fileencoding=utf-8

import unittest

from blivet3.devices import NetworkStorageDevice
from blivet3.devices import StorageDevice

from blivet3.formats import get_format


class FakeNetDev(StorageDevice, NetworkStorageDevice):
    _type = "fakenetdev"


class NetDevMountOptionTestCase(unittest.TestCase):

    def test_net_dev_setting(self):
        """ Verify netdev mount option setting after format assignment. """
        netdev = FakeNetDev("net1")
        dev = StorageDevice("dev1", fmt=get_format("ext4"))
        self.assertFalse("_netdev" in dev.format.options.split(","))

        dev.parents.append(netdev)
        dev.format = get_format("ext4")
        self.assertTrue("_netdev" in dev.format.options.split(","))

    def test_net_dev_update(self):
        """ Verify netdev mount option setting after device creation. """
        netdev = FakeNetDev("net1")
        dev = StorageDevice("dev1", fmt=get_format("ext4"))
        self.assertFalse("_netdev" in dev.format.options.split(","))

        dev.parents.append(netdev)

        # these create methods shouldn't write anything to disk
        netdev.create()
        dev.create()

        self.assertTrue("_netdev" in dev.format.options.split(","))
