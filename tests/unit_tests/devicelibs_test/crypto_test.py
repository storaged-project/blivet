import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from blivet.devicelibs import crypto
from blivet.errors import LUKSError


class PAESHelpersTestCase(unittest.TestCase):
    def test_cipher(self):
        self.assertTrue(crypto.is_paes_cipher("paes-xts-plain64"))
        for cipher in (None, "", "aes-xts-plain64", "paes", "paes-cbc-plain64"):
            self.assertFalse(crypto.is_paes_cipher(cipher))

    def test_volume_key_context(self):
        with patch.object(crypto.BlockDev, "CryptoKeyslotContext") as constructor:
            context = crypto.KeyslotContext(volume_key=b"\x00\xffsecure-key")
            constructor.assert_called_once_with(volume_key=b"\x00\xffsecure-key")
            self.assertTrue(context.valid)
            self.assertTrue(context.is_volume_key)
            self.assertFalse(context.is_passphrase)
            self.assertFalse(context.is_keyfile)
        with self.assertRaises(ValueError):
            crypto.KeyslotContext(volume_key=b"")

    def test_generate_secure_key(self):
        with patch.object(crypto.BlockDev, "s390", create=True) as s390:
            info = Mock()
            info.name = "test-key"
            s390.zkey_list.return_value = [info]
            self.assertIs(crypto.generate_secure_key("test-key", "CCA-AESCIPHER", 256,
                                                     ["/dev/test:luks-test"], ["01.0001"], 4096, True), info)
            s390.zkey_generate.assert_called_once_with("test-key", "CCA-AESCIPHER", 256,
                                                       ["/dev/test:luks-test"], ["01.0001"], 4096, True, None)
            s390.zkey_list.assert_called_once_with("test-key")
            s390.zkey_list.return_value = []
            with self.assertRaises(LUKSError):
                crypto.generate_secure_key("test-key")
            s390.zkey_remove.assert_called_once_with("test-key")

    def test_read_secure_key(self):
        with tempfile.NamedTemporaryFile() as key:
            key.write(b"\x00\xff\n\x80")
            key.flush()
            self.assertEqual(crypto.read_secure_key(key.name), b"\x00\xff\n\x80")

    def test_find_secure_key(self):
        with patch.object(crypto.BlockDev, "s390", create=True) as s390:
            first = Mock(volumes=["/dev/other:luks-other"])
            second = Mock(volumes=["/dev/test:luks-test", "/dev/another:luks-another"])
            s390.zkey_list.return_value = [Mock(volumes=None), first, second]
            self.assertIs(crypto.find_secure_key_for_volume("/dev/test"), second)
            self.assertIsNone(crypto.find_secure_key_for_volume("/dev/missing"))
            with tempfile.TemporaryDirectory() as directory:
                alias = os.path.join(directory, "alias")
                os.symlink("/dev/test", alias)
                self.assertIs(crypto.find_secure_key_for_volume(alias), second)

    def test_uuid_association(self):
        volume = "/dev/disk/by-uuid/test-uuid:luks-test"
        # No symlink is needed when matching after destruction. A different
        # UUID must not match even if both paths happen to resolve to one node.
        self.assertTrue(crypto.secure_key_volume_matches(volume, "/dev/renumbered", "test-uuid"))
        with patch.object(os.path, "realpath", return_value="/dev/renumbered"):
            self.assertFalse(crypto.secure_key_volume_matches(volume, "/dev/renumbered", "other-uuid"))
        with patch.object(crypto.BlockDev, "s390", create=True) as s390:
            key = Mock(volumes=[volume])
            s390.zkey_list.return_value = [key]
            self.assertIs(crypto.find_secure_key_for_volume("/dev/renumbered", uuid="test-uuid"), key)
            self.assertIsNone(crypto.find_secure_key_for_volume("/dev/renumbered", uuid="other-uuid"))

    def test_change_secure_key_volumes(self):
        with patch.object(crypto, "run_program_and_capture_output", return_value=(0, "")) as run:
            crypto.change_secure_key_volumes("test-key", ["/dev/disk/by-uuid/test:luks-test"])
            run.assert_called_once_with(["zkey", "change", "--name", "test-key", "--volumes",
                                         "/dev/disk/by-uuid/test:luks-test"], stderr_to_stdout=True)
            crypto.change_secure_key_volumes("test-key", ["/dev/test:luks-test", "/dev/alias:alias"], remove=True)
            self.assertEqual(run.call_args.args[0][-1], "-/dev/test:luks-test,/dev/alias:alias")
            run.return_value = (1, "repository unavailable")
            with self.assertRaisesRegex(LUKSError, "repository unavailable"):
                crypto.change_secure_key_volumes("test-key", ["/dev/test:luks-test"])
            run.reset_mock()
            with self.assertRaises(ValueError):
                crypto.change_secure_key_volumes("test-key", [])
            run.assert_not_called()
