#!/usr/bin/python
import os
import unittest

from devicelibs_test import baseclass
from blivet.formats import device_formats
import blivet.formats.fs as fs
import blivet.formats.swap as swap

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

class LabelingAsRootTestCase(baseclass.DevicelibsTestCase):
    """Tests for labeling a filesystem and reading its label.

       For some filesystems, there is an application for writing the label
       but the same application does not read the label. For those, it
       is only possible to check if the write operation completed succesfully.
    """

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingXFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.XFS(device=_LOOP_DEV0, label="root___filesystem")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.defaultLabel)

        an_fs.label = "temeraire"
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = ""
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = None
        self.assertRaisesRegexp(fs.FSError,
            "default label",
            an_fs.writeLabel)

        an_fs.label = "root___filesystem"
        self.assertRaisesRegexp(fs.FSError,
           "bad label format",
           an_fs.writeLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingXFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.XFS(device=_LOOP_DEV0, label="start")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), "start")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingXFSNone(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.XFS(device=_LOOP_DEV0, label=None)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.defaultLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingXFSEmpty(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.XFS(device=_LOOP_DEV0, label="")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), "")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingFATFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.FATFS(device=_LOOP_DEV0, label="root___filesystem")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.defaultLabel)

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = ""
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = None
        self.assertRaisesRegexp(fs.FSError,
            "default label",
            an_fs.writeLabel)

        an_fs.label = "root___filesystem"
        self.assertRaisesRegexp(fs.FSError,
           "bad label format",
           an_fs.writeLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingFATFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.FATFS(device=_LOOP_DEV0, label="start")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), "start")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingFATFSNone(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.FATFS(device=_LOOP_DEV0, label=None)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.defaultLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingFATFSEmpty(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.FATFS(device=_LOOP_DEV0, label="")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), "")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingExt2FS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.Ext2FS(device=_LOOP_DEV0, label="root___filesystem")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.defaultLabel)

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = ""
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = None
        self.assertRaisesRegexp(fs.FSError,
            "default label",
            an_fs.writeLabel)

        an_fs.label = "root___filesystem"
        self.assertRaisesRegexp(fs.FSError,
           "bad label format",
           an_fs.writeLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingExt2FS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.Ext2FS(device=_LOOP_DEV0, label="start")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), "start")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingExt2FSNone(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.Ext2FS(device=_LOOP_DEV0, label=None)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.defaultLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingExt2FSEmpty(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.Ext2FS(device=_LOOP_DEV0, label="")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), "")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingJFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.JFS(device=_LOOP_DEV0, label="root___filesystem")
        self.assertIsNone(an_fs.create())

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())

        self.assertRaisesRegexp(fs.FSError,
           "no application to read label",
           an_fs.readLabel)

        an_fs.label = ""
        self.assertIsNone(an_fs.writeLabel())

        an_fs.label = None
        self.assertRaisesRegexp(fs.FSError,
            "default label",
            an_fs.writeLabel)

        an_fs.label = "root___filesystem"
        self.assertRaisesRegexp(fs.FSError,
           "bad label format",
           an_fs.writeLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingReiserFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.ReiserFS(device=_LOOP_DEV0, label="root___filesystem")
        self.assertIsNone(an_fs.create())

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())

        self.assertRaisesRegexp(fs.FSError,
           "no application to read label",
           an_fs.readLabel)

        an_fs.label = ""
        self.assertIsNone(an_fs.writeLabel())

        an_fs.label = None
        self.assertRaisesRegexp(fs.FSError,
            "default label",
            an_fs.writeLabel)

        an_fs.label = "root___filesystem"
        self.assertRaisesRegexp(fs.FSError,
           "bad label format",
           an_fs.writeLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingHFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.HFS(device=_LOOP_DEV0, label="root___filesystem")
        self.assertIsNone(an_fs.create())

        self.assertRaisesRegexp(fs.FSError,
           "no application to read label",
           an_fs.readLabel)

        an_fs.label = "an fs"
        self.assertRaisesRegexp(fs.FSError,
           "no application to set label for filesystem",
           an_fs.writeLabel)

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingHFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.HFS(device=_LOOP_DEV0, label="start")
        self.assertIsNone(an_fs.create())

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingHFSNone(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.Ext2FS(device=_LOOP_DEV0, label=None)
        self.assertIsNone(an_fs.create())

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCreatingHFSEmpty(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.HFS(device=_LOOP_DEV0, label="")
        self.assertIsNone(an_fs.create())

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

def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(InitializationTestCase)
    suite2 = unittest.TestLoader().loadTestsFromTestCase(MethodsTestCase)
    return unittest.TestSuite([suite1, suite2])


if __name__ == "__main__":
    unittest.main()
