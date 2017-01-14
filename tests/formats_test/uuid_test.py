import unittest

import blivet.formats.fs as fs


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
