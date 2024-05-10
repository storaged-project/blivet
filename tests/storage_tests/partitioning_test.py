import unittest
from unittest.mock import patch, Mock

import parted

from blivet.partitioning import add_partition
from blivet.partitioning import get_next_partition_type
from blivet.partitioning import do_partitioning
from blivet.partitioning import allocate_partitions
from blivet.partitioning import get_free_regions
from blivet.partitioning import resolve_disk_tags
from blivet.partitioning import Request
from blivet.partitioning import Chunk
from blivet.partitioning import LVRequest
from blivet.partitioning import VGChunk
from blivet.partitioning import DiskChunk
from blivet.partitioning import PartitionRequest

from blivet.devices import StorageDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import DiskDevice
from blivet.devices import DiskFile
from blivet.devices import PartitionDevice
from blivet.devices.lvm import LVMCacheRequest

from blivet.errors import PartitioningError

from blivet.blivet import Blivet
from blivet.util import sparsetmpfile
from blivet.formats import get_format
from blivet.size import Size
from blivet.flags import flags

from .imagebackedtestcase import ImageBackedTestCase

# disklabel-type-specific constants
# keys: disklabel type string
# values: 3-tuple of (max_primary_count, supports_extended, max_logical_count)
disklabel_types = {'dos': (4, True),
                   'gpt': (128, False),
                   'mac': (62, False)}


class PartitioningTestCase(unittest.TestCase):

    def get_disk(self, disk_type, primary_count=0,
                 has_extended=False, logical_count=0):
        """ Return a mock representing a parted.Disk. """
        disk = Mock()

        disk.type = disk_type
        label_type_info = disklabel_types[disk_type]
        (max_primaries, supports_extended) = label_type_info

        # primary partitions
        disk.primaryPartitionCount = primary_count
        disk.maxPrimaryPartitionCount = max_primaries

        # extended partitions
        disk.supportsFeature = Mock(return_value=supports_extended)
        disk.getExtendedPartition = Mock(return_value=has_extended)

        # logical partitions
        disk.getLogicalPartitions = Mock(return_value=[0] * logical_count)

        return disk

    def test_next_partition_type(self):
        #
        # DOS
        #

        # empty disk, any type
        disk = self.get_disk(disk_type="dos")
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_NORMAL)

        # three primaries and no extended -> extended
        disk = self.get_disk(disk_type="dos", primary_count=3)
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_EXTENDED)

        # three primaries and an extended -> primary
        disk = self.get_disk(disk_type="dos", primary_count=3, has_extended=True)
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_NORMAL)

        # three primaries and an extended w/ no_primary -> logical
        disk = self.get_disk(disk_type="dos", primary_count=3, has_extended=True)
        self.assertEqual(get_next_partition_type(disk, no_primary=True),
                         parted.PARTITION_LOGICAL)

        # four primaries and an extended, available logical -> logical
        disk = self.get_disk(disk_type="dos", primary_count=4, has_extended=True,
                             logical_count=9)
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_LOGICAL)

        # four primaries and an extended -> logical
        disk = self.get_disk(disk_type="dos", primary_count=4, has_extended=True,
                             logical_count=11)
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_LOGICAL)

        # four primaries and no extended -> None
        disk = self.get_disk(disk_type="dos", primary_count=4,
                             has_extended=False)
        self.assertEqual(get_next_partition_type(disk), None)

        # free primary slot, extended -> primary
        disk = self.get_disk(disk_type="dos", primary_count=3, has_extended=True,
                             logical_count=11)
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_NORMAL)

        # free primary slot, extended w/ no_primary -> logical
        disk = self.get_disk(disk_type="dos", primary_count=3, has_extended=True,
                             logical_count=11)
        self.assertEqual(get_next_partition_type(disk, no_primary=True), parted.PARTITION_LOGICAL)

        #
        # GPT
        #

        # empty disk, any partition type
        disk = self.get_disk(disk_type="gpt")
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_NORMAL)

        # no empty slots -> None
        disk = self.get_disk(disk_type="gpt", primary_count=128)
        self.assertEqual(get_next_partition_type(disk), None)

        # no_primary -> None
        disk = self.get_disk(disk_type="gpt")
        self.assertEqual(get_next_partition_type(disk, no_primary=True), None)

        #
        # MAC
        #

        # empty disk, any partition type
        disk = self.get_disk(disk_type="mac")
        self.assertEqual(get_next_partition_type(disk), parted.PARTITION_NORMAL)

        # no empty slots -> None
        disk = self.get_disk(disk_type="mac", primary_count=62)
        self.assertEqual(get_next_partition_type(disk), None)

        # no_primary -> None
        disk = self.get_disk(disk_type="mac")
        self.assertEqual(get_next_partition_type(disk, no_primary=True), None)

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

    def test_chunk(self):
        dev1 = Mock()
        attrs = {"req_grow": True,
                 "id": 1,
                 "name": "req1"}
        dev1.configure_mock(**attrs)

        req1 = Request(dev1)
        req1.base = 10

        dev2 = Mock()
        attrs = {"req_grow": False,
                 "id": 2,
                 "name": "req2"}
        dev2.configure_mock(**attrs)

        req2 = Request(dev2)
        req2.base = 20

        chunk = Chunk(110, requests=[req1, req2])
        self.assertEqual(chunk.pool, 80)
        self.assertEqual(chunk.base, 10)

        dev3 = Mock()
        attrs = {"req_grow": True,
                 "id": 3,
                 "name": "req3"}
        dev3.configure_mock(**attrs)

        req3 = Request(dev3)
        req3.base = 20
        req3.max_growth = 35

        chunk.add_request(req3)
        self.assertEqual(chunk.pool, 60)
        self.assertEqual(chunk.base, 30)

        self.assertEqual(chunk.length_to_size(30), 30)
        self.assertEqual(chunk.size_to_length(40), 40)
        self.assertEqual(chunk.has_growable, True)

        chunk.grow_requests()

        # the chunk is done growing since its pool has been exhausted
        self.assertEqual(chunk.done, True)

        # there is still one request remaining since req1 has no maximum growth
        self.assertEqual(chunk.remaining, 1)

        # req1 is 10 units and growable with no limit
        # req2 is 20 units and not growable
        # req3 is 20 units and growable with a limits of 35 units of growth
        #
        # Requests are grown at rates proportional to their share of the
        # combined base size of all growable requests. If req3 had no max growth
        # it would get 40 units and req1 would get 20. Since req3 has a limit,
        # it will get 35 and req1 will get its 20 plus the leftovers from req3,
        # which comes out to 25.
        self.assertEqual(req1.growth, 25)
        self.assertEqual(req2.growth, 0)
        self.assertEqual(req3.growth, 35)

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

    def test_vgchunk(self):
        pv = StorageDevice("pv1", size=Size("40 GiB"),
                           fmt=get_format("lvmpv"))
        vg = LVMVolumeGroupDevice("vg", parents=[pv])
        lv1 = LVMLogicalVolumeDevice("lv1", parents=[vg],
                                     size=Size("1 GiB"), grow=True)
        lv2 = LVMLogicalVolumeDevice("lv2", parents=[vg],
                                     size=Size("10 GiB"), grow=True)
        lv3 = LVMLogicalVolumeDevice("lv3", parents=[vg],
                                     size=Size("10 GiB"), grow=True,
                                     maxsize=Size("12 GiB"))

        req1 = LVRequest(lv1)
        req2 = LVRequest(lv2)
        req3 = LVRequest(lv3)
        chunk = VGChunk(vg, requests=[req1, req2, req3])

        self.assertEqual(chunk.length, vg.extents)
        self.assertEqual(chunk.pool, vg.free_extents)
        base_size = vg.align(sum((lv.size for lv in vg.lvs), Size(0)), roundup=True)
        base = base_size / vg.pe_size
        self.assertEqual(chunk.base, base)

        # default extent size is 4 MiB
        self.assertEqual(chunk.length_to_size(4), Size("16 MiB"))
        self.assertEqual(chunk.size_to_length(Size("33 MiB")), 8)
        self.assertEqual(chunk.has_growable, True)

        self.assertEqual(chunk.remaining, 3)
        self.assertEqual(chunk.done, False)

        chunk.grow_requests()

        # the chunk is done growing since its pool has been exhausted
        self.assertEqual(chunk.done, True)

        # there are still two requests remaining since lv1 and lv2 have no max
        self.assertEqual(chunk.remaining, 2)

        #
        # validate the resulting growth
        #
        # lv1 has size 1 GiB (256 extents) and is growable with no limit
        # lv2 has size 10 GiB (2560 extents) and is growable with no limit
        # lv3 has size 10 GiB (2560 extents) and is growable with a max size of
        #     12 GiB (max growth of 512 extents)
        #
        # The vg initially has 4863 free extents.
        # The growth ratio should be 1:10:10.
        #
        # The first pass through should allocate 231 extents to lv1 and 2315
        # extents to each of lv2 and lv3, leaving one remaining extent, but
        # it should reclaim 1803 extents from lv3 since it has a maximum growth
        # of 512 extents (2 GiB).
        #
        # The second pass should then split up the remaining 1805 extents
        # between lv1 and lv2 at a ratio of 1:10, which ends up being 164 for
        # lv1 and 1640 for lv2. The remaining extent goes to lv2 because it is
        # first in the list after sorting with blivet.partitioning.lv_compare.
        #
        # Grand totals should be as follows:
        # lv1 should grow by 395 extents, or 1.54 GiB
        # lv2 should grow by 3956 extents, or 15.45 GiB
        # lv3 should grow by 512 extents, or 2 GiB
        self.assertEqual(req1.growth, 395)
        self.assertEqual(req2.growth, 3956)
        self.assertEqual(req3.growth, 512)

    def test_vgchunk_with_cache(self):
        pv = StorageDevice("pv1", size=Size("40 GiB"),
                           fmt=get_format("lvmpv"))
        # 1025 MiB so that the PV provides 1024 MiB of free space (see
        # LVMVolumeGroupDevice.extents)
        pv2 = StorageDevice("pv2", size=Size("1025 MiB"),
                            fmt=get_format("lvmpv"))
        vg = LVMVolumeGroupDevice("vg", parents=[pv, pv2])

        cache_req1 = LVMCacheRequest(Size("512 MiB"), [pv2], "writethrough")
        lv1 = LVMLogicalVolumeDevice("lv1", parents=[vg],
                                     size=Size("1 GiB"), grow=True,
                                     cache_request=cache_req1)

        cache_req2 = LVMCacheRequest(Size("512 MiB"), [pv2], "writethrough")
        lv2 = LVMLogicalVolumeDevice("lv2", parents=[vg],
                                     size=Size("10 GiB"), grow=True,
                                     cache_request=cache_req2)

        lv3 = LVMLogicalVolumeDevice("lv3", parents=[vg],
                                     size=Size("10 GiB"), grow=True,
                                     maxsize=Size("12 GiB"))

        req1 = LVRequest(lv1)
        req2 = LVRequest(lv2)
        req3 = LVRequest(lv3)
        chunk = VGChunk(vg, requests=[req1, req2, req3])

        chunk.grow_requests()

        # the chunk is done growing since its pool has been exhausted
        self.assertEqual(chunk.done, True)

        # there are still two requests remaining since lv1 and lv2 have no max
        self.assertEqual(chunk.remaining, 2)

        # All the sizes should be the same as without the caches (see the
        # test_vgchunk test for their "rationales") because the space for the
        # caches should just be reserved.
        self.assertEqual(req1.growth, 395)
        self.assertEqual(req2.growth, 3956)
        self.assertEqual(req3.growth, 512)

    def test_vgchunk_with_cache_pvfree(self):
        pv = StorageDevice("pv1", size=Size("40 GiB"),
                           fmt=get_format("lvmpv"))
        # 1069 MiB so that the PV provides 1068 MiB of free space (see
        # LVMVolumeGroupDevice.extents) which is 44 MiB more than the caches
        # need and which should thus be split into the LVs
        pv2 = StorageDevice("pv2", size=Size("1069 MiB"),
                            fmt=get_format("lvmpv"))
        vg = LVMVolumeGroupDevice("vg", parents=[pv, pv2])

        cache_req1 = LVMCacheRequest(Size("512 MiB"), [pv2], "writethrough")
        lv1 = LVMLogicalVolumeDevice("lv1", parents=[vg],
                                     size=Size("1 GiB"), grow=True,
                                     cache_request=cache_req1)

        cache_req2 = LVMCacheRequest(Size("512 MiB"), [pv2], "writethrough")
        lv2 = LVMLogicalVolumeDevice("lv2", parents=[vg],
                                     size=Size("10 GiB"), grow=True,
                                     cache_request=cache_req2)

        lv3 = LVMLogicalVolumeDevice("lv3", parents=[vg],
                                     size=Size("10 GiB"), grow=True,
                                     maxsize=Size("12 GiB"))

        req1 = LVRequest(lv1)
        req2 = LVRequest(lv2)
        req3 = LVRequest(lv3)
        chunk = VGChunk(vg, requests=[req1, req2, req3])

        chunk.grow_requests()

        # the chunk is done growing since its pool has been exhausted
        self.assertEqual(chunk.done, True)

        # there are still two requests remaining since lv1 and lv2 have no max
        self.assertEqual(chunk.remaining, 2)

        # All the sizes should be the same as without the caches (see the
        # test_vgchunk test for their "rationales") because the space for the
        # caches should just be reserved.
        # The extra 11 extents available on the pv2 should go in the 1:10 ratio
        # to req1 and req2.
        self.assertEqual(req1.growth, 395 + 1)
        self.assertEqual(req2.growth, 3956 + 10)
        self.assertEqual(req3.growth, 512)

    def test_align_free_regions(self):
        # disk with two free regions -- first unaligned, second aligned
        disk = Mock()
        disk.format.alignment.grainSize = 2048
        disk.format.parted_disk.getFreeSpaceRegions.return_value = [Mock(start=1, end=2049, length=2049),
                                                                    Mock(start=1, end=2048, length=2048)]

        free = get_free_regions([disk])
        self.assertEqual(free[0].length, 2049)
        self.assertEqual(free[1].length, 2048)

        free = get_free_regions([disk], align=True)
        self.assertEqual(free[0].length, 2048)
        self.assertEqual(free[1].length, 2048)


class ExtendedPartitionTestCase(ImageBackedTestCase):

    disks = {"disk1": Size("2 GiB")}
    initialize_disks = False

    def _set_up_storage(self):
        # Don't rely on the default being an msdos disklabel since the test
        # could be running on an EFI system.
        for name in self.disks:
            disk = self.blivet.devicetree.get_device_by_name(name)
            fmt = get_format("disklabel", label_type="msdos", device=disk.path)
            self.blivet.format_device(disk, fmt)

    def test_implicit_extended_partitions(self):
        """ Verify management of implicitly requested extended partition. """
        # By running partition allocation multiple times with enough partitions
        # to require an extended partition, we exercise the code that manages
        # the implicit extended partition.
        p1 = self.blivet.new_partition(size=Size("100 MiB"))
        self.blivet.create_device(p1)

        p2 = self.blivet.new_partition(size=Size("200 MiB"))
        self.blivet.create_device(p2)

        p3 = self.blivet.new_partition(size=Size("300 MiB"))
        self.blivet.create_device(p3)

        p4 = self.blivet.new_partition(size=Size("400 MiB"))
        self.blivet.create_device(p4)

        do_partitioning(self.blivet)

        # at this point there should be an extended partition
        self.assertIsNotNone(self.blivet.disks[0].format.extended_partition,
                             "no extended partition was created")

        # remove the last partition request and verify that the extended goes away as a result
        self.blivet.destroy_device(p4)
        do_partitioning(self.blivet)
        self.assertIsNone(self.blivet.disks[0].format.extended_partition,
                          "extended partition was not removed with last logical")

        p5 = self.blivet.new_partition(size=Size("500 MiB"))
        self.blivet.create_device(p5)

        do_partitioning(self.blivet)

        p6 = self.blivet.new_partition(size=Size("450 MiB"))
        self.blivet.create_device(p6)

        do_partitioning(self.blivet)

        self.assertIsNotNone(self.blivet.disks[0].format.extended_partition,
                             "no extended partition was created")

        self.blivet.do_it()

    def test_implicit_extended_partitions_installer_mode(self):
        flags.keep_empty_ext_partitions = False
        self.test_implicit_extended_partitions()
        flags.keep_empty_ext_partitions = True

    def test_explicit_extended_partitions(self):
        """ Verify that explicitly requested extended partitions work. """
        disk = self.blivet.disks[0]
        p1 = self.blivet.new_partition(size=Size("500 MiB"),
                                       part_type=parted.PARTITION_EXTENDED)
        self.blivet.create_device(p1)
        do_partitioning(self.blivet)

        self.assertEqual(p1.parted_partition.type, parted.PARTITION_EXTENDED)
        self.assertEqual(p1.parted_partition, disk.format.extended_partition)

        p2 = self.blivet.new_partition(size=Size("1 GiB"))
        self.blivet.create_device(p2)
        do_partitioning(self.blivet)

        self.assertEqual(p1.parted_partition, disk.format.extended_partition,
                         "user-specified extended partition was removed")

        self.blivet.do_it()


class DiskTagsTestCase(unittest.TestCase):
    def test_disk_tags(self):
        disks = []
        for i in range(3):
            disk = DiskDevice("disk%d" % i)
            disk.tags.add(str(i))
            disks.append(disk)

        self.assertEqual(resolve_disk_tags(disks, ["1"]), [disks[1]])
        self.assertEqual(resolve_disk_tags(disks, ["0", "2"]), [disks[0], disks[2]])
        self.assertEqual(resolve_disk_tags(disks, ["local"]), disks)
        self.assertEqual(resolve_disk_tags(disks, ["canteloupe"]), [])
