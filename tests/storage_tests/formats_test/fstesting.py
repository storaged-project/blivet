
import abc

import os
import tempfile

from . import loopbackedtestcase
from blivet.errors import FSError, FSResizeError, DeviceFormatError
from blivet.size import Size, ROUND_DOWN
from blivet.formats import fs


class FSAsRoot(loopbackedtestcase.LoopBackedTestCase, metaclass=abc.ABCMeta):

    _fs_class = abc.abstractproperty(
        doc="The class of the filesystem being tested on.")

    _DEVICE_SIZE = Size("100 MiB")
    _valid_label = "label"

    def __init__(self, methodName='run_test'):
        super(FSAsRoot, self).__init__(methodName=methodName, device_spec=[self._DEVICE_SIZE])

    def can_resize(self, an_fs):
        """ Returns True if this filesystem has all necessary resizing tools
            available.

            :param an_fs: a filesystem object
        """
        resize_tasks = (an_fs._resize, an_fs._size_info, an_fs._minsize)
        return not any(t.availability_errors for t in resize_tasks)

    def _test_sizes(self, an_fs):
        """ Test relationships between different size values.

            These tests assume that the filesystem exists and that
            the size and minimum size information has been updated.
        """
        _size = an_fs._size
        min_size = an_fs.min_size

        # If resizable, size is target_size
        if an_fs.resizable:
            expected_size = an_fs._target_size
        # If not resizable
        else:
            expected_size = _size
            # If the size can be obtained it will not be 0
            if not an_fs._size_info.availability_errors:
                self.assertNotEqual(expected_size, Size(0))
                self.assertTrue(expected_size <= self._DEVICE_SIZE)
            # Otherwise it will be 0, assuming the device was not initialized
            # with a size.
            else:
                self.assertEqual(expected_size, Size(0))
        self.assertEqual(an_fs.size, expected_size)

        # Only the resizable filesystems can figure out their current min size
        if not an_fs._size_info.availability_errors:
            expected_min_size = min_size
        else:
            expected_min_size = an_fs._min_size
        self.assertEqual(an_fs.min_size, expected_min_size)

        # max_size is a nice simple constant because it is just about
        # what the filesystem can represent
        self.assertEqual(an_fs.max_size, an_fs._max_size)

        # Since the device exists, current_size will always be the real size
        self.assertEqual(an_fs.current_size, _size)

        # Free is the actual size - the minimum size
        self.assertEqual(an_fs.free, max(Size(0), _size - expected_min_size))

        # target size is set by side-effect
        self.assertEqual(an_fs.target_size, an_fs._target_size)

    def test_instantiation(self):
        # Accept default size
        an_fs = self._fs_class()
        self.assertFalse(an_fs.exists)
        self.assertIsNone(an_fs.device)
        self.assertIsNone(an_fs.uuid)
        self.assertEqual(an_fs.options, ",".join(an_fs._mount.options))
        self.assertEqual(an_fs.resizable, False)

        # sizes
        self.assertEqual(an_fs.min_size, an_fs._min_size)
        self.assertEqual(an_fs.max_size, an_fs._max_size)
        self.assertEqual(an_fs.size, Size(0))
        self.assertEqual(an_fs.current_size, Size(0))
        self.assertEqual(an_fs.free, Size(0))
        self.assertEqual(an_fs.target_size, Size(0))

        # Choose a size
        NEW_SIZE = Size("32 MiB")
        an_fs = self._fs_class(size=NEW_SIZE)

        # sizes
        self.assertEqual(an_fs.min_size, an_fs._min_size)
        self.assertEqual(an_fs.max_size, an_fs._max_size)
        self.assertEqual(an_fs.size, NEW_SIZE)
        self.assertEqual(an_fs.current_size, Size(0))
        self.assertEqual(an_fs.free, Size(0))
        self.assertEqual(an_fs.target_size, NEW_SIZE)

    def test_creation(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.resizable, False)
        self.assertTrue(an_fs.exists)
        self.assertIsNone(an_fs.do_check())

        self.assertEqual(an_fs.min_size, an_fs._min_size)
        self.assertEqual(an_fs.max_size, an_fs._max_size)
        self.assertEqual(an_fs.size, Size(0))
        self.assertEqual(an_fs.current_size, Size(0))
        self.assertEqual(an_fs.free, Size(0))
        self.assertEqual(an_fs.target_size, Size(0))

    def test_labeling(self):
        an_fs = self._fs_class()
        if not an_fs.formattable or not an_fs.labeling():
            self.skipTest("can not label filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        an_fs.label = self._valid_label
        self.assertTrue(an_fs.label_format_ok(self._valid_label))
        self.assertIsNone(an_fs.create())
        try:
            label = an_fs.read_label()
            if an_fs.type in ("vfat", "efi"):
                self.assertEqual(label, self._valid_label.upper())
            else:
                self.assertEqual(label, self._valid_label)
        except FSError:
            pass

    def test_relabeling(self):
        an_fs = self._fs_class()
        if not an_fs.formattable or not an_fs.labeling():
            self.skipTest("can not label filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.label = "label"
        self.assertTrue(an_fs.label_format_ok(self._valid_label))
        if an_fs.relabels():
            self.assertIsNone(an_fs.write_label())
        else:
            with self.assertRaises(FSError):
                an_fs.write_label()

    def test_mounting(self):
        an_fs = self._fs_class()
        # FIXME: BTRFS fails to mount
        if isinstance(an_fs, fs.BTRFS):
            self.skipTest("no mounting filesystem %s" % an_fs.name)
        if not an_fs.formattable or not an_fs.mountable:
            self.skipTest("can not create or mount filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        self.assertTrue(an_fs.test_mount())

    def test_mountpoint(self):
        an_fs = self._fs_class()
        # FIXME: BTRFS fails to mount
        if isinstance(an_fs, fs.BTRFS):
            self.skipTest("no mounting filesystem %s" % an_fs.name)
        if not an_fs.formattable or not an_fs.mountable:
            self.skipTest("can not create or mount filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        mountpoint = tempfile.mkdtemp()
        an_fs.mount(mountpoint=mountpoint)
        self.assertEqual(an_fs.system_mountpoint, mountpoint)
        an_fs.unmount()
        self.assertIsNone(an_fs.system_mountpoint)
        os.rmdir(mountpoint)

    def test_resize(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        self._test_sizes(an_fs)
        # CHECKME: target size is still 0 after updated_size_info is called.
        self.assertEqual(an_fs.size, Size(0) if an_fs.resizable else an_fs._size)

        if not self.can_resize(an_fs):
            self.assertFalse(an_fs.resizable)
            # Not resizable, so can not do resizing actions.
            with self.assertRaises(DeviceFormatError):
                an_fs.target_size = Size("64 MiB")
            with self.assertRaises(DeviceFormatError):
                an_fs.do_resize()
        else:
            self.assertTrue(an_fs.resizable)
            # Try a reasonable target size
            TARGET_SIZE = Size("64 MiB")
            an_fs.target_size = TARGET_SIZE
            self.assertEqual(an_fs.target_size, TARGET_SIZE)
            self.assertNotEqual(an_fs._size, TARGET_SIZE)
            self.assertIsNone(an_fs.do_resize())
            ACTUAL_SIZE = TARGET_SIZE.round_to_nearest(an_fs._resize.unit, rounding=ROUND_DOWN)
            self.assertEqual(an_fs.size, ACTUAL_SIZE)
            self.assertEqual(an_fs._size, ACTUAL_SIZE)
            self._test_sizes(an_fs)

        # and no errors should occur when checking
        self.assertIsNone(an_fs.do_check())

    def test_no_explicit_target_size(self):
        """ Because _target_size has not been set, resize sets to min size. """
        # CHECK ME: This is debatable, maybe target size should be set to
        # _size if it is not set when size is calculated. Note that _target_size
        # gets value of _size in constructor, so if _size is set to not-zero
        # in constructor call behavior would be different.

        an_fs = self._fs_class()
        if not self.can_resize(an_fs):
            self.skipTest("Not checking resize for this test category.")
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)

        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        self.assertNotEqual(an_fs.current_size, an_fs.target_size)
        self.assertEqual(an_fs.current_size, an_fs._size)
        self.assertEqual(an_fs.target_size, Size(0))
        self.assertIsNone(an_fs.do_resize())
        self.assertEqual(an_fs.current_size, an_fs.min_size)
        self.assertEqual(an_fs.target_size, an_fs.min_size)
        self._test_sizes(an_fs)

    def test_no_explicit_target_size2(self):
        """ Because _target_size has been set to size in constructor the
            resize action resizes filesystem to that size.
        """
        SIZE = Size("64 MiB")
        an_fs = self._fs_class(size=SIZE)
        if not self.can_resize(an_fs):
            self.skipTest("Not checking resize for this test category.")
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)

        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        # The current size is the actual size, the target size is the size
        # set in the constructor.
        self.assertNotEqual(an_fs.current_size, an_fs.target_size)
        self.assertEqual(an_fs.target_size, SIZE)
        self.assertIsNone(an_fs.do_resize())
        self.assertEqual(an_fs.current_size, SIZE)
        self.assertEqual(an_fs.target_size, SIZE)
        self._test_sizes(an_fs)

    def test_shrink(self):
        an_fs = self._fs_class()
        if not self.can_resize(an_fs):
            self.skipTest("Not checking resize for this test category.")
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)

        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        TARGET_SIZE = Size("64 MiB")
        an_fs.target_size = TARGET_SIZE
        self.assertIsNone(an_fs.do_resize())

        TARGET_SIZE = TARGET_SIZE / 2
        self.assertTrue(TARGET_SIZE > an_fs.min_size)
        an_fs.target_size = TARGET_SIZE
        self.assertEqual(an_fs.target_size, TARGET_SIZE)
        self.assertNotEqual(an_fs._size, TARGET_SIZE)
        # FIXME:
        # do_check() in update_size_info() in do_resize() does not complete tidily
        # here, so resizable becomes False and self.target_size can not be
        # assigned to. This alerts us to the fact that now min size
        # and size are both incorrect values.
        if isinstance(an_fs, fs.NTFS):
            return
        self.assertIsNone(an_fs.do_resize())
        ACTUAL_SIZE = TARGET_SIZE.round_to_nearest(an_fs._resize.unit, rounding=ROUND_DOWN)
        self.assertEqual(an_fs._size, ACTUAL_SIZE)
        self._test_sizes(an_fs)

    def test_too_small(self):
        an_fs = self._fs_class()
        if not self.can_resize(an_fs):
            self.skipTest("Not checking resize for this test category.")
        if not an_fs.formattable:
            self.skipTest("can not create or resize filesystem %s" % an_fs.name)

        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        # can not set target size to less than minimum size
        # CHECKME: Should it raise an FSError instead?
        TARGET_SIZE = an_fs.min_size - Size(1)
        with self.assertRaises(ValueError):
            an_fs.target_size = TARGET_SIZE
        self.assertEqual(an_fs.target_size, Size(0))
        self._test_sizes(an_fs)

    def test_too_big(self):
        an_fs = self._fs_class()
        if not self.can_resize(an_fs):
            self.skipTest("Not checking resize for this test category.")
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)

        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        # can not set target size to maximum size
        # CHECKME: Should it raise an FSError instead?
        TARGET_SIZE = an_fs.max_size
        with self.assertRaises(ValueError):
            an_fs.target_size = TARGET_SIZE
        self.assertEqual(an_fs.target_size, Size(0))
        self._test_sizes(an_fs)

    def test_too_big2(self):
        an_fs = self._fs_class()
        if not self.can_resize(an_fs):
            self.skipTest("Not checking resize for this test category.")
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)

        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        # resizing to near the maximum filesystem size ought to fail
        old_size = an_fs._size
        BIG_SIZE = an_fs.max_size - Size(1)
        an_fs.target_size = BIG_SIZE
        self.assertEqual(an_fs.target_size, BIG_SIZE)
        with self.assertRaises(FSResizeError):
            an_fs.do_resize()

        # CHECKME: size and target size will be adjusted attempted values
        # while current_size will be actual value
        TARGET_SIZE = BIG_SIZE.round_to_nearest(an_fs._resize.unit, rounding=ROUND_DOWN)
        self.assertEqual(an_fs.target_size, TARGET_SIZE)
        self.assertEqual(an_fs.size, an_fs.target_size)
        self.assertEqual(an_fs.current_size, old_size)
        self._test_sizes(an_fs)
