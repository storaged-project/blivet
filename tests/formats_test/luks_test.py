try:
    from unittest.mock import patch
except ImportError:
    from mock import patch

import unittest

from blivet.formats.luks import LUKS

from blivet.size import Size

from tests import loopbackedtestcase


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

    def _luks_close(self):
        self.fmt.teardown()


class LUKSNodevTestCase(unittest.TestCase):
    def test_create_discard_option(self):
        # flags.discard_new=False --> no discard
        fmt = LUKS(exists=False)
        self.assertEqual(fmt.options, None)

        fmt = LUKS(exists=True)
        self.assertEqual(fmt.options, None)

        # flags.discard_new=True --> discard if creating new
        with patch("blivet.flags.flags.discard_new", True):
            fmt = LUKS(exists=True)
            self.assertEqual(fmt.options, None)

            fmt = LUKS(exists=False)
            self.assertEqual(fmt.options, "discard")

            # do not add if already there
            fmt = LUKS(exists=False, options="discard")
            self.assertEqual(fmt.options, "discard")

            # add with comma after other option(s)
            fmt = LUKS(exists=False, options="blah")
            self.assertEqual(fmt.options, "blah,discard")

    def test_key_size(self):
        # default cipher is AES-XTS with 512b key
        fmt = LUKS()
        self.assertEqual(fmt.cipher, "aes-xts-plain64")
        self.assertEqual(fmt.key_size, 512)

        # setting cipher shouldn't change the key size
        fmt = LUKS(cipher="aes-xts-plain64")
        self.assertEqual(fmt.key_size, 512)

        # all XTS mode ciphers should default to 512
        fmt = LUKS(cipher="serpent-xts-plain64")
        self.assertEqual(fmt.key_size, 512)

        # no default for non-XTS modes
        fmt = LUKS(cipher="aes-cbc-plain64")
        self.assertEqual(fmt.key_size, 0)

    def test_sector_size(self):
        fmt = LUKS()
        self.assertEqual(fmt.luks_sector_size, 0)

        with self.assertRaises(ValueError):
            fmt = LUKS(luks_version="luks1", luks_sector_size=4096)

        fmt = LUKS(luks_version="luks2", luks_sector_size=4096)
        self.assertEqual(fmt.luks_sector_size, 4096)
