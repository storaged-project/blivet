import unittest
from unittest.mock import Mock

import parted

from blivet.partitioning import get_next_partition_type
from blivet.partitioning import get_free_regions
from blivet.partitioning import resolve_disk_tags
from blivet.partitioning import Request
from blivet.partitioning import Chunk
from blivet.partitioning import LVRequest
from blivet.partitioning import VGChunk

from blivet.devices import StorageDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import DiskDevice
from blivet.devices.lvm import LVMCacheRequest

from blivet.formats import get_format
from blivet.size import Size


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
