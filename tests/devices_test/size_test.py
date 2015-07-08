
import unittest

from blivet.devices import StorageDevice
from blivet import errors
from blivet.formats import getFormat
from blivet.size import Size

class StorageDeviceSizeTest(unittest.TestCase):
    def _getDevice(self, *args, **kwargs):
        return StorageDevice(*args, **kwargs)

    def testSizeSetter(self):
        initial_size = Size('10 GiB')
        new_size = Size('2 GiB')

        ##
        ## setter sets the size
        ##
        dev = self._getDevice('sizetest', size=initial_size)
        self.assertEqual(dev.size, initial_size)

        dev.size = new_size
        self.assertEqual(dev.size, new_size)

        ##
        ## setter raises exn if size outside of format limits
        ##
        dev.format._maxSize = Size("5 GiB")
        with self.assertRaises(errors.DeviceError):
            dev.size = Size("6 GiB")

        ##
        ## new formats' min size is checked against device size
        ##
        fmt = getFormat(None)
        fmt._minSize = Size("10 GiB")
        with self.assertRaises(errors.DeviceError):
            dev.format = fmt

        # the format assignment should succeed without the min size conflict
        fmt._minSize = Size(0)
        dev.format = fmt

        ##
        ## new formats' max size is checked against device size
        ##
        fmt = getFormat(None)
        fmt._maxSize = Size("10 MiB")
        with self.assertRaises(errors.DeviceError):
            dev.format = fmt

        # the format assignment should succeed without the min size conflict
        fmt._maxSize = Size(0)
        dev.format = fmt

    def testSizeGetter(self):
        initial_size = Size("10 GiB")
        new_size = Size("5 GiB")
        dev = self._getDevice('sizetest', size=initial_size)

        ##
        ## getter returns the size in the basic case for non-existing devices
        ##
        self.assertEqual(dev.size, initial_size)

        # create a new device that exists
        dev = self._getDevice('sizetest', size=initial_size, exists=True)

        ##
        ## getter returns the size in the basic case for existing devices
        ##
        self.assertEqual(dev.size, initial_size)

        ##
        ## size does not reflect target size for non-resizable devices
        ##
        # bypass the setter since the min/max will be the current size for a
        # non-resizable device
        dev._targetSize = new_size
        self.assertEqual(dev.size, initial_size)

        ##
        ## getter returns target size when device is resizable and target size
        ## is non-zero
        ##
        dev._resizable = True
        dev.targetSize = new_size # verify that the target size setter works
        self.assertEqual(dev.size, new_size)
        self.assertEqual(dev.size, dev.targetSize)
        self.assertNotEqual(dev._size, dev.targetSize)

        ##
        ## getter returns current size when device is resizable and target size
        ## is zero
        ##
        dev.targetSize = Size(0)
        self.assertEqual(dev.size, initial_size)
        self.assertEqual(dev.size, dev.currentSize)
