from blivet.size import Size
import blivet.formats.fs as fs
import blivet.formats.swap as swap

from . import loopbackedtestcase
from . import fslabeling


class XFSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.XFS
    _invalid_label = "root filesystem"
    _default_label = ""
    _DEVICE_SIZE = Size("500 MiB")


class FATFSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.FATFS
    _invalid_label = "root___filesystem"
    _default_label = ""


class Ext2FSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.Ext2FS
    _invalid_label = "root___filesystem"
    _default_label = ""


class HFSPlusTestCase(fslabeling.LabelingAsRoot):
    _fs_class = fs.HFSPlus
    _invalid_label = "n" * 129
    _default_label = "Untitled"


class NTFSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.NTFS
    _invalid_label = "n" * 129
    _default_label = ""


class GFS2TestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.GFS2
    _invalid_label = "label:label*"
    _default_label = ""


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
