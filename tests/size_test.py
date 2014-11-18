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

import locale
import os
import unittest

from decimal import Decimal

import six

from blivet.i18n import _
from blivet.errors import SizePlacesError
from blivet import size
from blivet.size import Size, _EMPTY_PREFIX, _BINARY_PREFIXES, _DECIMAL_PREFIXES

if six.PY3:
    long = int # pylint: disable=redefined-builtin

class SizeTestCase(unittest.TestCase):

    def testExceptions(self):
        zero = Size(0)
        self.assertEqual(zero, Size(0.0))

        s = Size(500)
        with self.assertRaises(SizePlacesError):
            s.humanReadable(max_places=-1)

        self.assertEqual(s.humanReadable(max_places=0), "500 B")

    def _prefixTestHelper(self, numbytes, factor, prefix, abbr):
        c = numbytes * factor

        s = Size(c)
        self.assertEquals(s, Size(c))

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

        for factor, prefix, abbr in [_EMPTY_PREFIX] + _BINARY_PREFIXES + _DECIMAL_PREFIXES:
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

        # when min_value is 10 and single digit on left of decimal, display
        # with smaller unit.
        s = Size("9.68 TiB")
        self.assertEquals(s.humanReadable(max_places=2, min_value=10), "9912.32 GiB")
        s = Size("4.29 MiB")
        self.assertEquals(s.humanReadable(max_places=2, min_value=10), "4392.96 KiB")
        s = Size("7.18 KiB")
        self.assertEquals(s.humanReadable(max_places=2, min_value=10), "7352 B")

        # rounding should work with max_places limitted
        s = Size("12.687 TiB")
        self.assertEquals(s.humanReadable(max_places=2), "12.69 TiB")
        s = Size("23.7874 TiB")
        self.assertEquals(s.humanReadable(max_places=3), "23.787 TiB")
        s = Size("12.6998 TiB")
        self.assertEquals(s.humanReadable(max_places=2), "12.7 TiB")

        # byte values close to multiples of 2 are shown without trailing zeros
        s = Size(0xff)
        self.assertEquals(s.humanReadable(max_places=2), "255 B")
        s = Size(8193)
        self.assertEquals(s.humanReadable(max_places=2, min_value=10), "8193 B")

        # a fractional quantity is shown if the value deviates
        # from the whole number of units by more than 1%
        s = Size(16384 - (1024/100 + 1))
        self.assertEquals(s.humanReadable(max_places=2), "15.99 KiB")

        # if max_places is set to None, all digits are displayed
        s = Size(0xfffffffffffff)
        self.assertEquals(s.humanReadable(max_places=None), "3.9999999999999991118215803 PiB")
        s = Size(0x10000)
        self.assertEquals(s.humanReadable(max_places=None), "64 KiB")
        s = Size(0x10001)
        self.assertEquals(s.humanReadable(max_places=None), "64.0009765625 KiB")

        # test a very large quantity with no associated abbreviation or prefix
        s = Size(1024**9)
        self.assertEquals(s.humanReadable(max_places=2), "1024 YiB")
        s = Size(1024**9 - 1)
        self.assertEquals(s.humanReadable(max_places=2), "1024 YiB")
        s = Size(1024**9 + 1)
        self.assertEquals(s.humanReadable(max_places=2, strip=False), "1024.00 YiB")
        s = Size(1024**10)
        self.assertEquals(s.humanReadable(max_places=2), "1048576 YiB")

    def testHumanReadableFractionalQuantities(self):
        s = Size(0xfffffffffffff)
        self.assertEquals(s.humanReadable(max_places=2), "4 PiB")
        s = Size(0xfffff)
        self.assertEquals(s.humanReadable(max_places=2, strip=False), "1024.00 KiB")
        s = Size(0xffff)
        # value is not exactly 64 KiB, but w/ 2 places, value is 64.00 KiB
        # so the trailing 0s are stripped.
        self.assertEquals(s.humanReadable(max_places=2), "64 KiB")
        # since all significant digits are shown, there are no trailing 0s.
        self.assertEquals(s.humanReadable(max_places=None), "63.9990234375 KiB")

        # deviation is less than 1/2 of 1% of 1024
        s = Size(16384 - (1024/100/2))
        self.assertEquals(s.humanReadable(max_places=2), "16 KiB")
        # deviation is greater than 1/2 of 1% of 1024
        s = Size(16384 - ((1024/100/2) + 1))
        self.assertEquals(s.humanReadable(max_places=2), "15.99 KiB")

        s = Size(0x10000000000000)
        self.assertEquals(s.humanReadable(max_places=2), "4 PiB")


    def testMinValue(self):
        s = Size("9 MiB")
        self.assertEquals(s.humanReadable(), "9 MiB")
        self.assertEquals(s.humanReadable(min_value=10), "9216 KiB")

        s = Size("0.5 GiB")
        self.assertEquals(s.humanReadable(max_places=2, min_value=1), "512 MiB")
        self.assertEquals(s.humanReadable(max_places=2, min_value=Decimal(0.1)), "0.5 GiB")
        self.assertEquals(s.humanReadable(max_places=2, min_value=Decimal(1)), "512 MiB")

    def testConvertToPrecision(self):
        s = Size(1835008)
        self.assertEquals(s.convertTo(spec=""), 1835008)
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

class TranslationTestCase(unittest.TestCase):

    def __init__(self, methodName='runTest'):
        super(TranslationTestCase, self).__init__(methodName=methodName)

        # es_ES uses latin-characters but a comma as the radix separator
        # kk_KZ uses non-latin characters and is case-sensitive
        # ml_IN uses a lot of non-letter modifier characters
        # fa_IR uses non-ascii digits, or would if python supported that, but
        #       you know, just in case
        self.TEST_LANGS = ["es_ES.UTF-8", "kk_KZ.UTF-8", "ml_IN.UTF-8", "fa_IR.UTF-8"]

    def setUp(self):
        self.saved_lang = os.environ.get('LANG', None)

    def tearDown(self):
        os.environ['LANG'] = self.saved_lang
        locale.setlocale(locale.LC_ALL, '')

    def testMakeSpec(self):
        """ Tests for _makeSpecs(). """
        for lang in  self.TEST_LANGS:
            os.environ['LANG'] = lang
            locale.setlocale(locale.LC_ALL, '')

            # untranslated specs
            self.assertEqual(size._makeSpec(b"", b"BYTES", False), b"bytes")
            self.assertEqual(size._makeSpec(b"Mi", b"b", False), b"mib")

            # un-lower-cased specs
            self.assertEqual(size._makeSpec(b"", b"BYTES", False, False), b"BYTES")
            self.assertEqual(size._makeSpec(b"Mi", b"b", False, False), b"Mib")
            self.assertEqual(size._makeSpec(b"Mi", b"B", False, False), b"MiB")

            # translated specs
            res = size._makeSpec(b"", b"bytes", True)

            # Note that exp != _(b"bytes").lower() as one might expect
            exp = (_(b"") + _(b"bytes")).lower()
            self.assertEqual(res, exp)

    def testParseSpec(self):
        """ Tests for _parseSpec(). """
        for lang in  self.TEST_LANGS:
            os.environ['LANG'] = lang
            locale.setlocale(locale.LC_ALL, '')

            # Test parsing English spec in foreign locales
            self.assertEqual(size._parseSpec("1 kibibytes"), Decimal(1024))
            self.assertEqual(size._parseSpec("2 kibibyte"), Decimal(2048))
            self.assertEqual(size._parseSpec("2 kilobyte"), Decimal(2000))
            self.assertEqual(size._parseSpec("2 kilobytes"), Decimal(2000))
            self.assertEqual(size._parseSpec("2 KB"), Decimal(2000))
            self.assertEqual(size._parseSpec("2 K"), Decimal(2048))
            self.assertEqual(size._parseSpec("2 k"), Decimal(2048))
            self.assertEqual(size._parseSpec("2 Ki"), Decimal(2048))
            self.assertEqual(size._parseSpec("2 g"), Decimal(2 * 1024 ** 3))
            self.assertEqual(size._parseSpec("2 G"), Decimal(2 * 1024 ** 3))

            # Test parsing foreign spec
            self.assertEqual(size._parseSpec("1 %s%s" % (_("kibi"), _("bytes"))), Decimal(1024))

            # Can't parse a valueless number
            with self.assertRaises(ValueError):
                size._parseSpec("Ki")

            self.assertEqual(size._parseSpec("2 %s" % _("K")), Decimal(2048))
            self.assertEqual(size._parseSpec("2 %s" % _("Ki")), Decimal(2048))
            self.assertEqual(size._parseSpec("2 %s" % _("g")), Decimal(2 * 1024 ** 3))
            self.assertEqual(size._parseSpec("2 %s" % _("G")), Decimal(2 * 1024 ** 3))

    def testTranslated(self):
        s = Size("56.19 MiB")
        for lang in  self.TEST_LANGS:
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

    def testHumanReadableTranslation(self):
        s = Size("56.19 MiB")
        size_str = s.humanReadable()
        for lang in self.TEST_LANGS:

            os.environ['LANG'] = lang
            locale.setlocale(locale.LC_ALL, '')
            self.assertTrue(s.humanReadable().endswith("%s%s" % (_("Mi"), _("B"))))
            self.assertEqual(s.humanReadable(xlate=False), size_str)

    def testRoundToNearest(self):
        self.assertEqual(size.ROUND_DEFAULT, size.ROUND_HALF_UP)

        s = Size("10.3 GiB")
        self.assertEqual(s.roundToNearest("GiB"), Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=size.ROUND_DEFAULT),
                         Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=size.ROUND_DOWN),
                         Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=size.ROUND_UP),
                         Size("11 GiB"))
        # >>> Size("10.3 GiB").convertTo("MiB")
        # Decimal('10547.19999980926513671875')
        self.assertEqual(s.roundToNearest("MiB"), Size("10547 MiB"))
        self.assertEqual(s.roundToNearest("MiB", rounding=size.ROUND_UP),
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
        self.assertEqual(s.roundToNearest("GiB", rounding=size.ROUND_DEFAULT),
                         Size("11 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=size.ROUND_DOWN),
                         Size("10 GiB"))
        self.assertEqual(s.roundToNearest("GiB", rounding=size.ROUND_UP),
                         Size("11 GiB"))

        s = Size("513 GiB")
        self.assertEqual(s.roundToNearest("GiB"), s)
        self.assertEqual(s.roundToNearest("TiB"), Size("1 TiB"))
        self.assertEqual(s.roundToNearest("TiB", rounding=size.ROUND_DOWN),
                         Size(0))

class UtilityMethodsTestCase(unittest.TestCase):

    def testLowerASCII(self):
        """ Tests for _lowerASCII. """
        self.assertEqual(size._lowerASCII(b""), b"")
        self.assertEqual(size._lowerASCII(b"B"), b"b")

    def testArithmetic(self):
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
