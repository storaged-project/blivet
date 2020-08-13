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

import threading
from types import FunctionType
from abc import ABCMeta
from six import raise_from, wraps, PY3
import functools

from .errors import ThreadError
from .flags import flags

blivet_lock = threading.RLock(verbose=flags.debug_threads)


def _is_main_thread():
    if PY3:
        return threading.current_thread() == threading.main_thread()
    else:
        return threading.currentThread().name == "MainThread"


def exclusive(m):
    """ Run a callable while holding the global lock. """
    @wraps(m, set(functools.WRAPPER_ASSIGNMENTS) & set(dir(m)))
    def run_with_lock(*args, **kwargs):
        with blivet_lock:
            if _is_main_thread():
                exn_info = get_thread_exception()
                if exn_info[1]:
                    clear_thread_exception()
                    raise_from(ThreadError("raising queued exception"), exn_info[1])

            return m(*args, **kwargs)

    return run_with_lock


class SynchronizedMeta(type):
    """ Metaclass that wraps all methods with the exclusive decorator.

        To prevent specific methods from being wrapped, add the method name(s)
        to a class attribute called _unsynchronized_methods (list of str).
    """
    def __new__(cls, name, bases, dct):
        new_dct = {}

        for n in dct:
            obj = dct[n]
            # Do not decorate class or static methods.
            if n in dct.get('_unsynchronized_methods', []):
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


#
# Facilities for storing/retrieving information about an unhandled exception in a thread.
#
_exception_thread = None
_thread_exception = None


def save_thread_exception(thread, exc_info):
    global _exception_thread
    global _thread_exception

    if _exception_thread is None or _thread_exception is None:
        return

    _exception_thread = thread
    _thread_exception = exc_info


def clear_thread_exception():
    global _exception_thread
    global _thread_exception

    _exception_thread = None
    _thread_exception = None


def get_thread_exception():
    return (_exception_thread, _thread_exception)
