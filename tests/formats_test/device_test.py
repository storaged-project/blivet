import unittest

import blivet


class DeviceFormatTestCase(unittest.TestCase):

    def test_formats(self):
        absolute_path = "/abs/path"
        host_path = "host:path"
        garbage = "abc#<def>"
        for fclass in blivet.formats.device_formats.values():
            an_fs = fclass()

            # all formats accept None for device
            try:
                an_fs.device = None
            except ValueError:
                raise self.failureException("ValueError raised")

            # NoDevFS accepts anything
            if isinstance(an_fs, blivet.formats.fs.NoDevFS):
                try:
                    an_fs.device = absolute_path
                    an_fs.device = host_path
                    an_fs.device = garbage
                    an_fs.device = ""
                except ValueError:
                    raise self.failureException("ValueError raised")
            elif isinstance(an_fs, blivet.formats.fs.NFS):
                try:
                    an_fs.device = host_path
                except ValueError:
                    raise self.failureException("ValueError raised")

                with self.assertRaises(ValueError):
                    an_fs.device = absolute_path
                with self.assertRaises(ValueError):
                    an_fs.device = garbage
                with self.assertRaises(ValueError):
                    an_fs.device = ""
            else:
                try:
                    an_fs.device = absolute_path
                    an_fs.device = ""
                except ValueError:
                    raise self.failureException("ValueError raised")

                with self.assertRaises(ValueError):
                    an_fs.device = host_path
                with self.assertRaises(ValueError):
                    an_fs.device = garbage


class DeviceValueTestCase(unittest.TestCase):

    def test_value(self):
        for fclass in blivet.formats.device_formats.values():
            an_fs = fclass()

            if isinstance(an_fs, blivet.formats.fs.TmpFS):
                # type == device == _type == _device == "tmpfs" always
                vals = [an_fs.type, an_fs.device, an_fs._type, an_fs._device]
                self.assertTrue(all(x == "tmpfs" for x in vals))
                an_fs.device = "new"
                self.assertTrue(all(x == "tmpfs" for x in vals))
            elif isinstance(an_fs, blivet.formats.fs.NoDevFS):
                # type == device == _type == _device
                vals = [an_fs.type, an_fs.device, an_fs._device]
                self.assertTrue(all(x == an_fs._type for x in vals))
                an_fs.device = "new"
                # _type is unchanged, but type, device, _device have new value
                self.assertNotEqual(an_fs._type, "new")
                vals = [an_fs.type, an_fs.device, an_fs._device]
                self.assertTrue(all(x == "new" for x in vals))
            else:
                # other formats are straightforward
                typ = an_fs.type
                an_fs.device = "/abc:/def"
                self.assertEqual(an_fs.type, typ)
                self.assertEqual(an_fs.device, "/abc:/def")
