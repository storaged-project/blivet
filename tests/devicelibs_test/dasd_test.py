#!/usr/bin/python
import unittest

import blivet.devicelibs.dasd as dasd

class SanitizeTest(unittest.TestCase):

    def testSanitize(self):
        with self.assertRaises(ValueError):
            dasd.sanitize_dasd_dev_input("")

        # without a ., the whole value is assumed to be the device number
        # and a bus number is prepended
        dev = "1234abc"
        self.assertEqual(dasd.sanitize_dasd_dev_input(dev), '0.0.' + dev)

        # whatever is on the left side of the rightmost period is assumed to
        # be the bus number
        dev = "zed.1234abq"
        self.assertEqual(dasd.sanitize_dasd_dev_input(dev), dev)

        # the device number is padded on the left with 0s up to 4 digits
        dev = "zed.abc"
        self.assertEqual(dasd.sanitize_dasd_dev_input(dev), "zed.0abc")
        dev = "abc"
        self.assertEqual(dasd.sanitize_dasd_dev_input(dev), "0.0.0abc")
        dev = ".abc"
        self.assertEqual(dasd.sanitize_dasd_dev_input(dev), "0.0.0abc")

        # a complete number is unchanged
        dev = "0.0.abcd"
        self.assertEqual(dasd.sanitize_dasd_dev_input(dev), dev)
