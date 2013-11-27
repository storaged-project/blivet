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
           None : formats.DeviceFormat,
           "bogus" : formats.DeviceFormat,
           "biosboot" : formats.biosboot.BIOSBoot,
           "BIOS Boot" : formats.biosboot.BIOSBoot,
           "nodev" : formats.fs.NoDevFS
           }
        format_names = format_pairs.keys()
        format_values = [format_pairs[k] for k in format_names]

        self.assertEqual(
           [formats.get_device_format_class(x) for x in format_names],
           format_values)

        for name in format_names:
            self.assertIs(formats.getFormat(name).__class__, format_pairs[name])

def suite():
    return unittest.TestLoader().loadTestsFromTestCase(FormatsTestCase)
