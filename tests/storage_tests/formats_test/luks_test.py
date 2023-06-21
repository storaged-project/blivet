import os
import tempfile
import unittest

from blivet.formats.luks import LUKS, Integrity
from blivet.devicelibs import crypto
from blivet.errors import LUKSError
from blivet.size import Size

from . import loopbackedtestcase


class LUKSTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(LUKSTestCase, self).__init__(methodName=methodName, device_spec=[Size("100 MiB")])
        self.fmt = LUKS(passphrase="password")

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
        self.fmt.passphrase = "password"
        self.fmt.remove_passphrase()

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

            # create the luks format with both passphrase and keyfile
            self.fmt._key_file = temp.name
            self.fmt.create()

            # open first with just password
            self.fmt._key_file = None
            self.fmt.setup()
            self.fmt.teardown()

            # now with keyfile
            self.fmt._key_file = temp.name
            self.fmt.passphrase = None
            self.fmt.setup()
            self.fmt.teardown()

    def _luks_close(self):
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
