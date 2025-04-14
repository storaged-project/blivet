import os
import unittest

import blivet
import tempfile

from .storagetestcase import StorageTestCase


class FstabTestCase(StorageTestCase):

    _num_disks = 1

    @classmethod
    def setUpClass(cls):
        if not blivet.fstab.HAVE_LIBMOUNT:
            raise unittest.SkipTest("Missing libmount support required for this test")

    def setUp(self):
        super().setUp()

        blivet.flags.flags.auto_dev_updates = True

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

        blivet.flags.flags.auto_dev_updates = False

        self.storage.fstab.dest_file = None
        self.storage.fstab.src_file = None

        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        # restore original fstab target file
        self.storage.fstab.dest_file = "/etc/fstab"

        return super()._clean_up()

    def test_fstab(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        with tempfile.TemporaryDirectory() as tmpdirname:
            fstab_path = os.path.join(tmpdirname, 'fstab')

            # change write path of blivet.fstab
            self.storage.fstab.dest_file = fstab_path

            self.storage.initialize_disk(disk)

            pv = self.storage.new_partition(size=blivet.size.Size("100 MiB"), fmt_type="lvmpv",
                                            parents=[disk])
            self.storage.create_device(pv)

            blivet.partitioning.do_partitioning(self.storage)

            vg = self.storage.new_vg(name="blivetTestVG", parents=[pv])
            self.storage.create_device(vg)

            lv = self.storage.new_lv(fmt_type="ext4", size=blivet.size.Size("50 MiB"),
                                     parents=[vg], name="blivetTestLVMine")
            self.storage.create_device(lv)

            # specify device spec representation in fstab
            lv.format.fstab_spec_type = "PATH"
            lv.format.freq = 54321
            lv.format.passno = 2
            lv.format.options = "optionA,optionB"

            # Change the mountpoint, make sure the change will make it into the fstab
            ac = blivet.deviceaction.ActionConfigureFormat(device=lv, attr="mountpoint", new_value="/mnt/test2")
            self.storage.devicetree.actions.add(ac)

            self.storage.do_it()
            self.storage.reset()

            # Check fstab contents for added device
            with open(fstab_path, "r") as f:
                contents = f.read()
                self.assertTrue("blivetTestLVMine" in contents)
                self.assertTrue("54321" in contents)
                self.assertTrue("54321 2" in contents)
                self.assertTrue("optionA,optionB" in contents)

            # check that we can read and parse the fstab written above
            self.storage.fstab.src_file = fstab_path
            self.storage.reset()
            self.assertEqual(str(self.storage.fstab),
                             "/dev/mapper/blivetTestVG-blivetTestLVMine\t/mnt/test2\text4\toptionA,optionB\t54321\t2\t\n")

            # test some fstab functions here where we have a device and its fstab entry
            fstab = blivet.fstab.FSTabManager(src_file=fstab_path)
            fstab.read()
            lv = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestLVMine")
            entry = fstab.find_entry(file="/mnt/test2")
            self.assertIsNotNone(entry)

            dev = fstab.find_device(devicetree=self.storage.devicetree, spec="/dev/mapper/blivetTestVG-blivetTestLVMine")
            self.assertIsNotNone(dev)
            self.assertEqual(dev, lv)

            dev = fstab.find_device(devicetree=self.storage.devicetree, entry=entry)
            self.assertIsNotNone(dev)
            self.assertEqual(dev, lv)

            # remove the device
            dev = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestLVMine")
            self.storage.recursive_remove(dev)

            self.storage.do_it()
            self.storage.reset()

            # Check that previously added device is no longer in fstab
            with open(fstab_path, "r") as f:
                contents = f.read()
                self.assertFalse("blivetTestLVMine" in contents)
                self.assertFalse("/mnt/test2" in contents)

    def test_luks_creation(self):
        # test creation of a multiple layer device
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        fstab_path = '/tmp/myfstab'

        with tempfile.TemporaryDirectory() as tmpdirname:
            fstab_path = os.path.join(tmpdirname, 'fstab')

            # change write path of blivet.fstab
            self.storage.fstab.dest_file = fstab_path

            self.storage.initialize_disk(disk)

            var = self.storage.new_partition(fmt_type="luks",
                                             fmt_args={"passphrase": "opensaysme"},
                                             size=blivet.size.Size("200MiB"),
                                             parents=[disk],
                                             mountpoint="/mnt/test_fstab_luks_wrong")

            self.storage.create_device(var)

            varenc = blivet.devices.LUKSDevice(name="blivetTest_fstab_luks",
                                               size=var.size,
                                               parents=var)
            self.storage.create_device(varenc)

            varfs = blivet.formats.get_format(fmt_type="ext4",
                                              device=varenc.path,
                                              mountpoint="/mnt/test_fstab_luks_correct")
            self.storage.format_device(varenc, varfs)

            blivet.partitioning.do_partitioning(self.storage)

            self.storage.do_it()
            self.storage.reset()

            # Check fstab contents for added device
            with open(fstab_path, "r") as f:
                contents = f.read()
                self.assertTrue("/mnt/test_fstab_luks_correct" in contents)
                self.assertFalse("/mnt/test_fstab_luks_wrong" in contents)

    def test_btrfs_creation(self):
        unavailable_deps = blivet.devices.BTRFSVolumeDevice.unavailable_type_dependencies()
        if unavailable_deps:
            dep_str = ", ".join([d.name for d in unavailable_deps])
            raise unittest.SkipTest("some unavailable dependencies required for this test: %s" % dep_str)

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        fstab_path = '/tmp/myfstab'

        with tempfile.TemporaryDirectory() as tmpdirname:
            fstab_path = os.path.join(tmpdirname, 'fstab')

            # change write path of blivet.fstab
            self.storage.fstab.dest_file = fstab_path

            self.storage.initialize_disk(disk)

            part = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="btrfs",
                                              parents=[disk])
            self.storage.create_device(part)

            blivet.partitioning.do_partitioning(self.storage)

            vol = self.storage.new_btrfs(name="blivetTestVol", parents=[part])
            self.storage.create_device(vol)

            sub = self.storage.new_btrfs_sub_volume(parents=[vol], name="blivetTestSubVol1",
                                                    mountpoint="/home")
            self.storage.create_device(sub)

            # create second subvolume with some more settings
            sub = self.storage.new_btrfs_sub_volume(parents=[vol], name="blivetTestSubVol2",
                                                    mountpoint="/var",
                                                    fmt_args={"fstab_spec_type": "PATH",
                                                              "freq": 1, "passno": 1})
            self.storage.create_device(sub)

            self.storage.do_it()
            self.storage.reset()

            with open(fstab_path, "r") as f:
                contents = f.read()

            # mountpoints are set and fstab management enabled, fstab entries should be
            # automatically added for both subvolumes
            self.assertEqual(contents,
                             "%s1 /var btrfs subvol=blivetTestSubVol2 1 1\n"
                             "UUID=%s /home btrfs subvol=blivetTestSubVol1 0 0\n" % (self.vdevs[0], vol.uuid))

            # test some fstab functions here where we have a btrfs device and its fstab entry
            fstab = blivet.fstab.FSTabManager(src_file=fstab_path)
            fstab.read()
            sub = self.storage.devicetree.get_device_by_name("blivetTestSubVol1")
            entry = fstab.find_entry(file="/home")
            self.assertIsNotNone(entry)

            dev = fstab.find_device(devicetree=self.storage.devicetree, spec="UUID=%s" % vol.uuid,
                                    mntopts=["subvol=blivetTestSubVol1"])
            self.assertIsNotNone(dev)
            self.assertEqual(dev, sub)

            dev = fstab.find_device(devicetree=self.storage.devicetree, entry=entry)
            self.assertIsNotNone(dev)
            self.assertEqual(dev, sub)

    def test_swap_creation(self):
        # test swap creation for presence of FSTabOptions object
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        with tempfile.TemporaryDirectory() as tmpdirname:
            fstab_path = os.path.join(tmpdirname, 'fstab')

            # change write path of blivet.fstab
            self.storage.fstab.dest_file = fstab_path

            self.storage.format_device(disk, blivet.formats.get_format("swap"))

            try:
                self.storage.do_it()
            except AttributeError as e:
                if "has no attribute 'fstab'" in str(e):
                    self.fail("swap creation test failed on missing FSTabOptions object: %s" % str(e))
