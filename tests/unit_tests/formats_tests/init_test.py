import copy
import unittest

import blivet.formats as formats


class FormatsTestCase(unittest.TestCase):

    def test_formats_methods(self):
        ##
        # get_device_format_class
        ##
        format_pairs = {
            None: formats.DeviceFormat,
            "bogus": None,
            "biosboot": formats.biosboot.BIOSBoot,
            "BIOS Boot": formats.biosboot.BIOSBoot,
            "nodev": formats.fs.NoDevFS
        }
        format_names = format_pairs.keys()
        format_values = [format_pairs[k] for k in format_names]

        self.assertEqual(
            [formats.get_device_format_class(x) for x in format_names],
            format_values)

        # A DeviceFormat object is returned if lookup by name fails
        for name in format_names:
            self.assertIs(formats.get_format(name).__class__,
                          formats.DeviceFormat if format_pairs[name] is None else format_pairs[name])
        # Consecutively constructed DeviceFormat objects have consecutive ids
        names = [key for key in format_pairs.keys() if format_pairs[key] is not None]
        objs = [formats.get_format(name) for name in names]
        ids = [obj.id for obj in objs]
        self.assertEqual(ids, list(range(ids[0], ids[0] + len(ids))))

        # Copy or deepcopy should preserve the id
        self.assertEqual(ids, [copy.copy(obj).id for obj in objs])
        self.assertEqual(ids, [copy.deepcopy(obj).id for obj in objs])


class InitializationTestCase(unittest.TestCase):

    """Test FS object initialization."""

    def test_labels(self):
        """Initialize some filesystems with valid and invalid labels."""

        # Ext2FS has a maximum length of 16
        self.assertFalse(formats.fs.Ext2FS().label_format_ok("root___filesystem"))
        self.assertTrue(formats.fs.Ext2FS().label_format_ok("root__filesystem"))

        # FATFS has a maximum length of 11
        self.assertFalse(formats.fs.FATFS().label_format_ok("rtfilesystem"))
        self.assertTrue(formats.fs.FATFS().label_format_ok("rfilesystem"))

        # XFS has a maximum length 12 and does not allow spaces
        self.assertFalse(formats.fs.XFS().label_format_ok("root_filesyst"))
        self.assertFalse(formats.fs.XFS().label_format_ok("root file"))
        self.assertTrue(formats.fs.XFS().label_format_ok("root_filesys"))

        # HFSPlus has a maximum length of 128, minimum length of 1, and does not allow colons
        self.assertFalse(formats.fs.HFSPlus().label_format_ok("n" * 129))
        self.assertFalse(formats.fs.HFSPlus().label_format_ok("root:file"))
        self.assertFalse(formats.fs.HFSPlus().label_format_ok(""))
        self.assertTrue(formats.fs.HFSPlus().label_format_ok("n" * 128))

        # NTFS has a maximum length of 128
        self.assertFalse(formats.fs.NTFS().label_format_ok("n" * 129))
        self.assertTrue(formats.fs.NTFS().label_format_ok("n" * 128))

        # GFS2 has special format: two parts, limited lengths and characters
        self.assertFalse(formats.fs.GFS2().label_format_ok("label"))
        self.assertFalse(formats.fs.GFS2().label_format_ok("label:label:label"))
        self.assertFalse(formats.fs.GFS2().label_format_ok("n" * 33 + ":label"))
        self.assertFalse(formats.fs.GFS2().label_format_ok("label:" + "n" * 31))
        self.assertFalse(formats.fs.GFS2().label_format_ok("label:label*"))
        self.assertTrue(formats.fs.GFS2().label_format_ok("label:label"))

        # all devices are permitted to be passed a label argument of None
        # some will ignore it completely
        for _k, v in formats.device_formats.items():
            self.assertIsNotNone(v(label=None))
