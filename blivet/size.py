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

import re
import string
import locale
from collections import namedtuple

from decimal import Decimal
from decimal import InvalidOperation
from decimal import ROUND_DOWN, ROUND_UP, ROUND_HALF_UP

from .errors import SizePlacesError
from .i18n import _, P_, N_

ROUND_DEFAULT = ROUND_HALF_UP

# Container for size unit prefix information
_Prefix = namedtuple("Prefix", ["factor", "prefix", "abbr"])

# Decimal prefixes for different size increments, along with the name
# and accepted abbreviation for the prefix.  These prefixes are all
# for 'bytes'.
_decimalPrefixes = [_Prefix(1000, N_(b"kilo"), N_(b"k")),
                    _Prefix(1000**2, N_(b"mega"), N_(b"M")),
                    _Prefix(1000**3, N_(b"giga"), N_(b"G")),
                    _Prefix(1000**4, N_(b"tera"), N_(b"T")),
                    _Prefix(1000**5, N_(b"peta"), N_(b"P")),
                    _Prefix(1000**6, N_(b"exa"), N_(b"E")),
                    _Prefix(1000**7, N_(b"zetta"), N_(b"Z")),
                    _Prefix(1000**8, N_(b"yotta"), N_(b"Y"))]

# Binary prefixes for the different size increments.  Same structure
# as the above list.
_binaryPrefixes = [_Prefix(1024, N_(b"kibi"), N_(b"Ki")),
                   _Prefix(1024**2, N_(b"mebi"), N_(b"Mi")),
                   _Prefix(1024**3, N_(b"gibi"), N_(b"Gi")),
                   _Prefix(1024**4, N_(b"tebi"), N_(b"Ti")),
                   _Prefix(1024**5, N_(b"pebi"), N_(b"Pi")),
                   _Prefix(1024**6, N_(b"exbi"), N_(b"Ei")),
                   _Prefix(1024**7, N_(b"zebi"), N_(b"Zi")),
                   _Prefix(1024**8, N_(b"yobi"), N_(b"Yi"))]

# Handle 'B' separately so that it can be localized without translating
# both 'B' and 'b'
_bytes_letter = N_(b'B')
_bytes_words = [N_(b'byte'), N_(b'bytes')]
_prefixes = _binaryPrefixes + _decimalPrefixes

_ASCIIlower_table = string.maketrans(string.ascii_uppercase, string.ascii_lowercase)
def _lowerASCII(s):
    """Convert a string to lowercase using only ASCII character definitions."""
    return string.translate(s, _ASCIIlower_table)

_bytes = [_bytes_letter, _lowerASCII(_bytes_letter)] + _bytes_words

# Translated versions of the byte and prefix arrays
# All strings are decoded as utf-8 so that locale-specific upper/lower functions work
def _xlated_bytes():
    """Return a translated version of the bytes list as a list of unicode strings"""
    return [_(_bytes_letter).decode("utf-8") + _(_bytes_letter).decode("utf-8").lower()] + \
            [_(b).decode("utf-8") for b in _bytes_words]

def _xlated_binary_prefixes():
    return (_Prefix(p.factor, _(p.prefix).decode("utf-8"), _(p.abbr).decode("utf-8")) \
            for p in _binaryPrefixes)

def _xlated_prefixes():
    """Return translated prefixes as unicode strings"""
    xlated_binary = list(_xlated_binary_prefixes())
    xlated_decimal = [_Prefix(p.factor, _(p.prefix).decode("utf-8"), _(p.abbr).decode("utf-8")) \
                      for p in _decimalPrefixes]

    return xlated_binary + xlated_decimal

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
            specs.append(abbr.lower() + _(_bytes_letter).decode("utf-8").lower())
            specs.append(abbr.lower())
        else:
            specs.append(_lowerASCII(abbr) + _lowerASCII(_bytes_letter))
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
        spec_ascii = specifier.decode("ascii")
        # Convert back to a str type to match the _bytes and _prefixes arrays
        spec_ascii = str(spec_ascii)

        # Use the ASCII-only lowercase mapping
        spec_ascii = _lowerASCII(spec_ascii)
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    else:
        if spec_ascii and not spec_ascii.endswith("b"):
            spec_ascii += "ib"

        if spec_ascii in _bytes or not spec_ascii:
            return size

        for factor, prefix, abbr in _prefixes:
            check = _makeSpecs(prefix, abbr, False)

            if spec_ascii in check:
                return size * factor

    # No English match found, try localized size specs. Accept any utf-8
    # character and leave the result as a (unicode object.
    spec_local = specifier.decode("utf-8")

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
            _decimalPrefixes or _binaryPrefixes lists combined with a 'b' or
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
        if isinstance(value, str):
            size = _parseSpec(value)
        elif isinstance(value, (int, long, float, Decimal)):
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
        # Convert the result of humanReadable from unicode to str
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
    __rmul__ = __mul__

    def __div__(self, other, context=None):
        return Size(Decimal.__div__(self, other, context=context))

    def __mod__(self, other, context=None):
        return Size(Decimal.__mod__(self, other, context=context))

    def convertTo(self, spec="b"):
        """ Return the size in the units indicated by the specifier.  The
            specifier can be prefixes from the _decimalPrefixes and
            _binaryPrefixes lists combined with 'b' or 'B' for abbreviations) or
            'bytes' (for prefixes like kilo or mega).  The size is returned as a
            Decimal.
        """
        spec = spec.lower()

        if spec in _bytes:
            return Decimal(self)

        for factor, prefix, abbr in _prefixes:
            check = _makeSpecs(prefix, abbr, False)

            if spec in check:
                return Decimal(self) / Decimal(factor)

        return None

    def humanReadable(self, places=None, max_places=2):
        """ Return a string representation of this size with appropriate
            size specifier and in the specified number of decimal places
            (i.e. the maximal precision is only achieved by setting both places
            and max_places to None).
        """
        if places is not None and places < 0:
            raise SizePlacesError("places= must be >=0 or None")

        if max_places is not None and max_places < 0:
            raise SizePlacesError("max_places= must be >=0 or None")

        in_bytes = int(Decimal(self))
        if abs(in_bytes) < 1000:
            return "%d %s" % (in_bytes, _(_bytes_letter))

        prev_prefix = None
        for prefix_item in _xlated_prefixes():
            factor, prefix, abbr = prefix_item
            newcheck = super(Size, self).__div__(Decimal(factor))

            if abs(newcheck) < 1000:
                # nice value, use this factor, prefix and abbr
                break
            prev_prefix = prefix_item
        else:
            # no nice value found, just return size in bytes
            return "%s %s" % (in_bytes, _(_bytes_letter))

        if abs(newcheck) < 10:
            if prev_prefix is not None:
                factor, prefix, abbr = prev_prefix # pylint: disable=unpacking-non-sequence
                newcheck = super(Size, self).__div__(Decimal(factor))
            else:
                # less than 10 KiB
                return "%s %s" % (in_bytes, _(_bytes_letter))

        retval = newcheck
        if places is not None:
            retval = round(newcheck, places)

        if max_places is not None:
            if places is not None:
                limit = min((places, max_places))
            else:
                limit = max_places
            retval = round(newcheck, limit)

        if retval == int(retval):
            # integer value, no point in showing ".0" at the end
            retval = int(retval)

        # Format the value with '.' as the decimal separator
        # If necessary, substitute with a localized separator before returning
        retval_str = str(retval)
        radix = locale.nl_langinfo(locale.RADIXCHAR)
        if radix != '.':
            retval_str = retval_str.replace('.', radix)

        # abbr and prefix are unicode objects so that lower/upper work correctly
        # Convert them to str before concatenating so that the return type is
        # str.
        # pylint: disable=undefined-loop-variable
        if abbr:
            return retval_str + " " + abbr.encode("utf-8") + _(_bytes_letter)
        else:
            return retval_str + " " + prefix.encode("utf-8") + P_("byte", "bytes", newcheck)

    def roundToNearest(self, unit, rounding=ROUND_DEFAULT):
        """
            :param str unit: a unit specifier
            :keyword rounding: which direction to round
            :type rounding: one of ROUND_UP, ROUND_DOWN, or ROUND_DEFAULT
            :returns: Size rounded to nearest whole specified unit
            :rtype: :class:`Size`
        """
        if rounding not in (ROUND_UP, ROUND_DOWN, ROUND_DEFAULT):
            raise ValueError("invalid rounding specifier")

        rounded = self.convertTo(unit).to_integral_value(rounding=rounding)
        return Size("%s %s" % (rounded, unit))
