import os
import tempfile
import unittest

import blivet
from blivet.formats.luks import LUKS, Integrity
from blivet.devicelibs import crypto
from blivet.errors import LUKSError
from blivet.size import Size
import blivet.static_data

from . import loopbackedtestcase
from ..storagetestcase import StorageTestCase


class LUKSTestCase(loopbackedtestcase.LoopBackedTestCase):

    version = None

    def __init__(self, methodName='run_test'):
        super().__init__(methodName=methodName, device_spec=[Size("100 MiB")])
        self.fmt = LUKS(passphrase="password", luks_version=self.version)

    def test_size(self):
        self.fmt.device = self.loop_devices[0]

        # create and open the luks format
        self.fmt.create()
        self.fmt.setup()
        self.addCleanup(self._luks_close)

        # without update_size_info size should be 0
        self.assertEqual(self.fmt.current_size, Size(0))

        # get current size
        self.fmt.update_size_info()
        self.assertGreater(self.fmt.current_size, Size(0))

    def test_resize(self):
        self.fmt.device = self.loop_devices[0]

        # create and open the luks format
        self.fmt.create()
        self.fmt.setup()
        self.addCleanup(self._luks_close)

        # get current size to make format resizable
        self.assertFalse(self.fmt.resizable)
        self.fmt.update_size_info()
        self.assertTrue(self.fmt.resizable)

        # resize the format
        new_size = Size("50 MiB")
        self.fmt.target_size = new_size
        self.fmt.do_resize()

        # get current size
        self.fmt.update_size_info()
        self.assertEqual(self.fmt.current_size, new_size)

    def test_map_name(self):
        self.fmt.device = self.loop_devices[0]

        # create and open the luks format
        self.fmt.create()
        self.fmt.setup()
        self.addCleanup(self._luks_close)

        self.assertEqual(self.fmt.map_name, "luks-%s" % self.fmt.uuid)
        self.assertTrue(self.fmt.status)

        self.fmt.teardown()
        self.assertFalse(self.fmt.status)

    def test_add_remove_passphrase(self):
        self.fmt.device = self.loop_devices[0]

        # create the luks format
        self.fmt.create()

        # add a new passphrase
        self.fmt.add_passphrase("password2")

        # we should now be able to setup the format using this passphrase
        self.fmt.passphrase = "password2"
        self.fmt.setup()
        self.fmt.teardown()

        # remove the original passphrase
        self.fmt.remove_passphrase("password")
        self.fmt.passphrase = None

        # now setup should fail
        with self.assertRaises(LUKSError):
            self.fmt.setup()

        # setup with the new passphrase should still be possible
        self.fmt.passphrase = "password2"
        self.fmt.setup()
        self.fmt.teardown()

    def test_setup_keyfile(self):
        self.fmt.device = self.loop_devices[0]

        with tempfile.NamedTemporaryFile(prefix="blivet_test") as temp:
            temp.write(b"password2")
            temp.flush()

            # create the luks format with both passphrase and keyfile
            self.fmt.key_file = temp.name
            self.fmt.create()

            # open first with just password
            self.fmt.key_file = None
            self.fmt.setup()
            self.fmt.teardown()

            # now with keyfile
            self.fmt.key_file = temp.name
            self.fmt.passphrase = None
            self.fmt.setup()
            self.fmt.teardown()

    def _luks_close(self):
        self.fmt.teardown()


class LUKSTestCaseLUKS1(LUKSTestCase):
    version = "luks1"


class LUKSTestCaseLUKS2(LUKSTestCase):
    version = "luks2"


# prevent unittest from running the "abstract" test case
del LUKSTestCase


class LUKSContextTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(LUKSContextTestCase, self).__init__(methodName=methodName, device_spec=[Size("100 MiB")])

    def setUp(self):
        super().setUp()
        self.fmt = LUKS()
        self.fmt.device = self.loop_devices[0]

    def _clean_up(self):
        self.fmt.teardown()
        super()._clean_up()

    def test_passphrase_context(self):
        self.assertFalse(self.fmt.has_key)

        self.fmt.contexts.add_passphrase("passphrase")
        self.assertTrue(self.fmt.has_key)

        self.fmt.create()
        self.fmt.setup()

    def test_keyfile_context(self):
        self.assertFalse(self.fmt.has_key)

        self.fmt.contexts.add_keyfile("/non/existing")
        self.assertFalse(self.fmt.has_key)

        self.fmt.contexts.clear_contexts()

        with tempfile.NamedTemporaryFile(prefix="blivet_test") as temp:
            temp.write(b"password2")
            temp.flush()

            # create the luks format with both passphrase and keyfile
            self.fmt.contexts.add_keyfile(temp.name)
            self.assertTrue(self.fmt.has_key)
            self.fmt.create()

            self.fmt.setup()
            self.fmt.teardown()

    def test_multiple_contexts(self):
        self.fmt.contexts.add_passphrase("passphrase")
        self.fmt.contexts.add_passphrase("passphrase1")

        with tempfile.NamedTemporaryFile(prefix="blivet_test") as temp:
            temp.write(b"password2")
            temp.flush()

            # create the luks format with both passphrase and keyfile
            self.fmt.contexts.add_keyfile(temp.name)
            self.fmt.create()

            # we should now have three key slots, lets test one by one
            self.fmt.contexts.clear_contexts()

            # first passphrase
            self.fmt.contexts.clear_contexts()
            self.fmt.contexts.add_passphrase("passphrase")
            self.fmt.setup()
            self.fmt.teardown()

            # second passphrase
            self.fmt.contexts.clear_contexts()
            self.fmt.contexts.add_passphrase("passphrase1")
            self.fmt.setup()
            self.fmt.teardown()

            # keyfile
            self.fmt.contexts.clear_contexts()
            self.fmt.contexts.add_keyfile(temp.name)
            self.fmt.setup()
            self.fmt.teardown()

    def test_add_remove_context(self):
        self.fmt.contexts.add_passphrase("passphrase")
        self.fmt.create()

        # add new passphrase and test it
        self.fmt.add_key(crypto.KeyslotContext(passphrase="passphrase1"))
        self.fmt.contexts.clear_contexts()
        self.fmt.contexts.add_passphrase("passphrase1")
        self.fmt.setup()
        self.fmt.teardown()

        # remove the passphrase and test that the old one can still be used
        self.fmt.remove_key(crypto.KeyslotContext(passphrase="passphrase1"))
        self.fmt.contexts.clear_contexts()
        self.fmt.contexts.add_passphrase("passphrase1")

        # removed passphrase should no longer be usable
        with self.assertRaises(LUKSError):
            self.fmt.setup()

        self.fmt.contexts.clear_contexts()
        self.fmt.contexts.add_passphrase("passphrase")
        self.fmt.setup()
        self.fmt.teardown()


@unittest.skipUnless(Integrity._plugin.available, "Integrity support not available")
class IntegrityTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(IntegrityTestCase, self).__init__(methodName=methodName, device_spec=[Size("100 MiB")])

    def test_integrity(self):
        fmt = Integrity(device=self.loop_devices[0])
        self.assertEqual(fmt.algorithm, crypto.DEFAULT_INTEGRITY_ALGORITHM)

        # create and open the integrity format
        fmt.create()
        fmt.setup()
        self.assertTrue(fmt.status)
        self.assertTrue(os.path.exists("/dev/mapper/%s" % fmt.map_name))

        fmt.teardown()
        self.assertFalse(fmt.status)
        self.assertFalse(os.path.exists("/dev/mapper/%s" % fmt.map_name))


class LUKSResetTestCase(StorageTestCase):

    _num_disks = 1

    def setUp(self):
        super().setUp()

        disks = [os.path.basename(vdev) for vdev in self.vdevs]
        self.storage = blivet.Blivet()
        self.storage.exclusive_disks = disks
        self.storage.reset()

        # make sure only the targetcli disks are in the devicetree
        for disk in self.storage.disks:
            self.assertTrue(disk.path in self.vdevs)
            self.assertIsNone(disk.format.type)
            self.assertFalse(disk.children)

    def _clean_up(self):
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        return super()._clean_up()

    def test_luks_save_passphrase(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        fmt = LUKS(passphrase="password")
        self.storage.format_device(disk, fmt)
        self.storage.do_it()

        blivet.static_data.luks_data.save_passphrase(disk)
        self.storage.devicetree.populate()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.assertTrue(disk.format.has_key)
