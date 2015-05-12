#!/usr/bin/python
import os
import tempfile
import unittest

import blivet.formats.fs as fs
from blivet.size import Size, ROUND_DOWN

from tests import loopbackedtestcase

from . import fstesting

class Ext2FSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.Ext2FS

class Ext3FSTestCase(Ext2FSTestCase):
    _fs_class = fs.Ext3FS

class Ext4FSTestCase(Ext3FSTestCase):
    _fs_class = fs.Ext4FS

class FATFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.FATFS

class EFIFSTestCase(FATFSTestCase):
    _fs_class = fs.EFIFS

class BTRFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.BTRFS

@unittest.skip("Unable to create GFS2 filesystem.")
class GFS2TestCase(fstesting.FSAsRoot):
    _fs_class = fs.GFS2

class JFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.JFS

class ReiserFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.ReiserFS

class XFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.XFS

class HFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.HFS

class AppleBootstrapFSTestCase(HFSTestCase):
    _fs_class = fs.AppleBootstrapFS

class HFSPlusTestCase(fstesting.FSAsRoot):
    _fs_class = fs.HFSPlus

class MacEFIFSTestCase(HFSPlusTestCase):
    _fs_class = fs.MacEFIFS

@unittest.skip("Unable to create because NTFS._formattable is False.")
class NTFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.NTFS

@unittest.skip("Unable to create because device fails deviceCheck().")
class NFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.NFS

class NFSv4TestCase(NFSTestCase):
    _fs_class = fs.NFSv4

class Iso9660FS(fstesting.FSAsRoot):
    _fs_class = fs.Iso9660FS

@unittest.skip("Too strange to test using this framework.")
class NoDevFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.NoDevFS

class DevPtsFSTestCase(NoDevFSTestCase):
    _fs_class = fs.DevPtsFS

class ProcFSTestCase(NoDevFSTestCase):
    _fs_class = fs.ProcFS

class SysFSTestCase(NoDevFSTestCase):
    _fs_class = fs.SysFS

class TmpFSTestCase(NoDevFSTestCase):
    _fs_class = fs.TmpFS

class SELinuxFSTestCase(NoDevFSTestCase):
    _fs_class = fs.SELinuxFS

class USBFSTestCase(NoDevFSTestCase):
    _fs_class = fs.USBFS

class BindFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.BindFS

class SimpleTmpFSTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='runTest'):
        super(SimpleTmpFSTestCase, self).__init__(methodName=methodName)

    def testSimple(self):
        an_fs = fs.TmpFS()

        # a nodev fs need not have been created to exist
        self.assertTrue(an_fs.exists)
        self.assertEqual(an_fs.device, "tmpfs")
        self.assertTrue(an_fs.testMount())

class ResizeTmpFSTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='runTest'):
        super(ResizeTmpFSTestCase, self).__init__(methodName=methodName)
        self.an_fs = fs.TmpFS()
        self.an_fs.__class__._resizable = True
        self.mountpoint = None

    def setUp(self):
        self.mountpoint = tempfile.mkdtemp()
        self.an_fs.mountpoint = self.mountpoint
        self.an_fs.mount()

    def testResize(self):
        self.an_fs.updateSizeInfo()
        newsize = self.an_fs.currentSize * 2
        self.an_fs.targetSize = newsize
        self.assertIsNone(self.an_fs.doResize())
        self.assertEqual(self.an_fs.size, newsize.roundToNearest(self.an_fs._resize.unit, rounding=ROUND_DOWN))

    def testShrink(self):
        # Can not shrink tmpfs, because its minimum size is its current size
        self.an_fs.updateSizeInfo()
        newsize = Size("2 MiB")
        self.assertTrue(newsize < self.an_fs.currentSize)
        with self.assertRaises(ValueError):
            self.an_fs.targetSize = newsize

    def tearDown(self):
        try:
            self.an_fs.unmount()
        except Exception: # pylint: disable=broad-except
            pass
        os.rmdir(self.mountpoint)

if __name__ == "__main__":
    unittest.main()
