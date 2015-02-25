#!/usr/bin/python

import abc
from six import add_metaclass

import os
import tempfile

from tests import loopbackedtestcase
from blivet.errors import FSError, FSResizeError
from blivet.size import Size, ROUND_DOWN
from blivet.formats import fs

@add_metaclass(abc.ABCMeta)
class FSAsRoot(loopbackedtestcase.LoopBackedTestCase):

    _fs_class = abc.abstractproperty(
       doc="The class of the filesystem being tested on.")

    _resizable = abc.abstractproperty(
       doc="Should we expect to be able to resize this filesystem.")

    _DEVICE_SIZE = Size("100 MiB")

    def __init__(self, methodName='runTest'):
        super(FSAsRoot, self).__init__(methodName=methodName, deviceSpec=[self._DEVICE_SIZE])

    def setUp(self):
        an_fs = self._fs_class()
        if not an_fs.utilsAvailable:
            self.skipTest("utilities unavailable for filesystem %s" % an_fs.name)
        super(FSAsRoot, self).setUp()

    def _test_sizes(self, an_fs):
        """ Test relationships between different size values.

            These tests assume that the filesystem exists and that
            the size and minimum size information has been updated.
        """
        _size = an_fs._size
        min_size = an_fs.minSize

        # If resizable, size is targetSize
        if an_fs.resizable:
            expected_size = an_fs._targetSize
        # If not resizable
        else:
            expected_size = _size
            # If the size can be obtained it will not be 0
            if an_fs._info:
                self.assertNotEqual(expected_size, Size(0))
                self.assertTrue(expected_size <= self._DEVICE_SIZE)
            # Otherwise it will be 0, assuming the device was not initialized
            # with a size.
            else:
                self.assertEqual(expected_size, Size(0))
        self.assertEqual(an_fs.size, expected_size)

        # Only the resizable filesystems can figure out their current min size
        if an_fs._resize:
            expected_min_size = min_size
        else:
            expected_min_size = an_fs._minSize
        self.assertEqual(an_fs.minSize, expected_min_size)

        # maxSize is a nice simple constant because it is just about
        # what the filesystem can represent
        self.assertEqual(an_fs.maxSize, an_fs._maxSize)

        # Since the device exists, currentSize will always be the real size
        self.assertEqual(an_fs.currentSize, _size)

        # Free is the actual size - the minimum size
        self.assertEqual(an_fs.free, _size - expected_min_size)

        # target size is set by side-effect
        self.assertEqual(an_fs.targetSize, an_fs._targetSize)

    def testInstantiation(self):
        # Accept default size
        an_fs = self._fs_class()
        self.assertFalse(an_fs.exists)
        self.assertIsNone(an_fs.device)
        self.assertIsNone(an_fs.uuid)
        self.assertEqual(an_fs.options, ",".join(an_fs._mount.options))
        self.assertEqual(an_fs.resizable, False)

        # sizes
        expected_min_size = Size(0) if self._resizable else an_fs._minSize
        self.assertEqual(an_fs.minSize, expected_min_size)

        self.assertEqual(an_fs.maxSize, an_fs._maxSize)
        self.assertEqual(an_fs.size, Size(0))
        self.assertEqual(an_fs.currentSize, Size(0))
        self.assertEqual(an_fs.free, Size(0))
        self.assertEqual(an_fs.targetSize, Size(0))

        # Choose a size
        NEW_SIZE = Size("32 MiB")
        an_fs = self._fs_class(size=NEW_SIZE)

        # sizes
        expected_min_size = Size(0) if self._resizable else an_fs._minSize
        self.assertEqual(an_fs.minSize, expected_min_size)

        self.assertEqual(an_fs.maxSize, an_fs._maxSize)
        self.assertEqual(an_fs.size, NEW_SIZE)
        self.assertEqual(an_fs.currentSize, Size(0))
        self.assertEqual(an_fs.free, Size(0))
        self.assertEqual(an_fs.targetSize, NEW_SIZE)

    def testCreation(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            return
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.resizable, False)
        self.assertTrue(an_fs.exists)
        self.assertIsNone(an_fs.doCheck())

        expected_min_size = Size(0) if self._resizable else an_fs._minSize
        self.assertEqual(an_fs.minSize, expected_min_size)

        self.assertEqual(an_fs.maxSize, an_fs._maxSize)
        self.assertEqual(an_fs.size, Size(0))
        self.assertEqual(an_fs.currentSize, Size(0))
        self.assertEqual(an_fs.free, Size(0))
        self.assertEqual(an_fs.targetSize, Size(0))

    def testLabeling(self):
        an_fs = self._fs_class()
        if not an_fs.labeling():
            return
        an_fs.device = self.loopDevices[0]
        an_fs.label = "label"
        self.assertTrue(an_fs.labelFormatOK("label"))
        self.assertIsNone(an_fs.create())
        try:
            label = an_fs.readLabel()
            self.assertEqual(label, "label")
        except FSError:
            pass

    def testRelabeling(self):
        an_fs = self._fs_class()
        if not an_fs.labeling():
            return
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.label = "label"
        self.assertTrue(an_fs.labelFormatOK("label"))
        if an_fs.relabels():
            self.assertIsNone(an_fs.writeLabel())
        else:
            with self.assertRaises(FSError):
                an_fs.writeLabel()

    def testMounting(self):
        an_fs = self._fs_class()
        # FIXME: BTRFS fails to mount
        if isinstance(an_fs, fs.BTRFS):
            return
        if not an_fs.formattable:
            return
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        self.assertTrue(an_fs.testMount())

    def testMountpoint(self):
        an_fs = self._fs_class()
        # FIXME: BTRFS fails to mount
        if isinstance(an_fs, fs.BTRFS):
            return
        if not an_fs.formattable or not an_fs.mountable:
            return
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        mountpoint = tempfile.mkdtemp()
        an_fs.mount(mountpoint=mountpoint)
        self.assertEqual(an_fs.systemMountpoint, mountpoint)
        an_fs.unmount()
        self.assertIsNone(an_fs.systemMountpoint)
        os.rmdir(mountpoint)

    def testResize(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            return
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.updateSizeInfo()

        self._test_sizes(an_fs)
        # CHECKME: target size is still 0 after updatedSizeInfo is called.
        self.assertEqual(an_fs.size, Size(0) if an_fs.resizable else an_fs._size)

        if not self._resizable:
            self.assertFalse(an_fs.resizable)
            # Not resizable, so can not do resizing actions.
            with self.assertRaises(FSError):
                an_fs.targetSize = Size("64 MiB")
            with self.assertRaises(FSError):
                an_fs.doResize()
        else:
            self.assertTrue(an_fs.resizable)
            # Try a reasonable target size
            TARGET_SIZE = Size("64 MiB")
            an_fs.targetSize = TARGET_SIZE
            self.assertEqual(an_fs.targetSize, TARGET_SIZE)
            self.assertNotEqual(an_fs._size, TARGET_SIZE)
            self.assertIsNone(an_fs.doResize())
            ACTUAL_SIZE = TARGET_SIZE.roundToNearest(an_fs._resize.unit, rounding=ROUND_DOWN)
            self.assertEqual(an_fs.size, ACTUAL_SIZE)
            self.assertEqual(an_fs._size, ACTUAL_SIZE)
            self._test_sizes(an_fs)

        # and no errors should occur when checking
        self.assertIsNone(an_fs.doCheck())

    def testNoExplicitTargetSize(self):
        """ Because _targetSize has not been set, resize sets to min size. """
        # CHECK ME: This is debatable, maybe target size should be set to
        # _size if it is not set when size is calculated. Note that _targetSize
        # gets value of _size in constructor, so if _size is set to not-zero
        # in constructor call behavior would be different.
        if not self._resizable:
            return

        an_fs = self._fs_class()
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.updateSizeInfo()

        self.assertNotEqual(an_fs.currentSize, an_fs.targetSize)
        self.assertEqual(an_fs.currentSize, an_fs._size)
        self.assertEqual(an_fs.targetSize, Size(0))
        self.assertIsNone(an_fs.doResize())
        self.assertEqual(an_fs.currentSize, an_fs.minSize)
        self.assertEqual(an_fs.targetSize, an_fs.minSize)
        self._test_sizes(an_fs)

    def testNoExplicitTargetSize2(self):
        """ Because _targetSize has been set to size in constructor the
            resize action resizes filesystem to that size.
        """
        if not self._resizable:
            return

        SIZE = Size("64 MiB")
        an_fs = self._fs_class(size=SIZE)
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.updateSizeInfo()

        # The current size is the actual size, the target size is the size
        # set in the constructor.
        self.assertNotEqual(an_fs.currentSize, an_fs.targetSize)
        self.assertEqual(an_fs.targetSize, SIZE)
        self.assertIsNone(an_fs.doResize())
        self.assertEqual(an_fs.currentSize, SIZE)
        self.assertEqual(an_fs.targetSize, SIZE)
        self._test_sizes(an_fs)

    def testShrink(self):
        if not self._resizable:
            return

        an_fs = self._fs_class()
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.updateSizeInfo()

        TARGET_SIZE = Size("64 MiB")
        an_fs.targetSize = TARGET_SIZE
        self.assertIsNone(an_fs.doResize())

        TARGET_SIZE = TARGET_SIZE / 2
        self.assertTrue(TARGET_SIZE > an_fs.minSize)
        an_fs.targetSize = TARGET_SIZE
        self.assertEqual(an_fs.targetSize, TARGET_SIZE)
        self.assertNotEqual(an_fs._size, TARGET_SIZE)
        # FIXME:
        # doCheck() in updateSizeInfo() in doResize() does not complete tidily
        # here, so resizable becomes False and self.targetSize can not be
        # assigned to. This alerts us to the fact that now min size
        # and size are both incorrect values.
        if isinstance(an_fs, fs.NTFS):
            return
        self.assertIsNone(an_fs.doResize())
        ACTUAL_SIZE = TARGET_SIZE.roundToNearest(an_fs._resize.unit, rounding=ROUND_DOWN)
        self.assertEqual(an_fs._size, ACTUAL_SIZE)
        self._test_sizes(an_fs)

    def testTooSmall(self):
        if not self._resizable:
            return

        an_fs = self._fs_class()
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.updateSizeInfo()

        # can not set target size to less than minimum size
        # CHECKME: Should it raise an FSError instead?
        TARGET_SIZE = an_fs.minSize - Size(1)
        with self.assertRaises(ValueError):
            an_fs.targetSize = TARGET_SIZE
        self.assertEqual(an_fs.targetSize, Size(0))
        self._test_sizes(an_fs)

    def testTooBig(self):
        if not self._resizable:
            return

        an_fs = self._fs_class()
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.updateSizeInfo()

        # can not set target size to maximum size
        # CHECKME: Should it raise an FSError instead?
        TARGET_SIZE = an_fs.maxSize
        with self.assertRaises(ValueError):
            an_fs.targetSize = TARGET_SIZE
        self.assertEqual(an_fs.targetSize, Size(0))
        self._test_sizes(an_fs)

    def testTooBig2(self):
        if not self._resizable:
            return

        an_fs = self._fs_class()
        an_fs.device = self.loopDevices[0]
        self.assertIsNone(an_fs.create())
        an_fs.updateSizeInfo()

        # resizing to near the maximum filesystem size ought to fail
        old_size = an_fs._size
        BIG_SIZE = an_fs.maxSize - Size(1)
        an_fs.targetSize = BIG_SIZE
        self.assertEqual(an_fs.targetSize, BIG_SIZE)
        with self.assertRaises(FSResizeError):
            an_fs.doResize()

        # CHECKME: size and target size will be adjusted attempted values
        # while currentSize will be actual value
        TARGET_SIZE = BIG_SIZE.roundToNearest(an_fs._resize.unit, rounding=ROUND_DOWN)
        self.assertEqual(an_fs.targetSize, TARGET_SIZE)
        self.assertEqual(an_fs.size, an_fs.targetSize)
        self.assertEqual(an_fs.currentSize, old_size)
        self._test_sizes(an_fs)
