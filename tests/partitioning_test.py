#!/usr/bin/python

import os
import unittest
from mock import Mock

import parted

from blivet.partitioning import getNextPartitionType
from blivet.partitioning import doPartitioning

from tests.imagebackedtestcase import ImageBackedTestCase
from blivet.formats import getFormat
from blivet.size import Size
from blivet.flags import flags

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

@unittest.skipUnless(os.environ.get("JENKINS_HOME"), "jenkins only test")
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
