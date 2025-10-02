import unittest
from unittest.mock import patch, Mock

import parted

from blivet.partitioning import add_partition
from blivet.partitioning import do_partitioning
from blivet.partitioning import allocate_partitions
from blivet.partitioning import get_free_regions
from blivet.partitioning import DiskChunk
from blivet.partitioning import PartitionRequest

from blivet.devices import DiskFile
from blivet.devices import PartitionDevice

from blivet.errors import PartitioningError

from blivet.blivet import Blivet
from blivet.util import sparsetmpfile
from blivet.formats import get_format
from blivet.size import Size
from blivet.flags import flags

from .storagetestcase import StorageTestCase


class PartitioningTestCase(unittest.TestCase):

    def test_add_partition(self):
        with sparsetmpfile("addparttest", Size("50 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, exists=False, label_type="msdos")

            free = disk.format.parted_disk.getFreeSpaceRegions()[0]

            #
            # add a partition with an unaligned size
            #
            self.assertEqual(len(disk.format.partitions), 0)
            part = add_partition(disk.format, free, parted.PARTITION_NORMAL,
                                 Size("10 MiB") - Size(37))
            self.assertEqual(len(disk.format.partitions), 1)

            # an unaligned size still yields an aligned partition
            alignment = disk.format.alignment
            geom = part.geometry
            sector_size = Size(geom.device.sectorSize)
            self.assertEqual(alignment.isAligned(free, geom.start), True)
            self.assertEqual(alignment.isAligned(free, geom.end + 1), True)
            self.assertEqual(part.geometry.length, int(Size("10 MiB") // sector_size))

            disk.format.remove_partition(part)
            self.assertEqual(len(disk.format.partitions), 0)

            #
            # adding a partition smaller than the optimal io size should yield
            # a partition aligned using the minimal io size instead
            #
            opt_str = 'parted.Device.optimumAlignment'
            min_str = 'parted.Device.minimumAlignment'
            opt_al = parted.Alignment(offset=0, grainSize=8192)  # 4 MiB
            min_al = parted.Alignment(offset=0, grainSize=2048)  # 1 MiB
            disk.format._minimal_alignment = None  # drop cache
            disk.format._optimal_alignment = None  # drop cache
            with patch(opt_str, opt_al) as optimal, patch(min_str, min_al) as minimal:
                optimal_end = disk.format.get_end_alignment(alignment=optimal)
                minimal_end = disk.format.get_end_alignment(alignment=minimal)

                sector_size = Size(disk.format.sector_size)
                length = 4096  # 2 MiB
                size = Size(sector_size * length)
                part = add_partition(disk.format, free, parted.PARTITION_NORMAL,
                                     size)
                self.assertEqual(part.geometry.length, length)
                self.assertEqual(optimal.isAligned(free, part.geometry.start),
                                 False)
                self.assertEqual(minimal.isAligned(free, part.geometry.start),
                                 True)
                self.assertEqual(optimal_end.isAligned(free, part.geometry.end),
                                 False)
                self.assertEqual(minimal_end.isAligned(free, part.geometry.end),
                                 True)

                disk.format.remove_partition(part)
                self.assertEqual(len(disk.format.partitions), 0)

            #
            # adding a partition smaller than the minimal io size should yield
            # a partition whose size is aligned up to the minimal io size
            #
            opt_str = 'parted.Device.optimumAlignment'
            min_str = 'parted.Device.minimumAlignment'
            opt_al = parted.Alignment(offset=0, grainSize=8192)  # 4 MiB
            min_al = parted.Alignment(offset=0, grainSize=2048)  # 1 MiB
            disk.format._minimal_alignment = None  # drop cache
            disk.format._optimal_alignment = None  # drop cache
            with patch(opt_str, opt_al) as optimal, patch(min_str, min_al) as minimal:
                optimal_end = disk.format.get_end_alignment(alignment=optimal)
                minimal_end = disk.format.get_end_alignment(alignment=minimal)

                sector_size = Size(disk.format.sector_size)
                length = 1024  # 512 KiB
                size = Size(sector_size * length)
                part = add_partition(disk.format, free, parted.PARTITION_NORMAL,
                                     size)
                self.assertEqual(part.geometry.length, min_al.grainSize)
                self.assertEqual(optimal.isAligned(free, part.geometry.start),
                                 False)
                self.assertEqual(minimal.isAligned(free, part.geometry.start),
                                 True)
                self.assertEqual(optimal_end.isAligned(free, part.geometry.end),
                                 False)
                self.assertEqual(minimal_end.isAligned(free, part.geometry.end),
                                 True)

                disk.format.remove_partition(part)
                self.assertEqual(len(disk.format.partitions), 0)

            #
            # add a partition with an unaligned start sector
            #
            start_sector = 5003
            end_sector = 15001
            part = add_partition(disk.format, free, parted.PARTITION_NORMAL,
                                 None, start_sector, end_sector)
            self.assertEqual(len(disk.format.partitions), 1)

            # start and end sectors are exactly as specified
            self.assertEqual(part.geometry.start, start_sector)
            self.assertEqual(part.geometry.end, end_sector)

            disk.format.remove_partition(part)
            self.assertEqual(len(disk.format.partitions), 0)

            #
            # fail: add a logical partition to a primary free region
            #
            with self.assertRaisesRegex(PartitioningError,
                                        "no extended partition"):
                part = add_partition(disk.format, free, parted.PARTITION_LOGICAL,
                                     Size("10 MiB"))

            # add an extended partition to the disk
            placeholder = add_partition(disk.format, free,
                                        parted.PARTITION_NORMAL, Size("10 MiB"))
            all_free = disk.format.parted_disk.getFreeSpaceRegions()
            add_partition(disk.format, all_free[1],
                          parted.PARTITION_EXTENDED, Size("30 MiB"),
                          alignment.alignUp(all_free[1],
                                            placeholder.geometry.end))

            disk.format.remove_partition(placeholder)
            self.assertEqual(len(disk.format.partitions), 1)
            all_free = disk.format.parted_disk.getFreeSpaceRegions()

            #
            # add a logical partition to an extended free regions
            #
            part = add_partition(disk.format, all_free[1],
                                 parted.PARTITION_LOGICAL,
                                 Size("10 MiB"), all_free[1].start)
            self.assertEqual(part.type, parted.PARTITION_LOGICAL)

            disk.format.remove_partition(part)
            self.assertEqual(len(disk.format.partitions), 1)

            #
            # fail: add a primary partition to an extended free region
            #
            with self.assertRaisesRegex(PartitioningError, "overlap"):
                part = add_partition(disk.format, all_free[1],
                                     parted.PARTITION_NORMAL,
                                     Size("10 MiB"), all_free[1].start)

    def test_msdos_disk_chunk1(self):
        disk_size = Size("100 MiB")
        with sparsetmpfile("chunktest", disk_size) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, exists=False, label_type="msdos")

            p1 = PartitionDevice("p1", size=Size("10 MiB"), grow=True)
            p2 = PartitionDevice("p2", size=Size("30 MiB"), grow=True)

            disks = [disk]
            partitions = [p1, p2]
            free = get_free_regions([disk])
            self.assertEqual(len(free), 1,
                             "free region count %d not expected" % len(free))

            b = Mock(spec=Blivet)
            allocate_partitions(b, disks, partitions, free)

            requests = [PartitionRequest(p) for p in partitions]
            chunk = DiskChunk(free[0], requests=requests)

            # parted reports a first free sector of 32 for msdos on disk files. whatever.
            # XXX on gpt, the start is increased to 34 and the end is reduced from 204799 to 204766,
            #     yielding an expected length of 204733
            length_expected = 204768
            self.assertEqual(chunk.length, length_expected)

            base_expected = sum(p.parted_partition.geometry.length for p in partitions)
            self.assertEqual(chunk.base, base_expected)

            pool_expected = chunk.length - base_expected
            self.assertEqual(chunk.pool, pool_expected)

            self.assertEqual(chunk.done, False)
            self.assertEqual(chunk.remaining, 2)

            chunk.grow_requests()

            self.assertEqual(chunk.done, True)
            self.assertEqual(chunk.pool, 0)
            self.assertEqual(chunk.remaining, 2)

            #
            # validate the growth (everything in sectors)
            #
            # The chunk length is 204768. The base of p1 is 20480. The base of
            # p2 is 61440. The chunk has a base of 81920 and a pool of 122848.
            #
            # p1 should grow by 30712 while p2 grows by 92136 since p2's base
            # size is exactly three times that of p1.
            self.assertEqual(requests[0].growth, 30712)
            self.assertEqual(requests[1].growth, 92136)

    def test_msdos_disk_chunk2(self):
        disk_size = Size("100 MiB")
        with sparsetmpfile("chunktest", disk_size) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = get_format("disklabel", device=disk.path, exists=False, label_type="msdos")

            p1 = PartitionDevice("p1", size=Size("10 MiB"), grow=True)
            p2 = PartitionDevice("p2", size=Size("30 MiB"), grow=True)

            # format max size should be reflected in request max growth
            fmt = get_format("dummy")
            fmt._max_size = Size("12 MiB")
            p3 = PartitionDevice("p3", size=Size("10 MiB"), grow=True,
                                 fmt=fmt)

            p4 = PartitionDevice("p4", size=Size("7 MiB"))

            # partition max size should be reflected in request max growth
            p5 = PartitionDevice("p5", size=Size("5 MiB"), grow=True,
                                 maxsize=Size("6 MiB"))

            disks = [disk]
            partitions = [p1, p2, p3, p4, p5]
            free = get_free_regions([disk])
            self.assertEqual(len(free), 1,
                             "free region count %d not expected" % len(free))

            b = Mock(spec=Blivet)
            allocate_partitions(b, disks, partitions, free)

            requests = [PartitionRequest(p) for p in partitions]
            chunk = DiskChunk(free[0], requests=requests)

            self.assertEqual(len(chunk.requests), len(partitions))

            # parted reports a first free sector of 32 for disk files. whatever.
            length_expected = 204768
            self.assertEqual(chunk.length, length_expected)

            growable = [p for p in partitions if p.req_grow]
            fixed = [p for p in partitions if not p.req_grow]
            base_expected = sum(p.parted_partition.geometry.length for p in growable)
            self.assertEqual(chunk.base, base_expected)

            base_fixed = sum(p.parted_partition.geometry.length for p in fixed)
            pool_expected = chunk.length - base_expected - base_fixed
            self.assertEqual(chunk.pool, pool_expected)

            self.assertEqual(chunk.done, False)

            # since p5 is not growable it is initially done
            self.assertEqual(chunk.remaining, 4)

            chunk.grow_requests()

            #
            # validate the growth (in sectors)
            #
            # The chunk length is 204768.
            # Request bases:
            #   p1 20480
            #   p2 61440
            #   p3 20480
            #   p4 14336 (not included in chunk base since it isn't growable)
            #   p5 10240
            #
            # The chunk has a base 112640 and a pool of 77792.
            #
            # Request max growth:
            #   p1 0
            #   p2 0
            #   p3 4096
            #   p4 0
            #   p5 2048
            #
            # The first round should allocate to p1, p2, p3, p5 at a ratio of
            # 2:6:2:1, which is 14144, 42432, 14144, 7072. Due to max growth,
            # p3 and p5 will be limited and the extra (10048, 5024) will remain
            # in the pool. In the second round the remaining requests will be
            # p1 and p2. They will divide up the pool of 15072 at a ratio of
            # 1:3, which is 3768 and 11304. At this point the pool should be
            # empty.
            #
            # Total growth:
            #   p1 17912
            #   p2 53736
            #   p3 4096
            #   p4 0
            #   p5 2048
            #
            self.assertEqual(chunk.done, True)
            self.assertEqual(chunk.pool, 0)
            self.assertEqual(chunk.remaining, 2)    # p1, p2 have no max

            # chunk.requests got sorted, so use the list whose order we know
            self.assertEqual(requests[0].growth, 17912)
            self.assertEqual(requests[1].growth, 53736)
            self.assertEqual(requests[2].growth, 4096)
            self.assertEqual(requests[3].growth, 0)
            self.assertEqual(requests[4].growth, 2048)


class ExtendedPartitionTestCase(StorageTestCase):

    _num_disks = 1

    def setUp(self):
        super().setUp()

        self._blivet_setup()

        for path in self.vdevs:
            disk = self.storage.devicetree.get_device_by_path(path)
            fmt = get_format("disklabel", label_type="msdos", device=disk.path)
            self.storage.format_device(disk, fmt)

    def _clean_up(self):
        self._blivet_cleanup()

        return super()._clean_up()

    def test_implicit_extended_partitions(self):
        """ Verify management of implicitly requested extended partition. """
        # By running partition allocation multiple times with enough partitions
        # to require an extended partition, we exercise the code that manages
        # the implicit extended partition.
        p1 = self.storage.new_partition(size=Size("100 MiB"))
        self.storage.create_device(p1)

        p2 = self.storage.new_partition(size=Size("200 MiB"))
        self.storage.create_device(p2)

        p3 = self.storage.new_partition(size=Size("300 MiB"))
        self.storage.create_device(p3)

        p4 = self.storage.new_partition(size=Size("400 MiB"))
        self.storage.create_device(p4)

        do_partitioning(self.storage)

        # at this point there should be an extended partition
        self.assertIsNotNone(self.storage.disks[0].format.extended_partition,
                             "no extended partition was created")

        # remove the last partition request and verify that the extended goes away as a result
        self.storage.destroy_device(p4)
        do_partitioning(self.storage)
        self.assertIsNone(self.storage.disks[0].format.extended_partition,
                          "extended partition was not removed with last logical")

        p5 = self.storage.new_partition(size=Size("500 MiB"))
        self.storage.create_device(p5)

        do_partitioning(self.storage)

        p6 = self.storage.new_partition(size=Size("450 MiB"))
        self.storage.create_device(p6)

        do_partitioning(self.storage)

        self.assertIsNotNone(self.storage.disks[0].format.extended_partition,
                             "no extended partition was created")

        self.storage.do_it()

    def test_implicit_extended_partitions_installer_mode(self):
        flags.keep_empty_ext_partitions = False
        self.test_implicit_extended_partitions()
        flags.keep_empty_ext_partitions = True

    def test_explicit_extended_partitions(self):
        """ Verify that explicitly requested extended partitions work. """
        disk = self.storage.disks[0]
        p1 = self.storage.new_partition(size=Size("500 MiB"),
                                        part_type=parted.PARTITION_EXTENDED)
        self.storage.create_device(p1)
        do_partitioning(self.storage)

        self.assertEqual(p1.parted_partition.type, parted.PARTITION_EXTENDED)
        self.assertEqual(p1.parted_partition, disk.format.extended_partition)

        p2 = self.storage.new_partition(size=Size("1 GiB"))
        self.storage.create_device(p2)
        do_partitioning(self.storage)

        self.assertEqual(p1.parted_partition, disk.format.extended_partition,
                         "user-specified extended partition was removed")

        self.storage.do_it()
