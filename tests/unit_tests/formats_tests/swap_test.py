import six
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

        with six.assertRaisesRegex(self, DeviceError, "device is too large for new format"):
            StorageDevice("dev", size=Size("17 TiB"),
                          fmt=get_format("swap"))
