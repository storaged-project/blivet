import blivet.formats.luks as luks
from blivet.size import Size
from blivet.errors import DeviceFormatError, LUKSError

from tests import loopbackedtestcase

class LUKSTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='runTest'):
        super(LUKSTestCase, self).__init__(methodName=methodName, deviceSpec=[self.DEFAULT_STORE_SIZE])
        self.fmt = luks.LUKS(passphrase="passphrase", name="super-luks")

    def testSimple(self):
        """ Simple test of creation, setup, and teardown. """
        # test that creation of format on device occurs w/out error
        device = self.loopDevices[0]

        self.assertFalse(self.fmt.exists)
        self.fmt.device = device
        self.assertIsNone(self.fmt.create())
        self.assertIsNotNone(self.fmt.mapName)
        self.assertTrue(self.fmt.exists)
        self.assertTrue("LUKS" in self.fmt.name)

        # test that the device can be opened once created
        self.assertIsNone(self.fmt.setup())
        self.assertTrue(self.fmt.status)

        # test that the device can be closed again
        self.assertIsNone(self.fmt.teardown())
        self.assertFalse(self.fmt.status)

    def testSize(self):
        """ Test that sizes are calculated correctly. """
        device = self.loopDevices[0]

        # create the device
        self.fmt.device = device
        self.assertIsNone(self.fmt.create())

        # the size is 0
        self.assertEqual(self.fmt.size, Size(0))
        self.assertEqual(self.fmt.currentSize, Size(0))
        self.assertEqual(self.fmt.targetSize, Size(0))

        # open the luks device
        self.assertIsNone(self.fmt.setup())

        # size is unchanged
        self.assertEqual(self.fmt.size, Size(0))
        self.assertEqual(self.fmt.currentSize, Size(0))
        self.assertEqual(self.fmt.targetSize, Size(0))

        # update the size info
        self.fmt.updateSizeInfo()

        # set target size to imitate FS constructor
        self.fmt.targetSize = self.fmt._size

        # the size is greater than zero and less than the size of the device
        self.assertLess(self.fmt.size, self.DEFAULT_STORE_SIZE)
        self.assertGreater(self.fmt.size, Size(0))

        self.assertEqual(self.fmt.currentSize, self.fmt.size)
        self.assertEqual(self.fmt.targetSize, self.fmt.size)

        self.fmt.teardown()

    def testResize(self):
        """ Test that resizing does the correct thing. """
        device = self.loopDevices[0]

        # create the device
        self.fmt.device = device
        self.assertIsNone(self.fmt.create())

        self.fmt.updateSizeInfo()

        newsize = Size("64 MiB")
        self.fmt.targetSize = newsize

        # can not resize an unopened device
        with self.assertRaises(DeviceFormatError):
            self.fmt.resize()

        # open the luks device
        self.assertIsNone(self.fmt.setup())

        # can resize an opened device
        self.fmt.resize()

        # actually looking up the actual size, should yield same
        # as target size.
        self.assertEqual(self.fmt._sizeinfo.doTask(), newsize)

        # device format computed size
        self.assertEqual(self.fmt.size, newsize)
        self.assertEqual(self.fmt.currentSize, newsize)
        self.assertEqual(self.fmt.targetSize, newsize)

        self.fmt.teardown()

    def testResizeBounds(self):
        """ Test resizing outside the bounds of the device.
            Note that the bounds of the device are not the same as the
            bounds of the format.
        """
        device = self.loopDevices[0]

        # create the device
        self.fmt.device = device
        self.assertIsNone(self.fmt.create())

        self.fmt.updateSizeInfo()

        newsize = Size("128 MiB")
        self.fmt.targetSize = newsize

        # open the luks device
        self.assertIsNone(self.fmt.setup())

        # can not resize outside the bounds of the device
        with self.assertRaises(LUKSError):
            self.fmt.resize()

        newsize = Size("96 MiB")
        self.fmt.targetSize = newsize

        # can resize within the bounds of the device
        self.assertIsNone(self.fmt.resize())

        # actually looking up the actual size, should yield same
        # as target size.
        self.assertEqual(self.fmt._sizeinfo.doTask(), newsize)

        # device format computed size
        self.assertEqual(self.fmt.size, newsize)
        self.assertEqual(self.fmt.currentSize, newsize)
        self.assertEqual(self.fmt.targetSize, newsize)

        self.fmt.teardown()
