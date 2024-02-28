import unittest

from blivet.devices import DiskDevice
from blivet.devices import LUKSDevice
from blivet.devices import MDRaidArrayDevice

from blivet.formats import get_format


class DevicePackagesTestCase(unittest.TestCase):

    """Test device name validation"""

    def test_packages(self):
        dev1 = DiskDevice("name", fmt=get_format("mdmember"))

        dev2 = DiskDevice("other", fmt=get_format("mdmember"))
        dev = MDRaidArrayDevice("dev", level="raid1", parents=[dev1, dev2])
        luks = LUKSDevice("luks", parents=[dev])
        packages = luks.packages

        # no duplicates in list of packages
        self.assertEqual(len(packages), len(set(packages)))

        # several packages that ought to be included are
        for package in dev1.packages + dev2.packages + dev.packages:
            self.assertIn(package, packages)

        for package in dev1.format.packages + dev2.format.packages + dev.format.packages:
            self.assertIn(package, packages)
