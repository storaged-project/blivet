#!/usr/bin/python
import os
import unittest

from devicelibs_test import baseclass
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
        self.assertFalse(fs.HFS.labelFormatOK("".join(["n" for x in range(28)])))
        self.assertFalse(fs.HFS.labelFormatOK("root:file"))
        self.assertFalse(fs.HFS.labelFormatOK(""))
        self.assertTrue(fs.HFS.labelFormatOK("".join(["n" for x in range(27)])))

        # NTFS has a maximum length of 128
        self.assertFalse(fs.NTFS.labelFormatOK("".join(["n" for x in range(129)])))
        self.assertTrue(fs.NTFS.labelFormatOK("".join(["n" for x in range(128)])))

        # all devices are permitted to be passed a label argument of None
        # some will ignore it completely
        for k, v  in device_formats.items():
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
        self.assertEqual(reiserfs._labelfs.labelApp.setLabelCommand(reiserfs),
           ["reiserfstune", "-l", "myfs", "/dev"], msg="reiserfs")

        # JFS, XFS use a -L flag
        lflag_classes = [fs.JFS, fs.XFS]
        for k, v in [(k, v) for k, v in self.fs.items() if any(isinstance(v, c) for c in lflag_classes)]:
            self.assertEqual(v._labelfs.labelApp.setLabelCommand(v), [v._labelfs.labelApp.name, "-L", "myfs", "/dev"], msg=k)

        # Ext2FS and descendants and FATFS do not use a flag
        noflag_classes = [fs.Ext2FS, fs.FATFS]
        for k, v in [(k, v) for k, v in self.fs.items() if any(isinstance(v, c) for c in noflag_classes)]:
            self.assertEqual(v._labelfs.labelApp.setLabelCommand(v), [v._labelfs.labelApp.name, "/dev", "myfs"], msg=k)

        # all of the remaining are non-labeling so will accept any label
        label = "Houston, we have a problem!"
        for k, v in device_formats.items():
            if issubclass(v, fs.FS) and not v.labeling() and not issubclass(v, fs.NFS):
                self.assertEqual(v(device="/dev", label=label).label, label)

class XFSTestCase(fslabeling.CompleteLabelingAsRoot):
    def setUp(self):
        self._fs_class = fs.XFS
        self._invalid_label = "root filesystem"
        super(XFSTestCase, self).setUp()

class FATFSTestCase(fslabeling.CompleteLabelingAsRoot):
    def setUp(self):
        self._fs_class = fs.FATFS
        self._invalid_label = "root___filesystem"
        super(FATFSTestCase, self).setUp()

class Ext2FSTestCase(fslabeling.CompleteLabelingAsRoot):
    def setUp(self):
        self._fs_class = fs.Ext2FS
        self._invalid_label = "root___filesystem"
        super(Ext2FSTestCase, self).setUp()

class JFSTestCase(fslabeling.LabelingWithRelabeling):
    def setUp(self):
        self._fs_class = fs.JFS
        self._invalid_label = "root___filesystem"
        super(JFSTestCase, self).setUp()

class ReiserFSTestCase(fslabeling.LabelingWithRelabeling):
    def setUp(self):
        self._fs_class = fs.ReiserFS
        self._invalid_label = "root___filesystem"
        super(ReiserFSTestCase, self).setUp()

class HFSTestCase(fslabeling.LabelingAsRoot):
    def setUp(self):
        self._fs_class = fs.HFS
        self._invalid_label = "".join(["n" for x in range(28)])
        super(HFSTestCase, self).setUp()

@unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
class LabelingSwapSpaceTestCase(baseclass.DevicelibsTestCase):

    def testLabeling(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        swp = swap.SwapSpace(device=_LOOP_DEV0)
        swp.label = "mkswap is really pretty permissive about labels"
        self.assertIsNone(swp.create())

    def testCreatingSwapSpaceNone(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        swp = swap.SwapSpace(device=_LOOP_DEV0, label=None)
        self.assertIsNone(swp.create())

    def testCreatingSwapSpaceEmpty(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        swp = swap.SwapSpace(device=_LOOP_DEV0, label="")
        self.assertIsNone(swp.create())

if __name__ == "__main__":
    unittest.main()
