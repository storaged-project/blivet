#!/usr/bin/python
import copy
import unittest

import blivet.formats as formats

class FormatsTestCase(unittest.TestCase):

    def setUp(self):
        pass

    def testFormatsMethods(self):
        ##
        ## get_device_format_class
        ##
        format_pairs = {
           None : formats.DeviceFormat,
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
        ## Consecutively constructed DeviceFormat objects have consecutive ids
        names = [key for key in format_pairs.keys() if format_pairs[key] is not None]
        objs = [formats.getFormat(name) for name in names]
        ids = [obj.id for obj in objs]
        self.assertEqual(ids, list(range(ids[0], ids[0] + len(ids))))

        ## Copy or deepcopy should preserve the id
        self.assertEqual(ids, [copy.copy(obj).id for obj in objs])
        self.assertEqual(ids, [copy.deepcopy(obj).id for obj in objs])
