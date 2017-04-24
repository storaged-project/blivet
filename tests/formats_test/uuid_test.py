import unittest

import blivet.formats.fs as fs
import blivet.formats.swap as swap

from . import fsuuid


class InitializationTestCase(unittest.TestCase):

    """Test FS object initialization."""

    def test_uuids(self):
        """Initialize some filesystems with valid and invalid UUIDs."""

        # File systems that accept real UUIDs (RFC 4122)
        for fscls in [fs.Ext2FS, fs.JFS, fs.ReiserFS, fs.XFS, fs.HFSPlus]:
            uuid = "0invalid-uuid-with-righ-tlength00000"
            self.assertFalse(fscls().uuid_format_ok(uuid))
            uuid = "01234567-12341234123401234567891a"
            self.assertFalse(fscls().uuid_format_ok(uuid))
            uuid = "0123456-123-123-123-01234567891"
            self.assertFalse(fscls().uuid_format_ok(uuid))
            uuid = "01234567-xyz-1234-1234-1234-012345678911"
            self.assertFalse(fscls().uuid_format_ok(uuid))
            uuid = "01234567-1234-1234-1234-012345678911"
            self.assertTrue(fscls().uuid_format_ok(uuid))

        self.assertFalse(fs.FATFS().uuid_format_ok("1234-56789"))
        self.assertFalse(fs.FATFS().uuid_format_ok("abcd-ef00"))
        self.assertFalse(fs.FATFS().uuid_format_ok("12345678"))
        self.assertTrue(fs.FATFS().uuid_format_ok("1234-5678"))
        self.assertTrue(fs.FATFS().uuid_format_ok("ABCD-EF01"))

        self.assertFalse(fs.NTFS().uuid_format_ok("12345678901234567"))
        self.assertFalse(fs.NTFS().uuid_format_ok("abcdefgh"))
        self.assertFalse(fs.NTFS().uuid_format_ok("abcdefabcdefabcd"))
        self.assertTrue(fs.NTFS().uuid_format_ok("1234567890123456"))
        self.assertTrue(fs.NTFS().uuid_format_ok("ABCDEFABCDEFABCD"))


class XFSTestCase(fsuuid.SetUUIDWithMkFs):
    _fs_class = fs.XFS
    _invalid_uuid = "abcdefgh-ijkl-mnop-qrst-uvwxyz123456"
    _valid_uuid = "97e3d40f-dca8-497d-8b86-92f257402465"


class FATFSTestCase(fsuuid.SetUUIDWithMkFs):
    _fs_class = fs.FATFS
    _invalid_uuid = "c87ab0e1"
    _valid_uuid = "DEAD-BEEF"


class Ext2FSTestCase(fsuuid.SetUUIDWithMkFs):
    _fs_class = fs.Ext2FS
    _invalid_uuid = "abcdefgh-ijkl-mnop-qrst-uvwxyz123456"
    _valid_uuid = "bad19a10-075a-4e99-8922-e4638722a567"


class JFSTestCase(fsuuid.SetUUIDAfterMkFs):
    _fs_class = fs.JFS
    _invalid_uuid = "abcdefgh-ijkl-mnop-qrst-uvwxyz123456"
    _valid_uuid = "ac54f987-b371-45d9-8846-7d6204081e5c"


class ReiserFSTestCase(fsuuid.SetUUIDWithMkFs):
    _fs_class = fs.ReiserFS
    _invalid_uuid = "abcdefgh-ijkl-mnop-qrst-uvwxyz123456"
    _valid_uuid = "1761023e-bab8-4919-a2cb-f26c89fe1cfe"


class HFSPlusTestCase(fsuuid.SetUUIDAfterMkFs):
    _fs_class = fs.HFSPlus
    _invalid_uuid = "abcdefgh-ijkl-mnop-qrst-uvwxyz123456"
    _valid_uuid = "3e6d84ce-cca9-4f55-9950-59e5b31f0e36"


class NTFSTestCase(fsuuid.SetUUIDAfterMkFs):
    _fs_class = fs.NTFS
    _invalid_uuid = "b22193477ac947fb"
    _valid_uuid = "BC3B34461B8344A6"


class SwapSpaceTestCase(fsuuid.SetUUIDWithMkFs):
    _fs_class = swap.SwapSpace
    _invalid_uuid = "abcdefgh-ijkl-mnop-qrst-uvwxyz123456"
    _valid_uuid = "01234567-1234-1234-1234-012345678912"
