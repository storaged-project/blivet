
import unittest

from blivet.devicelibs import crypto
from blivet.devices import StorageDevice, LUKSDevice
from blivet import errors
from blivet.formats import get_format
from blivet.formats.luks import LUKS
from blivet.size import Size


class StorageDeviceSizeTest(unittest.TestCase):

    def _get_device(self, *args, **kwargs):
        return StorageDevice(*args, **kwargs)

    def test_size_setter(self):
        initial_size = Size('10 GiB')
        new_size = Size('2 GiB')

        ##
        # setter sets the size
        ##
        dev = self._get_device('sizetest', size=initial_size)
        self.assertEqual(dev.size, initial_size)

        dev.size = new_size
        self.assertEqual(dev.size, new_size)

        ##
        # setter raises exn if size outside of format limits
        ##
        dev.format._max_size = Size("5 GiB")
        with self.assertRaises(errors.DeviceError):
            dev.size = Size("6 GiB")

        ##
        # new formats' min size is checked against device size
        ##
        fmt = get_format(None)
        fmt._min_size = Size("10 GiB")
        with self.assertRaises(errors.DeviceError):
            dev.format = fmt

        # the format assignment should succeed without the min size conflict
        fmt._min_size = Size(0)
        dev.format = fmt

        ##
        # new formats' max size is checked against device size
        ##
        fmt = get_format(None)
        fmt._max_size = Size("10 MiB")
        with self.assertRaises(errors.DeviceError):
            dev.format = fmt

        # the format assignment should succeed without the min size conflict
        fmt._max_size = Size(0)
        dev.format = fmt

    def test_size_getter(self):
        initial_size = Size("10 GiB")
        new_size = Size("5 GiB")
        dev = self._get_device('sizetest', size=initial_size)

        ##
        # getter returns the size in the basic case for non-existing devices
        ##
        self.assertEqual(dev.size, initial_size)

        # create a new device that exists
        dev = self._get_device('sizetest', size=initial_size, exists=True)

        ##
        # getter returns the size in the basic case for existing devices
        ##
        self.assertEqual(dev.size, initial_size)

        ##
        # size does not reflect target size for non-resizable devices
        ##
        # bypass the setter since the min/max will be the current size for a
        # non-resizable device
        dev._target_size = new_size
        self.assertEqual(dev.size, initial_size)

        ##
        # getter returns target size when device is resizable and target size
        # is non-zero
        ##
        dev._resizable = True
        dev.format._resizable = True
        dev.target_size = new_size  # verify that the target size setter works
        self.assertEqual(dev.size, new_size)
        self.assertEqual(dev.size, dev.target_size)
        self.assertNotEqual(dev._size, dev.target_size)

        ##
        # getter returns current size when device is resizable and target size
        # is zero
        ##
        dev.target_size = Size(0)
        self.assertEqual(dev.size, initial_size)
        self.assertEqual(dev.size, dev.current_size)


class LUKSDeviceSizeTest(StorageDeviceSizeTest):

    def _get_device(self, *args, **kwargs):
        exists = kwargs.get("exists", False)
        parent = StorageDevice(*args, size=kwargs["size"] + crypto.LUKS_METADATA_SIZE, exists=exists)
        parent.format = LUKS()
        return LUKSDevice(*args, **kwargs, parents=[parent])

    def test_size_getter(self):
        initial_size = Size("10 GiB")
        dev = self._get_device('sizetest', size=initial_size)

        # for LUKS size depends on the backing device size
        self.assertEqual(dev.size, initial_size)
        self.assertEqual(dev.raw_device.size, initial_size + crypto.LUKS_METADATA_SIZE)
