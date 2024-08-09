import unittest
from unittest.mock import patch

from blivet.formats.luks import LUKS
from blivet.size import Size
from blivet.static_data import luks_data
from blivet import blockdev


class LUKSNodevTestCase(unittest.TestCase):
    def setUp(self):
        luks_data.pbkdf_args = None

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

    def test_luks2_pbkdf_memory_fips(self):
        fmt = LUKS(passphrase="passphrase")
        with patch("blivet.formats.luks.blockdev.crypto") as bd:
            # fips enabled, pbkdf memory should not be set
            with patch("blivet.formats.luks.crypto") as crypto:
                attrs = {"is_fips_enabled.return_value": True,
                         "get_optimal_luks_sector_size.return_value": 0,
                         "calculate_luks2_max_memory.return_value": Size("256 MiB")}
                crypto.configure_mock(**attrs)

                fmt._create()
                crypto.calculate_luks2_max_memory.assert_not_called()
                self.assertIsNone(bd.luks_format.call_args[1]["extra"])

            # fips disabled, pbkdf memory should be set
            with patch("blivet.formats.luks.crypto") as crypto:
                attrs = {"is_fips_enabled.return_value": False,
                         "get_optimal_luks_sector_size.return_value": 0,
                         "calculate_luks2_max_memory.return_value": Size("256 MiB")}
                crypto.configure_mock(**attrs)

                fmt._create()
                crypto.calculate_luks2_max_memory.assert_called()
                self.assertEqual(bd.luks_format.call_args[1]["extra"].pbkdf.max_memory_kb, 256 * 1024)

    def test_sector_size_luks1(self):
        fmt = LUKS(passphrase="passphrase")
        self.assertEqual(fmt.luks_sector_size, 0)

        # sector size is not valid for luks1
        with self.assertRaises(ValueError):
            fmt = LUKS(luks_version="luks1", luks_sector_size=4096, passphrase="passphrase")

        # just make sure we won't try to add the extra.sector_size argument ourselves
        fmt = LUKS(luks_version="luks1", passphrase="passphrase")
        with patch("blivet.devices.lvm.blockdev.crypto") as crypto:
            fmt._create()
            crypto.luks_format.assert_called()
            self.assertIsNone(crypto.luks_format.call_args[1]["extra"])

    def test_sector_size_luks2(self):
        fmt = LUKS(passphrase="passphrase")
        self.assertEqual(fmt.luks_sector_size, 0)

        fmt = LUKS(luks_version="luks2", luks_sector_size=4096, passphrase="passphrase")
        self.assertEqual(fmt.luks_sector_size, 4096)

        fmt = LUKS(passphrase="passphrase")
        with patch("blivet.devicelibs.crypto.calculate_luks2_max_memory", return_value=None):
            with patch("blivet.devicelibs.crypto.get_optimal_luks_sector_size", return_value=512):
                with patch("blivet.devices.lvm.blockdev.crypto") as crypto:
                    fmt._create()
                    crypto.luks_format.assert_called()
                    self.assertEqual(crypto.luks_format.call_args[1]["extra"].sector_size, 512)

        fmt = LUKS(passphrase="passphrase")
        with patch("blivet.devicelibs.crypto.calculate_luks2_max_memory", return_value=None):
            with patch("blivet.devicelibs.crypto.get_optimal_luks_sector_size", return_value=0):
                with patch("blivet.devices.lvm.blockdev.crypto") as crypto:
                    fmt._create()
                    crypto.luks_format.assert_called()
                    self.assertIsNone(crypto.luks_format.call_args[1]["extra"])

    def test_header_size(self):
        fmt = LUKS(luks_version="luks2")
        self.assertEqual(fmt._header_size, Size("16 MiB"))
        self.assertEqual(fmt._min_size, Size("16 MiB"))

        fmt = LUKS(luks_version="luks1")
        self.assertEqual(fmt._header_size, Size("2 MiB"))
        self.assertEqual(fmt._min_size, Size("2 MiB"))

        # default is luks2
        fmt = LUKS()
        self.assertEqual(fmt._header_size, Size("16 MiB"))
        self.assertEqual(fmt._min_size, Size("16 MiB"))

    def test_luks_opal(self):
        fmt = LUKS(exists=True)
        self.assertFalse(fmt.is_opal)
        self.assertFalse(fmt.protected)

        fmt = LUKS(luks_version="luks2-hw-opal", exists=True)
        self.assertTrue(fmt.is_opal)
        self.assertTrue(fmt.protected)

        fmt = LUKS(luks_version="luks2-hw-opal", passphrase="passphrase", opal_admin_passphrase="passphrase")
        with patch("blivet.devicelibs.crypto.calculate_luks2_max_memory", return_value=None):
            with patch("blivet.devicelibs.crypto.get_optimal_luks_sector_size", return_value=512):
                with patch("blivet.devices.lvm.blockdev.crypto") as crypto:
                    fmt._create()
                    crypto.luks_format.assert_not_called()
                    crypto.opal_format.assert_called()
                    self.assertEqual(crypto.opal_format.call_args[1]["hw_encryption"],
                                     blockdev.CryptoLUKSHWEncryptionType.OPAL_HW_AND_SW)
                    self.assertEqual(crypto.opal_format.call_args[1]["cipher"], "aes-xts-plain64")
                    self.assertEqual(crypto.opal_format.call_args[1]["key_size"], 512)

        fmt = LUKS(luks_version="luks2-hw-opal-only", passphrase="passphrase", opal_admin_passphrase="passphrase")
        with patch("blivet.devicelibs.crypto.calculate_luks2_max_memory", return_value=None):
            with patch("blivet.devicelibs.crypto.get_optimal_luks_sector_size", return_value=512):
                with patch("blivet.devices.lvm.blockdev.crypto") as crypto:
                    fmt._create()
                    crypto.luks_format.assert_not_called()
                    crypto.opal_format.assert_called()
                    self.assertEqual(crypto.opal_format.call_args[1]["hw_encryption"],
                                     blockdev.CryptoLUKSHWEncryptionType.OPAL_HW_ONLY)

                    # cipher and key size are not valid for HW encryption only
                    self.assertEqual(crypto.opal_format.call_args[1]["cipher"], None)
                    self.assertEqual(crypto.opal_format.call_args[1]["key_size"], 0)
