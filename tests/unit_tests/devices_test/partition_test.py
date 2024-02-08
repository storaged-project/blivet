from collections import namedtuple
import unittest
from unittest.mock import patch, Mock

from blivet.devices import PartitionDevice
from blivet.devices import StorageDevice
from blivet.errors import DeviceError


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
            fmt.type = "xfs"
            self.assertEqual(dev.weight, 0)

            fmt.mountpoint = "/boot"
            fmt.type = "ext4"
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
            self.assertEqual(dev.weight, 5000)

            #
            # UEFI
            #
            arch.is_x86.return_value = False
            arch.is_efi.return_value = True
            self.assertEqual(dev.weight, 5000)

            fmt.type = "biosboot"
            self.assertEqual(dev.weight, 5000)

            fmt.mountpoint = "/"
            fmt.type = "xfs"
            self.assertEqual(dev.weight, 0)

            #
            # arm
            #
            arch.is_x86.return_value = False
            arch.is_efi.return_value = False
            arch.is_arm.return_value = True

            fmt.mountpoint = "/"
            fmt.type = "xfs"
            self.assertEqual(dev.weight, -100)

            #
            # ppc
            #
            arch.is_arm.return_value = False
            arch.is_ppc.return_value = True
            arch.is_pmac.return_value = False
            arch.is_ipseries.return_value = False

            fmt.mountpoint = "/"
            fmt.type = "xfs"
            self.assertEqual(dev.weight, 0)

            fmt.type = "prepboot"
            self.assertEqual(dev.weight, 5000)

            fmt.type = "appleboot"
            self.assertEqual(dev.weight, 5000)

            arch.is_pmac.return_value = True
            self.assertEqual(dev.weight, 5000)

            fmt.type = "prepboot"
            self.assertEqual(dev.weight, 5000)

            arch.is_pmac.return_value = False
            arch.is_ipseries.return_value = True
            self.assertEqual(dev.weight, 5000)

            fmt.type = "appleboot"
            self.assertEqual(dev.weight, 5000)

            fmt.mountpoint = "/boot/efi"
            fmt.type = "efi"
            self.assertEqual(dev.weight, 5000)

            fmt.type = "biosboot"
            self.assertEqual(dev.weight, 5000)

            fmt.mountpoint = "/"
            fmt.type = "xfs"
            self.assertEqual(dev.weight, 0)

            fmt.mountpoint = "/boot"
            fmt.type = "ext4"
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

    @patch("blivet.devices.partition.PartitionDevice.update_size", lambda part: None)
    @patch("blivet.devices.partition.PartitionDevice.probe", lambda part: None)
    def test_disk_is_empty(self):
        disk = StorageDevice("testdisk", exists=True)
        disk._partitionable = True
        with patch.object(disk, "_format") as fmt:
            fmt.type = "disklabel"
            self.assertTrue(disk.is_empty)

            PartitionDevice("testpart1", exists=True, parents=[disk])
            self.assertFalse(disk.is_empty)

    def test_device_id(self):
        part = PartitionDevice("req1", exists=False)
        self.assertEqual(part.device_id, "req1")
