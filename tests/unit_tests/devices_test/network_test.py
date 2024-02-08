import unittest

from blivet.devices import NetworkStorageDevice
from blivet.devices import StorageDevice

from blivet.formats import get_format


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

    def test_net_dev_update_remove(self):
        """ Verify netdev mount option is removed after removing the netdev parent. """
        netdev = FakeNetDev("net1")
        dev = StorageDevice("dev1", parents=[netdev], fmt=get_format("ext4"))
        self.assertTrue("_netdev" in dev.format.options.split(","))

        dev.parents.remove(netdev)

        # these create methods shouldn't write anything to disk
        netdev.create()
        dev.create()

        self.assertFalse("_netdev" in dev.format.options.split(","))

    def test_net_device_manual(self):
        """ Verify netdev mount option is not removed if explicitly set by the user. """
        dev = StorageDevice("dev1", fmt=get_format("ext4", mountopts="_netdev"))
        self.assertTrue("_netdev" in dev.format.options.split(","))

        # these create methods shouldn't write anything to disk
        dev.create()

        self.assertTrue("_netdev" in dev.format.options.split(","))
