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

from threading import RLock, Condition, currentThread
from functools import wraps
from types import FunctionType
from abc import ABCMeta
import copy
import pprint

from .flags import flags
from .util import ObjectID

import logging
log = logging.getLogger("blivet")

blivet_lock = RLock(verbose=flags.debug_threads)

KEY_PRESENT = 'KEY_PRESENT'
KEY_ABSENT = 'KEY_ABSENT'

class StorageEventBase(ObjectID):
    _flag_names = ["starting", "stopping", "creating", "destroying", "resizing",
                   "changing"]

    def __init__(self):
        self._flags = dict()
        self._validate = dict()
        self.reset()

    @property
    def active(self):
        return any(self._flags.values())

    def reset(self):
        self._flags = {flag_name: False for flag_name in self._flag_names}
        self._validate = dict()

    def _get_flag(self, flag):
        return self._flags[flag]

    def _set_flag(self, flag, val):
        if val and self.active:
            raise RuntimeError("only one flag can be active at a time")

        self._flags[flag] = val

    starting = property(lambda s: s._get_flag("starting"),
                        lambda s,v: s._set_flag("starting", v))
    stopping = property(lambda s: s._get_flag("stopping"),
                        lambda s,v: s._set_flag("stopping", v))
    creating = property(lambda s: s._get_flag("creating"),
                        lambda s,v: s._set_flag("creating", v))
    destroying = property(lambda s: s._get_flag("destroying"),
                        lambda s,v: s._set_flag("destroying", v))
    resizing = property(lambda s: s._get_flag("resizing"),
                        lambda s,v: s._set_flag("resizing", v))
    changing = property(lambda s: s._get_flag("changing"),
                        lambda s,v: s._set_flag("changing", v))

    def info_update(self, *args, **kwargs):
        self._validate.update(*args, **kwargs)

    def info_remove(self, key):
        if key in self._validate:
            del self._validate[key]

    def validate(self, info):
        """ Verify that any udev key/value pairs are set correctly. """
        log.debug("validating %s udev info %s", self,
                                                pprint.pformat(self._validate))
        log.debug("ref: %s", pprint.pformat(dict(info)))
        valid = True
        for (key, value) in self._validate.items():
            if value == KEY_ABSENT and key in info:
                valid = False
                break
            elif value == KEY_PRESENT and key not in info:
                valid = False
                break
            elif value not in (KEY_ABSENT, KEY_PRESENT) and \
                 (key not in info or info[key] != value):
                valid = False
                break

        log.debug("returning %s", valid)
        return valid

class StorageEventSynchronizer(StorageEventBase):
    """ Manager for shared state related to storage operations.

        Each :class:`~.devices.StorageDevice` and
        :class:`~.formats.DeviceFormat` instance contains an instance of this
        class.

        It is used by uevent handlers to notify
        :class:`~.devices.StorageDevice` or :class:`~.formats.DeviceFormat`
        instances when operations like create, destroy, setup, teardown have
        completed.

        It only provides wait and notify methods, both of which are merely
        wrappers around the internal threading.Condition instance.
    """
    def __init__(self, passthrough=False):
        super(StorageEventSynchronizer, self).__init__()
        self._cv = Condition(blivet_lock, verbose=flags.debug_threads)
        self.passthrough = passthrough

    def __deepcopy__(self, memo):
        new = self.__class__.__new__(self.__class__)
        memo[id(self)] = new
        for (attr, value) in self.__dict__.items():
            if attr == "_cv":
                setattr(new, attr, Condition(blivet_lock,
                                             verbose=flags.debug_threads))
            else:
                setattr(new, attr, copy.deepcopy(value, memo))

        return new

    def wait(self, timeout=None):
        if self.passthrough or not flags.uevents:
            return

        args = [] if timeout is None else [timeout]
        self._cv.wait(*args)

    def notify(self, n=None):
        if self.passthrough or not flags.uevents:
            return

        args = [] if n is None else [n]
        self._cv.notify(*args)

class StorageEventSynchronizerSet(StorageEventBase):
    def __init__(self, ss_list):
        self.ss_list = ss_list
        super(StorageEventSynchronizerSet, self).__init__()

    def _get_flag(self, flag):
        if flag in ("creating", "destroying"):
            _flag = "changing"
        else:
            _flag = flag

        # they have to all be the same value
        vals = [getattr(ss, _flag) for ss in self.ss_list]
        if not (all(vals) or not any(vals)):
            raise RuntimeError("sync set members out of sync")
        return super(StorageEventSynchronizerSet, self)._get_flag(flag)

    def _set_flag(self, flag, val):
        if flag in ("creating", "destroying"):
            # create/destroy actions on parents manifest as generic change
            # events, ie: not noted as related to a create/destroy
            _flag = "changing"
        else:
            _flag = flag

        vals = [getattr(ss, _flag) for ss in self.ss_list]
        if not (all(vals) or not any(vals)):
            raise RuntimeError("sync set members out of sync")

        for ss in self.ss_list:
            setattr(ss, _flag, val)

        super(StorageEventSynchronizerSet, self)._set_flag(flag, val)

    def wait(self, timeout=None):
        for ss in self.ss_list:
            ss.wait(timeout=timeout)

    def notify(self, n=None):
        for ss in self.ss_list:
            ss.notify(n=n)

    def info_update(self, *args, **kwargs):
        super(StorageEventSynchronizerSet, self).info_update(*args, **kwargs)
        for ss in self.ss_list:
            ss.info_update(*args, **kwargs)

    def info_remove(self, key):
        super(StorageEventSynchronizerSet, self).info_remove(key)
        for ss in self.ss_list:
            ss.info_remove(key)

    def reset(self):
        super(StorageEventSynchronizerSet, self).reset()
        for ss in self.ss_list:
            ss.reset()

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
