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

from blivet.errors import SizePlacesError
from blivet.size import Size, _prefixes, ROUND_UP, ROUND_DOWN, ROUND_DEFAULT, ROUND_HALF_UP

class SizeTestCase(unittest.TestCase):
    def testExceptions(self):
        zero = Size(0)
        self.assertEqual(zero, 0.0)

        s = Size(500)
        with self.assertRaises(SizePlacesError):
            s.humanReadable(places=-1)

        self.assertEqual(s.humanReadable(places=0), "500 B")

    def _prefixTestHelper(self, numbytes, factor, prefix, abbr):
        c = numbytes * factor

        s = Size(c)
        self.assertEquals(s, c)

        if prefix:
            u = "%sbytes" % prefix
            s = Size("%ld %s" % (numbytes, u))
            self.assertEquals(s, c)
            self.assertEquals(s.convertTo(spec=u), numbytes)

        if abbr:
            u = "%sb" % abbr
            s = Size("%ld %s" % (numbytes, u))
            self.assertEquals(s, c)
            self.assertEquals(s.convertTo(spec=u), numbytes)

        if not prefix and not abbr:
            s = Size("%ld" % numbytes)
            self.assertEquals(s, c)
            self.assertEquals(s.convertTo(), numbytes)

    def testPrefixes(self):
        numbytes = long(47)
        self._prefixTestHelper(numbytes, 1, None, None)

        for factor, prefix, abbr in _prefixes:
            self._prefixTestHelper(numbytes, factor, prefix, abbr)

    def testHumanReadable(self):
        s = Size(long(58929971))
        self.assertEquals(s.humanReadable(), "56.2 MiB")

        s = Size(long(478360371))
        self.assertEquals(s.humanReadable(), "456.2 MiB")

        # humanReable output should be the same as input for big enough sizes
        # and enough places and integer values
        s = Size("12.68 TiB")
        self.assertEquals(s.humanReadable(max_places=2), "12.68 TiB")
        s = Size("26.55 MiB")
        self.assertEquals(s.humanReadable(max_places=2), "26.55 MiB")
        s = Size("300 MiB")
        self.assertEquals(s.humanReadable(max_places=2), "300 MiB")

        # smaller unit should be used for small sizes
        s = Size("9.68 TiB")
        self.assertEquals(s.humanReadable(max_places=2), "9912.32 GiB")
        s = Size("4.29 MiB")
        self.assertEquals(s.humanReadable(max_places=2), "4392.96 KiB")
        s = Size("7.18 KiB")
        self.assertEquals(s.humanReadable(max_places=2), "7352 B")

        # rounding should work with max_places limitted
        s = Size("12.687 TiB")
        self.assertEquals(s.humanReadable(max_places=2), "12.69 TiB")
        s = Size("23.7874 TiB")
        self.assertEquals(s.humanReadable(max_places=3), "23.787 TiB")
        s = Size("12.6998 TiB")
        self.assertEquals(s.humanReadable(max_places=2), "12.7 TiB")

    def testConvertToPrecision(self):
        s = Size(1835008)
        self.assertEquals(s.convertTo(spec="b"), 1835008)
        self.assertEquals(s.convertTo(spec="KiB"), 1792)
        self.assertEquals(s.convertTo(spec="MiB"), 1.75)

    def testNegative(self):
        s = Size("-500MiB")
        self.assertEquals(s.humanReadable(), "-500 MiB")
        self.assertEquals(s.convertTo(spec="b"), -524288000)

    def testPartialBytes(self):
        self.assertEquals(Size(1024.6), Size(1024))
        self.assertEquals(Size("%s KiB" % (1/1025.0,)), Size(0))
        self.assertEquals(Size("%s KiB" % (1/1023.0,)), Size(1))

    def testTranslated(self):
        import locale
        import os
        from blivet.i18n import _

        saved_lang = os.environ.get('LANG', None)

        # es_ES uses latin-characters but a comma as the radix separator
        # kk_KZ uses non-latin characters and is case-sensitive
        # te_IN uses a lot of non-letter modifier characters
        # fa_IR uses non-ascii digits, or would if python supported that, but
        #       you know, just in case
        test_langs = ["es_ES.UTF-8", "kk_KZ.UTF-8", "ml_IN.UTF-8", "fa_IR.UTF-8"]

        s = Size("56.19 MiB")
        for lang in test_langs:
            os.environ['LANG'] = lang
            locale.setlocale(locale.LC_ALL, '')

            # Check English parsing
            self.assertEquals(s, Size("56.19 MiB"))

            # Check native parsing
            self.assertEquals(s, Size("56.19 %s%s" % (_("Mi"), _("B"))))

            # Check native parsing, all lowercase
            self.assertEquals(s, Size(("56.19 %s%s" % (_("Mi"), _("B"))).lower()))

            # Check native parsing, all uppercase
            self.assertEquals(s, Size(("56.19 %s%s" % (_("Mi"), _("B"))).upper()))

            # If the radix separator is not a period, repeat the tests with the
            # native separator
            radix = locale.nl_langinfo(locale.RADIXCHAR)
            if radix != '.':
                self.assertEquals(s, Size("56%s19 MiB" % radix))
                self.assertEquals(s, Size("56%s19 %s%s" % (radix, _("Mi"), _("B"))))
                self.assertEquals(s, Size(("56%s19 %s%s" % (radix, _("Mi"), _("B"))).lower()))
                self.assertEquals(s, Size(("56%s19 %s%s" % (radix, _("Mi"), _("B"))).upper()))

        os.environ['LANG'] = saved_lang
        locale.setlocale(locale.LC_ALL, '')

    def testRoundToNearest(self):
        self.assertEqual(ROUND_DEFAULT, ROUND_HALF_UP)

        s = Size("10.3 GiB")
        self.assertEqual(s.roundToNearest("GiB"), Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=ROUND_DEFAULT),
                         Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=ROUND_DOWN),
                         Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=ROUND_UP),
                         Size("11 GiB"))
        # >>> Size("10.3 GiB").convertTo("MiB")
        # Decimal('10547.19999980926513671875')
        self.assertEqual(s.roundToNearest("MiB"), Size("10547 MiB"))
        self.assertEqual(s.roundToNearest("MiB", rounding=ROUND_UP),
                         Size("10548 MiB"))
        self.assertIsInstance(s.roundToNearest("MiB"), Size)
        with self.assertRaises(ValueError):
            s.roundToNearest("MiB", rounding='abc')

        # arbitrary decimal rounding constants are not allowed
        from decimal import ROUND_HALF_DOWN
        with self.assertRaises(ValueError):
            s.roundToNearest("MiB", rounding=ROUND_HALF_DOWN)

        s = Size("10.51 GiB")
        self.assertEqual(s.roundToNearest("GiB"), Size("11 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=ROUND_DEFAULT),
                         Size("11 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=ROUND_DOWN),
                         Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=ROUND_UP),
                         Size("11 GiB"))

        s = Size("513 GiB")
        self.assertEqual(s.roundToNearest("GiB"), s)
        self.assertEqual(s.roundToNearest("TiB"), Size("1 TiB"))
        self.assertEqual(s.roundToNearest("TiB", rounding=ROUND_DOWN),
                         Size(0))

    def testArithmetic(self):
        from decimal import Decimal
        s = Size("2GiB")

        # Make sure arithmatic operations with Size always result in the expected type
        self.assertIsInstance(s+s, Size)
        self.assertIsInstance(s-s, Size)
        self.assertIsInstance(s*s, Size)
        self.assertIsInstance(s/s, Size)
        self.assertIsInstance(s**Size(2), Decimal)
        self.assertIsInstance(s % Size(7), Size)


        # Make sure operations with non-Size on the right result in the expected type
        self.assertIsInstance(s+2, Size)
        self.assertIsInstance(s-2, Size)
        self.assertIsInstance(s*2, Size)
        self.assertIsInstance(s/2, Size)
        self.assertIsInstance(s**2, Decimal)
        self.assertIsInstance(s % 127, Size)

        # Make sure operations with non-Size on the left result in the expected type
        self.assertIsInstance(2+s, Size)
        self.assertIsInstance(2-s, Decimal)
        self.assertIsInstance(2*s, Size)
        self.assertIsInstance(2/s, Decimal)
        self.assertIsInstance(2**Size(2), Decimal)
        self.assertIsInstance(1024 % Size(127), Decimal)

if __name__ == "__main__":
    unittest.main()
