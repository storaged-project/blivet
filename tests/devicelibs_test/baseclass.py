import unittest
import os
import subprocess


def makeLoopDev(device_name, file_name, num_blocks=102400):
    """ Set up a loop device with a backing store.

        :param str device_name: the path of the loop device
        :param str file_name: the path of the backing file
        :param int num_blocks: the size of file_name in number of blocks
    """
    proc = subprocess.Popen(["dd", "if=/dev/zero", "of=%s" % file_name,
                             "bs=1024", "count=%d" % num_blocks],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("dd failed creating the file %s" % file_name)

    proc = subprocess.Popen(["losetup", device_name, file_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("losetup failed setting up the loop device %s" % device_name)

def removeLoopDev(device_name, file_name):
    proc = subprocess.Popen(["losetup", "-d", device_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        proc.communicate()
        if proc.returncode is not None:
            rc = proc.returncode
            break
    if rc:
        raise OSError("losetup failed removing the loop device %s" % device_name)

    os.unlink(file_name)

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
class DevicelibsTestCase(unittest.TestCase):

    _LOOP_DEVICES = ["/tmp/test-virtdev0", "/tmp/test-virtdev1"]

    def __init__(self, methodName='runTest'):
        unittest.TestCase.__init__(self, methodName=methodName)
        self._loopMap = {}

    def setUp(self):
        for store in self._LOOP_DEVICES:
            dev = getFreeLoopDev()
            makeLoopDev(dev, store)
            self._loopMap[store] = dev

    def tearDown(self):
        for (store, dev) in self._loopMap.iteritems():
            removeLoopDev(dev, store)
