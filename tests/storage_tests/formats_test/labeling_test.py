import unittest

from blivet.formats import device_formats
from blivet.size import Size
import blivet.formats.fs as fs
import blivet.formats.swap as swap

from . import loopbackedtestcase
from . import fslabeling


class InitializationTestCase(unittest.TestCase):

    """Test FS object initialization."""

    def test_labels(self):
        """Initialize some filesystems with valid and invalid labels."""

        # Ext2FS has a maximum length of 16
        self.assertFalse(fs.Ext2FS().label_format_ok("root___filesystem"))
        self.assertTrue(fs.Ext2FS().label_format_ok("root__filesystem"))

        # FATFS has a maximum length of 11
        self.assertFalse(fs.FATFS().label_format_ok("rtfilesystem"))
        self.assertTrue(fs.FATFS().label_format_ok("rfilesystem"))

        # JFS has a maximum length of 16
        self.assertFalse(fs.JFS().label_format_ok("root___filesystem"))
        self.assertTrue(fs.JFS().label_format_ok("root__filesystem"))

        # ReiserFS has a maximum length of 16
        self.assertFalse(fs.ReiserFS().label_format_ok("root___filesystem"))
        self.assertTrue(fs.ReiserFS().label_format_ok("root__filesystem"))

        # XFS has a maximum length 12 and does not allow spaces
        self.assertFalse(fs.XFS().label_format_ok("root_filesyst"))
        self.assertFalse(fs.XFS().label_format_ok("root file"))
        self.assertTrue(fs.XFS().label_format_ok("root_filesys"))

        # HFS has a maximum length of 27, minimum length of 1, and does not allow colons
        self.assertFalse(fs.HFS().label_format_ok("n" * 28))
        self.assertFalse(fs.HFS().label_format_ok("root:file"))
        self.assertFalse(fs.HFS().label_format_ok(""))
        self.assertTrue(fs.HFS().label_format_ok("n" * 27))

        # HFSPlus has a maximum length of 128, minimum length of 1, and does not allow colons
        self.assertFalse(fs.HFSPlus().label_format_ok("n" * 129))
        self.assertFalse(fs.HFSPlus().label_format_ok("root:file"))
        self.assertFalse(fs.HFSPlus().label_format_ok(""))
        self.assertTrue(fs.HFSPlus().label_format_ok("n" * 128))

        # NTFS has a maximum length of 128
        self.assertFalse(fs.NTFS().label_format_ok("n" * 129))
        self.assertTrue(fs.NTFS().label_format_ok("n" * 128))

        # all devices are permitted to be passed a label argument of None
        # some will ignore it completely
        for _k, v in device_formats.items():
            self.assertIsNotNone(v(label=None))


class XFSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.XFS
    _invalid_label = "root filesystem"
    _DEVICE_SIZE = Size("500 MiB")


class FATFSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.FATFS
    _invalid_label = "root___filesystem"


class Ext2FSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.Ext2FS
    _invalid_label = "root___filesystem"


class JFSTestCase(fslabeling.LabelingWithRelabeling):
    _fs_class = fs.JFS
    _invalid_label = "root___filesystem"


class ReiserFSTestCase(fslabeling.LabelingWithRelabeling):
    _fs_class = fs.ReiserFS
    _invalid_label = "root___filesystem"


class HFSTestCase(fslabeling.LabelingAsRoot):
    _fs_class = fs.HFS
    _invalid_label = "n" * 28


class HFSPlusTestCase(fslabeling.LabelingAsRoot):
    _fs_class = fs.HFSPlus
    _invalid_label = "n" * 129


@unittest.skip("Unable to create NTFS filesystem.")
class NTFSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.NTFS
    _invalid_label = "n" * 129


class LabelingSwapSpaceTestCase(loopbackedtestcase.LoopBackedTestCase):

    def test_labeling(self):
        swp = swap.SwapSpace(device=self.loop_devices[0])
        swp.label = "mkswap is really pretty permissive about labels"
        self.assertIsNone(swp.create())

    def test_creating_swap_space_none(self):
        swp = swap.SwapSpace(device=self.loop_devices[0], label=None)
        self.assertIsNone(swp.create())

    def test_creating_swap_space_empty(self):
        swp = swap.SwapSpace(device=self.loop_devices[0], label="")
        self.assertIsNone(swp.create())

    def test_relabel(self):
        swp = swap.SwapSpace(device=self.loop_devices[0])
        self.assertIsNone(swp.create())
        swp.label = "label"
        swp.write_label()
