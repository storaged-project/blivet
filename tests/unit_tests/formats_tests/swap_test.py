import unittest

from blivet.devices.storage import StorageDevice
from blivet.errors import DeviceError
from blivet.formats import get_format

from blivet.size import Size


class SwapNodevTestCase(unittest.TestCase):

    def test_swap_max_size(self):
        StorageDevice("dev", size=Size("129 GiB"),
                      fmt=get_format("swap"))

        StorageDevice("dev", size=Size("15 TiB"),
                      fmt=get_format("swap"))

        with self.assertRaisesRegex(DeviceError, "device is too large for new format"):
            StorageDevice("dev", size=Size("17 TiB"),
                          fmt=get_format("swap"))

    def test_swap_uuid_format(self):
        fmt = get_format("swap")

        # label -- at most 16 characters
        self.assertTrue(fmt.label_format_ok("label"))
        self.assertFalse(fmt.label_format_ok("a" * 17))

        # uuid -- RFC 4122 format
        self.assertTrue(fmt.uuid_format_ok("01234567-1234-1234-1234-012345678911"))
        self.assertFalse(fmt.uuid_format_ok("aaaa"))
