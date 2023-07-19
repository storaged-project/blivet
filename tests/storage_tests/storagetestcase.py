
import glob
import os
import re
import subprocess
import time
import tempfile
import unittest

from contextlib import contextmanager


_lio_devs = dict()


@contextmanager
def udev_settle():
    try:
        yield
    finally:
        os.system("udevadm settle")


def umount(what, retry=True):
    try:
        os.system("umount %s >/dev/null 2>&1" % what)
        os.rmdir(what)
    except OSError as e:
        # retry the umount if the device is busy
        if "busy" in str(e) and retry:
            time.sleep(2)
            umount(what, False)


def create_sparse_tempfile(name, size):
    """ Create a temporary sparse file.

        :param str name: suffix for filename
        :param size: the file size (in bytes)
        :returns: the path to the newly created file
    """
    (fd, path) = tempfile.mkstemp(prefix="blivet.", suffix="-%s" % name)
    os.close(fd)
    create_sparse_file(path, size)
    return path


def create_sparse_file(path, size):
    """ Create a sparse file.

        :param str path: the full path to the file
        :param size: the size of the file (in bytes)
        :returns: None
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    os.ftruncate(fd, size)
    os.close(fd)


def _delete_backstore(name):
    status = subprocess.call(["targetcli", "/backstores/fileio/ delete %s" % name],
                             stdout=subprocess.DEVNULL)
    if status != 0:
        raise RuntimeError("Failed to delete the '%s' fileio backstore" % name)


def _delete_target(wwn, backstore=None):
    status = subprocess.call(["targetcli", "/loopback delete %s" % wwn],
                             stdout=subprocess.DEVNULL)
    if status != 0:
        raise RuntimeError("Failed to delete the '%s' loopback device" % wwn)

    if backstore is not None:
        _delete_backstore(backstore)


def _delete_lun(wwn, delete_target=True, backstore=None):
    status = subprocess.call(["targetcli", "/loopback/%s/luns delete lun0" % wwn],
                             stdout=subprocess.DEVNULL)
    if status != 0:
        raise RuntimeError("Failed to delete the '%s' loopback device's lun0" % wwn)
    if delete_target:
        _delete_target(wwn, backstore)


def _get_lio_dev_path(store_wwn, tgt_wwn, store_name, retry=True):
    """Check if the lio device has been really created and is in /dev/disk/by-id"""

    # the backstore's wwn contains '-'s we need to get rid of and then take just
    # the fist 25 characters which participate in the device's ID
    wwn = store_wwn.replace("-", "")
    wwn = wwn[:25]

    globs = glob.glob("/dev/disk/by-id/wwn-*%s" % wwn)
    if len(globs) != 1:
        if retry:
            time.sleep(3)
            os.system("udevadm settle")
            return _get_lio_dev_path(store_wwn, tgt_wwn, store_wwn, False)
        else:
            _delete_target(tgt_wwn, store_name)
            raise RuntimeError("Failed to identify the resulting device for '%s'" % store_name)
    else:
        return os.path.realpath(globs[0])


def create_lio_device(fpath):
    """
    Creates a new LIO loopback device (using targetcli) on top of the
    :param:`fpath` backing file.

    :param str fpath: path of the backing file
    :returns: path of the newly created device (e.g. "/dev/sdb")
    :rtype: str

    """

    # "register" the backing file as a fileio backstore
    store_name = os.path.basename(fpath)
    status = subprocess.call(["targetcli", "/backstores/fileio/ create %s %s" % (store_name, fpath)], stdout=subprocess.DEVNULL)
    if status != 0:
        raise RuntimeError("Failed to register '%s' as a fileio backstore" % fpath)

    out = subprocess.check_output(["targetcli", "/backstores/fileio/%s info" % store_name])
    out = out.decode("utf-8")
    store_wwn = None
    for line in out.splitlines():
        if line.startswith("wwn: "):
            store_wwn = line[5:]
    if store_wwn is None:
        raise RuntimeError("Failed to determine '%s' backstore's wwn" % store_name)

    # set the optimal alignment because the default is weird and our
    # partitioning tests expect 2048
    status = subprocess.call(["targetcli", "/backstores/fileio/%s set attribute optimal_sectors=2048" % store_name], stdout=subprocess.DEVNULL)
    if status != 0:
        raise RuntimeError("Failed to set optimal alignment for '%s'" % store_name)

    # create a new loopback device
    out = subprocess.check_output(["targetcli", "/loopback create"])
    out = out.decode("utf-8")
    match = re.match(r'Created target (.*).', out)
    if match:
        tgt_wwn = match.groups()[0]
    else:
        _delete_backstore(store_name)
        raise RuntimeError("Failed to create a new loopback device")

    with udev_settle():
        status = subprocess.call(["targetcli", "/loopback/%s/luns create /backstores/fileio/%s" % (tgt_wwn, store_name)], stdout=subprocess.DEVNULL)
    if status != 0:
        _delete_target(tgt_wwn, store_name)
        raise RuntimeError("Failed to create a new LUN for '%s' using '%s'" % (tgt_wwn, store_name))

    dev_path = _get_lio_dev_path(store_wwn, tgt_wwn, store_name)

    _lio_devs[dev_path] = (tgt_wwn, store_name)
    return dev_path


def delete_lio_device(dev_path):
    """
    Delete a previously setup/created LIO device

    :param str dev_path: path of the device to delete

    """
    if dev_path in _lio_devs:
        wwn, store_name = _lio_devs[dev_path]
        _delete_lun(wwn, True, store_name)
    else:
        raise RuntimeError("Unknown device '%s'" % dev_path)


@unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
class StorageTestCase(unittest.TestCase):

    _disk_size = 2 * 1024**3

    def setUp(self):
        self.addCleanup(self._clean_up)

        self.vdevs = []
        self._dev_files = []

        for _ in range(2):
            dev_file = create_sparse_tempfile("blivet_test", self._disk_size)
            self._dev_files.append(dev_file)
            try:
                dev = create_lio_device(dev_file)
                self.vdevs.append(dev)
            except RuntimeError as e:
                raise RuntimeError("Failed to setup targetcli device for testing: %s" % e)

    def _clean_up(self):
        for dev in self.vdevs:
            try:
                delete_lio_device(dev)
            except RuntimeError:
                # just move on, we can do no better here
                pass

        for dev_file in self._dev_files:
            os.unlink(dev_file)
