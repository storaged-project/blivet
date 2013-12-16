#!/usr/bin/python
#
# tests/storage/size_tests.py
# Size test cases for the blivet module
#
# Copyright (C) 2010  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): David Cantrell <dcantrell@redhat.com>

import unittest

from blivet.errors import *
from blivet.size import Size, _prefixes

class SizeTestCase(unittest.TestCase):
    def testExceptions(self):
        self.assertRaises(SizeParamsError, Size)
        self.assertRaises(SizeParamsError, Size, bytes=500, en_spec="45GB")

        zero = Size(bytes=0)
        self.assertEqual(zero, 0.0)

        s = Size(bytes=500)
        self.assertRaises(SizePlacesError, s.humanReadable, places=-1)

        self.assertEqual(s.humanReadable(places=0), "500 B")

    def _prefixTestHelper(self, bytes, factor, prefix, abbr):
        c = bytes * factor

        s = Size(bytes=c)
        self.assertEquals(s, c)

        if prefix:
            u = "%sbytes" % prefix
            s = Size(en_spec="%ld %s" % (bytes, u))
            self.assertEquals(s, c)
            self.assertEquals(s.convertTo(en_spec=u), bytes)

        if abbr:
            u = "%sb" % abbr
            s = Size(en_spec="%ld %s" % (bytes, u))
            self.assertEquals(s, c)
            self.assertEquals(s.convertTo(en_spec=u), bytes)

        if not prefix and not abbr:
            s = Size(spec="%ld" % bytes)
            self.assertEquals(s, c)
            self.assertEquals(s.convertTo(), bytes)

    def testPrefixes(self):
        bytes = 47L
        self._prefixTestHelper(bytes, 1, None, None)

        for factor, prefix, abbr in _prefixes:
            self._prefixTestHelper(bytes, factor, prefix, abbr)

    def testHumanReadable(self):
        s = Size(bytes=58929971L)
        self.assertEquals(s.humanReadable(), "58.92 MB")

        s = Size(bytes=478360371L)
        self.assertEquals(s.humanReadable(), "478.36 MB")

    def testNegative(self):
        s = Size(spec="-500MiB")
        self.assertEquals(s.humanReadable(), "-500 MiB")
        self.assertEquals(s.convertTo(spec="b"), -524288000)

    def testPartialBytes(self):
        s = Size(bytes=1024.6)
        self.assertEquals(Size(bytes=1024.6), Size(bytes=1024))
        self.assertEquals(Size(spec="%s KiB" % (1/1025.0,)), Size(bytes=0))
        self.assertEquals(Size(spec="%s KiB" % (1/1023.0,)), Size(bytes=1))

def suite():
    return unittest.TestLoader().loadTestsFromTestCase(SizeTestCase)

if __name__ == "__main__":
    unittest.main()
