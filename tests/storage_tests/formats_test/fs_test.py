import os
import tempfile
import unittest

import parted

import blivet.formats.fs as fs
from blivet.size import Size, ROUND_DOWN
from blivet.errors import DeviceFormatError, FSError
from blivet.formats import get_format
from blivet.devices import PartitionDevice, DiskDevice
from blivet.flags import flags
from blivet.util import capture_output
from blivet import udev

from .loopbackedtestcase import LoopBackedTestCase

from . import fstesting


class Ext2FSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.Ext2FS


class Ext3FSTestCase(Ext2FSTestCase):
    _fs_class = fs.Ext3FS


class Ext4FSTestCase(Ext3FSTestCase):
    _fs_class = fs.Ext4FS

    def test_online_resize(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())
        an_fs.update_size_info()

        if not self.can_resize(an_fs):
            self.skipTest("filesystem is not resizable")

        # shrink offline first (ext doesn't support online shrinking)
        TARGET_SIZE = Size("64 MiB")
        an_fs.target_size = TARGET_SIZE
        self.assertEqual(an_fs.target_size, TARGET_SIZE)
        self.assertNotEqual(an_fs._size, TARGET_SIZE)
        self.assertIsNone(an_fs.do_resize())

        with tempfile.TemporaryDirectory() as mountpoint:
            an_fs.mount(mountpoint=mountpoint)

            # grow back when mounted
            TARGET_SIZE = Size("100 MiB")
            an_fs.target_size = TARGET_SIZE
            self.assertEqual(an_fs.target_size, TARGET_SIZE)
            self.assertNotEqual(an_fs._size, TARGET_SIZE)

            # should fail, online resize disabled by default
            with self.assertRaisesRegex(FSError, "Resizing of mounted filesystems is disabled"):
                an_fs.do_resize()

            # enable online resize
            flags.allow_online_fs_resize = True
            an_fs.do_resize()
            flags.allow_online_fs_resize = False
            self._test_sizes(an_fs)
            self.assertEqual(an_fs.system_mountpoint, mountpoint)

            an_fs.unmount()

    def test_create_options(self):
        label = "root-test-label"
        uuid = "c1b9d5a2-f162-11cf-9ece-0020afc76f16"

        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]

        # custom fs create options -- -L <label> and -U <uuid> for mke2fs
        an_fs.create_options = "-L %s -U %s" % (label, uuid)
        an_fs.create()

        sys_label = an_fs.read_label()
        self.assertEqual(sys_label, label)

        out = capture_output(["blkid", "-sUUID", "-ovalue", self.loop_devices[0]])
        self.assertEqual(out.strip(), uuid)

    def test_fs_is_empty(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())

        self.assertTrue(an_fs.is_empty)

        with tempfile.TemporaryDirectory() as mountpoint:
            an_fs.mount(mountpoint=mountpoint)
            os.makedirs(os.path.join(mountpoint, "test"))
            an_fs.unmount()
            self.assertFalse(an_fs.is_empty)

        self.assertFalse(an_fs.is_empty)


class FATFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.FATFS


class EFIFSTestCase(FATFSTestCase):
    _fs_class = fs.EFIFS


class BTRFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.BTRFS


class GFS2TestCase(fstesting.FSAsRoot):
    _fs_class = fs.GFS2
    _valid_label = "label:label"

    @classmethod
    def setUpClass(cls):
        # allow creating gfs2
        flags.gfs2 = True
        super(GFS2TestCase, cls).setUpClass()

    @classmethod
    def tearDownClass(cls):
        # reset flag back to default
        flags.gfs2 = False
        super(GFS2TestCase, cls).tearDownClass()


class XFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.XFS
    _DEVICE_SIZE = Size("500 MiB")

    def can_resize(self, an_fs):
        resize_tasks = (an_fs._resize, an_fs._size_info)
        return not any(t.availability_errors for t in resize_tasks)

    def _create_partition(self, disk, size):
        disk.format = get_format("disklabel", device=disk.path, label_type="msdos")
        disk.format.create()
        pstart = disk.format.alignment.grainSize
        pend = pstart + int(Size(size) / disk.format.parted_device.sectorSize)
        disk.format.add_partition(pstart, pend, parted.PARTITION_NORMAL)
        disk.format.parted_disk.commit()
        udev.settle()
        part = disk.format.parted_disk.getPartitionBySector(pstart)

        device = PartitionDevice(os.path.basename(part.path))
        device.disk = disk
        device.exists = True
        device.parted_partition = part

        return device

    def _remove_partition(self, partition, disk):
        disk.format.remove_partition(partition.parted_partition)
        disk.format.parted_disk.commit()

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
                an_fs.target_size = Size("300 MiB")
            with self.assertRaises(DeviceFormatError):
                an_fs.do_resize()
        else:
            disk = DiskDevice(os.path.basename(self.loop_devices[0]))
            part = self._create_partition(disk, Size("300 MiB"))
            an_fs = self._fs_class()
            an_fs.device = part.path
            self.assertIsNone(an_fs.create())
            an_fs.update_size_info()

            self.assertTrue(an_fs.resizable)

            # grow the partition so we can grow the filesystem
            self._remove_partition(part, disk)
            part = self._create_partition(disk, size=part.size + Size("40 MiB"))

            # Try a reasonable target size
            TARGET_SIZE = Size("325 MiB")
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

            self._remove_partition(part, disk)

    def test_shrink(self):
        self.skipTest("Not checking resize for this test category.")

    def test_too_small(self):
        self.skipTest("Not checking resize for this test category.")

    def test_no_explicit_target_size2(self):
        self.skipTest("Not checking resize for this test category.")

    def test_too_big2(self):
        # XXX this tests assumes that resizing to max size - 1 B will fail, but xfs_grow won't
        self.skipTest("Not checking resize for this test category.")

    def test_fs_is_empty(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        an_fs.device = self.loop_devices[0]
        self.assertIsNone(an_fs.create())

        self.assertTrue(an_fs.is_empty)

        with tempfile.TemporaryDirectory() as mountpoint:
            an_fs.mount(mountpoint=mountpoint)
            os.makedirs(os.path.join(mountpoint, "test"))
            an_fs.unmount()
            self.assertFalse(an_fs.is_empty)

        self.assertFalse(an_fs.is_empty)


class HFSPlusTestCase(fstesting.FSAsRoot):
    _fs_class = fs.HFSPlus


class MacEFIFSTestCase(HFSPlusTestCase):
    _fs_class = fs.MacEFIFS


class NTFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.NTFS


class F2FSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.F2FS


@unittest.skip("Unable to create because device fails device_check().")
class NFSTestCase(fstesting.FSAsRoot):
    _fs_class = fs.NFS


class NFSv4TestCase(NFSTestCase):
    _fs_class = fs.NFSv4


class Iso9660FS(fstesting.FSAsRoot):
    _fs_class = fs.Iso9660FS


class UDFFS(fstesting.FSAsRoot):
    _fs_class = fs.UDFFS


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


class SimpleTmpFSTestCase(LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(SimpleTmpFSTestCase, self).__init__(methodName=methodName)

    def test_simple(self):
        an_fs = fs.TmpFS()

        # a nodev fs need not have been created to exist
        self.assertTrue(an_fs.exists)
        self.assertEqual(an_fs.device, "tmpfs")
        self.assertTrue(an_fs.test_mount())


class ResizeTmpFSTestCase(LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(ResizeTmpFSTestCase, self).__init__(methodName=methodName)
        self.an_fs = fs.TmpFS()
        self.an_fs.__class__._resizable = True
        self.mountpoint = None

    def setUp(self):
        self.mountpoint = tempfile.mkdtemp()
        self.an_fs.mountpoint = self.mountpoint
        self.an_fs.mount()
        self.addCleanup(self._clean_up)

    def test_resize(self):
        self.an_fs.update_size_info()
        newsize = self.an_fs.current_size * 2
        self.an_fs.target_size = newsize
        self.assertIsNone(self.an_fs.do_resize())
        self.assertEqual(self.an_fs.size, newsize.round_to_nearest(self.an_fs._resize.unit, rounding=ROUND_DOWN))

    def test_shrink(self):
        # Can not shrink tmpfs, because its minimum size is its current size
        self.an_fs.update_size_info()
        newsize = Size("2 MiB")
        self.assertTrue(newsize < self.an_fs.current_size)
        with self.assertRaises(ValueError):
            self.an_fs.target_size = newsize

    def _clean_up(self):
        try:
            self.an_fs.unmount()
        except Exception:  # pylint: disable=broad-except
            pass
        os.rmdir(self.mountpoint)
