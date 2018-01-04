# vim:set fileencoding=utf-8

import os
import unittest
import parted

from mock import patch

from blivet.devices import DiskFile
from blivet.devices import PartitionDevice
from blivet.formats import getFormat
from blivet.size import Size
from blivet.util import sparsetmpfile

class PartitionDeviceTestCase(unittest.TestCase):

    def testTargetSize(self):
        with sparsetmpfile("targetsizetest", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = getFormat("disklabel", device=disk.path)
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.partedDevice.sectorSize)
            start = int(grain_size)
            orig_size = Size("6 MiB")
            end = start + int(orig_size / sector_size) - 1
            disk.format.addPartition(start, end)
            partition = disk.format.partedDisk.getPartitionBySector(start)
            self.assertNotEqual(partition, None)
            self.assertEqual(orig_size, Size(partition.getLength(unit='B')))

            device = PartitionDevice(os.path.basename(partition.path),
                                     size=orig_size)
            device.disk = disk
            device.exists = True
            device.partedPartition = partition

            device.format = getFormat("ext4", device=device.path)
            device.format.exists = True
            # grain size should be 1 MiB
            device.format._minInstanceSize = Size("2 MiB") + (grain_size / 2)
            device.format._resizable = True

            # Make sure things are as expected to begin with.
            self.assertEqual(device.size, orig_size)
            self.assertEqual(device.minSize, Size("3 MiB"))
            # start sector's at 1 MiB
            self.assertEqual(device.maxSize, Size("9 MiB"))

            # ValueError if not Size
            with self.assertRaisesRegex(ValueError,
                                         "new size must.*type Size"):
                device.targetSize = 22

            self.assertEqual(device.targetSize, orig_size)

            # ValueError if size smaller than minSize
            with self.assertRaisesRegex(ValueError,
                                         "size.*smaller than the minimum"):
                device.targetSize = Size("1 MiB")

            self.assertEqual(device.targetSize, orig_size)

            # ValueError if size larger than maxSize
            with self.assertRaisesRegex(ValueError,
                                         "size.*larger than the maximum"):
                device.targetSize = Size("11 MiB")

            self.assertEqual(device.targetSize, orig_size)

            # ValueError if unaligned
            with self.assertRaisesRegex(ValueError, "new size.*not.*aligned"):
                device.targetSize = Size("3.1 MiB")

            self.assertEqual(device.targetSize, orig_size)

            # successfully set a new target size
            new_target = device.maxSize
            device.targetSize = new_target
            self.assertEqual(device.targetSize, new_target)
            self.assertEqual(device.size, new_target)
            parted_size = Size(device.partedPartition.getLength(unit='B'))
            self.assertEqual(parted_size, device.targetSize)

            # reset target size to original size
            device.targetSize = orig_size
            self.assertEqual(device.targetSize, orig_size)
            self.assertEqual(device.size, orig_size)
            parted_size = Size(device.partedPartition.getLength(unit='B'))
            self.assertEqual(parted_size, device.targetSize)

    def testMinMaxSizeAlignment(self):
        with sparsetmpfile("minsizetest", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = getFormat("disklabel", device=disk.path)
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.partedDevice.sectorSize)
            start = int(grain_size)
            end = start + int(Size("6 MiB") / sector_size)
            disk.format.addPartition(start, end)
            partition = disk.format.partedDisk.getPartitionBySector(start)
            self.assertNotEqual(partition, None)

            device = PartitionDevice(os.path.basename(partition.path))
            device.disk = disk
            device.exists = True
            device.partedPartition = partition

            # Typical sector size is 512 B.
            # Default optimum alignment grain size is 2048 sectors, or 1 MiB.
            device.format = getFormat("ext4", device=device.path)
            device.format.exists = True
            device.format._minInstanceSize = Size("2 MiB") + (grain_size / 2)
            device.format._resizable = True

            ##
            ## minSize
            ##

            # The end sector based only on format min size should be unaligned.
            min_sectors = int(device.format.minSize / sector_size)
            min_end_sector = partition.geometry.start + min_sectors - 1
            self.assertEqual(
                disk.format.endAlignment.isAligned(partition.geometry,
                                                   min_end_sector),
                False)

            # The end sector based on device min size should be aligned.
            min_sectors = int(device.minSize / sector_size)
            min_end_sector = partition.geometry.start + min_sectors - 1
            self.assertEqual(
                disk.format.endAlignment.isAligned(partition.geometry,
                                                   min_end_sector),
                True)

            ##
            ## maxSize
            ##

            # Add a partition starting three sectors past an aligned sector and
            # extending to the end of the disk so that there's a free region
            # immediately following the first partition with an unaligned end
            # sector.
            free = disk.format.partedDisk.getFreeSpaceRegions()[-1]
            raw_start = int(Size("9 MiB") / sector_size)
            start = disk.format.alignment.alignUp(free, raw_start) + 3
            disk.format.addPartition(start, disk.format.partedDevice.length - 1)

            # Verify the end of the free region immediately following the first
            # partition is unaligned.
            free = disk.format.partedDisk.getFreeSpaceRegions()[1]
            self.assertEqual(disk.format.endAlignment.isAligned(free, free.end),
                             False)

            # The end sector based on device min size should be aligned.
            max_sectors = int(device.maxSize / sector_size)
            max_end_sector = partition.geometry.start + max_sectors - 1
            self.assertEqual(
                disk.format.endAlignment.isAligned(free, max_end_sector),
                True)

    @patch("blivet.devices.partition.PartitionDevice.readCurrentSize", lambda part: part.size)
    def testExtendedMinSize(self):
        with sparsetmpfile("extendedtest", Size("10 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = getFormat("disklabel", device=disk.path)
            grain_size = Size(disk.format.alignment.grainSize)
            sector_size = Size(disk.format.partedDevice.sectorSize)

            extended_start = int(grain_size)
            extended_end = extended_start + int(Size("6 MiB") / sector_size)
            disk.format.addPartition(extended_start, extended_end, parted.PARTITION_EXTENDED)
            extended = disk.format.extendedPartition
            self.assertNotEqual(extended, None)

            extended_device = PartitionDevice(os.path.basename(extended.path))
            extended_device.disk = disk
            extended_device.exists = True
            extended_device.partedPartition = extended

            # no logical partitions --> min size should be max of 1 KiB and grainSize
            self.assertEqual(extended_device.minSize,
                             extended_device.alignTargetSize(max(grain_size, Size("1 KiB"))))

            logical_start = extended_start + 1
            logical_end = extended_end // 2
            disk.format.addPartition(logical_start, logical_end, parted.PARTITION_LOGICAL)
            logical = disk.format.partedDisk.getPartitionBySector(logical_start)
            self.assertNotEqual(logical, None)

            logical_device = PartitionDevice(os.path.basename(logical.path))
            logical_device.disk = disk
            logical_device.exists = True
            logical_device.partedPartition = logical

            # logical partition present --> min size should be based on its end sector
            end_free = (extended_end - logical_end)*sector_size
            self.assertEqual(extended_device.minSize,
                             extended_device.alignTargetSize(extended_device.currentSize - end_free))
