# threads.py
# Utilities related to multithreading.
#
# Copyright (C) 2014,2015  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from threading import _RLock, currentThread
from functools import wraps
from types import FunctionType
from abc import ABCMeta

import logging
log = logging.getLogger("blivet")

class NoisyRLock(_RLock):
    def __enter__(self, *args, **kwargs):
        log.debug("enter[1]: %s (%s)", self, currentThread().name)
        super(NoisyRLock, self).__enter__(*args, **kwargs)
        log.debug("enter[2]: %s (%s)", self, currentThread().name)

    def __exit__(self, *args, **kwargs):
        log.debug("exit[1]: %s (%s)", self, currentThread().name)
        super(NoisyRLock, self).__exit__(*args, **kwargs)
        log.debug("exit[2]: %s (%s)", self, currentThread().name)

#blivet_lock = NoisyRLock()
blivet_lock = _RLock()

def exclusive(m):
    """ Run a bound method after aqcuiring the instance's lock. """
    @wraps(m)
    def run_with_lock(*args, **kwargs):
        # When the decorator is applied during creation of the method's class
        # instance we have a function object -- not a method. As a result, we
        # cannot use m.__self__ and instead must rely on the fact that the
        # instance is always passed as the first argument to the method.
        #log.debug("thread %s acquiring lock %s before calling %s",
        #          currentThread().name, blivet_lock, m.func_code.co_name)
        with blivet_lock:
            #log.debug("thread %s running %s", currentThread().name, m.func_code.co_name)
            return m(*args, **kwargs)

    return run_with_lock

class SynchronizedMeta(type):
    """ Metaclass that wraps all methods with the exclusive decorator.

        To prevent specific methods from being wrapped, add the method name(s)
        to a class attribute called _unsynchronized_methods (list of str).
    """
    def __new__(cls, name, bases, dct):
        wrapped = {}
        blacklist = dct.get('_unsynchronized_methods', [])
        for n in dct:
            obj = dct[n]
            # Do not decorate class or static methods.
            if type(dct[n]) is FunctionType:
                if n not in blacklist:
                    obj = exclusive(obj)

            wrapped[n] = obj

        return super(SynchronizedMeta, cls).__new__(cls, name, bases, wrapped)

class SynchronizedABCMeta(SynchronizedMeta, ABCMeta):
    pass
