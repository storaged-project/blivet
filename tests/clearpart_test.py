""" Clearpart command related unit tests
"""
import unittest
import mock

import blivet
import blivet.devices
from blivet.devices.lib import Tags
from blivet.flags import flags
from pykickstart.constants import CLEARPART_TYPE_ALL, CLEARPART_TYPE_LINUX
from pykickstart.constants import CLEARPART_TYPE_NONE, CLEARPART_TYPE_LIST
from parted import PARTITION_NORMAL

DEVICE_CLASSES = [
    blivet.devices.DiskDevice,
    blivet.devices.PartitionDevice
]

# access to protected attributes is needed for setting up the test environment
# pragma pylint: disable=protected-access


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES),
                     "some unsupported device classes required for this test")
class ClearPartTestCase(unittest.TestCase):
    """ Tests of clearpart command and its options
    """

    def setUp(self):
        flags.testing = True

        self.blivet = blivet.Blivet()
        disk_device = blivet.devices.DiskDevice
        partition_device = blivet.devices.PartitionDevice

        # prepare mock devices
        # sda is a disk with an existing disklabel containing two partitions
        self.sda = disk_device("sda", size=100000, exists=True)
        self.sda.format = blivet.formats.get_format("disklabel", device=self.sda.path,
                                                    exists=True)
        self.sda.format._parted_disk = mock.Mock()
        self.sda.format._parted_device = mock.Mock()
        self.sda.format._parted_disk.configure_mock(partitions=[])
        self.blivet.devicetree._add_device(self.sda)

        # sda1 is a partition containing an existing ext4 filesystem
        self.sda1 = partition_device("sda1", size=500, exists=True,
                                     parents=[self.sda])
        self.sda1._parted_partition = mock.Mock(**{'type': PARTITION_NORMAL,
                                                   'getFlag.return_value': 0})
        self.sda1.format = blivet.formats.get_format("ext4", mountpoint="/boot",
                                                     device=self.sda1.path,
                                                     exists=True)
        self.blivet.devicetree._add_device(self.sda1)

        # sda2 is a partition containing an existing vfat filesystem
        self.sda2 = partition_device("sda2", size=10000, exists=True,
                                     parents=[self.sda])
        self.sda2._parted_partition = mock.Mock(**{'type': PARTITION_NORMAL,
                                                   'getFlag.return_value': 0})
        self.sda2.format = blivet.formats.get_format("vfat", mountpoint="/foo",
                                                     device=self.sda2.path,
                                                     exists=True)
        self.blivet.devicetree._add_device(self.sda2)

        # sdb is an unpartitioned disk containing an xfs filesystem
        self.sdb = disk_device("sdb", size=100000, exists=True)
        self.sdb.format = blivet.formats.get_format("xfs", device=self.sdb.path,
                                                    exists=True)
        self.blivet.devicetree._add_device(self.sdb)

        # sdc is an unformatted/uninitialized/empty disk
        self.sdc = disk_device("sdc", size=100000, exists=True)
        self.blivet.devicetree._add_device(self.sdc)

        # sdd is a disk containing an existing disklabel with no partitions
        self.sdd = disk_device("sdd", size=100000, exists=True)
        self.sdd.format = blivet.formats.get_format("disklabel", device=self.sdd.path,
                                                    exists=True)
        self.blivet.devicetree._add_device(self.sdd)

        self.addCleanup(self._clean_up)

    def _clean_up(self):  # pylint: disable=no-self-use
        flags.testing = False

    def test_should_clear(self):
        """ Test the Blivet.should_clear method. """

        # clearpart type none
        self.blivet.config.clear_part_type = CLEARPART_TYPE_NONE
        self.assertFalse(self.blivet.should_clear(self.sda1),
                         msg="type none should not clear any partitions")
        self.assertFalse(self.blivet.should_clear(self.sda2),
                         msg="type none should not clear any partitions")

        self.blivet.config.initialize_disks = False
        self.assertFalse(self.blivet.should_clear(self.sda),
                         msg="type none should not clear non-empty disks")
        self.assertFalse(self.blivet.should_clear(self.sdb),
                         msg="type none should not clear formatting from "
                             "unpartitioned disks")

        self.assertFalse(self.blivet.should_clear(self.sdc),
                         msg="type none should not clear empty disk without "
                             "initlabel")
        self.assertFalse(self.blivet.should_clear(self.sdd),
                         msg="type none should not clear empty partition table "
                             "without initlabel")

        self.blivet.config.initialize_disks = True
        self.assertFalse(self.blivet.should_clear(self.sda),
                         msg="type none should not clear non-empty disks even "
                             "with initlabel")
        self.assertFalse(self.blivet.should_clear(self.sdb),
                         msg="type non should not clear formatting from "
                             "unpartitioned disks even with initlabel")
        self.assertTrue(self.blivet.should_clear(self.sdc),
                        msg="type none should clear empty disks when initlabel "
                            "is set")
        self.assertTrue(self.blivet.should_clear(self.sdd),
                        msg="type none should clear empty partition table when "
                            "initlabel is set")

        # clearpart type linux
        self.blivet.config.clear_part_type = CLEARPART_TYPE_LINUX
        self.assertTrue(self.blivet.should_clear(self.sda1),
                        msg="type linux should clear partitions containing "
                            "ext4 filesystems")
        self.assertFalse(self.blivet.should_clear(self.sda2),
                         msg="type linux should not clear partitions "
                             "containing vfat filesystems")

        self.blivet.config.initialize_disks = False
        self.assertFalse(self.blivet.should_clear(self.sda),
                         msg="type linux should not clear non-empty disklabels")
        self.assertTrue(self.blivet.should_clear(self.sdb),
                        msg="type linux should clear linux-native whole-disk "
                            "formatting regardless of initlabel setting")
        self.assertFalse(self.blivet.should_clear(self.sdc),
                         msg="type linux should not clear unformatted disks "
                             "unless initlabel is set")
        self.assertFalse(self.blivet.should_clear(self.sdd),
                         msg="type linux should not clear disks with empty "
                             "partition tables unless initlabel is set")

        self.blivet.config.initialize_disks = True
        self.assertFalse(self.blivet.should_clear(self.sda),
                         msg="type linux should not clear non-empty disklabels")
        self.assertTrue(self.blivet.should_clear(self.sdb),
                        msg="type linux should clear linux-native whole-disk "
                            "formatting regardless of initlabel setting")
        self.assertTrue(self.blivet.should_clear(self.sdc),
                        msg="type linux should clear unformatted disks when "
                        "initlabel is set")
        self.assertTrue(self.blivet.should_clear(self.sdd),
                        msg="type linux should clear disks with empty "
                        "partition tables when initlabel is set")

        self.sda1.protected = True
        self.assertFalse(self.blivet.should_clear(self.sda1),
                         msg="protected devices should never be cleared")
        self.assertFalse(self.blivet.should_clear(self.sda),
                         msg="disks containing protected devices should never "
                             "be cleared")
        self.sda1.protected = False

        # clearpart type all
        self.blivet.config.clear_part_type = CLEARPART_TYPE_ALL
        self.assertTrue(self.blivet.should_clear(self.sda1),
                        msg="type all should clear all partitions")
        self.assertTrue(self.blivet.should_clear(self.sda2),
                        msg="type all should clear all partitions")

        self.blivet.config.initialize_disks = False
        self.assertTrue(self.blivet.should_clear(self.sda),
                        msg="type all should initialize all disks")
        self.assertTrue(self.blivet.should_clear(self.sdb),
                        msg="type all should initialize all disks")
        self.assertTrue(self.blivet.should_clear(self.sdc),
                        msg="type all should initialize all disks")
        self.assertTrue(self.blivet.should_clear(self.sdd),
                        msg="type all should initialize all disks")

        self.blivet.config.initialize_disks = True
        self.assertTrue(self.blivet.should_clear(self.sda),
                        msg="type all should initialize all disks")
        self.assertTrue(self.blivet.should_clear(self.sdb),
                        msg="type all should initialize all disks")
        self.assertTrue(self.blivet.should_clear(self.sdc),
                        msg="type all should initialize all disks")
        self.assertTrue(self.blivet.should_clear(self.sdd),
                        msg="type all should initialize all disks")

        self.sda1.protected = True
        self.assertFalse(self.blivet.should_clear(self.sda1),
                         msg="protected devices should never be cleared")
        self.assertFalse(self.blivet.should_clear(self.sda),
                         msg="disks containing protected devices should never "
                             "be cleared")
        self.sda1.protected = False

    def test_should_clear_tags(self):
        """ Test the Blivet.should_clear method using tags. """

        # devices marked for cleaning
        self.blivet.config.clear_part_devices = ["sdd", "@ssd", "@local"]
        # devices tags configuration:
        self.sda.tags = {Tags.remote}
        self.sdb.tags = {Tags.ssd}
        self.sdc.tags = {Tags.local}
        self.sdd.tags = set()

        self.blivet.config.clear_part_type = CLEARPART_TYPE_LIST

        self.assertFalse(self.blivet.should_clear(self.sda),
                         msg="device should not be cleared")
        self.assertTrue(self.blivet.should_clear(self.sdb),
                        msg="device should be cleared")
        self.assertTrue(self.blivet.should_clear(self.sdc),
                        msg="device should be cleared")
        self.assertTrue(self.blivet.should_clear(self.sdd),
                        msg="device should be cleared")

        self.blivet.config.clear_part_devices = []
        self.blivet.config.clear_part_type = CLEARPART_TYPE_ALL

        self.blivet.config.clear_part_disks = ["sda", "@ssd", "@local"]
        self.assertTrue(self.blivet.should_clear(self.sda1),
                        msg="device should be cleared")

        self.blivet.config.clear_part_disks = ["@ssd", "@local"]
        self.assertFalse(self.blivet.should_clear(self.sda1),
                         msg="device should not be cleared")

        self.blivet.config.clear_part_disks = ["@ssd", "@remote"]
        self.assertTrue(self.blivet.should_clear(self.sda1),
                        msg="device should be cleared")

    def test_initialize_disk(self):
        """
            magic partitions
            non-empty partition table
        """
        pass

    def test_recursive_remove(self):
        """
            protected device at various points in stack
        """
        pass
