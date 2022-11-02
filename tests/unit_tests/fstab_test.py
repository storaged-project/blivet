import os
import unittest

from blivet.fstab import FSTabManager
from blivet.devices import DiskDevice
from blivet.formats import get_format
from blivet import Blivet

FSTAB_WRITE_FILE = "/tmp/test-blivet-fstab2"


class FSTabTestCase(unittest.TestCase):

    def setUp(self):
        self.fstab = FSTabManager()
        self.addCleanup(self._clean_up)

    def _clean_up(self):
        try:
            os.remove(FSTAB_WRITE_FILE)
        except FileNotFoundError:
            pass

    def test_fstab(self):

        self.fstab.src_file = None
        self.fstab.dest_file = FSTAB_WRITE_FILE

        # create new entries
        self.fstab.add_entry_by_specs("/dev/sda_dummy", "/mnt/mountpath", "xfs", "defaults")
        self.fstab.add_entry_by_specs("/dev/sdb_dummy", "/media/newpath", "ext4", "defaults")

        # try to find nonexistent entry based on device
        entry = self.fstab.find_entry_by_specs("/dev/nonexistent", None, None, None)
        self.assertEqual(entry, None)

        # try to find existing entry based on device
        entry = self.fstab.find_entry_by_specs("/dev/sda_dummy", None, None, None)
        # check that found item is the correct one
        self.assertEqual(entry.target, "/mnt/mountpath")

        self.fstab.remove_entry_by_specs(None, "/mnt/mountpath", None, None)
        entry = self.fstab.find_entry_by_specs(None, "/mnt/mountpath", None, None)
        self.assertEqual(entry, None)

        # write new fstab
        self.fstab.write()

        # read the file and verify its contents
        with open(FSTAB_WRITE_FILE, "r") as f:
            contents = f.read()
        self.assertTrue("/media/newpath" in contents)

    def test_from_device(self):

        device = DiskDevice("test_device", fmt=get_format("ext4", exists=True))
        device.format.mountpoint = "/media/fstab_test"

        self.assertEqual(self.fstab._from_device(device), ('/dev/test_device', '/media/fstab_test', 'ext4', None))

    def test_update(self):

        # Reset table
        self.fstab.read(None)

        # Device already present in fstab._table that should be kept there after fstab.update()
        dev1 = DiskDevice("already_present_keep", fmt=get_format("ext4", exists=True))
        dev1.format.mountpoint = "/media/fstab_test1"

        # Device already present in fstab._table which should be removed by fstab.update()
        dev2 = DiskDevice("already_present_remove", fmt=get_format("ext4", exists=True))
        dev2.format.mountpoint = "/media/fstab_test2"

        # Device not at fstab._table which should not be added since it is not mountable
        dev3 = DiskDevice("unmountable_skip")

        # Device not at fstab._table that should be added there after fstab.update()
        dev4 = DiskDevice("new", fmt=get_format("ext4", exists=True))
        dev4.format.mountpoint = "/media/fstab_test3"

        self.fstab.add_entry_by_device(dev1)
        self.fstab.add_entry_by_device(dev2)

        self.fstab.update([dev1, dev3, dev4])

        # write new fstab
        self.fstab.write("/tmp/test_blivet_fstab2")

        with open("/tmp/test_blivet_fstab2", "r") as f:
            contents = f.read()

        self.assertTrue("already_present_keep" in contents)
        self.assertFalse("already_present_remove" in contents)
        self.assertFalse("unmountable_skip" in contents)
        self.assertTrue("new" in contents)

    def test_find_device(self):
        # Reset table
        self.fstab.read(None)

        b = Blivet()

        dev1 = DiskDevice("sda_dummy", exists=True, fmt=get_format("xfs", exists=True))
        dev1.format.mountpoint = "/mnt/mountpath"
        b.devicetree._add_device(dev1)

        dev2 = self.fstab.find_device_by_specs(b, "/dev/sda_dummy", "/mnt/mountpath", "xfs", "defaults")

        self.assertEqual(dev1, dev2)

    def test_get_device(self):

        # Reset table
        self.fstab.read(None)

        b = Blivet()

        dev1 = DiskDevice("sda_dummy", exists=True, fmt=get_format("xfs", exists=True))
        dev1.format.mountpoint = "/mnt/mountpath"
        b.devicetree._add_device(dev1)

        dev2 = self.fstab.get_device_by_specs(b, "/dev/sda_dummy", "/mnt/mountpath", "xfs", "defaults")

        self.assertEqual(dev1, dev2)
