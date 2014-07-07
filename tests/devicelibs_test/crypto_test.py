#!/usr/bin/python
import unittest

import tempfile
import os

from blivet.devicelibs import crypto
from blivet.errors import CryptoError
from tests import loopbackedtestcase

#FIXME: some of these tests expect behavior which is not correct
#
#The following is a list of the known incorrect behaviors:
# *) The CryptSetup constructor raises an IOError if a device cannot be
# opened. The various luks* methods that use CryptSetup don't catch this
# exception, so they also raise an IOError. These methods should
# all catch and handle the IOError appropriately.
# *) All luks_* methods that take a key_file don't use it and they all raise
# a value error if they do not get a passphrase, even if they get a keyfile.
# This should happen only in the case where flags.installer_mode is True.
# In other cases, the key_file should be used appropriately. The passphrase
# and key_file arguments are mutually exclusive, and this should be handled
# appropriately.
# *) luks_status returns unmassaged int returned by CryptSetup.status,
# not bool as the documentation states. The documentation should be brought
# in line with the code, or vice-veras. It may be that the value returned by
# CryptSetup.status is informative and that it would be useful to preserve it.
# The numeric values are enumerated in libcryptsetup.h.

class CryptoTestCase(loopbackedtestcase.LoopBackedTestCase):

    def testCryptoMisc(self):
        _LOOP_DEV0 = self.loopDevices[0]
        _LOOP_DEV1 = self.loopDevices[1]


        ##
        ## is_luks
        ##
        # pass
        self.assertEqual(crypto.is_luks(_LOOP_DEV0), -22)
        with self.assertRaisesRegexp(IOError, "Device cannot be opened"):
            crypto.is_luks("/not/existing/device")

        ##
        ## luks_format
        ##
        # pass
        self.assertEqual(crypto.luks_format(_LOOP_DEV0, passphrase="secret", cipher="aes-cbc-essiv:sha256", key_size=256), None)
        self.assertEqual(crypto.is_luks(_LOOP_DEV0), 0)

        # make a key file
        handle, keyfile = tempfile.mkstemp(prefix="key", text=False)
        os.write(handle, "nobodyknows")
        os.close(handle)

        # format with key file
        with self.assertRaisesRegexp(ValueError, "requires passphrase"):
            crypto.luks_format(_LOOP_DEV1, key_file=keyfile)

        # fail
        with self.assertRaisesRegexp(IOError, "Device cannot be opened"):
            crypto.luks_format("/not/existing/device", passphrase="secret", cipher="aes-cbc-essiv:sha256", key_size=256)

        # no passhprase or key file
        with self.assertRaisesRegexp(ValueError, "requires passphrase"):
            crypto.luks_format(_LOOP_DEV1, cipher="aes-cbc-essiv:sha256", key_size=256)

        ##
        ## is_luks
        ##
        # pass
        self.assertEqual(crypto.is_luks(_LOOP_DEV0), 0)    # 0 = is luks
        self.assertEqual(crypto.is_luks(_LOOP_DEV1), -22)

        ##
        ## luks_add_key
        ##
        # pass
        self.assertEqual(crypto.luks_add_key(_LOOP_DEV0, new_passphrase="another-secret", passphrase="secret"), None)

        # fail
        with self.assertRaisesRegexp(CryptoError, "luks add key failed"):
            crypto.luks_add_key(_LOOP_DEV0, new_passphrase="another-secret", passphrase="wrong-passphrase")

        ##
        ## luks_remove_key
        ##
        # fail
        with self.assertRaisesRegexp(CryptoError, "luks remove key failed"):
            crypto.luks_remove_key(_LOOP_DEV0, del_passphrase="another-secret", passphrase="wrong-pasphrase")

        # pass
        self.assertEqual(crypto.luks_remove_key(_LOOP_DEV0, del_passphrase="another-secret", passphrase="secret"), None)

        # fail
        with self.assertRaisesRegexp(IOError, "Device cannot be opened"):
            crypto.luks_open("/not/existing/device", "another-crypted", passphrase="secret")

        # no passhprase or key file
        with self.assertRaisesRegexp(ValueError, "luks_format requires passphrase"):
            crypto.luks_open(_LOOP_DEV1, "another-crypted")

        with self.assertRaisesRegexp(IOError, "Device cannot be opened"):
            crypto.luks_status("another-crypted")
        with self.assertRaisesRegexp(IOError, "Device cannot be opened"):
            crypto.luks_close("wrong-name")

        # cleanup
        os.unlink(keyfile)

class CryptoTestCase2(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='runTest'):
        """Set up the names by which luks knows these devices."""
        super(CryptoTestCase2, self).__init__(methodName=methodName)
        self._names = ["crypted", "encrypted"]

    def tearDown(self):
        """Close all devices just in case they are still open."""
        for name in self._names:
            try:
                crypto.luks_close(name)
            except (IOError, CryptoError):
                pass
        super(CryptoTestCase2, self).tearDown()

    def testCryptoOpen(self):
        _LOOP_DEV0 = self.loopDevices[0]
        _LOOP_DEV1 = self.loopDevices[1]

        _name0 = self._names[0]
        _name1 = self._names[1]

        ##
        ## luks_format
        ##
        # pass
        self.assertEqual(crypto.luks_format(_LOOP_DEV0, passphrase="secret", cipher="aes-cbc-essiv:sha256", key_size=256), None)
        self.assertEqual(crypto.luks_format(_LOOP_DEV1, passphrase="hidden", cipher="aes-cbc-essiv:sha256", key_size=256), None)

        ##
        ## luks_open
        ##
        # pass
        self.assertEqual(crypto.luks_open(_LOOP_DEV0, _name0, passphrase="secret"), None)
        self.assertEqual(crypto.luks_open(_LOOP_DEV1, _name1, passphrase="hidden"), None)

        ##
        ## luks_status
        ##
        # pass
        self.assertEqual(crypto.luks_status(_name0), 2)
        self.assertEqual(crypto.luks_status(_name1), 2)

        ##
        ## luks_uuid
        ##
        # pass
        uuid = crypto.luks_uuid(_LOOP_DEV0)
        self.assertEqual(crypto.luks_uuid(_LOOP_DEV0), uuid)
        uuid = crypto.luks_uuid(_LOOP_DEV1)
        self.assertEqual(crypto.luks_uuid(_LOOP_DEV1), uuid)

        ##
        ## luks_close
        ##
        # pass
        self.assertEqual(crypto.luks_close(_name0), None)
        self.assertEqual(crypto.luks_close(_name1), None)

        # already closed
        with self.assertRaisesRegexp(IOError, "Device cannot be opened"):
            crypto.luks_close("crypted")
        with self.assertRaisesRegexp(IOError, "Device cannot be opened"):
            crypto.luks_close("encrypted")

class CryptoTestCase3(unittest.TestCase):
    def testPassphrase(self):
        exp = r"([0-9A-Za-z./]{5}-)*[0-9A-Za-z./]{0,4}"
        bp = crypto.generateBackupPassphrase()
        self.assertRegexpMatches(bp, exp)

if __name__ == "__main__":
    unittest.main()
