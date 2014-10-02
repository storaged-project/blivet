# size.py
# Python module to represent storage sizes
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

import itertools
import re
import string
import locale
from collections import namedtuple

from decimal import Decimal
from decimal import InvalidOperation
from decimal import ROUND_DOWN
import six

from .errors import SizePlacesError
from .i18n import _, N_


# Container for size unit prefix information
_Prefix = namedtuple("Prefix", ["factor", "prefix", "abbr"])

_DECIMAL_FACTOR = 10 ** 3
_BINARY_FACTOR = 2 ** 10

# Decimal prefixes for different size increments, along with the name
# and accepted abbreviation for the prefix.  These prefixes are all
# for 'bytes'.
_DECIMAL_PREFIXES = [
   _Prefix(_DECIMAL_FACTOR ** 1, N_(b"kilo"), N_(b"k")),
   _Prefix(_DECIMAL_FACTOR ** 2, N_(b"mega"), N_(b"M")),
   _Prefix(_DECIMAL_FACTOR ** 3, N_(b"giga"), N_(b"G")),
   _Prefix(_DECIMAL_FACTOR ** 4, N_(b"tera"), N_(b"T")),
   _Prefix(_DECIMAL_FACTOR ** 5, N_(b"peta"), N_(b"P")),
   _Prefix(_DECIMAL_FACTOR ** 6, N_(b"exa"), N_(b"E")),
   _Prefix(_DECIMAL_FACTOR ** 7, N_(b"zetta"), N_(b"Z")),
   _Prefix(_DECIMAL_FACTOR ** 8, N_(b"yotta"), N_(b"Y"))
]

# Binary prefixes for the different size increments.  Same structure
# as the above list.
_BINARY_PREFIXES = [
   _Prefix(_BINARY_FACTOR ** 1, N_(b"kibi"), N_(b"Ki")),
   _Prefix(_BINARY_FACTOR ** 2, N_(b"mebi"), N_(b"Mi")),
   _Prefix(_BINARY_FACTOR ** 3, N_(b"gibi"), N_(b"Gi")),
   _Prefix(_BINARY_FACTOR ** 4, N_(b"tebi"), N_(b"Ti")),
   _Prefix(_BINARY_FACTOR ** 5, N_(b"pebi"), N_(b"Pi")),
   _Prefix(_BINARY_FACTOR ** 6, N_(b"exbi"), N_(b"Ei")),
   _Prefix(_BINARY_FACTOR ** 7, N_(b"zebi"), N_(b"Zi")),
   _Prefix(_BINARY_FACTOR ** 8, N_(b"yobi"), N_(b"Yi"))
]

# Empty prefix works both for decimal and binary
_EMPTY_PREFIX = _Prefix(1, u"", u"")

_BYTES = [N_(b'B'), N_(b'b'), N_(b'byte'), N_(b'bytes')]
_PREFIXES = _BINARY_PREFIXES + _DECIMAL_PREFIXES

# Translated versions of the byte and prefix arrays as lazy comprehensions
# All strings are decoded as utf-8 so that locale-specific upper/lower functions work
def _xlated_bytes():
    return (_(b).decode("utf-8") for b in _BYTES)

def _xlated_prefix(p):
    return _Prefix(p.factor, _(p.prefix).decode("utf-8"), _(p.abbr).decode("utf-8"))

def _xlated_binary_prefixes():
    return (_xlated_prefix(p) for p in _BINARY_PREFIXES)

def _xlated_decimal_prefixes():
    return (_xlated_prefix(p) for p in _DECIMAL_PREFIXES)

def _xlated_prefixes():
    return itertools.chain(_xlated_binary_prefixes(), _xlated_decimal_prefixes())

_ASCIIlower_table = string.maketrans(string.ascii_uppercase, string.ascii_lowercase)
def _lowerASCII(s):
    """Convert a string to lowercase using only ASCII character definitions."""
    return string.translate(s, _ASCIIlower_table)

def _makeSpecs(prefix, abbr, xlate):
    """ Internal method used to generate a list of specifiers. """
    specs = []

    if prefix:
        if xlate:
            specs.append(prefix.lower() + _(b"byte").decode("utf-8"))
            specs.append(prefix.lower() + _(b"bytes").decode("utf-8"))
        else:
            specs.append(_lowerASCII(prefix) + "byte")
            specs.append(_lowerASCII(prefix) + "bytes")

    if abbr:
        if xlate:
            specs.append(abbr.lower() + _(b"b").decode("utf-8"))
            specs.append(abbr.lower())
        else:
            specs.append(_lowerASCII(abbr) + "b")
            specs.append(_lowerASCII(abbr))

    return specs

def _parseSpec(spec):
    """ Parse string representation of size. """
    if not spec:
        raise ValueError("invalid size specification", spec)

    # Replace the localized radix character with a .
    radix = locale.nl_langinfo(locale.RADIXCHAR)
    if radix != '.':
        spec = spec.replace(radix, '.')

    # Match the string using only digit/space/not-space, since the
    # string might be non-English and contain non-letter characters
    # that Python doesn't understand as parts of words.
    m = re.match(r'(-?\s*[0-9.]+)\s*([^\s]*)$', spec.strip())
    if not m:
        raise ValueError("invalid size specification", spec)

    try:
        size = Decimal(m.groups()[0])
    except InvalidOperation:
        raise ValueError("invalid size specification", spec)

    specifier = m.groups()[1]

    # Only attempt to parse as English if all characters are ASCII
    try:
        # This will raise UnicodeDecodeError if specifier contains non-ascii
        # characters
        if six.PY2:
            spec_ascii = specifier.decode("ascii")
            # Convert back to a str type to match the _BYTES and _PREFIXES arrays
            spec_ascii = str(spec_ascii)
        else:
            # This will raise UnicodeEncodeError if specifier contains any non-ascii
            # in Python3 `bytes` are new Python2 `str`
            spec_ascii = bytes(specifier, 'ascii')

        # Use the ASCII-only lowercase mapping
        spec_ascii = _lowerASCII(spec_ascii)
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    else:
        if spec_ascii and not spec_ascii.endswith("b"):
            spec_ascii += "ib"

        if spec_ascii in _BYTES or not spec_ascii:
            return size

        for factor, prefix, abbr in _PREFIXES:
            check = _makeSpecs(prefix, abbr, False)

            if spec_ascii in check:
                return size * factor

    # No English match found, try localized size specs. Accept any utf-8
    # character and leave the result as a (unicode object.
    if six.PY2:
        spec_local = specifier.decode("utf-8")
    else:
        # str = unicode in Python3
        spec_local = specifier

    # Use the locale-specific lowercasing
    spec_local = spec_local.lower()

    if spec_local in _xlated_bytes():
        return size

    for factor, prefix, abbr in _xlated_prefixes():
        check  = _makeSpecs(prefix, abbr, True)

        if spec_local in check:
            return size * factor

    raise ValueError("invalid size specification", spec)

class Size(Decimal):
    """ Common class to represent storage device and filesystem sizes.
        Can handle parsing strings such as 45MB or 6.7GB to initialize
        itself, or can be initialized with a numerical size in bytes.
        Also generates human readable strings to a specified number of
        decimal places.
    """

    def __new__(cls, value=0, context=None):
        """ Initialize a new Size object.  Must pass a bytes or a spec value
            for size. The bytes value is a numerical value for the size
            this object represents, in bytes.  The spec value is a string
            specification of the size using any of the size specifiers in the
            _DECIMAL_PREFIXES or _BINARY_PREFIXES lists combined with a 'b' or
            'B'.  For example, to specify 640 kilobytes, you could pass any of
            these spec parameters:

                "640kb"
                "640 kb"
                "640KB"
                "640 KB"
                "640 kilobytes"

            If you want to use a spec value to represent a bytes value,
            you can use the letter 'b' or 'B' or omit the size specifier.
        """
        if isinstance(value, (six.string_types, bytes)):
            size = _parseSpec(value)
        elif isinstance(value, (six.integer_types, float, Decimal)):
            size = Decimal(value)
        elif isinstance(value, Size):
            size = Decimal(value.convertTo("b"))
        else:
            raise ValueError("invalid value %s for size" % value)

        # drop any partial byte
        size = size.to_integral_value(rounding=ROUND_DOWN)
        self = Decimal.__new__(cls, value=size)
        return self

    def __str__(self, eng=False, context=None):
        return self.humanReadable()

    def __repr__(self):
        return "Size('%s')" % self

    def __deepcopy__(self, memo):
        return Size(self.convertTo(spec="b"))

    def __add__(self, other, context=None):
        return Size(Decimal.__add__(self, other, context=context))

    # needed to make sum() work with Size arguments
    def __radd__(self, other, context=None):
        return Size(Decimal.__radd__(self, other, context=context))

    def __sub__(self, other, context=None):
        # subtraction is implemented using __add__ and negation, so we'll
        # be getting passed a Size
        return Decimal.__sub__(self, other, context=context)

    def __mul__(self, other, context=None):
        return Size(Decimal.__mul__(self, other, context=context))

    def __div__(self, other, context=None):
        return Size(Decimal.__div__(self, other, context=context))

    def __mod__(self, other, context=None):
        return Size(Decimal.__mod__(self, other, context=context))

    def convertTo(self, spec="b"):
        """ Return the size in the units indicated by the specifier.  The
            specifier can be prefixes from the _DECIMAL_PREFIXES and
            _BINARY_PREFIXES lists combined with 'b' or 'B' for abbreviations)
            or 'bytes' (for prefixes like kilo or mega). The size is returned
            as a Decimal.
        """
        spec = spec.lower()

        if spec in _BYTES:
            return Decimal(self)

        for factor, prefix, abbr in _PREFIXES:
            check = _makeSpecs(prefix, abbr, False)

            if spec in check:
                return Decimal(self) / Decimal(factor)

        return None

    def humanReadable(self, max_places=2, strip=True, min_value=1):
        """ Return a string representation of this size with appropriate
            size specifier and in the specified number of decimal places.
            Values are always represented using binary not decimal units.
            For example, if the number of bytes represented by this size
            is 65531, expect the representation to be something like
            64.00 KiB, not 65.53 KB.

            :param max_places: number of decimal places to use, default is 2
            :type max_places: an integer type or NoneType
            :param bool strip: True if trailing zeros are to be stripped.
            :param min_value: Lower bound for value, default is 1.
            :type min_value: A precise numeric type: int, long, or Decimal
            :returns: a representation of the size
            :rtype: str

            If max_places is set to None, all non-zero digits will be shown.
            Otherwise, max_places digits will be shown.

            If strip is True and there is a fractional quantity, trailing
            zeros are removed up to the decimal point.

            min_value sets the smallest value allowed.
            If min_value is 10, then single digits on the lhs of
            the decimal will be avoided if possible. In that case,
            9216 KiB is preferred to 9 MiB. However, 1 B has no alternative.
            If min_value is 1, however, 9 MiB is preferred.
            If min_value is 0.1, then 0.75 GiB is preferred to 768 MiB,
            but 0.05 GiB is still displayed as 51.2 MiB.

            humanReadable() is a function that evaluates to a number which
            represents a range of values. For a constant choice of max_places,
            all ranges are of equal size, and are bisected by the result. So,
            if n.humanReadable() == x U and b is the number of bytes in 1 U,
            and e = 1/2 * 1/(10^max_places) * b, then x - e < n < x + e.
        """
        if max_places is not None and (max_places < 0 or not isinstance(max_places, six.integer_types)):
            raise SizePlacesError("max_places must be None or an non-negative integer value")

        if min_value < 0 or not isinstance(min_value, (six.integer_types, Decimal)):
            raise ValueError("min_value must be a precise positive numeric value.")

        # Find the smallest prefix which will allow a number less than
        # _BINARY_FACTOR * min_value to the left of the decimal point.
        # If the number is so large that no prefix will satisfy this
        # requirement use the largest prefix.
        for factor, _prefix, abbr in itertools.chain([_EMPTY_PREFIX], _xlated_binary_prefixes()):
            newcheck = super(Size, self).__div__(Decimal(factor))

            if abs(newcheck) < _BINARY_FACTOR * min_value:
                # nice value, use this factor, prefix and abbr
                break

        if max_places is not None:
            newcheck = newcheck.quantize(Decimal(10) ** -max_places)

        retval_str = str(newcheck)

        if '.' in retval_str and strip:
            retval_str = retval_str.rstrip("0").rstrip(".")

        # If necessary, substitute with a localized separator before returning
        radix = locale.nl_langinfo(locale.RADIXCHAR)
        if radix != '.':
            retval_str = retval_str.replace('.', radix)

        # Convert unicode objects to str before concatenating so that the
        # resulting expression is a str.
        # pylint: disable=undefined-loop-variable
        return retval_str + " " + abbr.encode("utf-8") + _("B")
