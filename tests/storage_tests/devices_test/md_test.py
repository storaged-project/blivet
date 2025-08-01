import os
import time

from contextlib import contextmanager

import blivet.deviceaction
import blivet.devicelibs

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
                time.sleep(1)


class MDTestCase(StorageTestCase):

    raidname = "blivetTestRAID"

    def setUp(self):
        super().setUp()

        self._blivet_setup()

    def _clean_up(self):
        self._blivet_cleanup()

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

    def _test_mdraid(self, raid_level, members, metadata_version=None):
        parts = self._prepare_members(members)
        array = self.storage.new_mdarray(name=self.raidname, parents=parts,
                                         level=raid_level, total_devices=members,
                                         member_devices=members,
                                         metadata_version=metadata_version)
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

        if metadata_version:
            self.assertEqual(array.metadata_version, metadata_version)
        else:
            self.assertEqual(array.metadata_version, "1.2")

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

    def test_mdraid_raid1_version_10(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID1, 2, "1.0")

    def test_mdraid_raid1_version_11(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID1, 2, "1.1")

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


class MDDiskTestCase(StorageTestCase):

    _num_disks = 2
    _disk_size = 200 * 1024**2

    raidname = "blivetTestRAIDDisk"

    def setUp(self):
        super().setUp()

        self._blivet_setup()

    def _remove_array(self, wipefs=True):
        # cleanup with mdadm
        if wipefs:
            _ret = blivet.util.run_program(["wipefs", "-a", "/dev/md/%s" % self.raidname])
        _ret = blivet.util.run_program(["mdadm", "--stop", "/dev/md/%s" % self.raidname])
        _ret = blivet.util.run_program(["mdadm", "--zero-superblock", self.vdevs[0], self.vdevs[1]])

    def _clean_up(self):
        self._remove_array()
        return super()._clean_up()

    def _create_array(self, metadata_version="1.2"):
        disk1 = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk1)
        self.storage.format_device(disk1, blivet.formats.get_format("mdmember"))

        disk2 = self.storage.devicetree.get_device_by_path(self.vdevs[1])
        self.assertIsNotNone(disk2)
        self.storage.format_device(disk2, blivet.formats.get_format("mdmember"))

        members = [disk1, disk2]

        array = self.storage.new_mdarray(name=self.raidname, parents=members,
                                         level=blivet.devicelibs.raid.RAID1,
                                         total_devices=2, member_devices=2,
                                         metadata_version=metadata_version)
        self.storage.create_device(array)

        with wait_for_resync():
            self.storage.do_it()
        self.storage.reset()

        return members

    def _test_mdraid_raid1_on_disk(self, metadata_version):
        members = self._create_array(metadata_version)

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.level, blivet.devicelibs.raid.RAID1)
        self.assertEqual(array.member_devices, 2)
        self.assertEqual(array.spares, 0)
        self.assertCountEqual([m.name for m in array.members],
                              [d.name for d in members])
        for member in array.members:
            self.assertEqual(member.format.md_uuid, array.uuid)
        self.assertTrue(array.is_disk)
        self.assertEqual(array.metadata_version, metadata_version)

    def test_mdraid_raid1_on_disk_version_10(self):
        self._test_mdraid_raid1_on_disk("1.0")

    def test_mdraid_raid1_on_disk_version_11(self):
        self._test_mdraid_raid1_on_disk("1.1")

    def test_mdraid_raid1_on_disk_version_12(self):
        self._test_mdraid_raid1_on_disk("1.2")

    def test_mdraid_raid_on_disk_external_rhbz2357484(self):
        # create the raid  GPT using "external" tools (mdadm and parted)
        _ret = blivet.util.run_program(["mdadm", "--create", "--run", "/dev/md/%s" % self.raidname,
                                        "--level=raid0", "--raid-devices=2",
                                        self.vdevs[0], self.vdevs[1]])
        _ret = blivet.util.run_program(["parted", "--script", "/dev/md/%s" % self.raidname,
                                        "mklabel", "gpt", "mkpart", "primary", "1MiB", "300MiB"])
        self.storage.reset()

        # remove the raid
        self._remove_array()

        # and create a new with different level and the same name as above
        _ret = blivet.util.run_program(["mdadm", "--create", "--run", "/dev/md/%s" % self.raidname,
                                        "--level=raid1", "--raid-devices=2",
                                        self.vdevs[0], self.vdevs[1]])
        _ret = blivet.util.run_program(["parted", "--script", "/dev/md/%s" % self.raidname,
                                        "mklabel", "gpt", "mkpart", "primary", "1MiB", "150MiB"])

        # XXX udev races, sometimes we just don't get the `linux_raid_member` format on the disks
        # in udev after creating the array above
        _ret = blivet.util.run_program(["udevadm", "trigger", "-s", "block", "--settle"])

        with wait_for_resync():
            self.storage.reset()
        self.storage.reset()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)
        self.assertEqual(array.level, blivet.devicelibs.raid.RAID1)

        # check the partition table and partition on the array
        self.assertEqual(array.format.type, "disklabel")
        self.assertEqual(array.format.label_type, "gpt")
        self.assertEqual(len(array.children), 1)

    def test_stale_metadata_removal_pv(self):
        """ Test that a stale LVM PV format is removed from a newly created MD array """
        # manually create MD with PV format but without VG
        _ret = blivet.util.run_program(["mdadm", "--create", "--run", "/dev/md/%s" % self.raidname,
                                        "--level=raid1", "--raid-devices=2",
                                        self.vdevs[0], self.vdevs[1]])
        _ret = blivet.util.run_program(["pvcreate", "/dev/md/%s" % self.raidname])

        # remove the array without wiping it
        self._remove_array(wipefs=False)

        # now create the array with blivet
        self._create_array()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)

        # check that the PV format was correctly wiped
        self.assertIsNone(array.format.type)

        out = blivet.util.capture_output(["blkid", "-p", "-sTYPE", "-ovalue", array.path])
        self.assertFalse(out)

    def test_stale_metadata_removal_vg(self):
        """ Test that a stale LVM VG is removed from a newly created MD array """
        # manually create MD with with VG
        _ret = blivet.util.run_program(["mdadm", "--create", "--run", "/dev/md/%s" % self.raidname,
                                        "--level=raid1", "--raid-devices=2",
                                        self.vdevs[0], self.vdevs[1]])
        _ret = blivet.util.run_program(["vgcreate", "blivetTestStaleVG", "/dev/md/%s" % self.raidname])

        # remove the array without wiping it
        self._remove_array(wipefs=False)

        # now create the array with blivet
        self._create_array()

        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)

        # check that the VG was removed and the PV format was correctly wiped
        vg = self.storage.devicetree.get_device_by_name("blivetTestStaleVG")
        self.assertIsNone(vg)

        self.assertIsNone(array.format.type)

        out = blivet.util.capture_output(["blkid", "-p", "-sTYPE", "-ovalue", array.path])
        self.assertFalse(out)


class MDLUKSTestCase(StorageTestCase):

    _num_disks = 2

    raidname = "blivetTestRAIDLUKS"
    passphrase = "passphrase"

    def setUp(self):
        super().setUp()

        self._blivet_setup()

    def _clean_up(self):
        self._blivet_cleanup()

        return super()._clean_up()

    def _prepare_members(self, members):
        luks_devs = []
        for i in range(members):
            disk = self.storage.devicetree.get_device_by_path(self.vdevs[i])
            self.assertIsNotNone(disk)
            self.storage.initialize_disk(disk)

            pbkdf = blivet.formats.luks.LUKS2PBKDFArgs(type="pbkdf2", time_ms=100)
            part = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="luks",
                                              fmt_args={"passphrase": self.passphrase, "pbkdf_args": pbkdf},
                                              parents=[disk])
            self.storage.create_device(part)

            luks_dev = blivet.devices.LUKSDevice("luks-%s" % part.name, size=part.size,
                                                 parents=[part])
            self.storage.create_device(luks_dev)
            self.storage.format_device(luks_dev, blivet.formats.get_format("mdmember"))
            luks_devs.append(luks_dev)

        blivet.partitioning.do_partitioning(self.storage)

        return luks_devs

    def _test_mdraid(self, raid_level, members):
        luks_devs = self._prepare_members(members)
        array = self.storage.new_mdarray(name=self.raidname, parents=luks_devs,
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
                              [p.name for p in luks_devs])
        for member in array.members:
            self.assertEqual(member.format.md_uuid, array.uuid)

        array.teardown()
        for member in array.members:
            member.teardown()

        parts_names = [parent.parents[0].name for parent in array.members]

        self.storage.reset()

        parts = []
        for name in parts_names:
            part = self.storage.devicetree.get_device_by_name(name)
            self.assertIsNotNone(part)
            self.assertEqual(part.format.type, "luks")
            parts.append(part)

        # unlock just one of the LUKS partitions
        parts[0].format.passphrase = self.passphrase
        parts[0].format.setup()
        self.assertTrue(parts[0].format.status)

        self.storage.devicetree.populate()

        # array should not be in the tree
        array = self.storage.devicetree.get_device_by_name(self.raidname)

        self.assertIsNone(array)

        # unlock rest of the LUKS devices
        for part in parts[1:]:
            part.format.passphrase = self.passphrase
            part.format.setup()
            self.assertTrue(parts[0].format.status)

        # now the array should be in the tree and we should be able to activate it
        self.storage.devicetree.populate()
        array = self.storage.devicetree.get_device_by_name(self.raidname)
        self.assertIsNotNone(array)

        array.setup()
        self.assertTrue(array.status)
        self.assertEqual(len(array.members), members)

    def test_luks_mdraid_raid0(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID0, 2)

    def test_luks_mdraid_raid1(self):
        self._test_mdraid(blivet.devicelibs.raid.RAID1, 2)


class BIOSRAIDTestCase(StorageTestCase):

    _num_disks = 2

    def setUp(self):
        super().setUp()

        disks = [os.path.basename(vdev) for vdev in self.vdevs]
        self.storage = blivet.Blivet()
        self.storage.exclusive_disks = disks + ["vol0"]
        self.storage.reset()

        # make sure only the targetcli disks are in the devicetree
        for disk in self.storage.disks:
            if disk.name == "vol0":
                continue
            self.assertTrue(disk.path in self.vdevs)
            self.assertIsNone(disk.format.type)
            self.assertFalse(disk.children)

    def _clean_up(self):
        # cleanup with mdadm
        _ret = blivet.util.run_program(["mdadm", "--stop", "/dev/md/vol0"])
        _ret = blivet.util.run_program(["mdadm", "--stop", "/dev/md/ddf"])
        _ret = blivet.util.run_program(["mdadm", "--zero-superblock", self.vdevs[0], self.vdevs[1]])

        return super()._clean_up()

    def _create_ddf_raid(self):
        # prepare a fake DDF RAID using mdadm
        ret = blivet.util.run_program(["mdadm", "--create", "/dev/md/ddf", "--run", "--level=container",
                                       "--metadata=ddf", "--raid-devices=2", self.vdevs[0], self.vdevs[1]])
        if ret != 0:
            raise RuntimeError("Failed to setup DDF RAID for testing")

        ret = blivet.util.run_program(["mdadm", "--create", "/dev/md/vol0", "--run", "--level=raid0",
                                       "--raid-devices=1", "/dev/md/ddf", "--force"])
        if ret != 0:
            raise RuntimeError("Failed to setup DDF RAID for testing")

        # joys of creating devices for tests manually, we need to encourage udev
        # a bit to actually have the correct information for reset after creating
        # the DDF array
        blivet.udev.trigger(action="change", path=self.vdevs[0])
        blivet.udev.trigger(action="change", path=self.vdevs[1])
        blivet.udev.settle()

    def test_ddf_raid(self):
        self._create_ddf_raid()

        with wait_for_resync():
            self.storage.reset()

        # check that we can correctly detect BIOS RAID arrays
        vol0 = self.storage.devicetree.get_device_by_name("vol0")
        self.assertIsNotNone(vol0)
        self.assertEqual(vol0.type, "mdbiosraidarray")
        self.assertEqual(vol0.level.name, "raid0")
        self.assertEqual(len(vol0.parents), 1)

        ddf = self.storage.devicetree.get_device_by_name("ddf")
        self.assertIsNotNone(ddf)
        self.assertEqual(ddf.type, "mdcontainer")
        self.assertEqual(ddf.level.name, "container")
        self.assertEqual(len(ddf.children), 1)
        self.assertEqual(ddf.children[0], vol0)
        self.assertEqual(len(ddf.parents), 2)
        self.assertCountEqual([p.path for p in ddf.parents], [self.vdevs[0], self.vdevs[1]])

        # check that partitions can be created and recognized on the array
        self.storage.initialize_disk(vol0)
        part = self.storage.new_partition(size=blivet.size.Size("100 MiB"), parents=[vol0])
        self.storage.create_device(part)

        blivet.partitioning.do_partitioning(self.storage)
        self.storage.do_it()

        self.storage.reset()

        part = self.storage.devicetree.get_device_by_name("vol0p1")
        self.assertIsNotNone(part)
