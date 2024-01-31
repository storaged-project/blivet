import os

from .storagetestcase import StorageTestCase

import blivet
import tempfile


class FstabTestCase(StorageTestCase):

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

        self.storage.fstab.dest_file = None

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
            lv.format.fstab.spec_type = "PATH"
            lv.format.fstab.freq = 54321
            lv.format.fstab.passno = 2
            lv.format.fstab.mntops = ['optionA', 'optionB']

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

            dev = self.storage.devicetree.get_device_by_name("blivetTestVG-blivetTestLVMine")
            self.storage.recursive_remove(dev)

            self.storage.do_it()
            self.storage.reset()

            # Check that previously added device is no longer in fstab
            with open(fstab_path, "r") as f:
                contents = f.read()
                self.assertFalse("blivetTestLVMine" in contents)
                self.assertFalse("/mnt/test2" in contents)

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
