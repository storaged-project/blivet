import unittest

from ..storagetestcase import StorageTestCase
from packaging.version import Version

import blivet

from blivet.devices.stratis import StratisFilesystemDevice, StratisClevisConfig


class StratisTestCaseBase(StorageTestCase):

    @classmethod
    def setUpClass(cls):
        unavailable_deps = StratisFilesystemDevice.unavailable_type_dependencies()
        if unavailable_deps:
            dep_str = ", ".join([d.name for d in unavailable_deps])
            raise unittest.SkipTest("some unavailable dependencies required for this test: %s" % dep_str)

    def setUp(self):
        super().setUp()

        self._blivet_setup()

    def _clean_up(self):
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        return super()._clean_up()


class StratisTestCase(StratisTestCaseBase):

    _num_disks = 2

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
                                             encrypted=True, passphrase="fipsneeds8chars")
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
        self.assertIsNone(pool._clevis)

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

    def test_stratis_add_device(self):
        disk1 = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk1)
        self.storage.initialize_disk(disk1)

        bd1 = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                         parents=[disk1])
        self.storage.create_device(bd1)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.new_stratis_pool(name="blivetTestPool", parents=[bd1])
        self.storage.create_device(pool)

        self.storage.do_it()
        self.storage.reset()

        disk2 = self.storage.devicetree.get_device_by_path(self.vdevs[1])
        self.assertIsNotNone(disk2)
        self.storage.initialize_disk(disk2)

        bd2 = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                         parents=[disk2])
        self.storage.create_device(bd2)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")

        ac = blivet.deviceaction.ActionAddMember(pool, bd2)
        self.storage.devicetree.actions.add(ac)
        self.storage.do_it()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertEqual(len(pool.parents), 2)
        self.assertCountEqual([p.path for p in pool.parents], [self.vdevs[0] + "1", self.vdevs[1] + "1"])

        bd2 = self.storage.devicetree.get_device_by_path(self.vdevs[1] + "1")
        self.assertEqual(bd2.format.pool_name, pool.name)
        self.assertEqual(bd2.format.pool_uuid, pool.uuid)

    def _get_stratis_version(self):
        out = blivet.util.capture_output(["stratis", "--version"])
        return Version(out)

    def test_stratis_pool_start_stop(self):
        if self._get_stratis_version() < Version("3.8.0"):
            self.skipTest("Stratis 3.8.0 or newer needed for start/stop support")

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

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertTrue(pool.status)

        # try teardown and setup
        pool.teardown()
        self.assertFalse(pool.status)
        pool.setup()
        self.assertTrue(pool.status)

        # teardown again to test reset with stopped pool
        pool.teardown()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertFalse(pool.status)

        # start the pool again to be able to remove it
        pool.setup()

        # run reset() to get the filesystems
        self.storage.reset()
        fs = self.storage.devicetree.get_device_by_name("blivetTestPool/blivetTestFS")
        self.assertIsNotNone(fs)

        # stop the pool again to test removing stopped pool
        pool.teardown()
        self.storage.reset()
        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")

        self.storage.destroy_device(pool)
        self.storage.do_it()
        self.storage.reset()

        # we didn't remove the block devices so the pool should be back
        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)

        pool.setup()

    def test_stratis_pool_start_stop_encrypted(self):
        if self._get_stratis_version() < Version("3.8.0"):
            self.skipTest("Stratis 3.8.0 or newer needed for start/stop support")

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        bd = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                        parents=[disk])
        self.storage.create_device(bd)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.new_stratis_pool(name="blivetTestPool", parents=[bd],
                                             encrypted=True, passphrase="fipsneeds8chars")
        self.storage.create_device(pool)

        self.storage.do_it()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertTrue(pool.status)

        # try teardown and setup
        pool.teardown()
        self.assertFalse(pool.status)

        # setup won't work without passphrase
        with self.assertRaisesRegex(blivet.errors.StratisError, "Passphrase or key file must be set for encrypted Stratis pool setup"):
            pool.setup()

        pool.passphrase = "fipsneeds8chars"
        pool.setup()
        self.assertTrue(pool.status)

        # teardown again to test reset with stopped pool
        pool.teardown()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertFalse(pool.status)

        # start the pool again to be able to remove it
        pool.passphrase = "fipsneeds8chars"
        pool.setup()


@unittest.skip("Requires TPM or Tang configuration")
class StratisTestCaseClevis(StratisTestCaseBase):

    _num_disks = 1

    # XXX: we don't have Tang server, this test will be always skipped
    #      the test cases are kept here for manual testing
    _tang_server = None

    def test_stratis_encrypted_clevis_tang(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        bd = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                        parents=[disk])
        self.storage.create_device(bd)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.new_stratis_pool(name="blivetTestPool", parents=[bd],
                                             encrypted=True, passphrase="fipsneeds8chars",
                                             clevis=StratisClevisConfig(pin="tang",
                                                                        tang_url=self._tang_server,
                                                                        tang_thumbprint=None))
        self.storage.create_device(pool)

        self.storage.do_it()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertEqual(pool.type, "stratis pool")
        self.assertTrue(pool.encrypted)
        self.assertIsNotNone(pool._clevis)
        self.assertEqual(pool._clevis.pin, "tang")
        self.assertEqual(pool._clevis.tang_url, self._tang_server)
        self.assertIsNotNone(pool._clevis.tang_thumbprint)

    def test_stratis_encrypted_clevis_tpm(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.storage.initialize_disk(disk)

        bd = self.storage.new_partition(size=blivet.size.Size("1 GiB"), fmt_type="stratis",
                                        parents=[disk])
        self.storage.create_device(bd)

        blivet.partitioning.do_partitioning(self.storage)

        pool = self.storage.new_stratis_pool(name="blivetTestPool", parents=[bd],
                                             encrypted=True, passphrase="fipsneeds8chars",
                                             clevis=StratisClevisConfig(pin="tpm2"))
        self.storage.create_device(pool)

        self.storage.do_it()
        self.storage.reset()

        pool = self.storage.devicetree.get_device_by_name("blivetTestPool")
        self.assertIsNotNone(pool)
        self.assertEqual(pool.type, "stratis pool")
        self.assertTrue(pool.encrypted)
        self.assertIsNotNone(pool._clevis)
        self.assertEqual(pool._clevis.pin, "tpm2")
        self.assertIsNone(pool._clevis.tang_url)
        self.assertIsNone(pool._clevis.tang_thumbprint)
