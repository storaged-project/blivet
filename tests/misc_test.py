import unittest

try:
    from unittest.mock import patch, Mock
except ImportError:
    from mock import patch, Mock

import blivet

from blivet.devices import PartitionDevice, DiskDevice, StorageDevice


class SuggestNameTestCase(unittest.TestCase):

    def test_suggest_container_name(self):
        b = blivet.Blivet()

        with patch("blivet.devicetree.DeviceTree.names", []):
            name = b.suggest_container_name(prefix="blivet")
            self.assertEqual(name, "blivet")

        with patch("blivet.devicetree.DeviceTree.names", ["blivet"]):
            name = b.suggest_container_name(prefix="blivet")
            self.assertEqual(name, "blivet00")

        with patch("blivet.devicetree.DeviceTree.names", ["blivet"] + ["blivet%02d" % i for i in range(100)]):
            with self.assertRaises(RuntimeError):
                b.suggest_container_name(prefix="blivet")

    def test_suggest_device_name(self):
        b = blivet.Blivet()

        with patch("blivet.devicetree.DeviceTree.names", []):
            name = b.suggest_device_name()
            self.assertEqual(name, "00")

            name = b.suggest_device_name(prefix="blivet")
            self.assertEqual(name, "blivet00")

            name = b.suggest_device_name(mountpoint="/")
            self.assertEqual(name, "root")

            name = b.suggest_device_name(prefix="blivet", mountpoint="/")
            self.assertEqual(name, "blivet_root")

            name = b.suggest_device_name(parent=blivet.devices.Device(name="parent"), mountpoint="/")
            self.assertEqual(name, "root")

        with patch("blivet.devicetree.DeviceTree.names", ["00"]):
            name = b.suggest_device_name()
            self.assertEqual(name, "01")

        with patch("blivet.devicetree.DeviceTree.names", ["parent-root"]):
            name = b.suggest_device_name(parent=blivet.devices.Device(name="parent"), mountpoint="/")
            self.assertEqual(name, "root00")


class SortDevicesTest(unittest.TestCase):

    def test_sort_devices(self):
        bl = blivet.Blivet()

        disk = DiskDevice("sda", parents=[], size=blivet.size.Size("1 GiB"))
        bl.devicetree._add_device(disk)

        for i in range(1, 12):
            part = PartitionDevice(name="sda%d" % i, parents=[disk])
            part.parents = [disk]
            part._parted_partition = Mock(number=i)
            bl.devicetree._add_device(part)

        self.assertEqual([d.name for d in bl.devices],
                         ["sda"] + ["sda%d" % i for i in range(1, 12)])

        # disk children should be also sorted
        self.assertEqual([d.name for d in disk.children],
                         ["sda%d" % i for i in range(1, 12)])

        # add some "extra" devices just to be sure the "non-partition" sort still works
        bl.devicetree._add_device(StorageDevice("sdb", parents=[]))
        bl.devicetree._add_device(StorageDevice("nvme0n1", parents=[]))
        bl.devicetree._add_device(StorageDevice("10", parents=[]))

        self.assertEqual([d.name for d in bl.devices],
                         ["10", "nvme0n1", "sda"] + ["sda%d" % i for i in range(1, 12)] + ["sdb"])
