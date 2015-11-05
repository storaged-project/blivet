# i18n.py
# Internationalization functions
#
# Copyright (C) 2013  Red Hat, Inc.
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
# Red Hat Author(s): David Shea <dshea@redhat.com>

__all__ = ["_", "N_", "P_"]

import gettext
import locale
import six

# Create and cache a translations object for the current LC_MESSAGES value
_cached_translations = {}


def _get_translations():
    # Use setlocale instead of getlocale even though that looks like it makes no sense,
    # since this way we're just reading environment variables instead of mandating some
    # sequence of setlocale calls or whatever, since this is also how the gettext functions
    # behave. This differs from the behavior of gettext.find if $LANGUAGE is being used, but
    # on the other hand no one uses $LANGUAGE.
    lc_messages = locale.setlocale(locale.LC_MESSAGES, None)
    if lc_messages not in _cached_translations:
        _cached_translations[lc_messages] = gettext.translation("blivet", fallback=True)
    return _cached_translations[lc_messages]


N_ = lambda x: x

# In Python 2, return the translated strings as unicode objects.
# yes, pylint, the lambdas are necessary, because I want _get_translations()
# evaluated on every call.
# pylint: disable=unnecessary-lambda
if six.PY2:
    _ = lambda x: _get_translations().ugettext(x) if x != "" else u""
    P_ = lambda x, y, z: _get_translations().ungettext(x, y, z)
else:
    _ = lambda x: _get_translations().gettext(x) if x != "" else ""
    P_ = lambda x, y, z: _get_translations().ngettext(x, y, z)
