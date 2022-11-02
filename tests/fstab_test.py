import os

from .storagetestcase import StorageTestCase

import blivet

FSTAB_WRITE_FILE = "/var/tmp/test-blivet-fstab"

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

        os.remove(FSTAB_WRITE_FILE)
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        return super()._clean_up()

        # restore original fstab target file
        self.storage.fstab.dest_file = "/etc/fstab"

    def test_fstab(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        # change write path of blivet.fstab
        self.storage.fstab.dest_file = FSTAB_WRITE_FILE

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

        # Change the mountpoint, make sure the change will make it into the fstab
        ac = blivet.deviceaction.ActionConfigureFormat(device=lv, attr="mountpoint", new_value="/mnt/test2")
        self.storage.devicetree.actions.add(ac)

        self.storage.do_it()
        self.storage.reset()

        with open(FSTAB_WRITE_FILE, "r") as f:
            contents = f.read()
            print(contents)
            self.assertTrue("blivetTestLVMine" in contents)
            self.assertTrue("/mnt/test2" in contents)



