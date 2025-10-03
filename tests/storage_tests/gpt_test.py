import unittest
from uuid import UUID

from .storagetestcase import StorageTestCase

from blivet.devicelibs import gpt
from blivet.devices import LUKSDevice
from blivet.flags import flags
from blivet import formats
from blivet.formats import get_format
from blivet import partitioning
from blivet.size import Size

import parted


class GPTTestBase(StorageTestCase):

    _num_disks = 1

    # Default parted GUID for "Linux Data" partition
    LINUX_DATA_GUID = UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")

    def setUp(self):
        super().setUp()
        self._blivet_setup()
        self._set_up_storage()

    def _clean_up(self):
        self._blivet_cleanup()
        return super()._clean_up()

    def _set_up_storage(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        self.storage.format_device(disk, get_format("disklabel", label_type="gpt"))

        # A part whose UUID varies per architecture, without FS formatted
        self.root = self.storage.new_partition(
            size=Size("10MiB"), maxsize=Size("50GiB"), grow=True,
            parents=[disk], mountpoint="/")
        self.storage.create_device(self.root)

        # A part whose UUID is fixed per architecture, without FS formatted
        self.home = self.storage.new_partition(
            size=Size("50MiB"), parents=[disk],
            mountpoint="/home")
        self.storage.create_device(self.home)

        # A part whose UUID is fixed per architecture, with FS formatted
        self.tmp = self.storage.new_partition(
            fmt_type="ext4", size=Size("50MiB"),
            parents=[disk], mountpoint="/tmp")
        self.storage.create_device(self.tmp)

        # A part whose UUID specified explicitly, with FS formatted
        self.srv = self.storage.new_partition(
            fmt_type="ext4", size=Size("50MiB"),
            parents=[disk], mountpoint="/srv",
            part_type_uuid=gpt.gpt_part_uuid_for_mountpoint("/srv"))
        self.storage.create_device(self.srv)

        # A part with no special UUID assignment
        self.etc = self.storage.new_partition(
            size=Size("20MiB"), parents=[disk],
            mountpoint="/etc")
        self.storage.create_device(self.etc)

        # A part whose UUID is based off fmt type
        self.swap = self.storage.new_partition(
            fmt_type="swap", size=Size("20MiB"), parents=[disk])
        self.storage.create_device(self.swap)

        # An encrypted part
        self.usrluks = self.storage.new_partition(
            fmt_type="luks", fmt_args={
                "passphrase": "123456",
            }, size=Size("100MiB"),
            parents=[disk], mountpoint="/usr")
        self.storage.create_device(self.usrluks)

        self.usr = LUKSDevice(
            name="luks-user", size=self.usrluks.size, parents=self.usrluks)
        self.storage.create_device(self.usr)

        extfs = formats.get_format(
            fmt_type="ext4", device=self.usr.path, mountpoint="/usr")
        self.storage.format_device(self.usr, extfs)

        # Allocate the partitions
        partitioning.do_partitioning(self.storage)

        self.storage.do_it()


class GPTDiscoverableTestCase(GPTTestBase):

    def setUp(self):
        olddisc = flags.gpt_discoverable_partitions
        flags.gpt_discoverable_partitions = True
        super(GPTDiscoverableTestCase, self).setUp()
        flags.gpt_discoverable_partitions = olddisc

    @unittest.skipUnless(hasattr(parted.Partition, "type_uuid"),
                         "requires part type UUID in pyparted")
    def test_check_gpt_part_type(self):
        want = gpt.gpt_part_uuid_for_mountpoint("/")
        got = UUID(bytes=self.root.parted_partition.type_uuid)
        self.assertEqual(want, got)

        want = gpt.gpt_part_uuid_for_mountpoint("/home")
        got = UUID(bytes=self.home.parted_partition.type_uuid)
        self.assertEqual(want, got)

        want = gpt.gpt_part_uuid_for_mountpoint("/tmp")
        got = UUID(bytes=self.tmp.parted_partition.type_uuid)
        self.assertEqual(want, got)

        want = gpt.gpt_part_uuid_for_mountpoint("/srv")
        got = UUID(bytes=self.srv.parted_partition.type_uuid)
        self.assertEqual(want, got)

        got = UUID(bytes=self.etc.parted_partition.type_uuid)
        self.assertEqual(self.LINUX_DATA_GUID, got)

        want = gpt.gpt_part_uuid_for_volume(gpt.GPT_VOL_SWAP)
        got = UUID(bytes=self.swap.parted_partition.type_uuid)
        self.assertEqual(want, got)

        want = gpt.gpt_part_uuid_for_mountpoint("/usr")
        got = UUID(bytes=self.usrluks.parted_partition.type_uuid)
        self.assertEqual(want, got)


class GPTNonDiscoverableTestCase(GPTTestBase):

    def setUp(self):
        olddisc = flags.gpt_discoverable_partitions
        flags.gpt_discoverable_partitions = False
        super(GPTNonDiscoverableTestCase, self).setUp()
        flags.gpt_discoverable_partitions = olddisc

    @unittest.skipUnless(hasattr(parted.Partition, "type_uuid"),
                         "requires part type UUID in pyparted")
    def test_check_gpt_part_type(self):

        got = UUID(bytes=self.root.parted_partition.type_uuid)
        self.assertEqual(self.LINUX_DATA_GUID, got)

        got = UUID(bytes=self.home.parted_partition.type_uuid)
        self.assertEqual(self.LINUX_DATA_GUID, got)

        got = UUID(bytes=self.tmp.parted_partition.type_uuid)
        self.assertEqual(self.LINUX_DATA_GUID, got)

        want = gpt.gpt_part_uuid_for_mountpoint("/srv")
        got = UUID(bytes=self.srv.parted_partition.type_uuid)
        self.assertEqual(want, got)

        got = UUID(bytes=self.etc.parted_partition.type_uuid)
        self.assertEqual(self.LINUX_DATA_GUID, got)

        want = gpt.gpt_part_uuid_for_volume(gpt.GPT_VOL_SWAP)
        got = UUID(bytes=self.swap.parted_partition.type_uuid)
        self.assertEqual(want, got)

        got = UUID(bytes=self.usrluks.parted_partition.type_uuid)
        self.assertEqual(self.LINUX_DATA_GUID, got)
