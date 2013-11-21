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

from errors import *
from i18n import _, P_, N_

# Container for size unit prefix information
_Prefix = namedtuple("Prefix", ["factor", "prefix", "abbr"])

# Decimal prefixes for different size increments, along with the name
# and accepted abbreviation for the prefix.  These prefixes are all
# for 'bytes'.
_decimalPrefix = [_Prefix(1000, N_("kilo"), N_("k")),
                  _Prefix(1000**2, N_("mega"), N_("M")),
                  _Prefix(1000**3, N_("giga"), N_("G")),
                  _Prefix(1000**4, N_("tera"), N_("T")),
                  _Prefix(1000**5, N_("peta"), N_("P")),
                  _Prefix(1000**6, N_("exa"), N_("E")),
                  _Prefix(1000**7, N_("zetta"), N_("Z")),
                  _Prefix(1000**8, N_("yotta"), N_("Y"))]

# Binary prefixes for the different size increments.  Same structure
# as the above list.
_binaryPrefix = [_Prefix(1024, N_("kibi"), N_("Ki")),
                 _Prefix(1024**2, N_("mebi"), N_("Mi")),
                 _Prefix(1024**3, N_("gibi"), N_("Gi")),
                 _Prefix(1024**4, N_("tebi"), None),
                 _Prefix(1024**5, N_("pebi"), None),
                 _Prefix(1024**6, N_("ebi"), None),
                 _Prefix(1024**7, N_("zebi"), None),
                 _Prefix(1024**8, N_("yobi"), None)]

_bytes = [N_('b'), N_('byte'), N_('bytes')]
_prefixes = _decimalPrefix + _binaryPrefix

# Translated versions of the byte and prefix arrays
# All strings are decoded as utf-8 so that locale-specific upper/lower functions work
def _xlated_bytes():
    return [_(b).decode("utf-8") for b in _bytes]

def _xlated_prefixes():
    _xlated_list = []
    for factor, prefix, abbr in _prefixes:
        _xlated_prefix = _(prefix)
        _xlated_abbr = _(abbr)
        if _xlated_prefix:
            _xlated_prefix = _xlated_prefix.decode("utf-8")
        if _xlated_abbr:
            _xlated_abbr = _xlated_abbr.decode("utf-8")

        _xlated_list.append(_Prefix(factor, _xlated_prefix, _xlated_abbr))

    return _xlated_list

_ASCIIlower_table = string.maketrans(string.ascii_uppercase, string.ascii_lowercase)
def _lowerASCII(s):
    """Convert a string to lowercase using only ASCII character definitions."""
    return string.translate(s, _ASCIIlower_table)

def _makeSpecs(prefix, abbr, xlate):
    """ Internal method used to generate a list of specifiers. """
    specs = []

    if prefix:
        if xlate:
            specs.append(prefix.lower() + _("byte").decode("utf-8"))
            specs.append(prefix.lower() + _("bytes").decode("utf-8"))
        else:
            specs.append(_lowerASCII(prefix) + "byte")
            specs.append(_lowerASCII(prefix) + "bytes")

    if abbr:
        if xlate:
            specs.append(abbr.lower() + _("b").decode("utf-8"))
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

    if size < 0:
        raise SizeNotPositiveError("spec= param must be >=0")

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
    except UnicodeDecodeError:
        pass
    else:
        if spec_ascii in _bytes or not spec_ascii:
            return size

        for factor, prefix, abbr in _prefixes:
            check = _makeSpecs(prefix, abbr, False)

            if spec_ascii in check:
                return size * factor

    # No English match found, try localized size specs. Accept any utf-8
    # character and leave the result as a unicode object.
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

    def __new__(cls, bytes=None,  spec=None):
        """ Initialize a new Size object.  Must pass either bytes or spec,
            but not both.  The bytes parameter is a numerical value for
            the size this object represents, in bytes.  The spec parameter
            is a string specification of the size using any of the size
            specifiers in the _decimalPrefix or _binaryPrefix lists combined
            with a 'b' or 'B'.  For example, to specify 640 kilobytes, you
            could pass any of these parameter:

                spec="640kb"
                spec="640 kb"
                spec="640KB"
                spec="640 KB"
                spec="640 kilobytes"

            If you want to use spec to pass a bytes value, you can use the
            letter 'b' or 'B' or simply leave the specifier off and bytes
            will be assumed.
        """
        if bytes and spec:
            raise SizeParamsError("only specify one parameter")

        if bytes is not None:
            if type(bytes).__name__ in ["int", "long", "float", 'Decimal'] and bytes >= 0:
                self = Decimal.__new__(cls, value=bytes)
            else:
                raise SizeNotPositiveError("bytes= param must be >=0")
        elif spec:
            self = Decimal.__new__(cls, value=_parseSpec(spec))
        else:
            raise SizeParamsError("missing bytes= or spec=")

        return self

    def __str__(self, context=None):
        return self.humanReadable()

    def __repr__(self):
        return "Size('%s')" % self

    def __add__(self, other, context=None):
        return Size(bytes=Decimal.__add__(self, other, context=context))

    # needed to make sum() work with Size arguments
    def __radd__(self, other, context=None):
        return Size(bytes=Decimal.__radd__(self, other, context=context))

    def __sub__(self, other, context=None):
        # subtraction is implemented using __add__ and negation, so we'll
        # be getting passed a Size
        return Decimal.__sub__(self, other, context=context)

    def __mul__(self, other, context=None):
        return Size(bytes=Decimal.__mul__(self, other, context=context))

    def __div__(self, other, context=None):
        return Size(bytes=Decimal.__div__(self, other, context=context))

    def _trimEnd(self, val):
        """ Internal method to trim trailing zeros. """
        val = re.sub(r'(\.\d*?)0+$', '\\1', val)
        while val.endswith('.'):
            val = val[:-1]

        return val

    def convertTo(self, spec="b"):
        """ Return the size in the units indicated by the specifier.  The
            specifier can be prefixes from the _decimalPrefix and
            _binaryPrefix lists combined with 'b' or 'B' for abbreviations)
            or 'bytes' (for prefixes like kilo or mega).  The size is
            returned as a Decimal.
        """
        spec = spec.lower()

        if spec in _bytes:
            return self

        for factor, prefix, abbr in _prefixes:
            check = _makeSpecs(prefix, abbr, False)

            if spec in check:
                return Decimal(self / Decimal(factor))

        return None

    def humanReadable(self, places=None, max_places=2):
        """ Return a string representation of this size with appropriate
            size specifier and in the specified number of decimal places
            (default: auto with a maximum of 2 decimal places).
        """
        if places is not None and places < 0:
            raise SizePlacesError("places= must be >=0 or None")

        if max_places is not None and max_places < 0:
            raise SizePlacesError("max_places= must be >=0 or None")

        check = self._trimEnd("%d" % self)

        if Decimal(check) < 1000:
            return "%s B" % check

        for factor, prefix, abbr in _xlated_prefixes():
            newcheck = super(Size, self).__div__(Decimal(factor))

            if newcheck < 1000:
                # nice value, use this factor, prefix and abbr
                break

        # Format the value with '.' as the decimal separator
        # If necessary, substitute with a localized separator before returning
        if places is not None:
            fmt = "%%.%df" % places
            retval = fmt % newcheck
        else:
            retval = self._trimEnd("%f" % newcheck)

        if max_places is not None:
            (whole, point, fraction) = retval.partition(".")
            if point and len(fraction) > max_places:
                if max_places == 0:
                    retval = whole
                else:
                    retval = "%s%s%s" % (whole, point, fraction[:max_places])

        radix = locale.nl_langinfo(locale.RADIXCHAR)
        if radix != '.':
            retval = retval.replace('.', radix)

        if abbr:
            return retval + " " + abbr + _("B").decode("utf-8")
        else:
            return retval + " " + prefix + P_("byte", "bytes", newcheck).decode("utf-8")
