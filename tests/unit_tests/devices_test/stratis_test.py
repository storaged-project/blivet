import unittest
from unittest.mock import patch, PropertyMock

import blivet

from blivet.devices import StorageDevice
from blivet.devices import StratisPoolDevice
from blivet.devices import StratisFilesystemDevice
from blivet.devices.stratis import StratisClevisConfig
from blivet.errors import StratisError, InconsistentParentSectorSize
from blivet.size import Size


DEVICE_CLASSES = [
    StratisPoolDevice,
    StratisFilesystemDevice,
    StorageDevice
]


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class BlivetNewStratisDeviceTest(unittest.TestCase):
    def test_new_stratis(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("2 GiB"), exists=False)

        b.devicetree._add_device(bd)

        with patch("blivet.devicetree.DeviceTree.names", []):
            pool = b.new_stratis_pool(name="testpool", parents=[bd])
        self.assertEqual(pool.name, "testpool")
        self.assertEqual(pool.size, bd.size)

        with patch("blivet.devicelibs.stratis.pool_used", lambda _d, _e: Size("512 MiB")):
            self.assertAlmostEqual(pool.free_space, Size("1.5 GiB"))

        with patch("blivet.devicetree.DeviceTree.names", []):
            fs = b.new_stratis_filesystem(name="testfs", parents=[pool], size=Size("1 GiB"))

        self.assertEqual(fs.name, "testpool/testfs")
        self.assertEqual(fs.path, "/dev/stratis/%s" % fs.name)
        self.assertEqual(fs.size, Size("1 GiB"))
        self.assertEqual(fs.pool, pool)
        self.assertEqual(fs.format.type, "stratis xfs")
        # for 1 TiB filesystem, metadata should take around 1 GiB
        self.assertAlmostEqual(fs.used_size, Size("20 MiB"), delta=Size("1 MiB"))

        with patch("blivet.devicetree.DeviceTree.names", []):
            with self.assertRaisesRegex(StratisError, "not enough free space in the pool"):
                # not enough free space for a 2 TiB filesystem
                b.new_stratis_filesystem(name="testfs2", parents=[pool], size=Size("2 TiB"))

        b.create_device(pool)
        b.create_device(fs)

        with patch("blivet.devicelibs.stratis") as stratis_dbus:
            with patch.object(pool, "_pre_create"):
                with patch.object(pool, "_post_create"):
                    pool.create()
                    stratis_dbus.create_pool.assert_called_with(name='testpool',
                                                                devices=['/dev/bd1'],
                                                                encrypted=False,
                                                                passphrase=None,
                                                                key_file=None,
                                                                clevis=None)

        # we would get this from pool._post_create
        pool.uuid = "c4fc9ebe-e173-4cab-8d81-cc6abddbe02d"

        with patch("blivet.devicelibs.stratis") as stratis_dbus:
            with patch.object(fs, "_pre_create"):
                with patch.object(fs, "_post_create"):
                    fs.create()
                    stratis_dbus.create_filesystem.assert_called_with(name="testfs",
                                                                      pool_uuid="c4fc9ebe-e173-4cab-8d81-cc6abddbe02d",
                                                                      fs_size=Size("1 GiB"))

    def test_new_encrypted_stratis(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("1 GiB"), exists=True)

        b.devicetree._add_device(bd)

        with patch("blivet.devicetree.DeviceTree.names", []):
            pool = b.new_stratis_pool(name="testpool", parents=[bd], encrypted=True, passphrase="secret")
        self.assertEqual(pool.name, "testpool")
        self.assertEqual(pool.size, bd.size)
        self.assertTrue(pool.encrypted)
        self.assertTrue(pool.has_key)

        b.create_device(pool)

        with patch("blivet.devicelibs.stratis") as stratis_dbus:
            with patch.object(pool, "_pre_create"):
                with patch.object(pool, "_post_create"):
                    pool.create()
                    stratis_dbus.create_pool.assert_called_with(name='testpool',
                                                                devices=['/dev/bd1'],
                                                                encrypted=True,
                                                                passphrase="secret",
                                                                key_file=None,
                                                                clevis=None)

    def test_new_encrypted_stratis_clevis(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("1 GiB"), exists=True)

        b.devicetree._add_device(bd)

        clevis = StratisClevisConfig(pin="tang", tang_url="xxx", tang_thumbprint="xxx")
        with patch("blivet.devicetree.DeviceTree.names", []):
            pool = b.new_stratis_pool(name="testpool", parents=[bd], passphrase="secret", encrypted=True, clevis=clevis)
        self.assertEqual(pool.name, "testpool")
        self.assertEqual(pool.size, bd.size)
        self.assertTrue(pool.encrypted)
        self.assertTrue(pool.has_key)

        b.create_device(pool)

        with patch("blivet.devicelibs.stratis") as stratis_dbus:
            with patch.object(pool, "_pre_create"):
                with patch.object(pool, "_post_create"):
                    pool.create()
                    stratis_dbus.create_pool.assert_called_with(name='testpool',
                                                                devices=['/dev/bd1'],
                                                                encrypted=True,
                                                                passphrase="secret",
                                                                key_file=None,
                                                                clevis=clevis)

    def test_new_stratis_no_size(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("2 GiB"), exists=False)

        b.devicetree._add_device(bd)

        with patch("blivet.devicetree.DeviceTree.names", []):
            pool = b.new_stratis_pool(name="testpool", parents=[bd])
        self.assertEqual(pool.name, "testpool")
        self.assertEqual(pool.size, bd.size)

        with patch("blivet.devicelibs.stratis.pool_used", lambda _d, _e: Size("512 MiB")):
            self.assertAlmostEqual(pool.free_space, Size("1.5 GiB"))

        with patch("blivet.devicetree.DeviceTree.names", []):
            fs = b.new_stratis_filesystem(name="testfs", parents=[pool])

        self.assertEqual(fs.name, "testpool/testfs")
        self.assertEqual(fs.path, "/dev/stratis/%s" % fs.name)
        self.assertEqual(fs.size, Size("1 TiB"))
        self.assertEqual(fs.pool, pool)
        self.assertEqual(fs.format.type, "stratis xfs")
        # for 1 TiB filesystem, metadata should take around 1 GiB
        self.assertAlmostEqual(fs.used_size, Size("1 GiB"), delta=Size("50 MiB"))

        b.create_device(pool)
        b.create_device(fs)

        with patch("blivet.devicelibs.stratis") as stratis_dbus:
            with patch.object(pool, "_pre_create"):
                with patch.object(pool, "_post_create"):
                    pool.create()
                    stratis_dbus.create_pool.assert_called_with(name='testpool',
                                                                devices=['/dev/bd1'],
                                                                encrypted=False,
                                                                passphrase=None,
                                                                key_file=None,
                                                                clevis=None)

        # we would get this from pool._post_create
        pool.uuid = "c4fc9ebe-e173-4cab-8d81-cc6abddbe02d"

        with patch("blivet.devicelibs.stratis") as stratis_dbus:
            with patch.object(fs, "_pre_create"):
                with patch.object(fs, "_post_create"):
                    fs.create()
                    stratis_dbus.create_filesystem.assert_called_with(name="testfs",
                                                                      pool_uuid="c4fc9ebe-e173-4cab-8d81-cc6abddbe02d",
                                                                      fs_size=Size("1 TiB"))

    def test_device_id(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("2 GiB"), exists=False)

        pool = StratisPoolDevice("testpool", parents=[bd])
        self.assertEqual(pool.device_id, "STRATIS-testpool")

        fs = StratisFilesystemDevice("testfs", parents=[pool], size=Size("1 GiB"))
        self.assertEqual(fs.device_id, "STRATIS-testpool/testfs")

    def test_pool_inconsistent_sector_size(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("2 GiB"), exists=False)
        bd2 = StorageDevice("bd2", fmt=blivet.formats.get_format("stratis"),
                            size=Size("2 GiB"), exists=False)

        with patch("blivet.devices.StorageDevice.sector_size", new_callable=PropertyMock) as mock_property:
            mock_property.__get__ = lambda _mock, bd, _class: 512 if bd.name == "bd1" else 4096
            with self.assertRaisesRegex(InconsistentParentSectorSize, "Cannot create pool"):
                StratisPoolDevice("testpool", parents=[bd, bd2])

    def test_filesystem_round_size(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("2 GiB"), exists=False)
        pool = StratisPoolDevice("testpool", parents=[bd])

        fs = StratisFilesystemDevice("testfs", parents=[pool], size=Size("1 GiB") + Size(1))
        # size should be rounded down to 1 GiB
        self.assertEqual(fs.size, Size("1 GiB"))
