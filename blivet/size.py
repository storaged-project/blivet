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
import sys
from collections import namedtuple

from decimal import Decimal
from decimal import InvalidOperation
from decimal import ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
import six

from .errors import SizePlacesError
from .i18n import _, N_
from .util import stringize, unicodeize

ROUND_DEFAULT = ROUND_HALF_UP

# Container for size unit prefix information
_Prefix = namedtuple("Prefix", ["factor", "prefix", "abbr"])

_DECIMAL_FACTOR = 10 ** 3
_BINARY_FACTOR = 2 ** 10

_BYTES_SYMBOL = N_("B")
_BYTES_WORDS = (N_("bytes"), N_("byte"))

# Symbolic constants for units
B = _Prefix(1, "", "")

KB = _Prefix(_DECIMAL_FACTOR ** 1, N_("kilo"), N_("k"))
MB = _Prefix(_DECIMAL_FACTOR ** 2, N_("mega"), N_("M"))
GB = _Prefix(_DECIMAL_FACTOR ** 3, N_("giga"), N_("G"))
TB = _Prefix(_DECIMAL_FACTOR ** 4, N_("tera"), N_("T"))
PB = _Prefix(_DECIMAL_FACTOR ** 5, N_("peta"), N_("P"))
EB = _Prefix(_DECIMAL_FACTOR ** 6, N_("exa"), N_("E"))
ZB = _Prefix(_DECIMAL_FACTOR ** 7, N_("zetta"), N_("Z"))
YB = _Prefix(_DECIMAL_FACTOR ** 8, N_("yotta"), N_("Y"))

KiB = _Prefix(_BINARY_FACTOR ** 1, N_("kibi"), N_("Ki"))
MiB = _Prefix(_BINARY_FACTOR ** 2, N_("mebi"), N_("Mi"))
GiB = _Prefix(_BINARY_FACTOR ** 3, N_("gibi"), N_("Gi"))
TiB = _Prefix(_BINARY_FACTOR ** 4, N_("tebi"), N_("Ti"))
PiB = _Prefix(_BINARY_FACTOR ** 5, N_("pebi"), N_("Pi"))
EiB = _Prefix(_BINARY_FACTOR ** 6, N_("exbi"), N_("Ei"))
ZiB = _Prefix(_BINARY_FACTOR ** 7, N_("zebi"), N_("Zi"))
YiB = _Prefix(_BINARY_FACTOR ** 8, N_("yobi"), N_("Yi"))

# Categories of symbolic constants
_DECIMAL_PREFIXES = [KB, MB, GB, TB, PB, EB, ZB, YB]
_BINARY_PREFIXES = [KiB, MiB, GiB, TiB, PiB, EiB, ZiB, YiB]
_EMPTY_PREFIX = B

if six.PY2:
    _ASCIIlower_table = string.maketrans(string.ascii_uppercase, string.ascii_lowercase) # pylint: disable=no-member
else:
    _ASCIIlower_table = str.maketrans(string.ascii_uppercase, string.ascii_lowercase) # pylint: disable=no-member

def _lowerASCII(s):
    """Convert a string to lowercase using only ASCII character definitions.

       :param s: string instance to convert
       :type s: str or bytes
       :returns: lower-cased string
       :rtype: str
    """

    # XXX: Python 3 has str.maketrans() and bytes.maketrans() so we should
    # ideally use one or the other depending on the type of 's'. But it turns
    # out we expect this function to always return string even if given bytes.
    if not six.PY2 and isinstance(s, bytes):
        s = s.decode(sys.getdefaultencoding())
    return s.translate(_ASCIIlower_table) # pylint: disable=no-member

def _makeSpec(prefix, suffix, xlate, lowercase=True):
    """ Synthesizes a whole word from prefix and suffix.

        :param str prefix: a prefix
        :param str suffixes: a suffix
        :param bool xlate: if True, treat as locale specific
        :param bool lowercase: if True, make all lowercase

        :returns:  whole word
        :rtype: str
    """
    if xlate:
        word = (_(prefix) + _(suffix))
        return word.lower() if lowercase else word
    else:
        word = prefix + suffix
        return _lowerASCII(word) if lowercase else word

def unitStr(unit, xlate=False):
    """ Return a string representation of unit.

        :param unit: a named unit, e.g., KiB
        :param bool xlate: if True, translate to current locale
        :rtype: some kind of string type
        :returns: string representation of unit
    """
    return _makeSpec(unit.abbr, _BYTES_SYMBOL, xlate, lowercase=False)

def parseUnits(spec, xlate):
    """ Parse a unit specification and return corresponding factor.

        :param spec: a units specifier
        :type spec: any type of string like object
        :param bool xlate: if True, assume locale specific

        :returns: a named constant corresponding to spec, if found
        :rtype: _Prefix or NoneType

        Looks first for exact matches for a specifier, but, failing that,
        searches for partial matches for abbreviations.

        Normalizes units to lowercase, e.g., MiB and mib are treated the same.
    """
    if spec == "":
        return B

    if xlate:
        spec = spec.lower()
    else:
        spec = _lowerASCII(spec)

    # Search for complete matches
    for unit in [_EMPTY_PREFIX] + _BINARY_PREFIXES + _DECIMAL_PREFIXES:
        if spec == _makeSpec(unit.abbr, _BYTES_SYMBOL, xlate) or \
           spec in (_makeSpec(unit.prefix, s, xlate) for s in _BYTES_WORDS):
            return unit

    # Search for unambiguous partial match among binary abbreviations
    matches = [p for p in _BINARY_PREFIXES if _makeSpec(p.abbr, "", xlate).startswith(spec)]
    if len(matches) == 1:
        return matches[0]

    return None

def parseSpec(spec):
    """ Parse string representation of size.

        :param spec: the specification of a size with, optionally, units
        :type spec: any type of string like object
        :returns: numeric value of the specification in bytes
        :rtype: Decimal

        :raises ValueError: if spec is unparseable

        Tries to parse the spec first as English, if that fails, as
        a locale specific string.
    """

    if not spec:
        raise ValueError("invalid size specification", spec)

    # Replace the localized radix character with a .
    radix = locale.nl_langinfo(locale.RADIXCHAR)
    if radix != '.':
        spec = spec.replace(radix, '.')

    m = re.match(r'(?P<numeric>(-|\+)?\s*(?P<base>([0-9]+)|([0-9]*\.[0-9]+)|([0-9]+\.[0-9]*))(?P<exp>(e|E)(-|\+)[0-9]+)?)\s*(?P<rest>[^\s]*)$', spec.strip())
    if not m:
        raise ValueError("invalid size specification", spec)

    try:
        size = Decimal(m.group('numeric'))
    except InvalidOperation:
        raise ValueError("invalid size specification", spec)

    specifier = m.group('rest')

    # First try to parse as English.
    try:
        if six.PY2:
            spec_ascii = str(specifier.decode("ascii"))
        else:
            spec_ascii = bytes(specifier, 'ascii')
    except (UnicodeDecodeError, UnicodeEncodeError):
        # String contains non-ascii characters, so can not be English.
        pass
    else:
        unit = parseUnits(spec_ascii, False)
        if unit is not None:
            return size * unit.factor

    # No English match found, try localized size specs.
    if six.PY2:
        if isinstance(specifier, unicode):
            spec_local = specifier
        else:
            spec_local = specifier.decode("utf-8")
    else:
        spec_local = specifier

    unit = parseUnits(spec_local, True)
    if unit is not None:
        return size * unit.factor

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
            size = parseSpec(value)
        elif isinstance(value, (six.integer_types, float, Decimal)):
            size = Decimal(value)
        elif isinstance(value, Size):
            size = Decimal(value.convertTo())
        else:
            raise ValueError("invalid value %s for size" % value)

        # drop any partial byte
        size = size.to_integral_value(rounding=ROUND_DOWN)
        self = Decimal.__new__(cls, value=size, context=context)
        return self

    # Force str and unicode types since the translated sizespec may be unicode
    def _toString(self):
        return self.humanReadable()

    def __str__(self, eng=False, context=None):
        return stringize(self._toString())

    def __unicode__(self):
        return unicodeize(self._toString())

    def __repr__(self):
        return "Size('%s')" % self

    def __deepcopy__(self, memo):
        return Size(self.convertTo())

    # pickling support for Size
    # see https://docs.python.org/3/library/pickle.html#object.__reduce__
    def __reduce__(self):
        return (self.__class__, (self.convertTo(),))

    def __add__(self, other, context=None):
        return Size(Decimal.__add__(self, other))

    # needed to make sum() work with Size arguments
    def __radd__(self, other, context=None):
        return Size(Decimal.__radd__(self, other))

    def __sub__(self, other, context=None):
        return Size(Decimal.__sub__(self, other))

    def __mul__(self, other, context=None):
        return Size(Decimal.__mul__(self, other))
    __rmul__ = __mul__

    def __div__(self, other, context=None):
        return Size(Decimal.__div__(self, other))

    def __mod__(self, other, context=None):
        return Size(Decimal.__mod__(self, other))

    def convertTo(self, spec=None):
        """ Return the size in the units indicated by the specifier.

            :param spec: a units specifier
            :returns: a numeric value in the units indicated by the specifier
            :rtype: Decimal
        """
        return Decimal(self) / Decimal((spec or B).factor)

    def humanReadable(self, max_places=2, strip=True, min_value=1, xlate=True):
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
            :param bool xlate: If True, translate for current locale
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
        limit = _BINARY_FACTOR * min_value
        for unit in [_EMPTY_PREFIX] + _BINARY_PREFIXES:
            newcheck = self.convertTo(unit)

            if abs(newcheck) < limit:
                break

        if max_places is not None:
            newcheck = newcheck.quantize(Decimal(10) ** -max_places)

        retval_str = str(newcheck)

        if '.' in retval_str and strip:
            retval_str = retval_str.rstrip("0").rstrip(".")

        if xlate:
            radix = locale.nl_langinfo(locale.RADIXCHAR)
            if radix != '.':
                retval_str = retval_str.replace('.', radix)

        # pylint: disable=undefined-loop-variable
        return retval_str + " " + _makeSpec(unit.abbr, _BYTES_SYMBOL, xlate, lowercase=False)

    def roundToNearest(self, unit, rounding=ROUND_DEFAULT):
        """ Rounds to nearest unit specified as a named constant or a Size.

            :param unit: a unit specifier
            :type unit: a named constant like KiB, or any non-negative Size
            :keyword rounding: which direction to round
            :type rounding: one of ROUND_UP, ROUND_DOWN, or ROUND_DEFAULT
            :returns: Size rounded to nearest whole specified unit
            :rtype: :class:`Size`

            If unit is Size(0), returns Size(0).
        """
        if rounding not in (ROUND_UP, ROUND_DOWN, ROUND_DEFAULT):
            raise ValueError("invalid rounding specifier")

        factor = getattr(unit, "factor", unit)

        if factor == Size(0):
            return Size(0)

        factor = Decimal(factor)
        if factor < 0:
            raise ValueError("invalid rounding unit: %s" % factor)

        rounded = (Decimal(self) / factor).to_integral_value(rounding=rounding)
        return Size(rounded * factor)
