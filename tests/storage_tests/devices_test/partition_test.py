# vim:set fileencoding=utf-8

from collections import namedtuple
import os
import six
import unittest
import blivet.deviceaction
import parted

try:
    from unittest.mock import patch
except ImportError:
    from mock import patch

import blivet
from blivet.devices import DiskFile
from blivet.devices import PartitionDevice
from blivet.formats import get_format
from blivet.size import Size
from blivet.util import sparsetmpfile

from ..storagetestcase import StorageTestCase


Weighted = namedtuple("Weighted", ["fstype", "mountpoint", "true_funcs", "weight"])

weighted = [Weighted(fstype=None, mountpoint="/", true_funcs=[], weight=0),
            Weighted(fstype=None, mountpoint="/boot", true_funcs=[], weight=2000),
            Weighted(fstype="biosboot", mountpoint=None, true_funcs=['is_x86'], weight=5000),
            Weighted(fstype="efi", mountpoint="/boot/efi", true_funcs=['is_efi'], weight=5000),
            Weighted(fstype="prepboot", mountpoint=None, true_funcs=['is_ppc', 'is_ipseries'], weight=5000),
            Weighted(fstype="appleboot", mountpoint=None, true_funcs=['is_ppc', 'is_pmac'], weight=5000),
            Weighted(fstype=None, mountpoint="/", true_funcs=['is_arm'], weight=-100)]

arch_funcs = ['is_arm', 'is_efi', 'is_ipseries', 'is_pmac', 'is_ppc', 'is_x86']


class PartitionDeviceTestCase(unittest.TestCase):

    def test_target_size(self):
        with sparsetmpfile("targetsizetest", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, label_type="msdos")
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.parted_device.sectorSize)
            start = int(grain_size)
            orig_size = Size("6 MiB")
            end = start + int(orig_size / sector_size) - 1
            disk.format.add_partition(start, end)
            partition = disk.format.parted_disk.getPartitionBySector(start)
            self.assertNotEqual(partition, None)
            self.assertEqual(orig_size, Size(partition.getLength(unit='B')))

            device = PartitionDevice(os.path.basename(partition.path),
                                     size=orig_size)
            device.disk = disk
            device.exists = True
            device.parted_partition = partition

            device.format = get_format("ext4", device=device.path)
            device.format.exists = True
            # grain size should be 1 MiB
            device.format._min_instance_size = Size("2 MiB") + (grain_size / 2)
            device.format._resizable = True

            # Make sure things are as expected to begin with.
            self.assertEqual(device.size, orig_size)
            self.assertEqual(device.min_size, Size("3 MiB"))
            # start sector's at 1 MiB
            self.assertEqual(device.max_size, Size("9 MiB"))

            # ValueError if not Size
            with six.assertRaisesRegex(self, ValueError,
                                       "new size must.*type Size"):
                device.target_size = 22

            self.assertEqual(device.target_size, orig_size)

            # ValueError if size smaller than min_size
            with six.assertRaisesRegex(self, ValueError,
                                       "size.*smaller than the minimum"):
                device.target_size = Size("1 MiB")

            self.assertEqual(device.target_size, orig_size)

            # ValueError if size larger than max_size
            with six.assertRaisesRegex(self, ValueError,
                                       "size.*larger than the maximum"):
                device.target_size = Size("11 MiB")

            self.assertEqual(device.target_size, orig_size)

            # ValueError if unaligned
            with six.assertRaisesRegex(self, ValueError, "new size.*not.*aligned"):
                device.target_size = Size("3.1 MiB")

            self.assertEqual(device.target_size, orig_size)

            # successfully set a new target size
            new_target = device.max_size
            device.target_size = new_target
            self.assertEqual(device.target_size, new_target)
            self.assertEqual(device.size, new_target)
            parted_size = Size(device.parted_partition.getLength(unit='B'))
            self.assertEqual(parted_size, device.target_size)

            # reset target size to original size
            device.target_size = orig_size
            self.assertEqual(device.target_size, orig_size)
            self.assertEqual(device.size, orig_size)
            parted_size = Size(device.parted_partition.getLength(unit='B'))
            self.assertEqual(parted_size, device.target_size)

    def test_min_max_size_alignment(self):
        with sparsetmpfile("minsizetest", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path)
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.parted_device.sectorSize)
            start = int(grain_size)
            end = start + int(Size("6 MiB") / sector_size)
            disk.format.add_partition(start, end)
            partition = disk.format.parted_disk.getPartitionBySector(start)
            self.assertNotEqual(partition, None)

            device = PartitionDevice(os.path.basename(partition.path))
            device.disk = disk
            device.exists = True
            device.parted_partition = partition

            # Typical sector size is 512 B.
            # Default optimum alignment grain size is 2048 sectors, or 1 MiB.
            device.format = get_format("ext4", device=device.path)
            device.format.exists = True
            device.format._min_instance_size = Size("2 MiB") + (grain_size / 2)
            device.format._resizable = True

            ##
            # min_size
            ##

            # The end sector based only on format min size should be unaligned.
            min_sectors = int(device.format.min_size / sector_size)
            min_end_sector = partition.geometry.start + min_sectors - 1
            self.assertEqual(
                disk.format.end_alignment.isAligned(partition.geometry,
                                                    min_end_sector),
                False)

            # The end sector based on device min size should be aligned.
            min_sectors = int(device.min_size / sector_size)
            min_end_sector = partition.geometry.start + min_sectors - 1
            self.assertEqual(
                disk.format.end_alignment.isAligned(partition.geometry,
                                                    min_end_sector),
                True)

            ##
            # max_size
            ##

            # Add a partition starting three sectors past an aligned sector and
            # extending to the end of the disk so that there's a free region
            # immediately following the first partition with an unaligned end
            # sector.
            free = disk.format.parted_disk.getFreeSpaceRegions()[-1]
            raw_start = int(Size("9 MiB") / sector_size)
            start = disk.format.alignment.alignUp(free, raw_start) + 3
            disk.format.add_partition(start, disk.format.parted_device.length - 1)

            # Verify the end of the free region immediately following the first
            # partition is unaligned.
            free = disk.format.parted_disk.getFreeSpaceRegions()[1]
            self.assertEqual(disk.format.end_alignment.isAligned(free, free.end),
                             False)

            # The end sector based on device min size should be aligned.
            max_sectors = int(device.max_size / sector_size)
            max_end_sector = partition.geometry.start + max_sectors - 1
            self.assertEqual(
                disk.format.end_alignment.isAligned(free, max_end_sector),
                True)

    @patch("blivet.devices.partition.PartitionDevice.read_current_size", lambda part: part.size)
    def test_extended_min_size(self):
        with sparsetmpfile("extendedtest", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, label_type="msdos")
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.parted_device.sectorSize)

            extended_start = int(grain_size)
            extended_end = extended_start + int(Size("6 MiB") / sector_size)
            disk.format.add_partition(extended_start, extended_end, parted.PARTITION_EXTENDED)
            extended = disk.format.extended_partition
            self.assertNotEqual(extended, None)

            extended_device = PartitionDevice(os.path.basename(extended.path))
            extended_device.disk = disk
            extended_device.exists = True
            extended_device.parted_partition = extended

            # existing extended partition should be always resizable
            self.assertTrue(extended_device.resizable)

            # no logical partitions --> min size should be max of 1 KiB and grain_size
            self.assertEqual(extended_device.min_size,
                             extended_device.align_target_size(max(grain_size, Size("1 KiB"))))

            logical_start = extended_start + 1
            logical_end = extended_end // 2
            disk.format.add_partition(logical_start, logical_end, parted.PARTITION_LOGICAL)
            logical = disk.format.parted_disk.getPartitionBySector(logical_start)
            self.assertNotEqual(logical, None)

            logical_device = PartitionDevice(os.path.basename(logical.path))
            logical_device.disk = disk
            logical_device.exists = True
            logical_device.parted_partition = logical

            # logical partition present --> min size should be based on its end sector
            end_free = (extended_end - logical_end) * sector_size
            self.assertEqual(extended_device.min_size,
                             extended_device.align_target_size(extended_device.current_size - end_free))


class PartitionTestCase(StorageTestCase):

    def setUp(self):
        super().setUp()

        disks = [os.path.basename(vdev) for vdev in self.vdevs]
        self.storage = blivet.Blivet()
        self.storage.exclusive_disks = disks
        self.storage.reset()

        # make sure only the targetcli disks are in the devicetree
        for disk in self.storage.disks:
            self.assertTrue(disk.path in self.vdevs)
            self.assertIsNone(disk.format.type)
            self.assertFalse(disk.children)

    def _clean_up(self):
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

    def test_msdos_basic(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.format_device(disk, blivet.formats.get_format("disklabel", label_type="msdos"))

        for i in range(4):
            part = self.storage.new_partition(size=Size("100 MiB"), parents=[disk],
                                              primary=True)
            self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        self.storage.do_it()
        self.storage.reset()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.assertEqual(disk.format.type, "disklabel")
        self.assertEqual(disk.format.label_type, "msdos")
        self.assertIsNotNone(disk.format.parted_disk)
        self.assertIsNotNone(disk.format.parted_device)
        self.assertEqual(len(disk.format.partitions), 4)
        self.assertEqual(len(disk.format.primary_partitions), 4)
        self.assertEqual(len(disk.children), 4)

        for i in range(4):
            part = self.storage.devicetree.get_device_by_path(self.vdevs[0] + str(i + 1))
            self.assertIsNotNone(part)
            self.assertEqual(part.type, "partition")
            self.assertEqual(part.disk, disk)
            self.assertEqual(part.size, Size("100 MiB"))
            self.assertTrue(part.is_primary)
            self.assertFalse(part.is_extended)
            self.assertFalse(part.is_logical)
            self.assertIsNotNone(part.parted_partition)

    def test_msdos_extended(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.format_device(disk, blivet.formats.get_format("disklabel", label_type="msdos"))

        part = self.storage.new_partition(size=Size("100 MiB"), parents=[disk])
        self.storage.create_device(part)

        part = self.storage.new_partition(size=Size("1 GiB"), parents=[disk],
                                          part_type=parted.PARTITION_EXTENDED)
        self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        for i in range(4):
            part = self.storage.new_partition(size=Size("100 MiB"), parents=[disk],
                                              part_type=parted.PARTITION_LOGICAL)
            self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        self.storage.do_it()
        self.storage.reset()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.assertEqual(disk.format.type, "disklabel")
        self.assertEqual(disk.format.label_type, "msdos")
        self.assertIsNotNone(disk.format.parted_disk)
        self.assertIsNotNone(disk.format.parted_device)
        self.assertEqual(len(disk.format.partitions), 6)
        self.assertEqual(len(disk.format.primary_partitions), 1)
        self.assertEqual(len(disk.children), 6)

        for i in range(4, 8):
            part = self.storage.devicetree.get_device_by_path(self.vdevs[0] + str(i + 1))
            self.assertIsNotNone(part)
            self.assertEqual(part.type, "partition")
            self.assertEqual(part.disk, disk)
            self.assertEqual(part.size, Size("100 MiB"))
            self.assertFalse(part.is_primary)
            self.assertFalse(part.is_extended)
            self.assertTrue(part.is_logical)
            self.assertIsNotNone(part.parted_partition)

    def test_gpt_basic(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.format_device(disk, blivet.formats.get_format("disklabel", label_type="gpt"))

        for i in range(4):
            part = self.storage.new_partition(size=Size("100 MiB"), parents=[disk],)
            self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        self.storage.do_it()
        self.storage.reset()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.assertEqual(disk.format.type, "disklabel")
        self.assertEqual(disk.format.label_type, "gpt")
        self.assertIsNotNone(disk.format.parted_disk)
        self.assertIsNotNone(disk.format.parted_device)
        self.assertEqual(len(disk.format.partitions), 4)
        self.assertEqual(len(disk.format.primary_partitions), 4)
        self.assertEqual(len(disk.children), 4)

        for i in range(4):
            part = self.storage.devicetree.get_device_by_path(self.vdevs[0] + str(i + 1))
            self.assertIsNotNone(part)
            self.assertEqual(part.type, "partition")
            self.assertEqual(part.disk, disk)
            self.assertEqual(part.size, Size("100 MiB"))
            self.assertTrue(part.is_primary)
            self.assertFalse(part.is_extended)
            self.assertFalse(part.is_logical)
            self.assertIsNotNone(part.parted_partition)

    def _partition_wipe_check(self):
        part1 = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "1")
        self.assertIsNotNone(part1)
        self.assertIsNone(part1.format.type)

        out = blivet.util.capture_output(["blkid", "-p", "-sTYPE", "-ovalue", self.vdevs[0] + "1"])
        self.assertEqual(out.strip(), "")

        part2 = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "2")
        self.assertIsNotNone(part2)
        self.assertEqual(part2.format.type, "ext4")

        try:
            part2.format.do_check()
        except blivet.errors.FSError as e:
            self.fail("Partition wipe corrupted filesystem on an adjacent partition: %s" % str(e))

        out = blivet.util.capture_output(["blkid", "-p", "-sTYPE", "-ovalue", self.vdevs[0] + "2"])
        self.assertEqual(out.strip(), "ext4")

    def test_partition_wipe_ext(self):
        """ Check that any stray filesystem metadata are removed before creating a partition """
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.format_device(disk, blivet.formats.get_format("disklabel", label_type="gpt"))

        # create two partitions with ext4
        part1 = self.storage.new_partition(size=Size("100 MiB"), parents=[disk],
                                           fmt=blivet.formats.get_format("ext4"))
        self.storage.create_device(part1)

        part2 = self.storage.new_partition(size=Size("1 MiB"), parents=[disk], grow=True,
                                           fmt=blivet.formats.get_format("ext4"))
        self.storage.create_device(part2)

        blivet.partitioning.do_partitioning(self.storage)

        self.storage.do_it()
        self.storage.reset()

        # remove the first partition (only the partition without removing the format)
        part1 = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "1")
        ac = blivet.deviceaction.ActionDestroyDevice(part1)
        self.storage.devicetree.actions.add(ac)

        self.storage.do_it()
        self.storage.reset()

        # create the first partition again (without ext4)
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        part1 = self.storage.new_partition(size=Size("100 MiB"), parents=[disk])
        self.storage.create_device(part1)

        blivet.partitioning.do_partitioning(self.storage)

        # XXX PartitionDevice._post_create calls wipefs on the partition, we want to check that
        # the _pre_create dd wipe works so we need to skip the _post_create wipefs call
        part1._post_create = lambda: None

        self.storage.do_it()
        self.storage.reset()

        # make sure the ext4 signature is not present on part1 (and untouched on part2)
        self._partition_wipe_check()

    def test_partition_wipe_mdraid(self):
        """ Check that any stray RAID metadata are removed before creating a partition """
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.format_device(disk, blivet.formats.get_format("disklabel", label_type="gpt"))

        # create two partitions, one empty, one with ext4
        part1 = self.storage.new_partition(size=Size("100 MiB"), parents=[disk])
        self.storage.create_device(part1)

        part2 = self.storage.new_partition(size=Size("1 MiB"), parents=[disk], grow=True,
                                           fmt=blivet.formats.get_format("ext4"))
        self.storage.create_device(part2)

        blivet.partitioning.do_partitioning(self.storage)

        self.storage.do_it()
        self.storage.reset()

        # create MD RAID with metadata 1.0 on the first partition
        ret = blivet.util.run_program(["mdadm", "--create", "blivetMDTest", "--level=linear",
                                       "--metadata=1.0", "--raid-devices=1", "--force", part1.path])
        self.assertEqual(ret, 0, "Failed to create RAID array for partition wipe test")
        ret = blivet.util.run_program(["mdadm", "--stop", "/dev/md/blivetMDTest"])
        self.assertEqual(ret, 0, "Failed to create RAID array for partition wipe test")

        # now remove the partition without removing the array first
        part1 = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "1")
        ac = blivet.deviceaction.ActionDestroyDevice(part1)
        self.storage.devicetree.actions.add(ac)

        self.storage.do_it()
        self.storage.reset()

        # create the first partition again (without format)
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        part1 = self.storage.new_partition(size=Size("100 MiB"), parents=[disk])
        self.storage.create_device(part1)

        blivet.partitioning.do_partitioning(self.storage)

        # XXX PartitionDevice._post_create calls wipefs on the partition, we want to check that
        # the _pre_create dd wipe works so we need to skip the _post_create wipefs call
        part1._post_create = lambda: None

        self.storage.do_it()
        self.storage.reset()

        # make sure the mdmember signature is not present on part1 (and ext4 is untouched on part2)
        self._partition_wipe_check()
