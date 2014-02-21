import unittest
import mock

import blivet
from pykickstart.constants import CLEARPART_TYPE_ALL, CLEARPART_TYPE_LINUX, CLEARPART_TYPE_NONE
from parted import PARTITION_NORMAL
from blivet.flags import flags

class ClearPartTestCase(unittest.TestCase):
    def setUp(self):
        flags.testing = True

    def testShouldClear(self):
        """ Test the Blivet.shouldClear method. """
        b = blivet.Blivet()

        DiskDevice = blivet.devices.DiskDevice
        PartitionDevice = blivet.devices.PartitionDevice

        # sda is a disk with an existing disklabel containing two partitions
        sda = DiskDevice("sda", size=100000, exists=True)
        sda.format = blivet.formats.getFormat("disklabel", device=sda.path,
                                              exists=True)
        sda.format._partedDisk = mock.Mock()
        sda.format._partedDevice = mock.Mock()
        sda.format._partedDisk.configure_mock(partitions=[])
        b.devicetree._addDevice(sda)

        # sda1 is a partition containing an existing ext4 filesystem
        sda1 = PartitionDevice("sda1", size=500, exists=True,
                               parents=[sda])
        sda1._partedPartition = mock.Mock(**{'type': PARTITION_NORMAL,
                                             'getFlag.return_value': 0})
        sda1.format = blivet.formats.getFormat("ext4", mountpoint="/boot",
                                               device=sda1.path,
                                               exists=True)
        b.devicetree._addDevice(sda1)

        # sda2 is a partition containing an existing vfat filesystem
        sda2 = PartitionDevice("sda2", size=10000, exists=True,
                               parents=[sda])
        sda2._partedPartition = mock.Mock(**{'type': PARTITION_NORMAL,
                                             'getFlag.return_value': 0})
        sda2.format = blivet.formats.getFormat("vfat", mountpoint="/foo",
                                               device=sda2.path,
                                               exists=True)
        b.devicetree._addDevice(sda2)

        # sdb is an unpartitioned disk containing an xfs filesystem
        sdb = DiskDevice("sdb", size=100000, exists=True)
        sdb.format = blivet.formats.getFormat("xfs", device=sdb.path,
                                              exists=True)
        b.devicetree._addDevice(sdb)

        # sdc is an unformatted/uninitialized/empty disk
        sdc = DiskDevice("sdc", size=100000, exists=True)
        b.devicetree._addDevice(sdc)

        # sdd is a disk containing an existing disklabel with no partitions
        sdd = DiskDevice("sdd", size=100000, exists=True)
        sdd.format = blivet.formats.getFormat("disklabel", device=sdd.path,
                                              exists=True)
        b.devicetree._addDevice(sdd)

        #
        # clearpart type none
        #
        b.config.clearPartType = CLEARPART_TYPE_NONE
        self.assertFalse(b.shouldClear(sda1),
                         msg="type none should not clear any partitions")
        self.assertFalse(b.shouldClear(sda2),
                         msg="type none should not clear any partitions")

        b.config.initializeDisks = False
        self.assertFalse(b.shouldClear(sda),
                         msg="type none should not clear non-empty disks")
        self.assertFalse(b.shouldClear(sdb),
                         msg="type none should not clear formatting from "
                             "unpartitioned disks")

        self.assertFalse(b.shouldClear(sdc),
                         msg="type none should not clear empty disk without "
                             "initlabel")
        self.assertFalse(b.shouldClear(sdd),
                         msg="type none should not clear empty partition table "
                             "without initlabel")

        b.config.initializeDisks = True
        self.assertFalse(b.shouldClear(sda),
                         msg="type none should not clear non-empty disks even "
                             "with initlabel")
        self.assertFalse(b.shouldClear(sdb),
                         msg="type non should not clear formatting from "
                             "unpartitioned disks even with initlabel")
        self.assertTrue(b.shouldClear(sdc),
                        msg="type none should clear empty disks when initlabel "
                            "is set")
        self.assertTrue(b.shouldClear(sdd),
                        msg="type none should clear empty partition table when "
                            "initlabel is set")

        #
        # clearpart type linux
        #
        b.config.clearPartType = CLEARPART_TYPE_LINUX
        self.assertTrue(b.shouldClear(sda1),
                        msg="type linux should clear partitions containing "
                            "ext4 filesystems")
        self.assertFalse(b.shouldClear(sda2),
                         msg="type linux should not clear partitions "
                             "containing vfat filesystems")

        b.config.initializeDisks = False
        self.assertFalse(b.shouldClear(sda),
                         msg="type linux should not clear non-empty disklabels")
        self.assertTrue(b.shouldClear(sdb),
                        msg="type linux should clear linux-native whole-disk "
                            "formatting regardless of initlabel setting")
        self.assertFalse(b.shouldClear(sdc),
                         msg="type linux should not clear unformatted disks "
                             "unless initlabel is set")
        self.assertFalse(b.shouldClear(sdd),
                         msg="type linux should not clear disks with empty "
                             "partition tables unless initlabel is set")

        b.config.initializeDisks = True
        self.assertFalse(b.shouldClear(sda),
                         msg="type linux should not clear non-empty disklabels")
        self.assertTrue(b.shouldClear(sdb),
                        msg="type linux should clear linux-native whole-disk "
                            "formatting regardless of initlabel setting")
        self.assertTrue(b.shouldClear(sdc),
                         msg="type linux should clear unformatted disks when "
                             "initlabel is set")
        self.assertTrue(b.shouldClear(sdd),
                         msg="type linux should clear disks with empty "
                             "partition tables when initlabel is set")

        sda1.protected = True
        self.assertFalse(b.shouldClear(sda1),
                         msg="protected devices should never be cleared")
        self.assertFalse(b.shouldClear(sda),
                         msg="disks containing protected devices should never "
                             "be cleared")
        sda1.protected = False

        #
        # clearpart type all
        #
        b.config.clearPartType = CLEARPART_TYPE_ALL
        self.assertTrue(b.shouldClear(sda1),
                        msg="type all should clear all partitions")
        self.assertTrue(b.shouldClear(sda2),
                        msg="type all should clear all partitions")

        b.config.initializeDisks = False
        self.assertTrue(b.shouldClear(sda),
                        msg="type all should initialize all disks")
        self.assertTrue(b.shouldClear(sdb),
                        msg="type all should initialize all disks")
        self.assertTrue(b.shouldClear(sdc),
                        msg="type all should initialize all disks")
        self.assertTrue(b.shouldClear(sdd),
                        msg="type all should initialize all disks")

        b.config.initializeDisks = True
        self.assertTrue(b.shouldClear(sda),
                        msg="type all should initialize all disks")
        self.assertTrue(b.shouldClear(sdb),
                        msg="type all should initialize all disks")
        self.assertTrue(b.shouldClear(sdc),
                        msg="type all should initialize all disks")
        self.assertTrue(b.shouldClear(sdd),
                        msg="type all should initialize all disks")

        sda1.protected = True
        self.assertFalse(b.shouldClear(sda1),
                         msg="protected devices should never be cleared")
        self.assertFalse(b.shouldClear(sda),
                         msg="disks containing protected devices should never "
                             "be cleared")
        sda1.protected = False

        #
        # clearpart type list
        #
        # TODO

    def tearDown(self):
        flags.testing = False

    def testInitializeDisk(self):
        """
            magic partitions
            non-empty partition table
        """
        pass

    def testRecursiveRemove(self):
        """
            protected device at various points in stack
        """
        pass
