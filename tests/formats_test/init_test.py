#!/usr/bin/python
import unittest

import blivet.formats as formats
import blivet.errors as errors

class FormatsTestCase(unittest.TestCase):

    def setUp(self):
        pass

    def testFormatsMethods(self):
        ##
        ## get_device_format_class
        ##
        format_pairs = {
           None : None,
           "bogus" : None,
           "biosboot" : formats.biosboot.BIOSBoot,
           "BIOS Boot" : formats.biosboot.BIOSBoot,
           "nodev" : formats.fs.NoDevFS
           }
        format_names = format_pairs.keys()
        format_values = [format_pairs[k] for k in format_names]

        self.assertEqual(
           [formats.get_device_format_class(x) for x in format_names],
           format_values)

        ## A DeviceFormat object is returned if lookup by name fails
        for name in format_names:
            self.assertIs(formats.getFormat(name).__class__,
               formats.DeviceFormat if format_pairs[name] is None else format_pairs[name])
        ## Consecutively constructed DeviceFormat object have consecutive ids
        names = [key for key in format_pairs.keys() if format_pairs[key] is not None]
        ids = [formats.getFormat(name).object_id for name in names]
        self.assertEqual(ids, range(ids[0], ids[0] + len(ids)))

def suite():
    return unittest.TestLoader().loadTestsFromTestCase(FormatsTestCase)
