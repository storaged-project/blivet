# event.py
# Event management classes.
#
# Copyright (C) 2015  Red Hat, Inc.
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

import abc
import copy
from collections import deque
from threading import RLock, Timer
import pyudev
from six import add_metaclass

from . import udev
from . import util
from .errors import EventHandlerError, EventParamError, EventQueueEmptyError
from .flags import flags

import logging
log = logging.getLogger("blivet")

##
## Event
##
@add_metaclass(abc.ABCMeta)
class Event(util.ObjectID):
    def __init__(self, action, info):
        """
            :param str action: a string describing the type of event
            :param info: information about the device

            The info parameter can be of any type provided that the subclass
            using it does so appropriately.
        """
        self.action = action
        self.info = info

    @abc.abstractproperty
    def device(self):
        """ Basename (friendly) of device this event acted upon. """
        return None

    def __str__(self):
        return "%s %s [%d]" % (self.action, self.device, self.id)

class UdevEvent(Event):
    def __init__(self, action, info):
        """
            :param str action: a string describing the type of event
            :param :class:`pyudev.Device` info: udev db entry
        """
        super(UdevEvent, self).__init__(action, info)

    @property
    def device(self):
        return udev.device_get_name(self.info)

##
## EventQueue
##
class EventQueue(object):
    def __init__(self):
        self._queue = deque()
        self._lock = RLock()

        # list of (device, action, count) tuples
        self._blacklist = []

    def _blacklist_match(self, event):
        """ Return True if this event should be ignored """
        match = None
        for (device, action, count) in self._blacklist:
            if ((device is None or event.device == device) and
                (action is None or event.action == action)):
                match = (device, action, count)
                break

        return match

    def _blacklist_update(self, entry):
        """ Update blacklist after a hit at the specified index. """
        count = entry[2]
        if count == 1:
            self._blacklist.remove(entry)
        elif count > 1:
            idx = self._blacklist.index(entry)
            self._blacklist[idx] = (entry[0], entry[1], count - 1)

    def enqueue(self, event):
        with self._lock:
            bl_entry = self._blacklist_match(event)
            if bl_entry is None:
                self._queue.append(event)
            else:
                self._blacklist_update(bl_entry)

    def dequeue(self):
        """ Dequeue and return the next event.

            :returns: the next uevent
            :rtype: :class:`~.Event`
            :raises class:`~.errors.EventQueueEmptyError` if the queue is empty
        """
        with self._lock:
            if not self._queue:
                raise EventQueueEmptyError()

            return self._queue.popleft()

    def blacklist_add(self, device=None, action=None, count=1):
        """ Ignore future events.

            :keyword str device: ignore events on the named device
            :keyword str action: ignore events of the specified type
            :keyword int count: number of events to ignore

            device of None means blacklist events on all devices
            action of None means blacklist all event types
            count of 0 means permanently blacklist this device/action pair
        """
        self._blacklist.append((device, action, count))

    def __list__(self):
        return list(self._queue)

    def __iter__(self):
        return iter(self._queue)

    def __deepcopy__(self, memo):
        new = self.__class__.__new__(self.__class__)
        memo[id(self)] = new
        for (attr, value) in self.__dict__.items():
            if attr == "_lock":
                setattr(new, attr, RLock())
            else:
                setattr(new, attr, copy.deepcopy(value, memo))

        return new


##
## EventHandler
##
@add_metaclass(abc.ABCMeta)
class EventHandler(object):
    _event_queue_class = EventQueue

    def __init__(self, handler_cb=None, notify_cb=None):
        self._handler_cb = None
        self._notify_cb = None

        if handler_cb is not None:
            self.handler_cb = handler_cb

        if notify_cb is not None:
            self.notify_cb = notify_cb

        self._queue = self._event_queue_class()

    #
    # handler_cb is the main event handler
    #
    def _set_handler_cb(self, cb):
        if not callable(cb):
            raise EventParamError("handler must be callable")

        self._handler_cb = cb

    def _get_handler_cb(self):
        return self._handler_cb

    handler_cb = property(lambda h: h._get_handler_cb(),
                          lambda h, cb: h._set_handler_cb(cb))

    #
    # notify_cb is a notification handler that runs after the main handler
    #
    def _set_notify_cb(self, cb):
        if not callable(cb) or cb.func_code.argcount < 1:
            raise EventParamError("callback function must accept at least one arg")

        self._notify_cb = cb

    def _get_notify_cb(self):
        return self._notify_cb

    notify_cb = property(lambda h: h._get_notify_cb(),
                         lambda h, cb: h._set_notify_cb(cb))

    @abc.abstractproperty
    def enabled(self):
        return False

    @abc.abstractmethod
    def enable(self):
        """ Enable monitoring and handling of events.

            :raises: :class:`~.errors.EventHandlerError` if no callback defined
        """
        if self.handler_cb is None:
            raise EventHandlerError("cannot enable handler with no callback")

    @abc.abstractmethod
    def disable(self):
        """ Disable monitoring and handling of events. """
        pass

    def blacklist_event(self, device=None, action=None, count=1):
        """ Ignore future events.

            :keyword str device: ignore events on the named device
            :keyword str action: ignore events of the specified type
            :keyword int count: number of events to ignore
        """
        self._queue.blacklist_add(device=device, action=action, count=count)

    def next_event(self):
        return self._queue.dequeue()

    @property
    def events_pending(self):
        return len(self._queue._queue)

    @abc.abstractmethod
    def enqueue_event(self, *args, **kwargs):
        """ Convert an event into :class:`~.Event` and enqueue it. """
        pass

    def handle_event(self, *args, **kwargs):
        """ Enqueue an event and call the configured handler. """
        self.enqueue_event(*args, **kwargs)
        Timer(0, self.handler_cb).start()

class UdevEventHandler(EventHandler):
    def __init__(self, handler_cb, notify_cb=None):
        super(UdevEventHandler, self).__init__(handler_cb, notify_cb=notify_cb)
        self._pyudev_observer = None

    def __deepcopy__(self, memo):
        return util.variable_copy(self, memo, shallow=('_pyudev_observer'))

    @property
    def enabled(self):
        return self._pyudev_observer and self._pyudev_observer.monitor.started

    def enable(self):
        """ Enable monitoring and handling of block device uevents. """
        super(UdevEventHandler, self).enable()
        monitor = pyudev.Monitor.from_netlink(udev.global_udev)
        monitor.filter_by("block")
        self._pyudev_observer = pyudev.MonitorObserver(monitor,
                                                       self.handle_event)
        self._pyudev_observer.start()
        flags.uevents = True

    def disable(self):
        """ Disable monitoring and handling of block device uevents. """
        if self._pyudev_observer:
            self._pyudev_observer.stop()
            self._pyudev_observer = None

        flags.uevents = False

    def enqueue_event(self, *args, **kwargs):
        event = UdevEvent(args[0], args[1])
        log.debug("-> %s", event)
        self._queue.enqueue(event)

    def handle_event(self, *args, **kwargs):
        """ Enqueue a uevent and call the configured handler. """
        super(UdevEventHandler, self).handle_event(args[0], args[1])
