#!/usr/bin/python
import os
import unittest

from devicelibs_test import baseclass
from blivet.formats import device_formats
import blivet.formats.fs as fs

class InitializationTestCase(unittest.TestCase):
    """Test FS object initialization."""

    def testLabels(self):
        """Initialize some filesystems with valid and invalid labels."""

        # Ext2FS has a maximum length of 16
        self.assertRaisesRegexp(fs.FSError,
           "Filesystem label.*incorrectly formatted",
           fs.Ext2FS,
           device="/dev", label="root___filesystem")

        self.assertIsNotNone(fs.Ext2FS(label="root__filesystem"))

        # FATFS has a maximum length of 11
        self.assertRaisesRegexp(fs.FSError,
           "Filesystem label.*incorrectly formatted",
           fs.FATFS,
           device="/dev", label="rtfilesystem")

        self.assertIsNotNone(fs.FATFS(label="rfilesystem"))

        # JFS has a maximum length of 16
        self.assertRaisesRegexp(fs.FSError,
           "Filesystem label.*incorrectly formatted",
           fs.JFS,
           device="/dev", label="root___filesystem")

        self.assertIsNotNone(fs.JFS(label="root__filesystem"))

        # ReiserFS has a maximum length of 16
        self.assertRaisesRegexp(fs.FSError,
           "Filesystem label.*incorrectly formatted",
           fs.ReiserFS,
           device="/dev", label="root___filesystem")

        self.assertIsNotNone(fs.ReiserFS(label="root__filesystem"))

        #XFS has a maximum length 12 and does not allow spaces
        self.assertRaisesRegexp(fs.FSError,
           "Filesystem label.*incorrectly formatted",
           fs.XFS,
           device="/dev", label="root filesyst")
        self.assertRaisesRegexp(fs.FSError,
           "Filesystem label.*incorrectly formatted",
           fs.XFS,
           device="/dev", label="root file")

        self.assertIsNotNone(fs.XFS(label="root_filesys"))

        # all devices are permitted to have a label of None
        for k, v  in device_formats.items():
            self.assertIsNotNone(v(label=None))

class MethodsTestCase(unittest.TestCase):
    """Test some methods that do not require actual images."""

    def setUp(self):
        self.fs = {}
        for k, v  in device_formats.items():
            if issubclass(v, fs.FS) and not issubclass(v, fs.NFS):
                self.fs[k] = v(device="/dev", label="myfs")


    def testGetLabelArgs(self):
        self.longMessage = True

        # ReiserFS uses a -l flag
        reiserfs = self.fs["reiserfs"]
        self.assertEqual(reiserfs._labelfs.setLabelCommand(reiserfs),
           ["reiserfstune", "-l", "myfs", "/dev"], msg="reiserfs")

        # JFS, XFS use a -L flag
        lflag_classes = [fs.JFS, fs.XFS]
        for k, v in [(k, v) for k, v in self.fs.items() if any(isinstance(v, c) for c in lflag_classes)]:
            self.assertEqual(v._labelfs.setLabelCommand(v), [v._labelfs.name, "-L", "myfs", "/dev"], msg=k)

        # Ext2FS and descendants and FATFS do not use a flag
        noflag_classes = [fs.Ext2FS, fs.FATFS]
        for k, v in [(k, v) for k, v in self.fs.items() if any(isinstance(v, c) for c in noflag_classes)]:
            self.assertEqual(v._labelfs.setLabelCommand(v), [v._labelfs.name, "/dev", "myfs"], msg=k)

        # all of the remaining should have no labelfsProg
        omit_classes = [ fs.ReiserFS ] + lflag_classes + noflag_classes
        for k, v in [(k, v) for k, v in self.fs.items() if not any(isinstance(v, c) for c in omit_classes)]:
            self.assertIsNone(v.labelfsProg)

class LabelingAsRootTestCase(baseclass.DevicelibsTestCase):
    """Tests for labeling a filesystem and reading its label.

       For some filesystems, there is an application for writing the label
       but the same application does not read the label. For those, it
       is only possible to check if the write operation completed succesfully.
    """

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingXFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.XFS(device=_LOOP_DEV0)
        self.assertIsNone(an_fs.create())

        an_fs.label = "temeraire"
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = None
        self.assertRaisesRegexp(fs.FSError,
            "can not unset a filesystem label",
            an_fs.writeLabel)
        self.assertEqual(an_fs.readLabel(), "temeraire")

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingFATFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.FATFS(device=_LOOP_DEV0)
        self.assertIsNone(an_fs.create())

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = None
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)


    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingExt2FS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.Ext2FS(device=_LOOP_DEV0)
        self.assertIsNone(an_fs.create())

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = None
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)


    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingJFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.JFS(device=_LOOP_DEV0)
        self.assertIsNone(an_fs.create())

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())

        self.assertRaisesRegexp(fs.FSError,
           "no application to read label",
           an_fs.readLabel)

        an_fs.label = None
        self.assertIsNone(an_fs.writeLabel())


    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testLabelingReiserFS(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]

        an_fs = fs.ReiserFS(device=_LOOP_DEV0)
        self.assertIsNone(an_fs.create())

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())

        self.assertRaisesRegexp(fs.FSError,
           "no application to read label",
           an_fs.readLabel)

        an_fs.label = None
        self.assertIsNone(an_fs.writeLabel())

def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(InitializationTestCase)
    suite2 = unittest.TestLoader().loadTestsFromTestCase(MethodsTestCase)
    return unittest.TestSuite([suite1, suite2])


if __name__ == "__main__":
    unittest.main()
