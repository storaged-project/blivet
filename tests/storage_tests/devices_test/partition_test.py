import os
import unittest
from uuid import UUID
import parted

from unittest.mock import patch

from blivet.devices import DiskFile
from blivet.devices import PartitionDevice
from blivet.devicelibs.gpt import gpt_part_uuid_for_mountpoint
from blivet.formats import get_format
from blivet.flags import flags
from blivet.size import Size
from blivet.util import sparsetmpfile


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
            with self.assertRaisesRegex(ValueError, "new size must.*type Size"):
                device.target_size = 22

            self.assertEqual(device.target_size, orig_size)

            # ValueError if size smaller than min_size
            with self.assertRaisesRegex(ValueError, "size.*smaller than the minimum"):
                device.target_size = Size("1 MiB")

            self.assertEqual(device.target_size, orig_size)

            # ValueError if size larger than max_size
            with self.assertRaisesRegex(ValueError, "size.*larger than the maximum"):
                device.target_size = Size("11 MiB")

            self.assertEqual(device.target_size, orig_size)

            # ValueError if unaligned
            with self.assertRaisesRegex(ValueError, "new size.*not.*aligned"):
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
            disk.format = get_format("disklabel", device=disk.path, label_type="msdos")
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

    @unittest.skipUnless(hasattr(parted.Partition, "type_uuid"),
                         "requires part type UUID in pyparted")
    def test_part_type_uuid(self):
        with sparsetmpfile("part_type_uuid", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, label_type="gpt")
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.parted_device.sectorSize)
            start = int(grain_size)
            end = start + int(Size("6 MiB") / sector_size)
            uuid = UUID("98bae220-872f-4895-853a-00ca5cadab1e")
            disk.format.add_partition(start, end, part_type_uuid=uuid)
            partition = disk.format.parted_disk.getPartitionBySector(start)
            self.assertNotEqual(partition, None)

            self.assertEqual(partition.type_uuid, uuid.bytes)

    @unittest.skipUnless(hasattr(parted.Partition, "type_uuid"),
                         "requires part type UUID in pyparted")
    def test_dev_part_type_uuid(self):
        with sparsetmpfile("part_type_uuid", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, label_type="gpt")
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.parted_device.sectorSize)
            start = int(grain_size)
            end = start + int(Size("6 MiB") / sector_size)
            uuid1 = UUID("98bae220-872f-4895-853a-00ca5cadab1e")
            uuid2 = UUID("a2cf8a75-c460-41cd-844c-00ca5cadab1e")

            device = PartitionDevice("demo",
                                     size=int(Size("6 MiB") / sector_size),
                                     exists=False,
                                     part_type_uuid=uuid2)

            self.assertEqual(device.part_type_uuid, uuid2)
            self.assertEqual(device.part_type_uuid_req, uuid2)

            disk.format.add_partition(start, end, part_type_uuid=uuid1)
            partition = disk.format.parted_disk.getPartitionBySector(start)
            self.assertNotEqual(partition, None)

            device.disk = disk
            device.exists = True
            device.parted_partition = partition

            self.assertEqual(device.part_type_uuid, uuid1)
            self.assertEqual(device.part_type_uuid_req, uuid2)

    @unittest.skipUnless(hasattr(parted.Partition, "type_uuid"),
                         "requires part type UUID in pyparted")
    def test_dev_part_type_gpt_autodiscover(self):
        with sparsetmpfile("part_type_uuid", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, label_type="gpt")
            sector_size = Size(disk.format.parted_device.sectorSize)
            device = PartitionDevice("demo",
                                     size=int(Size("6 MiB") / sector_size),
                                     exists=False,
                                     mountpoint="/home")
            device.disk = disk

            flags.gpt_discoverable_partitions = False
            self.assertEqual(device.part_type_uuid, None)
            flags.gpt_discoverable_partitions = True
            self.assertEqual(device.part_type_uuid,
                             gpt_part_uuid_for_mountpoint("/home"))
