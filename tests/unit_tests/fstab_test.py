import copy
import os
import unittest
from unittest.mock import Mock

from blivet.fstab import FSTabManager, FSTabEntry, HAVE_LIBMOUNT
from blivet.devices import DiskDevice, StratisPoolDevice, StratisFilesystemDevice
from blivet.formats import get_format
from blivet.size import Size
from blivet import Blivet

FSTAB_WRITE_FILE = "/tmp/test-blivet-fstab2"


class FSTabTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not HAVE_LIBMOUNT:
            raise unittest.SkipTest("Missing libmount support required for this test")

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

        entry = FSTabEntry("/dev/sda_dummy", "/media/wrongpath", "xfs", ["defaults"])

        # create new entries

        # entry.file value should be overridden by add_entry.file parameter
        self.fstab.add_entry(file="/mnt/mountpath", entry=entry)
        self.fstab.add_entry("/dev/sdb_dummy", "/media/newpath", "ext4", ["defaults"])

        # test the iterator and check that 2 entries are present
        self.assertEqual((sum(1 for _ in self.fstab)), 2, "invalid number of entries in fstab table")

        # try to find nonexistent entry based on device
        entry = self.fstab.find_entry("/dev/nonexistent")
        self.assertEqual(entry, None)

        # try to find existing entry based on device
        entry = self.fstab.find_entry("/dev/sda_dummy")
        # check that item was found and it is the correct one
        self.assertIsNotNone(entry, self.fstab)
        self.assertEqual(entry.file, "/mnt/mountpath")

        self.fstab.remove_entry(file="/mnt/mountpath")

        # check that number of entries is now 1
        self.assertEqual((sum(1 for _ in self.fstab)), 1, "invalid number of entries in fstab table")

        entry = self.fstab.find_entry(file="/mnt/mountpath")
        self.assertEqual(entry, None)

        # write new fstab
        self.fstab.write()

        # read the file and verify its contents
        with open(FSTAB_WRITE_FILE, "r") as f:
            contents = f.read()
        self.assertTrue("/media/newpath" in contents)

    def test_deepcopy(self):
        fstab1 = FSTabManager(None, 'dest')

        fstab1.add_entry("/dev/dev1", "path1", "xfs", ["Ph'nglui", "mglw'nafh", "Cthulhu"])
        fstab1.add_entry("/dev/dev2", "path2", "ext4", ["R'lyeh", "wgah'nagl", "fhtagn"])

        fstab2 = copy.deepcopy(fstab1)

        self.assertEqual(fstab1.src_file, fstab2.src_file)
        self.assertEqual(fstab1.dest_file, fstab2.dest_file)

        # Both versions has the same length
        self.assertEqual(sum(1 for _ in fstab1), sum(1 for _ in fstab1))

        # All entries are the same in the same order
        for entry1, entry2 in zip(fstab1, fstab2):
            self.assertEqual(entry1, entry2)

    def test_entry_from_device(self):

        device = DiskDevice("test_device", fmt=get_format("ext4", exists=True))
        device.format.mountpoint = "/media/fstab_test"

        _entry = self.fstab.entry_from_device(device)
        self.assertEqual(_entry, FSTabEntry('/dev/test_device', '/media/fstab_test', 'ext4', None, 0, 0))

    def test_entry_from_device_stratis(self):
        pool = StratisPoolDevice("testpool", parents=[], exists=True)
        device = StratisFilesystemDevice("testfs", parents=[pool], size=Size("1 GiB"), exists=True)
        device.format = get_format("stratis xfs")
        device.format.mountpoint = "/media/fstab_test"

        _entry = self.fstab.entry_from_device(device)
        self.assertEqual(_entry, FSTabEntry('/dev/stratis/testpool/testfs', '/media/fstab_test', 'xfs', None, 0, 0))

    def test_update(self):

        # Reset table
        self.fstab.src_file = None
        self.fstab.read()

        # Device is not in the table and should be added
        dev1 = DiskDevice("device1", fmt=get_format("ext4", exists=True))
        dev1.format.mountpoint = "/media/fstab_original_mountpoint"

        action = Mock()
        action.device = dev1
        action.is_create = True

        self.fstab.update(action, None)

        entry = self.fstab.entry_from_device(dev1)
        self.assertIsNotNone(self.fstab.find_entry(entry=entry))

        # Device is in the table and its mountpoint has changed
        action = Mock()
        dev1.format.mountpoint = "/media/fstab_changed_mountpoint"
        action.device = dev1
        action.is_destroy = False
        action.is_create = False
        action.is_configure = True
        action.is_format = True
        bae_entry = self.fstab.find_entry(entry=entry)

        self.fstab.update(action, bae_entry)
        self.assertIsNotNone(self.fstab.find_entry(spec="/dev/device1", file="/media/fstab_changed_mountpoint"))

        # Device is already present in the table and should be removed
        action = Mock()
        action.device = dev1
        action.is_destroy = True
        bae_entry = self.fstab.find_entry(entry=entry)

        self.fstab.update(action, bae_entry)
        self.assertIsNone(self.fstab.find_entry(entry=entry))

        # Device not at fstab._table which should not be added since it is not mountable
        dev2 = DiskDevice("unmountable_skip")

        # Add mountpoint just to mess with fstab manager
        dev2.format.mountpoint = "/media/absent_in_fstab"

        # Make sure that the device is not mountable
        self.assertFalse(dev2.format.mountable)

        action = Mock()
        action.device = dev2
        action.is_create = True

        self.fstab.update(action, None)
        self.assertIsNone(self.fstab.find_entry(file="/media/absent_in_fstab"))

    def test_find_device(self):
        # Reset table
        self.fstab.src_file = None
        self.fstab.read()

        b = Blivet()

        dev1 = DiskDevice("sda_dummy", exists=True, fmt=get_format("xfs", exists=True))
        dev1.format.mountpoint = "/mnt/mountpath"
        b.devicetree._add_device(dev1)

        dev2 = self.fstab.find_device(b.devicetree, "/dev/sda_dummy")

        self.assertEqual(dev1, dev2)

    def test_get_device(self):

        # Reset table
        self.fstab.src_file = None
        self.fstab.read()

        b = Blivet()

        dev1 = DiskDevice("sda_dummy", exists=True, fmt=get_format("xfs", exists=True))
        dev1.format.mountpoint = "/mnt/mountpath"
        b.devicetree._add_device(dev1)

        dev2 = self.fstab.get_device(b.devicetree, "/dev/sda_dummy", "/mnt/mountpath", "xfs", ["defaults"])

        self.assertEqual(dev1, dev2)
