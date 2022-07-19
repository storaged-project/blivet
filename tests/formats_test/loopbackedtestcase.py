import unittest
import os
import subprocess
import tempfile

from blivet.size import Size


def make_store(file_name, num_blocks=102400, block_size=1024):
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


def make_loop_dev(device_name, file_name):
    """ Set up a loop device with a backing store.

        :param str device_name: the path of the loop device
        :param str file_name: the path of the backing file
    """

    proc = subprocess.Popen(["losetup", device_name, file_name, "--partscan"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("losetup failed setting up the loop device %s" % device_name)


def remove_loop_dev(device_name):
    proc = subprocess.Popen(["losetup", "-d", device_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("losetup failed removing the loop device %s" % device_name)


def get_free_loop_dev():
    """ Get the name of the free loop device that losetup reports.

        :returns: the name of the free loop device
        :rtype: str
        :raises OSError: on failure
    """
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

    return out.decode("utf-8")


@unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
class LoopBackedTestCase(unittest.TestCase):

    DEFAULT_BLOCK_SIZE = Size("1 KiB")
    DEFAULT_STORE_SIZE = Size("100 MiB")
    _DEFAULT_DEVICE_SPEC = [DEFAULT_STORE_SIZE, DEFAULT_STORE_SIZE]

    def __init__(self, methodName='run_test', device_spec=None, block_size=None):
        """ LoopBackedTestCase manages loop devices.

            It constructs loop devices according to loop_device_spec,
            sets them up, and tears them down again.

            :param device_spec: list containing the size of each loop device
            :type device_spec: list of Size or NoneType
            :param block_size: block size for dd command when making devices
            :type block_size: Size or NoneType
        """
        unittest.TestCase.__init__(self, methodName=methodName)
        self._device_spec = device_spec or self._DEFAULT_DEVICE_SPEC
        self._loop_map = []
        self.loop_devices = []
        self.block_size = block_size or self.DEFAULT_BLOCK_SIZE

        if any(d % self.block_size != Size(0) for d in self._device_spec):
            raise ValueError("Every device size must be a multiple of the block size.")

    def setUp(self):
        for index, size in enumerate(self._device_spec):
            num_blocks = int(size / self.block_size)
            tmpfile = tempfile.NamedTemporaryFile(suffix="-%d" % index, prefix="test-virtdev-", dir="/var/tmp", delete=False)
            tmpfile.close()

            store = tmpfile.name
            make_store(store, num_blocks, int(self.block_size))

            dev = None
            try:
                dev = get_free_loop_dev()
                make_loop_dev(dev, store)
            except OSError:
                os.unlink(store)
                raise

            self._loop_map.append((dev, store))
            self.loop_devices.append(dev)

        self.addCleanup(self._clean_up)

    def _clean_up(self):
        # Guarantees that every item in _loop_map receives a minimum of
        # three chances to be removed or deleted as appropriate.
        num_tries = 3 * len(self._loop_map)
        for _ in range(num_tries):
            # If worklist is empty, quit
            if not self._loop_map:
                break

            # get worklist item from front
            dev, store = self._loop_map.pop(0)

            # try to clean up dev, store pair
            # if cleanup fails, push pair onto back
            # dev is None if removal has already succeeded
            if dev is not None:
                try:
                    remove_loop_dev(dev)
                    try:
                        os.unlink(store)
                    except OSError:
                        self._loop_map.append((None, store))
                except OSError:
                    self._loop_map.append((dev, store))
