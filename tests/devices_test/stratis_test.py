import test_compat  # pylint: disable=unused-import

import unittest

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

        pool = b.new_stratis_pool(name="testpool", parents=[bd])
        self.assertEqual(pool.name, "testpool")
        self.assertEqual(pool.size, bd.size)

        fs = b.new_stratis_filesystem(name="testfs", parents=[pool])

        self.assertEqual(fs.name, "testpool/testfs")
        self.assertEqual(fs.path, "/dev/stratis/%s" % fs.name)
        self.assertEqual(fs.size, Size("1 TiB"))
        self.assertEqual(fs.pool, pool)
        self.assertEqual(fs.format.type, "stratis_xfs")
