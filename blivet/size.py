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

from decimal import Decimal
from decimal import InvalidOperation

from errors import *
from i18n import _, P_, N_

# Decimal prefixes for different size increments, along with the name
# and accepted abbreviation for the prefix.  These prefixes are all
# for 'bytes'.
_decimalPrefix = [(1000, N_("kilo"), N_("k")),
                  (1000**2, N_("mega"), N_("M")),
                  (1000**3, N_("giga"), N_("G")),
                  (1000**4, N_("tera"), N_("T")),
                  (1000**5, N_("peta"), N_("P")),
                  (1000**6, N_("exa"), N_("E")),
                  (1000**7, N_("zetta"), N_("Z")),
                  (1000**8, N_("yotta"), N_("Y"))]

# Binary prefixes for the different size increments.  Same structure
# as the above list.
_binaryPrefix = [(1024, N_("kibi"), N_("Ki")),
                 (1024**2, N_("mebi"), N_("Mi")),
                 (1024**3, N_("gibi"), N_("Gi")),
                 (1024**4, N_("tebi"), N_("Ti")),
                 (1024**5, N_("pebi"), N_("Pi")),
                 (1024**6, N_("exbi"), N_("Ei")),
                 (1024**7, N_("zebi"), N_("Zi")),
                 (1024**8, N_("yobi"), N_("Yi"))]

_bytes = [N_('B'), N_('b'), N_('byte'), N_('bytes')]
_prefixes = _binaryPrefix + _decimalPrefix

def _makeSpecs(prefix, abbr, xlate):
    """ Internal method used to generate a list of specifiers. """
    specs = []

    if prefix:
        if xlate:
            specs.append(prefix.lower() + _("byte"))
            specs.append(prefix.lower() + _("bytes"))
        else:
            specs.append(prefix.lower() + "byte")
            specs.append(prefix.lower() + "bytes")

    if abbr:
        if xlate:
            specs.append(abbr.lower() + _("b"))
        else:
            specs.append(abbr.lower() + "b")
        specs.append(abbr.lower())

    return specs

def _parseSpec(spec, xlate):
    """ Parse string representation of size. """
    if not spec:
        raise ValueError("invalid size specification", spec)

    # This regex isn't ideal, since \w matches both letters and digits,
    # but python doesn't provide a means to match only Unicode letters.
    # Probably the worst that will come of it is that bad specs will fail
    # more confusingly.
    m = re.match(r'(-?\s*[0-9.]+)\s*(\w*)$', spec.decode("utf-8").strip(), flags=re.UNICODE)
    if not m:
        raise ValueError("invalid size specification", spec)

    try:
        size = Decimal(m.groups()[0])
    except InvalidOperation:
        raise ValueError("invalid size specification", spec)

    if size < 0:
        raise SizeNotPositiveError("spec= param must be >=0")

    specifier = m.groups()[1].lower()
    if xlate:
        bytes = [_(b) for b in _bytes]
    else:
        bytes = _bytes
    if not specifier or specifier in bytes:
        return size

    if xlate:
        prefixes = [_(p) for p in _prefixes]
    else:
        prefixes = _prefixes
    for factor, prefix, abbr in prefixes:
        check = _makeSpecs(prefix, abbr, xlate)

        if specifier in check:
            return size * factor

    raise ValueError("invalid size specification", spec)

class Size(Decimal):
    """ Common class to represent storage device and filesystem sizes.
        Can handle parsing strings such as 45MB or 6.7GB to initialize
        itself, or can be initialized with a numerical size in bytes.
        Also generates human readable strings to a specified number of
        decimal places.
    """

    def __new__(cls, bytes=None, spec=None, en_spec=None):
        """ Initialize a new Size object.  Must pass only one of bytes, spec,
            or en_spec.  The bytes parameter is a numerical value for the size
            this object represents, in bytes.  The spec and en_spec parameters
            are string specifications of the size using any of the size
            specifiers in the _decimalPrefix or _binaryPrefix lists combined
            with the abbreviation for "byte" in the current locale ('b' or 'B'
            in English).  For example, to specify 640 kilobytes, you could pass
            any of these parameter:

                en_spec="640kb"
                en_spec="640 kb"
                en_spec="640KB"
                en_spec="640 KB"
                en_spec="640 kilobytes"

            en_spec strings are in English, while spec strings are in the
            language for the current locale. So Size objects initialized with
            constant strings should use something like Size(en_spec="3000 MB"),
            while Size objects created from user input should use 
            Size(spec=input).

            If you want to use spec or en_spec to pass a bytes value, you can
            use the localized version of the letter 'b' or 'B' or simply leave
            the specifier off and bytes will be assumed.
        """
        if (bytes and (spec or en_spec)) or (spec and (bytes or en_spec)) or \
                (en_spec and (bytes or spec)):
            raise SizeParamsError("only specify one parameter")

        if bytes is not None:
            if type(bytes).__name__ in ["int", "long", "float", 'Decimal'] and bytes >= 0:
                self = Decimal.__new__(cls, value=bytes)
            else:
                raise SizeNotPositiveError("bytes= param must be >=0")
        elif spec:
            self = Decimal.__new__(cls, value=_parseSpec(spec, True))
        elif en_spec:
            self = Decimal.__new__(cls, value=_parseSpec(en_spec, False))
        else:
            raise SizeParamsError("missing bytes=, spec=, or en_spec=")

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

    def convertTo(self, spec=None, en_spec=None):
        """ Return the size in the units indicated by the specifier.  The
            specifier can be prefixes from the _decimalPrefix and
            _binaryPrefix lists combined with the localized version of 'b' or
            'B' for abbreviations) or 'bytes' (for prefixes like kilo or mega).
            The size is returned as a Decimal.

            en_spec strings are treated as English, while spec strings are in
            language for the current locale.
        """
        if spec and en_spec:
            raise SizeParamsError("only specify one of spec= or en_spec=")

        if not (spec or en_spec):
            en_spec = "b"

        if spec:
            xlate = True
        else:
            spec = en_spec
            xlate = False

        spec = spec.lower()

        if xlate:
            bytes = [_(b) for b in _bytes]
        else:
            bytes = _bytes
        if spec in bytes:
            return self

        if xlate:
            prefixes = [_(p) for p in _prefixes]
        else:
            prefixes = _prefixes
        for factor, prefix, abbr in _prefixes:
            check = _makeSpecs(prefix, abbr, xlate)

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
            return "%s %s" % (check, _("B"))

        prefixes_xlated = [_(p) for p in _prefixes]
        for factor, prefix, abbr in prefixes_xlated:
            newcheck = super(Size, self).__div__(Decimal(factor))

            if newcheck < 1000:
                # nice value, use this factor, prefix and abbr
                break

        if places is not None:
            newcheck_str = str(newcheck)
            retval = newcheck_str
            if "." in newcheck_str:
                dot_idx = newcheck_str.index(".")
                retval = newcheck_str[:dot_idx+places+1]
        else:
            retval = self._trimEnd(str(newcheck))

        if max_places is not None:
            (whole, point, fraction) = retval.partition(".")
            if point and len(fraction) > max_places:
                if max_places == 0:
                    retval = whole
                else:
                    retval = "%s.%s" % (whole, fraction[:max_places])

        if abbr:
            return retval + " " + abbr + _("B")
        else:
            return retval + " " + prefix + P_("byte", "bytes", newcheck)
