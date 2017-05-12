import test_compat

import parted
from six.moves import mock
import unittest

import blivet
from blivet.size import Size

patch = mock.patch


class DiskLabelTestCase(unittest.TestCase):

    @patch("blivet.formats.disklabel.DiskLabel.fresh_parted_disk", None)
    def test_get_alignment(self):
        dl = blivet.formats.disklabel.DiskLabel()
        dl._parted_disk = mock.Mock()
        dl._parted_device = mock.Mock()
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
        self.assertEqual(dl._get_minimal_alignment(), minimal_alignment)
        self.assertEqual(dl._get_optimal_alignment(), optimal_alignment)

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
        self.assertEqual(dl.alignment, dl._get_optimal_alignment())
        self.assertEqual(dl.end_alignment, dl.get_end_alignment())
