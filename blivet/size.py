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

from bytesize import bytesize

# we just need to make these objects available here
# pylint: disable=unused-import
from bytesize.bytesize import B, KiB, MiB, GiB, TiB, PiB, EiB, ZiB, YiB, KB, MB, GB, TB, PB, EB, ZB, YB
from bytesize.bytesize import ROUND_UP, ROUND_DOWN, ROUND_HALF_UP


def unit_str(unit, xlate=False):
    """ Return a string representation of unit.

        :param unit: a named unit, e.g., KiB
        :param bool xlate: if True, translate to current locale
        :rtype: some kind of string type
        :returns: string representation of unit
    """
    return bytesize.unit_str(unit, xlate)


class Size(bytesize.Size):
    """ Common class to represent storage device and filesystem sizes.
        Can handle parsing strings such as 45MB or 6.7GB to initialize
        itself, or can be initialized with a numerical size in bytes.
        Also generates human readable strings to a specified number of
        decimal places.
    """

    def __abs__(self):
        return Size(bytesize.Size.__abs__(self))

    def __add__(self, other):
        return Size(bytesize.Size.__add__(self, other))

    # needed to make sum() work with Size arguments
    def __radd__(self, other):
        return Size(bytesize.Size.__radd__(self, other))

    def __sub__(self, other):
        return Size(bytesize.Size.__sub__(self, other))

    def __rsub__(self, other):
        return Size(bytesize.Size.__rsub__(self, other))

    def __mul__(self, other):
        return Size(bytesize.Size.__mul__(self, other))
    __rmul__ = __mul__

    def __div__(self, other):       # pylint: disable=unused-argument
        ret = bytesize.Size.__div__(self, other)  # pylint: disable=no-member
        if isinstance(ret, bytesize.Size):
            ret = Size(ret)

        return ret

    def __truediv__(self, other):
        ret = bytesize.Size.__truediv__(self, other)
        if isinstance(ret, bytesize.Size):
            ret = Size(ret)

        return ret

    def __floordiv__(self, other):
        ret = bytesize.Size.__floordiv__(self, other)
        if isinstance(ret, bytesize.Size):
            ret = Size(ret)

        return ret

    def __mod__(self, other):
        return Size(bytesize.Size.__mod__(self, other))

    def __deepcopy__(self, memo_dict):
        return Size(bytesize.Size.__deepcopy__(self, memo_dict))

    # pylint: disable=arguments-differ
    def convert_to(self, spec=None):
        """ Return the size in the units indicated by the specifier.

            :param spec: a units specifier
            :type spec: a units specifier or :class:`Size`
            :returns: a numeric value in the units indicated by the specifier
            :rtype: Decimal
            :raises ValueError: if Size unit specifier is non-positive

            .. versionadded:: 1.6
               spec parameter may be Size as well as units specifier.
        """
        if isinstance(spec, Size):
            if spec == Size(0):
                raise ValueError("cannot convert to 0 size")
            return bytesize.Size.__truediv__(self, spec)
        spec = B if spec is None else spec
        return bytesize.Size.convert_to(self, spec)

    def human_readable(self, min_unit=B, max_places=2, xlate=True):
        """ Return a string representation of this size with appropriate
            size specifier and in the specified number of decimal places.
            Values are always represented using binary not decimal units.
            For example, if the number of bytes represented by this size
            is 65531, expect the representation to be something like
            64.00 KiB, not 65.53 KB.

            :param min_unit: the smallest unit the returned representation should use
            :type min_unit: one of the B, KiB, MiB,... (binary) units from this module
                            or str ("B", "KiB",...)
            :param max_places: number of decimal places to use
            :type max_places: an integer type or NoneType
            :param bool xlate: If True, translate for current locale
            :returns: a representation of the size
            :rtype: str

        """

        if max_places is None:
            max_places = -1
        return bytesize.Size.human_readable(self, min_unit, max_places, xlate)

    # pylint: disable=arguments-differ
    def round_to_nearest(self, size, rounding):
        """ Rounds to nearest unit specified as a named constant or a Size.

            :param size: a size specifier
            :type size: a named constant like KiB, or any non-negative Size
            :keyword rounding: which direction to round
            :type rounding: one of ROUND_UP, ROUND_DOWN, or ROUND_HALF_UP
            :returns: Size rounded to nearest whole specified unit
            :rtype: :class:`Size`

            If size is Size(0), returns Size(0).
        """
        if rounding not in (ROUND_UP, ROUND_DOWN, ROUND_HALF_UP):
            raise ValueError("invalid rounding specifier")

        if isinstance(size, Size):
            if size.get_bytes() == 0:
                return Size(0)
            elif size < Size(0):
                raise ValueError("invalid rounding size: %s" % size)

        return Size(bytesize.Size.round_to_nearest(self, size, rounding))

    def ensure_percent_reserve(self, percent):
        """Get a new size with given space reserve.

            :param percent: number of percent to reserve
            :returns: a new size with :param:`percent` space reserve
            :rtype: :class:`Size`

            Best described with an example:
            >>> Size("80 GiB").ensure_percent_reserve(20)
            Size (100 GiB)

            This method returns a new size in which there's a :param:`percent`%
            reserve (on top of the original size). In other words::

              with_reserve - orig_size == with_reserve * (percent / 100)

            except that due to float arithmetics the numbers are unlikely to be
            exactly equal.
        """
        return Size(self * (1 / (1 - (percent / 100))))
