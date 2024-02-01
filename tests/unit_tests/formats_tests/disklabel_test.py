import parted
import unittest
from unittest.mock import Mock, PropertyMock, patch

import blivet
from blivet.size import Size


class DiskLabelTestCase(unittest.TestCase):

    @patch("blivet.formats.disklabel.DiskLabel.fresh_parted_disk", None)
    def test_get_alignment(self):
        dl = blivet.formats.disklabel.DiskLabel()
        dl._parted_disk = Mock()
        dl._parted_device = Mock()
        dl._parted_device.sectorSize = 512

        # 512 byte grain sze
        disklabel_alignment = parted.Alignment(grainSize=1, offset=0)
        dl._parted_disk.partitionAlignment = disklabel_alignment

        # 1 MiB grain size
        minimal_alignment = parted.Alignment(grainSize=2048, offset=0)
        dl._parted_device.minimumAlignment = minimal_alignment

        # 4 MiB grain size
        optimal_alignment = parted.Alignment(grainSize=8192, offset=0)
        dl._parted_device.optimumAlignment = optimal_alignment

        # expected end alignments
        optimal_end_alignment = parted.Alignment(
            grainSize=optimal_alignment.grainSize,
            offset=-1)
        minimal_end_alignment = parted.Alignment(
            grainSize=minimal_alignment.grainSize,
            offset=-1)

        # make sure the private methods all return the expected values
        self.assertEqual(dl._get_disk_label_alignment(), disklabel_alignment)
        self.assertEqual(dl.get_minimal_alignment(), minimal_alignment)
        self.assertEqual(dl.get_optimal_alignment(), optimal_alignment)

        # validate result when passing a start alignment to get_end_alignment
        self.assertEqual(dl.get_end_alignment(alignment=optimal_alignment),
                         optimal_end_alignment)
        self.assertEqual(dl.get_end_alignment(alignment=minimal_alignment),
                         minimal_end_alignment)

        # by default we should return the optimal alignment
        self.assertEqual(dl.get_alignment(), optimal_alignment)
        self.assertEqual(dl.get_end_alignment(), optimal_end_alignment)

        # when passed a size smaller than the optimal io size we should return
        # the minimal alignment
        self.assertEqual(dl.get_alignment(size=Size("2 MiB")), minimal_alignment)
        self.assertEqual(dl.get_end_alignment(size=Size("2 MiB")),
                         minimal_end_alignment)

        # test the old deprecated properties' values
        self.assertEqual(dl.alignment, dl.get_optimal_alignment())
        self.assertEqual(dl.end_alignment, dl.get_end_alignment())

    @patch("blivet.formats.disklabel.arch")
    def test_platform_label_types(self, arch):
        disklabel_class = blivet.formats.disklabel.DiskLabel

        arch.is_s390.return_value = False
        arch.is_efi.return_value = False
        arch.is_aarch64.return_value = False
        arch.is_arm.return_value = False
        arch.is_pmac.return_value = False
        arch.is_x86.return_value = False

        self.assertEqual(disklabel_class.get_platform_label_types(), ["msdos", "gpt"])

        arch.is_pmac.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["mac"])
        arch.is_pmac.return_value = False

        arch.is_efi.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["gpt", "msdos"])
        arch.is_aarch64.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["gpt", "msdos"])
        arch.is_aarch64.return_value = False
        arch.is_arm.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["msdos", "gpt"])
        arch.is_arm.return_value = False
        arch.is_efi.return_value = False

        arch.is_arm.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["msdos", "gpt"])
        arch.is_arm.return_value = False

        # this simulates x86_64
        arch.is_x86.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["gpt", "msdos"])
        arch.is_efi.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["gpt", "msdos"])
        arch.is_x86.return_value = False
        arch.is_efi.return_value = False

        arch.is_s390.return_value = True
        self.assertEqual(disklabel_class.get_platform_label_types(), ["msdos", "gpt", "dasd"])
        arch.is_s390.return_value = False

    def test_label_type_size_check(self):
        dl = blivet.formats.disklabel.DiskLabel()
        dl._parted_disk = Mock()
        dl._parted_device = Mock()

        with patch("blivet.formats.disklabel.parted") as patched_parted:
            patched_parted.freshDisk.return_value = Mock(name="parted.Disk", maxPartitionStartSector=10)
            dl._parted_device.length = 100
            self.assertEqual(dl._label_type_size_check("foo"), False)

            dl._parted_device.length = 10
            self.assertEqual(dl._label_type_size_check("foo"), False)

            dl._parted_device.length = 9
            self.assertEqual(dl._label_type_size_check("foo"), True)

        with patch.object(blivet.formats.disklabel.DiskLabel, "parted_device", new=PropertyMock(return_value=None)):
            # no parted device -> no passing size check
            self.assertEqual(dl._label_type_size_check("msdos"), False)

    @patch("blivet.formats.disklabel.arch")
    def test_best_label_type(self, arch):
        """
            1. is always in _disklabel_types
            2. is the default unless the device is too long for the default
            3. is msdos for fba dasd on S390
            4. is dasd for non-fba dasd on S390
        """
        dl = blivet.formats.disklabel.DiskLabel()
        dl._parted_disk = Mock()
        dl._parted_device = Mock()
        dl._device = "labeltypefakedev"

        arch.is_s390.return_value = False
        arch.is_efi.return_value = False
        arch.is_aarch64.return_value = False
        arch.is_arm.return_value = False
        arch.is_pmac.return_value = False
        arch.is_x86.return_value = False

        with patch.object(dl, '_label_type_size_check') as size_check:
            # size check passes for first type ("msdos")
            size_check.return_value = True
            self.assertEqual(dl._get_best_label_type(), "msdos")

            # size checks all fail -> label type is None
            size_check.return_value = False
            self.assertEqual(dl._get_best_label_type(), None)

            # size check passes on second call -> label type is "gpt" (second in platform list)
            size_check.side_effect = [False, True]
            self.assertEqual(dl._get_best_label_type(), "gpt")

        arch.is_pmac.return_value = True
        with patch.object(dl, '_label_type_size_check') as size_check:
            size_check.return_value = True
            self.assertEqual(dl._get_best_label_type(), "mac")
        arch.is_pmac.return_value = False

        arch.is_efi.return_value = True
        with patch.object(dl, '_label_type_size_check') as size_check:
            size_check.return_value = True
            self.assertEqual(dl._get_best_label_type(), "gpt")
        arch.is_efi.return_value = False

        arch.is_s390.return_value = True
        with patch('blivet.util.detect_virt') as virt:
            virt.return_value = False
            with patch.object(dl, '_label_type_size_check') as size_check:
                size_check.return_value = True
                with patch("blivet.formats.disklabel.blockdev.s390") as _s390:
                    _s390.dasd_is_fba.return_value = False
                    self.assertEqual(dl._get_best_label_type(), "msdos")

                    _s390.dasd_is_fba.return_value = True
                    self.assertEqual(dl._get_best_label_type(), "msdos")

                    _s390.dasd_is_fba.return_value = False
                    dl._parted_device.type = parted.DEVICE_DASD
                    self.assertEqual(dl._get_best_label_type(), "dasd")
        arch.is_s390.return_value = False
