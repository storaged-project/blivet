#!/usr/bin/python
import unittest

from tests import loopbackedtestcase
from blivet.formats import device_formats
import blivet.formats.fs as fs
import blivet.formats.swap as swap

from . import fslabeling

class InitializationTestCase(unittest.TestCase):
    """Test FS object initialization."""

    def testLabels(self):
        """Initialize some filesystems with valid and invalid labels."""

        # Ext2FS has a maximum length of 16
        self.assertFalse(fs.Ext2FS.labelFormatOK("root___filesystem"))
        self.assertTrue(fs.Ext2FS.labelFormatOK("root__filesystem"))

        # FATFS has a maximum length of 11
        self.assertFalse(fs.FATFS.labelFormatOK("rtfilesystem"))
        self.assertTrue(fs.FATFS.labelFormatOK("rfilesystem"))

        # JFS has a maximum length of 16
        self.assertFalse(fs.JFS.labelFormatOK("root___filesystem"))
        self.assertTrue(fs.JFS.labelFormatOK("root__filesystem"))

        # ReiserFS has a maximum length of 16
        self.assertFalse(fs.ReiserFS.labelFormatOK("root___filesystem"))
        self.assertTrue(fs.ReiserFS.labelFormatOK("root__filesystem"))

        #XFS has a maximum length 12 and does not allow spaces
        self.assertFalse(fs.XFS.labelFormatOK("root_filesyst"))
        self.assertFalse(fs.XFS.labelFormatOK("root file"))
        self.assertTrue(fs.XFS.labelFormatOK("root_filesys"))

        #HFS has a maximum length of 27, minimum length of 1, and does not allow colons
        self.assertFalse(fs.HFS.labelFormatOK("n" * 28))
        self.assertFalse(fs.HFS.labelFormatOK("root:file"))
        self.assertFalse(fs.HFS.labelFormatOK(""))
        self.assertTrue(fs.HFS.labelFormatOK("n" * 27))

        #HFSPlus has a maximum length of 128, minimum length of 1, and does not allow colons
        self.assertFalse(fs.HFSPlus.labelFormatOK("n" * 129))
        self.assertFalse(fs.HFSPlus.labelFormatOK("root:file"))
        self.assertFalse(fs.HFSPlus.labelFormatOK(""))
        self.assertTrue(fs.HFSPlus.labelFormatOK("n" * 128))

        # NTFS has a maximum length of 128
        self.assertFalse(fs.NTFS.labelFormatOK("n" * 129))
        self.assertTrue(fs.NTFS.labelFormatOK("n" * 128))

        # all devices are permitted to be passed a label argument of None
        # some will ignore it completely
        for _k, v  in device_formats.items():
            self.assertIsNotNone(v(label=None))

class MethodsTestCase(unittest.TestCase):
    """Test some methods that do not require actual images."""

    def setUp(self):
        self.fs = {}
        for k, v  in device_formats.items():
            if issubclass(v, fs.FS) and v.labeling():
                self.fs[k] = v(device="/dev", label="myfs")


    def testGetLabelArgs(self):
        self.longMessage = True

        # ReiserFS uses a -l flag
        reiserfs = self.fs["reiserfs"]
        self.assertEqual(reiserfs._labelfs.label_app.setLabelCommand(reiserfs),
           ["reiserfstune", "-l", "myfs", "/dev"], msg="reiserfs")

        # JFS, XFS use a -L flag
        lflag_classes = [fs.JFS, fs.XFS]
        for name, klass in ((k, v) for k, v in self.fs.items() if any(isinstance(v, c) for c in lflag_classes)):
            self.assertEqual(klass._labelfs.label_app.setLabelCommand(klass), [klass._labelfs.label_app.name, "-L", "myfs", "/dev"], msg=name)

        # Ext2FS and descendants and FATFS do not use a flag
        noflag_classes = [fs.Ext2FS, fs.FATFS]
        for name, klass in ((k, v) for k, v in self.fs.items() if any(isinstance(v, c) for c in noflag_classes)):
            self.assertEqual(klass._labelfs.label_app.setLabelCommand(klass), [klass._labelfs.label_app.name, "/dev", "myfs"], msg=name)

        # all of the remaining are non-labeling so will accept any label
        label = "Houston, we have a problem!"
        for name, klass in device_formats.items():
            if issubclass(klass, fs.FS) and not klass.labeling() and not issubclass(klass, fs.NFS):
                self.assertEqual(klass(device="/dev", label=label).label, label, msg=name)

class XFSTestCase(fslabeling.CompleteLabelingAsRoot):
    _fs_class = fs.XFS
    _invalid_label = "root filesystem"

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

    def testLabeling(self):
        swp = swap.SwapSpace(device=self.loopDevices[0])
        swp.label = "mkswap is really pretty permissive about labels"
        self.assertIsNone(swp.create())

    def testCreatingSwapSpaceNone(self):
        swp = swap.SwapSpace(device=self.loopDevices[0], label=None)
        self.assertIsNone(swp.create())

    def testCreatingSwapSpaceEmpty(self):
        swp = swap.SwapSpace(device=self.loopDevices[0], label="")
        self.assertIsNone(swp.create())

if __name__ == "__main__":
    unittest.main()
