#!/usr/bin/python
import unittest

import tempfile
import os

from tests.devicelibs_test import baseclass

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

class CryptoTestCase(baseclass.DevicelibsTestCase):

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCryptoMisc(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        import blivet.devicelibs.crypto as crypto

        ##
        ## is_luks
        ##
        # pass
        self.assertEqual(crypto.is_luks(_LOOP_DEV0), -22)
        self.assertRaisesRegexp(IOError,
            "Device cannot be opened",
            crypto.is_luks,
            "/not/existing/device")

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
        self.assertRaisesRegexp(ValueError,
           "requires passphrase",
           crypto.luks_format,
           _LOOP_DEV1, key_file=keyfile)

        # fail
        self.assertRaisesRegexp(IOError,
           "Device cannot be opened",
           crypto.luks_format,
           "/not/existing/device", passphrase="secret", cipher="aes-cbc-essiv:sha256", key_size=256)

        # no passhprase or key file
        self.assertRaisesRegexp(ValueError,
           "requires passphrase",
           crypto.luks_format,
           _LOOP_DEV1, cipher="aes-cbc-essiv:sha256", key_size=256)

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
        self.assertRaisesRegexp(crypto.CryptoError,
           "luks add key failed",
           crypto.luks_add_key,
           _LOOP_DEV0, new_passphrase="another-secret", passphrase="wrong-passphrase")

        ##
        ## luks_remove_key
        ##
        # fail
        self.assertRaisesRegexp(crypto.CryptoError,
           "luks remove key failed",
           crypto.luks_remove_key,
           _LOOP_DEV0, del_passphrase="another-secret", passphrase="wrong-pasphrase")

        # pass
        self.assertEqual(crypto.luks_remove_key(_LOOP_DEV0, del_passphrase="another-secret", passphrase="secret"), None)

        # fail
        self.assertRaisesRegexp(IOError,
           "Device cannot be opened",
           crypto.luks_open,
           "/not/existing/device", "another-crypted", passphrase="secret")

        # no passhprase or key file
        self.assertRaisesRegexp(ValueError,
           "luks_format requires passphrase",
           crypto.luks_open,
           _LOOP_DEV1, "another-crypted")

        self.assertRaisesRegexp(IOError,
           "Device cannot be opened",
           crypto.luks_status,
           "another-crypted")
        self.assertRaisesRegexp(IOError,
           "Device cannot be opened",
           crypto.luks_close,
           "wrong-name")

        # cleanup
        os.unlink(keyfile)

class CryptoTestCase2(baseclass.DevicelibsTestCase):

    def __init__(self, *args, **kwargs):
        """Set up the names by which luks knows these devices."""
        super(CryptoTestCase2, self).__init__(*args, **kwargs)
        self._names = { self._LOOP_DEVICES[0]: "crypted",
           self._LOOP_DEVICES[1]: "encrypted" }

    def tearDown(self):
        """Close all devices just in case they are still open."""
        import blivet.devicelibs.crypto as crypto
        for name in self._names.values():
            try:
                crypto.luks_close(name)
            except (IOError, crypto.CryptoError):
                pass
        super(CryptoTestCase2, self).tearDown()

    @unittest.skipUnless(os.geteuid() == 0, "requires root privileges")
    def testCryptoOpen(self):
        _LOOP_DEV0 = self._loopMap[self._LOOP_DEVICES[0]]
        _LOOP_DEV1 = self._loopMap[self._LOOP_DEVICES[1]]

        _name0 = self._names[self._LOOP_DEVICES[0]]
        _name1 = self._names[self._LOOP_DEVICES[1]]

        import blivet.devicelibs.crypto as crypto

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
        self.assertRaisesRegexp(IOError,
           "Device cannot be opened",
           crypto.luks_close,
           "crypted")
        self.assertRaisesRegexp(IOError,
           "Device cannot be opened",
           crypto.luks_close,
           "encrypted")

def suite():
    return unittest.TestLoader().loadTestsFromTestCase(CryptoTestCase)


if __name__ == "__main__":
    unittest.main()
