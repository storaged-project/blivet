import test_compat  # pylint: disable=unused-import

import unittest
from six.moves.mock import patch  # pylint: disable=no-name-in-module,import-error

import blivet

from blivet.devices import StorageDevice
from blivet.devices import StratisPoolDevice
from blivet.devices import StratisFilesystemDevice
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
                           size=Size("1 GiB"), exists=True)

        b.devicetree._add_device(bd)

        pool = b.new_stratis_pool(name="testpool", parents=[bd])
        self.assertEqual(pool.name, "testpool")
        self.assertEqual(pool.size, bd.size)

        fs = b.new_stratis_filesystem(name="testfs", parents=[pool])

        self.assertEqual(fs.name, "testpool/testfs")
        self.assertEqual(fs.path, "/dev/stratis/%s" % fs.name)
        self.assertEqual(fs.size, Size("1 TiB"))
        self.assertEqual(fs.pool, pool)
        self.assertEqual(fs.format.type, "stratis_xfs")

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
                                                                key_file=None)

        # we would get this from pool._post_create
        pool.uuid = "c4fc9ebe-e173-4cab-8d81-cc6abddbe02d"

        with patch("blivet.devicelibs.stratis") as stratis_dbus:
            with patch.object(fs, "_pre_create"):
                with patch.object(fs, "_post_create"):
                    fs.create()
                    stratis_dbus.create_filesystem.assert_called_with("testfs",
                                                                      "c4fc9ebe-e173-4cab-8d81-cc6abddbe02d")

    def test_new_encryted_stratis(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("stratis"),
                           size=Size("1 GiB"), exists=True)

        b.devicetree._add_device(bd)

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
                                                                key_file=None)
