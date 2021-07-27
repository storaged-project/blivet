import unittest

try:
    from unittest.mock import patch
except ImportError:
    from mock import patch

import blivet


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
