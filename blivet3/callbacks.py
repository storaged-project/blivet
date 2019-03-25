#
# Copyright (C) 2014  Red Hat, Inc.
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
# Red Hat Author(s): Vratislav Podzimek <vpodzime@redhat.com>
#

"""
Module providing classes defining the callbacks used by Blivet and their
arguments.

"""

from collections import namedtuple

# A private namedtuple class with self-descriptive fields for passing callbacks
# to the blivet.do_it method. Each field should be populated with a function
# taking the matching CallbackTypeData (create_format_pre ->
# CreateFormatPreData, etc.)  object or None if no such callback is provided.
_CallbacksRegister = namedtuple("_CallbacksRegister",
                                ["create_format_pre",
                                 "create_format_post",
                                 "resize_format_pre",
                                 "resize_format_post",
                                 "wait_for_entropy",
                                 "report_progress"])


def create_new_callbacks_register(create_format_pre=None,
                                  create_format_post=None,
                                  resize_format_pre=None,
                                  resize_format_post=None,
                                  wait_for_entropy=None,
                                  report_progress=None):
    """
    A function for creating a new opaque object holding the references to
    callbacks. The point of this function is to hide the implementation of such
    object and to provide default values for non-specified fields (e.g. newly
    added callbacks).

    :type create_format_pre: :class:`.CreateFormatPreData` -> NoneType
    :type create_format_post: :class:`.CreateFormatPostData` -> NoneType
    :type resize_format_pre: :class:`.ResizeFormatPreData` -> NoneType
    :type resize_format_post: :class:`.ResizeFormatPostData` -> NoneType
    :param wait_for_entropy: callback for waiting for enough entropy whose return
                             value indicates whether continuing regardless of
                             available entropy should be forced (True) or not (False)
    :type wait_for_entropy: :class:`.WaitForEntropyData` -> bool
    :type report_progress: :class:`.ReportProgressData` -> NoneType

    """

    return _CallbacksRegister(create_format_pre, create_format_post,
                              resize_format_pre, resize_format_post,
                              wait_for_entropy, report_progress)


CreateFormatPreData = namedtuple("CreateFormatPreData",
                                 ["msg"])
CreateFormatPostData = namedtuple("CreateFormatPostData",
                                  ["msg"])
ResizeFormatPreData = namedtuple("ResizeFormatPreData",
                                 ["msg"])
ResizeFormatPostData = namedtuple("ResizeFormatPostData",
                                  ["msg"])
WaitForEntropyData = namedtuple("WaitForEntropyData",
                                ["msg", "min_entropy"])
ReportProgressData = namedtuple("ReportProgressData",
                                ["msg"])


#
# Callbacks for changes to the model.
#
class CallbackList(object):
    def __init__(self):
        self._cb_list = list()

    def add(self, cb):
        """ Add a callback. """
        self._cb_list.append(cb)

    def remove(self, cb):
        """ Remove a callback. """
        self._cb_list.remove(cb)

    def __call__(self, *args, **kwargs):
        """ Run all of the callbacks. """
        for cb in self._cb_list:
            cb(*args, **kwargs)


class Callbacks(object):
    """A collection of callbacks for various events

       Each trigger/event gets a list of callbacks to run, represented by an
       instance of :class:`~.callbacks.CallbackList`.
    """
    def __init__(self):
        self.populate_started = CallbackList()
        """callback list for when devicetree population is started"""

        self.device_scanned = CallbackList()
        """callback list for when a device scan is completed"""

        self.device_added = CallbackList()
        """callback list for when a device is added to the devicetree"""

        self.device_removed = CallbackList()
        """callback list for when a device is removed from the devicetree"""

        self.format_added = CallbackList()
        """callback list for when a format is added to a device"""

        self.format_removed = CallbackList()
        """callback list for when a format is removed from a device"""

        self.action_added = CallbackList()
        """ callback list for when an action is added/registered/scheduled"""

        self.action_removed = CallbackList()
        """ callback list for when an action is removed/canceled"""

        self.action_executed = CallbackList()
        """ callback list for when an action is executed"""

        self.parent_added = CallbackList()
        """ callback list for when a member device is added to a container device"""

        self.parent_removed = CallbackList()
        """ callback list for when a member device is removed from a container device"""

        self.attribute_changed = CallbackList()
        """ callback list for when a device or format attribute's value is changed"""


"""
    .. data:: callbacks

        .. note::
           The arguments for these callbacks are provided by name, so any callbacks
           you provide should be able to handle that.

        .. function:: populate_started_cb(n_devices)

           Devicetree population was started.

           :param int n_devices: (expected) total number of devices to scan


        .. function:: device_scanned_cb(device_name)

           A device scan was finished (note that some devices may be scanned
           multiple times).

           :param str device_name: name of the device that was scanned


        .. function:: device_added_cb(device)

           A device was added to the devicetree.

           :param device: the device that was added
           :type device: :class:`~.devices.StorageDevice`


        .. function:: device_removed_cb(device)

           A device was removed from the devicetree.

           :param device: the device instance that was removed
           :type device: :class:`~.devices.StorageDevice`


        .. function:: format_added_cb(device, fmt)

           A new format was added to the device.

           :param device: the device
           :type device: :class:`~.devices.StorageDevice`
           :param fmt: the added format
           :type fmt: :class:`~.formats.DeviceFormat`


        .. function:: format_removed_cb(device, fmt)

           A format was removed from the device.

           :param device: the device
           :type device: :class:`~.devices.StorageDevice`
           :param fmt: the removed format
           :type fmt: :class:`~.formats.DeviceFormat`


        .. function:: action_added_cb(action)

           An action was scheduled/registered/added.

           :param action: the action
           :type action: :class:`~.deviceaction.DeviceAction`


        .. function:: action_removed_cb(action)

           An action was canceled/removed.

           :param action: the action
           :type action: :class:`~.deviceaction.DeviceAction`


        .. function:: action_executed_cb(action)

           An action was executed/completed.

           :param action: the action
           :type action: :class:`~.deviceaction.DeviceAction`


        .. function:: parent_added_cb(device, parent)

           A member device was added to a container device.

           :param device: the member device
           :type device: :class:`~.devices.StorageDevice`
           :param device: the container device
           :type device: :class:`~.devices.StorageDevice`


        .. function:: parent_removed_cb(device, parent)

           A member device was removed from a container device.

           :param device: the device instance that was removed
           :type device: :class:`~.devices.StorageDevice`
           :param device: the container device
           :type device: :class:`~.devices.StorageDevice`


        .. function:: attribute_changed_cb(device, attr, old, new, fmt=None)

           An attribute value was changed.

           :param device: the device
           :type device: :class:`~.devices.StorageDevice`
           :param str attr: the attribute name
           :param old: the old value
           :param new: the new value
           :keyword fmt: the format, if a format attribute is what changed
           :type fmt: :class:`~.formats.DeviceFormat`


"""
callbacks = Callbacks()
