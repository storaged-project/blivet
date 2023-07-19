import glob
import os
import re
import shutil
import subprocess
import unittest

from contextlib import contextmanager

from .storagetestcase import create_sparse_tempfile


def read_file(filename, mode="r"):
    with open(filename, mode) as f:
        content = f.read()
    return content


@contextmanager
def udev_settle():
    try:
        yield
    finally:
        os.system("udevadm settle")


def _delete_backstore(name):
    status = subprocess.call(["targetcli", "/backstores/fileio/ delete %s" % name],
                             stdout=subprocess.DEVNULL)
    if status != 0:
        raise RuntimeError("Failed to delete the '%s' fileio backstore" % name)


def delete_iscsi_target(iqn, backstore=None):
    status = subprocess.call(["targetcli", "/iscsi delete %s" % iqn],
                             stdout=subprocess.DEVNULL)
    if status != 0:
        raise RuntimeError("Failed to delete the '%s' iscsi device" % iqn)

    if backstore is not None:
        _delete_backstore(backstore)


def create_iscsi_target(fpath, initiator_name=None):
    """
    Creates a new iSCSI target (using targetcli) on top of the
    :param:`fpath` backing file.

    :param str fpath: path of the backing file
    :returns: iSCSI IQN, backstore name
    :rtype: tuple of str

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

    # create a new iscsi device
    out = subprocess.check_output(["targetcli", "/iscsi create"])
    out = out.decode("utf-8")
    match = re.match(r'Created target (.*).', out)
    if match:
        iqn = match.groups()[0]
    else:
        _delete_backstore(store_name)
        raise RuntimeError("Failed to create a new iscsi target")

    with udev_settle():
        status = subprocess.call(["targetcli", "/iscsi/%s/tpg1/luns create /backstores/fileio/%s" % (iqn, store_name)], stdout=subprocess.DEVNULL)
    if status != 0:
        delete_iscsi_target(iqn, store_name)
        raise RuntimeError("Failed to create a new LUN for '%s' using '%s'" % (iqn, store_name))

    if initiator_name:
        status = subprocess.call(["targetcli", "/iscsi/%s/tpg1/acls create %s" % (iqn, initiator_name)], stdout=subprocess.DEVNULL)
        if status != 0:
            delete_iscsi_target(iqn, store_name)
            raise RuntimeError("Failed to set ACLs for '%s'" % iqn)

    return iqn, store_name


@unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
@unittest.skipUnless(os.environ.get("JENKINS_HOME"), "jenkins only test")
@unittest.skipUnless(shutil.which("iscsiadm"), "iscsiadm not available")
class ISCSITestCase(unittest.TestCase):

    _disk_size = 512 * 1024**2
    initiator = 'iqn.1994-05.com.redhat:iscsi-test'

    def setUp(self):
        self.addCleanup(self._clean_up)

        self._dev_file = None
        self.dev = None

        self._dev_file = create_sparse_tempfile("blivet_test", self._disk_size)
        try:
            self.dev, self.backstore = create_iscsi_target(self._dev_file, self.initiator)
        except RuntimeError as e:
            raise RuntimeError("Failed to setup targetcli device for testing: %s" % e)

    def _force_logout(self):
        subprocess.call(["iscsiadm", "--mode", "node", "--logout", "--name", self.dev], stdout=subprocess.DEVNULL)

    def _clean_up(self):
        self._force_logout()
        delete_iscsi_target(self.dev, self.backstore)
        os.unlink(self._dev_file)

    def test_discover_login(self):
        from blivet.iscsi import iscsi, has_iscsi

        if not has_iscsi() or not iscsi.available:
            self.skipTest("iSCSI not available, skipping")

        # initially set the initiator to the correct/allowed one
        iscsi.initiator = self.initiator
        nodes = iscsi.discover("127.0.0.1")
        self.assertTrue(nodes)

        if len(nodes) > 1:
            self.skipTest("Discovered more than one iSCSI target on localhost, skipping")

        self.assertEqual(nodes[0].address, "127.0.0.1")
        self.assertEqual(nodes[0].port, 3260)
        self.assertEqual(nodes[0].name, self.dev)

        # change the initiator name to a wrong one
        iscsi.initiator = self.initiator + "_1"
        self.assertEqual(iscsi.initiator, self.initiator + "_1")

        # check the change made it to /etc/iscsi/initiatorname.iscsi
        initiator_file = read_file("/etc/iscsi/initiatorname.iscsi").strip()
        self.assertEqual(initiator_file, "InitiatorName=%s" % self.initiator + "_1")

        # try to login (should fail)
        ret, err = iscsi.log_into_node(nodes[0])
        self.assertFalse(ret)
        self.assertIn("authorization failure", err)

        # change the initiator name back to the correct one
        iscsi.initiator = self.initiator
        self.assertEqual(iscsi.initiator, self.initiator)

        # check the change made it to /etc/iscsi/initiatorname.iscsi
        initiator_file = read_file("/etc/iscsi/initiatorname.iscsi").strip()
        self.assertEqual(initiator_file, "InitiatorName=%s" % self.initiator)

        # try to login (should work now)
        ret, err = iscsi.log_into_node(nodes[0])
        self.assertTrue(ret, "Login failed: %s" % err)

        # check the session for initiator name
        sessions = glob.glob("/sys/class/iscsi_session/*/")
        self.assertTrue(sessions)
        self.assertEqual(len(sessions), 1)
        initiator = read_file(sessions[0] + "initiatorname").strip()
        self.assertEqual(initiator, iscsi.initiator)
