import os
import time

from contextlib import contextmanager

from ..storagetestcase import StorageTestCase

import blivet


@contextmanager
def wait_for_resync():
    try:
        yield
    finally:
        time.sleep(2)
        action = True
        while action:
            with open("/proc/mdstat", "r") as f:
                action = "resync" in f.read()
            if action:
                print("Sleeping")
                time.sleep(1)


class MDTestCase(StorageTestCase):

    raidname = "blivetTestRAID"

    def setUp(self):
        super().setUp()

        disks = [os.path.basename(vdev) for vdev in self.vdevs]
        self.storage = blivet.Blivet()
        self.storage.exclusive_disks = disks
        self.storage.reset()

        # make sure only the targetcli disks are in the devicetree
        for disk in self.storage.disks:
            self.assertTrue(disk.path in self.vdevs)
            self.assertIsNone(disk.format.type)
            self.assertFalse(disk.children)

    def _clean_up(self):
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        return super()._clean_up()

    def _prepare_members(self, members):
        parts = []
        for i in range(members):
            disk = self.storage.devicetree.get_device_by_path(self.vdevs[i])
            self.assertIsNotNone(disk)
            self.storage.initialize_disk(disk)

            part = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="mdmember",
                                              parents=[disk])
            self.storage.create_device(part)
            parts.append(part)

        blivet.partitioning.do_partitioning(self.storage)

        return parts

    def _test_mdraid(self, raid_level, members):
        parts = self._prepare_members(members)
        array = self.storage.new_mdarray(name=self.raidname, parents=parts,
                                         level=raid_level, total_devices=members,
                                         member_devices=members)
        self.storage.create_device(array)

        with wait_for_resync():
            self.storage.do_it()
        self.storage.reset()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.level, raid_level)
        self.assertEqual(array.member_devices, members)
        self.assertEqual(array.spares, 0)
        self.assertCountEqual([m.name for m in array.members],
                              [p.name for p in parts])
        for member in array.members:
            self.assertEqual(member.format.md_uuid, array.uuid)

    def test_mdraid_raid0(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID0, 2)

    def test_mdraid_raid1(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID1, 2)

    def test_mdraid_raid5(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID5, 3)

    def test_mdraid_raid6(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID6, 4)

    def test_mdraid_raid10(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID10, 4)

    def test_mdraid_raid0_extra(self):
        parts = self._prepare_members(2)
        array = self.storage.new_mdarray(name=self.raidname, parents=parts,
                                         level=blivet.devicelibs.raid.RAID0,
                                         total_devices=2,
                                         member_devices=2,
                                         chunk_size=blivet.size.Size("1 MiB"),
                                         metadata_version="1.2")
        self.storage.create_device(array)

        with wait_for_resync():
            self.storage.do_it()
        self.storage.reset()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.chunk_size, blivet.size.Size("1 MiB"))
        self.assertEqual(array.metadata_version, "1.2")

    def test_mdraid_raid1_spare(self):
        parts = self._prepare_members(3)
        array = self.storage.new_mdarray(name=self.raidname, parents=parts,
                                         level=blivet.devicelibs.raid.RAID1,
                                         total_devices=3,
                                         member_devices=2)
        self.storage.create_device(array)

        with wait_for_resync():
            self.storage.do_it()
        self.storage.reset()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.level, blivet.devicelibs.raid.RAID1)
        self.assertEqual(array.total_devices, 3)
        self.assertEqual(array.member_devices, 2)
        self.assertEqual(array.spares, 1)
        self.assertCountEqual([m.name for m in array.members],
                              [p.name for p in parts])
        for member in array.members:
            self.assertEqual(member.format.md_uuid, array.uuid)

    def test_mdraid_members_add_remove(self):
        parts = self._prepare_members(2)
        array = self.storage.new_mdarray(name=self.raidname, parents=parts,
                                         level=blivet.devicelibs.raid.RAID1,
                                         total_devices=2,
                                         member_devices=2)
        self.storage.create_device(array)

        with wait_for_resync():
            self.storage.do_it()
        self.storage.reset()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.level, blivet.devicelibs.raid.RAID1)
        self.assertEqual(array.total_devices, 2)
        self.assertEqual(array.member_devices, 2)
        self.assertEqual(array.spares, 0)

        # add third disk to the array
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[2])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        part = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="mdmember",
                                          parents=[disk])
        self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)

        array = self.storage.devicetree.get_device_by_name(self.raidname)

        ac = blivet.deviceaction.ActionAddMember(array, part)
        self.storage.devicetree.actions.add(ac)

        with wait_for_resync():
            self.storage.do_it()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.level, blivet.devicelibs.raid.RAID1)
        self.assertEqual(array.total_devices, 3)
        self.assertEqual(array.member_devices, 3)
        self.assertEqual(array.spares, 0)
        self.assertEqual(part.format.md_uuid, array.uuid)

        # and now remove it from the array
        ac = blivet.deviceaction.ActionRemoveMember(array, part)
        self.storage.devicetree.actions.add(ac)

        with wait_for_resync():
            self.storage.do_it()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.level, blivet.devicelibs.raid.RAID1)
        self.assertEqual(array.total_devices, 2)
        self.assertEqual(array.member_devices, 2)
        self.assertEqual(array.spares, 0)
        self.assertFalse(array.degraded)
        self.assertIsNone(part.format.md_uuid)
