# vim:set fileencoding=utf-8
import test_compat  # pylint: disable=unused-import

from collections import namedtuple
import os
import six
import unittest
import parted

from six.moves.mock import Mock, patch  # pylint: disable=no-name-in-module,import-error

from blivet.devices import DiskFile
from blivet.devices import PartitionDevice
from blivet.devices import StorageDevice
from blivet.errors import DeviceError
from blivet.formats import get_format
from blivet.size import Size
from blivet.util import sparsetmpfile


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

    @patch("blivet.devices.partition.PartitionDevice.update_size", lambda part: None)
    @patch("blivet.devices.partition.PartitionDevice.probe", lambda part: None)
    def test_ctor_parted_partition_error_handling(self):
        disk = StorageDevice("testdisk", exists=True)
        disk._partitionable = True
        with patch.object(disk, "_format") as fmt:
            fmt.type = "disklabel"
            self.assertTrue(disk.partitioned)

            fmt.supported = True

            # Normal case, no exn.
            device = PartitionDevice("testpart1", exists=True, parents=[disk])
            self.assertIn(device, disk.children)
            device.parents.remove(disk)
            self.assertEqual(len(disk.children), 0, msg="disk has children when it should not")

            # Parted doesn't find a partition, exn is raised.
            fmt.parted_disk.getPartitionByPath.return_value = None
            self.assertRaises(DeviceError, PartitionDevice, "testpart1", exists=True, parents=[disk])
            self.assertEqual(len(disk.children), 0, msg="device is still attached to disk in spite of ctor error")

    @patch("blivet.devices.partition.arch")
    def test_weight_1(self, *patches):
        arch = patches[0]

        dev = PartitionDevice('req1', exists=False)

        arch.is_x86.return_value = False
        arch.is_efi.return_value = False
        arch.is_arm.return_value = False
        arch.is_ppc.return_value = False

        dev.req_base_weight = -7
        self.assertEqual(dev.weight, -7)
        dev.req_base_weight = None

        with patch.object(dev, "_format") as fmt:
            fmt.mountable = True

            # weights for / and /boot are not platform-specific (except for arm)
            fmt.mountpoint = "/"
            self.assertEqual(dev.weight, 0)

            fmt.mountpoint = "/boot"
            self.assertEqual(dev.weight, 2000)

            #
            # x86 (BIOS)
            #
            arch.is_x86.return_value = True
            arch.is_efi.return_value = False

            # user-specified weight should override other logic
            dev.req_base_weight = -7
            self.assertEqual(dev.weight, -7)
            dev.req_base_weight = None

            fmt.mountpoint = ""
            self.assertEqual(dev.weight, 0)

            fmt.type = "biosboot"
            self.assertEqual(dev.weight, 5000)

            fmt.mountpoint = "/boot/efi"
            fmt.type = "efi"
            self.assertEqual(dev.weight, 0)

            #
            # UEFI
            #
            arch.is_x86.return_value = False
            arch.is_efi.return_value = True
            self.assertEqual(dev.weight, 5000)

            fmt.type = "biosboot"
            self.assertEqual(dev.weight, 0)

            fmt.mountpoint = "/"
            self.assertEqual(dev.weight, 0)

            #
            # arm
            #
            arch.is_x86.return_value = False
            arch.is_efi.return_value = False
            arch.is_arm.return_value = True

            fmt.mountpoint = "/"
            self.assertEqual(dev.weight, -100)

            #
            # ppc
            #
            arch.is_arm.return_value = False
            arch.is_ppc.return_value = True
            arch.is_pmac.return_value = False
            arch.is_ipseries.return_value = False

            fmt.mountpoint = "/"
            self.assertEqual(dev.weight, 0)

            fmt.type = "prepboot"
            self.assertEqual(dev.weight, 0)

            fmt.type = "appleboot"
            self.assertEqual(dev.weight, 0)

            arch.is_pmac.return_value = True
            self.assertEqual(dev.weight, 5000)

            fmt.type = "prepboot"
            self.assertEqual(dev.weight, 0)

            arch.is_pmac.return_value = False
            arch.is_ipseries.return_value = True
            self.assertEqual(dev.weight, 5000)

            fmt.type = "appleboot"
            self.assertEqual(dev.weight, 0)

            fmt.mountpoint = "/boot/efi"
            fmt.type = "efi"
            self.assertEqual(dev.weight, 0)

            fmt.type = "biosboot"
            self.assertEqual(dev.weight, 0)

            fmt.mountpoint = "/"
            self.assertEqual(dev.weight, 0)

            fmt.mountpoint = "/boot"
            self.assertEqual(dev.weight, 2000)

    def test_weight_2(self):
        for spec in weighted:
            part = PartitionDevice('weight_test')
            part._format = Mock(name="fmt", type=spec.fstype, mountpoint=spec.mountpoint,
                                mountable=spec.mountpoint is not None)
            with patch('blivet.devices.partition.arch') as _arch:
                for func in arch_funcs:
                    f = getattr(_arch, func)
                    f.return_value = func in spec.true_funcs

                self.assertEqual(part.weight, spec.weight)
