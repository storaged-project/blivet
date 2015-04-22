import unittest2 as unittest
import os
import random
import subprocess

from blivet.size import Size

def makeStore(file_name, num_blocks=102400, block_size=1024):
    """ Set up the backing store for a loop device.

        :param str file_name: the path of the backing file
        :param int num_blocks: the size of file_name in number of blocks
        :param int block_size: the number of bytes in a block
    """
    proc = subprocess.Popen(["dd", "if=/dev/zero", "of=%s" % file_name,
                             "bs=%d" % block_size, "count=%d" % num_blocks],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("dd failed creating the file %s" % file_name)

def makeLoopDev(device_name, file_name):
    """ Set up a loop device with a backing store.

        :param str device_name: the path of the loop device
        :param str file_name: the path of the backing file
    """

    proc = subprocess.Popen(["losetup", device_name, file_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("losetup failed setting up the loop device %s" % device_name)

def removeLoopDev(device_name):
    proc = subprocess.Popen(["losetup", "-d", device_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("losetup failed removing the loop device %s" % device_name)

def getFreeLoopDev():
    # There's a race condition here where another process could grab the loop
    # device losetup gives us before we have time to set it up, but that's just
    # a chance we'll have to take.
    proc = subprocess.Popen(["losetup", "-f"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = None

    while True:
        (out, _err) = proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            out = out.strip()
            break

    if rc:
        raise OSError("losetup failed to find a free device")

    return out

@unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
class LoopBackedTestCase(unittest.TestCase):

    DEFAULT_BLOCK_SIZE = Size("1 KiB")
    DEFAULT_STORE_SIZE = Size("100 MiB")
    _DEFAULT_DEVICE_SPEC = [DEFAULT_STORE_SIZE, DEFAULT_STORE_SIZE]
    _STORE_FILE_TEMPLATE = 'test-virtdev%d-%s'
    _STORE_FILE_PATH = '/var/tmp'

    def __init__(self, methodName='runTest', deviceSpec=None, block_size=None):
        """ DevicelibsTestCase manages loop devices.

            It constructs loop devices according to loopDeviceSpec,
            sets them up, and tears them down again.

            :param deviceSpec: list containing the size of each loop device
            :type deviceSpec: list of Size or NoneType
            :param block_size: block size for dd command when making devices
            :type block_size: Size or NoneType
        """
        unittest.TestCase.__init__(self, methodName=methodName)
        self._deviceSpec = deviceSpec or self._DEFAULT_DEVICE_SPEC
        self._loopMap = []
        self.loopDevices = []
        self.block_size = block_size or self.DEFAULT_BLOCK_SIZE

        if any(d % self.block_size != Size(0) for d in self._deviceSpec):
            raise ValueError("Every device size must be a multiple of the block size.")

    def setUp(self):
        random_str = '%06x' % random.randrange(16**6)
        for index, size in enumerate(self._deviceSpec):
            store = os.path.join(self._STORE_FILE_PATH, self._STORE_FILE_TEMPLATE % (index, random_str))
            num_blocks = int(size / self.block_size)
            makeStore(store, num_blocks, int(self.block_size))

            dev = None
            try:
                dev = getFreeLoopDev()
                makeLoopDev(dev, store)
            except OSError:
                os.unlink(store)
                raise

            self._loopMap.append((dev, store))
            self.loopDevices.append(dev)

    def tearDown(self):
        l = len(self._loopMap)
        for _ in range(3 * l):
            if not self._loopMap:
                break
            dev, store = self._loopMap.pop(0)
            try:
                removeLoopDev(dev)
                os.unlink(store)
            except OSError:
                self._loopMap.append((dev, store))
