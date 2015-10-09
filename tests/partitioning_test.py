#!/usr/bin/python

import unittest
from mock import Mock, patch

import parted

from blivet.partitioning import addPartition
from blivet.partitioning import getNextPartitionType
from blivet.partitioning import doPartitioning
from blivet.partitioning import Request
from blivet.partitioning import Chunk
from blivet.partitioning import LVRequest
from blivet.partitioning import VGChunk

from blivet.devices import DiskFile
from blivet.devices import StorageDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice

from tests.imagebackedtestcase import ImageBackedTestCase
from blivet.formats import getFormat
from blivet.size import Size
from blivet.flags import flags
from blivet.util import sparsetmpfile

# disklabel-type-specific constants
# keys: disklabel type string
# values: 3-tuple of (max_primary_count, supports_extended, max_logical_count)
disklabel_types = {'dos': (4, True, 11),
                   'gpt': (128, False, 0),
                   'mac': (62, False, 0)}

class PartitioningTestCase(unittest.TestCase):
    def getDisk(self, disk_type, primary_count=0,
                has_extended=False, logical_count=0):
        """ Return a mock representing a parted.Disk. """
        disk = Mock()

        disk.type = disk_type
        label_type_info = disklabel_types[disk_type]
        (max_primaries, supports_extended, max_logicals) = label_type_info

        # primary partitions
        disk.primaryPartitionCount = primary_count
        disk.maxPrimaryPartitionCount = max_primaries

        # extended partitions
        disk.supportsFeature = Mock(return_value=supports_extended)
        disk.getExtendedPartition = Mock(return_value=has_extended)

        # logical partitions
        disk.getMaxLogicalPartitions = Mock(return_value=max_logicals)
        disk.getLogicalPartitions = Mock(return_value=[0]*logical_count)

        return disk

    def testNextPartitionType(self):
        #
        # DOS
        #

        # empty disk, any type
        disk = self.getDisk(disk_type="dos")
        self.assertEqual(getNextPartitionType(disk), parted.PARTITION_NORMAL)

        # three primaries and no extended -> extended
        disk = self.getDisk(disk_type="dos", primary_count=3)
        self.assertEqual(getNextPartitionType(disk), parted.PARTITION_EXTENDED)

        # three primaries and an extended -> primary
        disk = self.getDisk(disk_type="dos", primary_count=3, has_extended=True)
        self.assertEqual(getNextPartitionType(disk), parted.PARTITION_NORMAL)

        # three primaries and an extended w/ no_primary -> logical
        disk = self.getDisk(disk_type="dos", primary_count=3, has_extended=True)
        self.assertEqual(getNextPartitionType(disk, no_primary=True),
                         parted.PARTITION_LOGICAL)

        # four primaries and an extended, available logical -> logical
        disk = self.getDisk(disk_type="dos", primary_count=4, has_extended=True,
                            logical_count=9)
        self.assertEqual(getNextPartitionType(disk), parted.PARTITION_LOGICAL)

        # four primaries and an extended, no available logical -> None
        disk = self.getDisk(disk_type="dos", primary_count=4, has_extended=True,
                            logical_count=11)
        self.assertEqual(getNextPartitionType(disk), None)

        # four primaries and no extended -> None
        disk = self.getDisk(disk_type="dos", primary_count=4,
                            has_extended=False)
        self.assertEqual(getNextPartitionType(disk), None)

        # free primary slot, extended, no free logical slot -> primary
        disk = self.getDisk(disk_type="dos", primary_count=3, has_extended=True,
                            logical_count=11)
        self.assertEqual(getNextPartitionType(disk), parted.PARTITION_NORMAL)

        # free primary slot, extended, no free logical slot w/ no_primary
        # -> None
        disk = self.getDisk(disk_type="dos", primary_count=3, has_extended=True,
                            logical_count=11)
        self.assertEqual(getNextPartitionType(disk, no_primary=True), None)

        #
        # GPT
        #

        # empty disk, any partition type
        disk = self.getDisk(disk_type="gpt")
        self.assertEqual(getNextPartitionType(disk), parted.PARTITION_NORMAL)

        # no empty slots -> None
        disk = self.getDisk(disk_type="gpt", primary_count=128)
        self.assertEqual(getNextPartitionType(disk), None)

        # no_primary -> None
        disk = self.getDisk(disk_type="gpt")
        self.assertEqual(getNextPartitionType(disk, no_primary=True), None)

        #
        # MAC
        #

        # empty disk, any partition type
        disk = self.getDisk(disk_type="mac")
        self.assertEqual(getNextPartitionType(disk), parted.PARTITION_NORMAL)

        # no empty slots -> None
        disk = self.getDisk(disk_type="mac", primary_count=62)
        self.assertEqual(getNextPartitionType(disk), None)

        # no_primary -> None
        disk = self.getDisk(disk_type="mac")
        self.assertEqual(getNextPartitionType(disk, no_primary=True), None)

    def testAddPartition(self):
        with sparsetmpfile("addparttest", Size("50 MiB")) as disk_file:
            disk = DiskFile(disk_file)
            disk.format = getFormat("disklabel", device=disk.path, exists=False)

            free = disk.format.partedDisk.getFreeSpaceRegions()[0]

            #
            # add a partition with an unaligned size
            #
            self.assertEqual(len(disk.format.partitions), 0)
            part = addPartition(disk.format, free, parted.PARTITION_NORMAL,
                                Size("10 MiB") - Size(37))
            self.assertEqual(len(disk.format.partitions), 1)

            # an unaligned size still yields an aligned partition
            alignment = disk.format.alignment
            geom = part.geometry
            sector_size = Size(geom.device.sectorSize)
            self.assertEqual(alignment.isAligned(free, geom.start), True)
            self.assertEqual(alignment.isAligned(free, geom.end + 1), True)
            self.assertEqual(part.geometry.length, int(Size("10 MiB") // sector_size))

            disk.format.removePartition(part)
            self.assertEqual(len(disk.format.partitions), 0)

            #
            # adding a partition smaller than the optimal io size should yield
            # a partition aligned using the minimal io size instead
            #
            opt_str = 'parted.Device.optimumAlignment'
            min_str = 'parted.Device.minimumAlignment'
            opt_al = parted.Alignment(offset=0, grainSize=8192) # 4 MiB
            min_al = parted.Alignment(offset=0, grainSize=2048) # 1 MiB
            with patch(opt_str, opt_al) as optimal, patch(min_str, min_al) as minimal:
                optimal_end = disk.format.getEndAlignment(alignment=optimal)
                minimal_end = disk.format.getEndAlignment(alignment=minimal)

                sector_size = Size(disk.format.sectorSize)
                length = 4096 # 2 MiB
                size = Size(sector_size * length)
                part = addPartition(disk.format, free, parted.PARTITION_NORMAL,
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

                disk.format.removePartition(part)
                self.assertEqual(len(disk.format.partitions), 0)

            #
            # add a partition with an unaligned start sector
            #
            start_sector = 5003
            end_sector = 15001
            part = addPartition(disk.format, free, parted.PARTITION_NORMAL,
                                None, start_sector, end_sector)
            self.assertEqual(len(disk.format.partitions), 1)

            # start and end sectors are exactly as specified
            self.assertEqual(part.geometry.start, start_sector)
            self.assertEqual(part.geometry.end, end_sector)

            disk.format.removePartition(part)
            self.assertEqual(len(disk.format.partitions), 0)

            #
            # fail: add a logical partition to a primary free region
            #
            with self.assertRaisesRegexp(parted.PartitionException,
                                         "no extended partition"):
                part = addPartition(disk.format, free, parted.PARTITION_LOGICAL,
                                    Size("10 MiB"))

            ## add an extended partition to the disk
            placeholder = addPartition(disk.format, free,
                                       parted.PARTITION_NORMAL, Size("10 MiB"))
            all_free = disk.format.partedDisk.getFreeSpaceRegions()
            addPartition(disk.format, all_free[1],
                         parted.PARTITION_EXTENDED, Size("30 MiB"),
                         alignment.alignUp(all_free[1],
                                           placeholder.geometry.end))

            disk.format.removePartition(placeholder)
            self.assertEqual(len(disk.format.partitions), 1)
            all_free = disk.format.partedDisk.getFreeSpaceRegions()

            #
            # add a logical partition to an extended free regions
            #
            part = addPartition(disk.format, all_free[1],
                                parted.PARTITION_LOGICAL,
                                Size("10 MiB"), all_free[1].start)
            self.assertEqual(part.type, parted.PARTITION_LOGICAL)

            disk.format.removePartition(part)
            self.assertEqual(len(disk.format.partitions), 1)

            #
            # fail: add a primary partition to an extended free region
            #
            with self.assertRaisesRegexp(parted.PartitionException, "overlap"):
                part = addPartition(disk.format, all_free[1],
                                    parted.PARTITION_NORMAL,
                                    Size("10 MiB"), all_free[1].start)


    def testChunk(self):
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

        chunk.addRequest(req3)
        self.assertEqual(chunk.pool, 60)
        self.assertEqual(chunk.base, 30)

        self.assertEqual(chunk.lengthToSize(30), 30)
        self.assertEqual(chunk.sizeToLength(40), 40)
        self.assertEqual(chunk.hasGrowable, True)

        chunk.growRequests()

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

    def testVGChunk(self):
        pv = StorageDevice("pv1", size=Size("40 GiB"),
                           fmt=getFormat("lvmpv"))
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
        self.assertEqual(chunk.pool, vg.freeExtents)
        base_size = vg.align(sum(lv.size for lv in vg.lvs), roundup=True)
        base = base_size / vg.peSize
        self.assertEqual(chunk.base, base)

        # default extent size is 4 MiB
        self.assertEqual(chunk.lengthToSize(4), Size("16 MiB"))
        self.assertEqual(chunk.sizeToLength(Size("33 MiB")), 8)
        self.assertEqual(chunk.hasGrowable, True)

        self.assertEqual(chunk.remaining, 3)
        self.assertEqual(chunk.done, False)

        chunk.growRequests()

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
        # first in the list after sorting with blivet.partitioning.lvCompare.
        #
        # Grand totals should be as follows:
        # lv1 should grow by 395 extents, or 1.54 GiB
        # lv2 should grow by 3956 extents, or 15.45 GiB
        # lv3 should grow by 512 extents, or 2 GiB
        self.assertEqual(req1.growth, 395)
        self.assertEqual(req2.growth, 3956)
        self.assertEqual(req3.growth, 512)

class ExtendedPartitionTestCase(ImageBackedTestCase):

    disks = {"disk1": Size("2 GiB")}
    initialize_disks = False

    def _set_up_storage(self):
        # Don't rely on the default being an msdos disklabel since the test
        # could be running on an EFI system.
        for name in self.disks:
            disk = self.blivet.devicetree.getDeviceByName(name)
            fmt = getFormat("disklabel", labelType="msdos", device=disk.path)
            self.blivet.formatDevice(disk, fmt)

    def testImplicitExtendedPartitions(self):
        """ Verify management of implicitly requested extended partition. """
        # By running partition allocation multiple times with enough partitions
        # to require an extended partition, we exercise the code that manages
        # the implicit extended partition.
        p1 = self.blivet.newPartition(size=Size("100 MiB"))
        self.blivet.createDevice(p1)

        p2 = self.blivet.newPartition(size=Size("200 MiB"))
        self.blivet.createDevice(p2)

        p3 = self.blivet.newPartition(size=Size("300 MiB"))
        self.blivet.createDevice(p3)

        p4 = self.blivet.newPartition(size=Size("400 MiB"))
        self.blivet.createDevice(p4)

        doPartitioning(self.blivet)

        # at this point there should be an extended partition
        self.assertIsNotNone(self.blivet.disks[0].format.extendedPartition,
                             "no extended partition was created")

        # remove the last partition request and verify that the extended goes away as a result
        self.blivet.destroyDevice(p4)
        doPartitioning(self.blivet)
        self.assertIsNone(self.blivet.disks[0].format.extendedPartition,
                          "extended partition was not removed with last logical")

        p5 = self.blivet.newPartition(size=Size("500 MiB"))
        self.blivet.createDevice(p5)

        doPartitioning(self.blivet)

        p6 = self.blivet.newPartition(size=Size("450 MiB"))
        self.blivet.createDevice(p6)

        doPartitioning(self.blivet)

        self.assertIsNotNone(self.blivet.disks[0].format.extendedPartition,
                             "no extended partition was created")

        self.blivet.doIt()

    def testImplicitExtendedPartitionsInstallerMode(self):
        flags.installer_mode = True
        self.testImplicitExtendedPartitions()
        flags.install_mode = False

    def testExplicitExtendedPartitions(self):
        """ Verify that explicitly requested extended partitions work. """
        disk = self.blivet.disks[0]
        p1 = self.blivet.newPartition(size=Size("500 MiB"),
                                      partType=parted.PARTITION_EXTENDED)
        self.blivet.createDevice(p1)
        doPartitioning(self.blivet)

        self.assertEqual(p1.partedPartition.type, parted.PARTITION_EXTENDED)
        self.assertEqual(p1.partedPartition, disk.format.extendedPartition)

        p2 = self.blivet.newPartition(size=Size("1 GiB"))
        self.blivet.createDevice(p2)
        doPartitioning(self.blivet)

        self.assertEqual(p1.partedPartition, disk.format.extendedPartition,
                         "user-specified extended partition was removed")

        self.blivet.doIt()

if __name__ == "__main__":
    unittest.main()
