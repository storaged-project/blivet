# threads.py
# Utilities related to multithreading.
#
# Copyright (C) 2014,2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from threading import RLock
from functools import wraps
from types import FunctionType
from abc import ABCMeta

from .flags import flags

blivet_lock = RLock(verbose=flags.debug_threads)


def exclusive(m):
    """ Run a callable while holding the global lock. """
    @wraps(m)
    def run_with_lock(*args, **kwargs):
        with blivet_lock:
            return m(*args, **kwargs)

    return run_with_lock


class SynchronizedMeta(type):
    """ Metaclass that wraps all methods with the exclusive decorator.

        To prevent specific methods from being wrapped, add the method name(s)
        to a class attribute called _unsynchronized_methods (list of str).
    """
    def __new__(cls, name, bases, dct):
        new_dct = {}
        blacklist = dct.get('_unsynchronized_methods', [])

        for n in dct:
            obj = dct[n]
            # Do not decorate class or static methods.
            if n in blacklist:
                pass
            elif isinstance(obj, FunctionType):
                obj = exclusive(obj)
            elif isinstance(obj, property):
                obj = property(fget=exclusive(obj.__get__),
                               fset=exclusive(obj.__set__),
                               fdel=exclusive(obj.__delattr__),
                               doc=obj.__doc__)

            new_dct[n] = obj

        return super(SynchronizedMeta, cls).__new__(cls, name, bases, new_dct)


class SynchronizedABCMeta(SynchronizedMeta, ABCMeta):
    pass
