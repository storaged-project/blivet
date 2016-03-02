import unittest
from decimal import Decimal

from blivet.formats.fs import FS, Ext2FS, Ext3FS, Ext4FS, BTRFS, FATFS
from blivet.size import Size

class FSOverheadTestCase(unittest.TestCase):

    def testRequiredSizeFS(self):
        # FS is abstract parent which doesn't have metadata
        self.assertEqual(FS.getRequiredSize(Size("100 MiB")), Size("100 MiB"))
        self.assertEqual(Ext2FS.getRequiredSize(Size("100 MiB")), Size("100 MiB") / Decimal(0.93))

    def testBiggestOverheadFS(self):
        self.assertTrue(FS.biggestOverheadFS() is BTRFS)
        self.assertTrue(FS.biggestOverheadFS([FATFS, Ext2FS, Ext3FS, Ext4FS]) is Ext4FS)

        with self.assertRaises(ValueError):
            FS.biggestOverheadFS([])

        # only classes with FS parent will be used
        with self.assertRaises(ValueError):
            class Dummy(object):
                pass

            FS.biggestOverheadFS([Dummy])

