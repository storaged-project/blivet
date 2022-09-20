import os
import unittest

from ..storagetestcase import StorageTestCase

import blivet

from blivet.devices.stratis import StratisFilesystemDevice


class StratisTestCase(StorageTestCase):

    @classmethod
    def setUpClass(cls):
        unavailable_deps = StratisFilesystemDevice.unavailable_type_dependencies()
        if unavailable_deps:
            dep_str = ", ".join([d.name for d in unavailable_deps])
            raise unittest.SkipTest("some unavailable dependencies required for this test: %s" % dep_str)

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

    def test_stratis_basic(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        bd = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                        parents=[disk])
        self.storage.create_device(bd)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.new_stratis_pool(name="blivetTestPool", parents=[bd])
        self.storage.create_device(pool)

        fs = self.storage.new_stratis_filesystem(name="blivetTestFS", parents=[pool],
                                                 size=blivet.size.Size("800 MiB"))
        self.storage.create_device(fs)

        self.storage.do_it()
        self.storage.reset()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        bd = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "1")
        self.assertIsNotNone(bd)
        self.assertIsInstance(bd, blivet.devices.PartitionDevice)
        self.assertIsNotNone(bd.format)
        self.assertEqual(bd.format.type, "stratis")

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertIsInstance(pool, blivet.devices.StratisPoolDevice)
        self.assertIsNotNone(pool.format)
        self.assertIsNone(pool.format.type)
        self.assertEqual(bd.format.pool_name, pool.name)
        self.assertEqual(len(pool.parents), 1)
        self.assertEqual(pool.parents[0], bd)

        fs = self.storage.devicetree.get_device_by_name("blivetTestPool/blivetTestFS")
        self.assertIsNotNone(fs)
        self.assertIsInstance(fs, blivet.devices.StratisFilesystemDevice)
        self.assertIsNotNone(fs.format)
        self.assertEqual(fs.format.type, "stratis xfs")
        self.assertEqual(fs.pool, pool)
        self.assertEqual(len(fs.parents), 1)
        self.assertEqual(fs.parents[0], pool)

    def test_stratis_encrypted(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        bd = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                        parents=[disk])
        self.storage.create_device(bd)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.new_stratis_pool(name="blivetTestPool", parents=[bd],
                                             encrypted=True, passphrase="abcde")
        self.storage.create_device(pool)

        self.storage.do_it()
        self.storage.reset()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        bd = self.storage.devicetree.get_device_by_path(self.vdevs[0] + "1")
        self.assertIsNotNone(bd)
        self.assertIsInstance(bd, blivet.devices.PartitionDevice)
        self.assertIsNotNone(bd.format)
        self.assertEqual(bd.format.type, "stratis")

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertIsInstance(pool, blivet.devices.StratisPoolDevice)
        self.assertIsNotNone(pool.format)
        self.assertIsNone(pool.format.type)
        self.assertEqual(bd.format.pool_name, pool.name)
        self.assertEqual(len(pool.parents), 1)
        self.assertEqual(pool.parents[0], bd)
        self.assertTrue(pool.encrypted)

    def test_stratis_overprovision(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        bd = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                        parents=[disk])
        self.storage.create_device(bd)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.new_stratis_pool(name="blivetTestPool", parents=[bd])
        self.storage.create_device(pool)

        self.storage.do_it()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)

        with self.assertRaisesRegex(blivet.errors.StratisError, "not enough free space in the pool"):
            fs = self.storage.new_stratis_filesystem(name="blivetTestFS", parents=[pool],
                                                     size=blivet.size.Size("1 TiB"))

        fs = self.storage.new_stratis_filesystem(name="blivetTestFS", parents=[pool],
                                                 size=blivet.size.Size("2 GiB"))
        self.storage.create_device(fs)

        self.storage.do_it()
        self.storage.reset()

        fs = self.storage.devicetree.get_device_by_name("blivetTestPool/blivetTestFS")
        self.assertIsNotNone(fs)
        self.assertIsInstance(fs, blivet.devices.StratisFilesystemDevice)
        self.assertAlmostEqual(fs.size, blivet.size.Size("2 GiB"), delta=blivet.size.Size("10 MiB"))
