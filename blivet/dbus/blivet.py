#
# Copyright (C) 2016  Red Hat, Inc.
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
from collections import OrderedDict
import sys

import dbus

from blivet import Blivet
from blivet.callbacks import callbacks
from blivet.util import ObjectID
from .action import DBusAction
from .constants import BLIVET_INTERFACE, BLIVET_OBJECT_PATH, BUS_NAME
from .device import DBusDevice
from .format import DBusFormat
from .object import DBusObject


class DBusBlivet(DBusObject):
    """ This class provides the main entry point to the Blivet1 service.

        It provides methods for controlling the blivet service and querying its
        state.
    """
    def __init__(self, manager):
        super().__init__()
        self._dbus_actions = OrderedDict()
        self._dbus_devices = OrderedDict()
        self._dbus_formats = OrderedDict()
        self._manager = manager  # provides ObjectManager interface
        self._blivet = Blivet()
        self._set_up_callbacks()
        self._id = ObjectID().id

    def _set_up_callbacks(self):
        callbacks.device_added.add(self._device_added)
        callbacks.device_removed.add(self._device_removed)
        callbacks.format_added.add(self._format_added)
        callbacks.format_removed.add(self._format_removed)
        callbacks.action_added.add(self._action_added)
        callbacks.action_removed.add(self._action_removed)
        callbacks.action_executed.add(self._action_executed)

    @property
    def id(self):
        return self._id

    @property
    def object_path(self):
        return BLIVET_OBJECT_PATH

    @property
    def interface(self):
        return BLIVET_INTERFACE

    @property
    def properties(self):
        props = {"Devices": self.ListDevices()}
        return props

    def _device_removed(self, device):
        """ Update ObjectManager interface after a device is removed. """
        removed_object_path = DBusDevice.get_object_path_by_id(device.id)
        removed = self._dbus_devices[removed_object_path]
        fmt_object_path = DBusFormat.get_object_path_by_id(device.format.id)
        # Make sure the format gets removed in case the device was removed w/o
        # removing the format first.
        if fmt_object_path in self._dbus_formats:
            self._format_removed(device.format)
        self._manager.remove_object(removed)
        del self._dbus_devices[removed_object_path]

    def _device_added(self, device):
        """ Update ObjectManager interface after a device is added. """
        added = DBusDevice(device)
        self._dbus_devices[added.object_path] = added
        self._manager.add_object(added)

    def _format_removed(self, fmt):
        removed_object_path = DBusFormat.get_object_path_by_id(fmt.id)
        removed = self._dbus_formats[removed_object_path]
        self._manager.remove_object(removed)
        del self._dbus_formats[removed_object_path]

    def _format_added(self, fmt):
        added = DBusFormat(fmt)
        self._dbus_formats[added.object_path] = added
        self._manager.add_object(added)

    def _action_removed(self, action):
        removed_object_path = DBusAction.get_object_path_by_id(action.id)
        removed = self._dbus_actions[removed_object_path]
        self._manager.remove_object(removed)
        del self._dbus_actions[removed_object_path]

    def _action_added(self, action):
        added = DBusAction(action)
        self._dbus_actions[added.object_path] = added
        self._manager.add_object(added)

    def _action_executed(self, action):
        if action.is_destroy:
            if action.is_device:
                self._device_removed(action.device)
            elif action.is_format:
                self._format_removed(action.device, action.format)

        self._action_removed(action)

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE)
    def Reset(self):
        """ Reset the Blivet instance and populate the device tree. """
        old_devices = self._blivet.devices[:]
        for removed in old_devices:
            self._device_removed(device=removed)

        self._blivet.reset()

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE)
    def Exit(self):
        """ Stop the blivet service. """
        sys.exit(0)

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, out_signature='ao')
    def ListDevices(self):
        """ Return a list of strings describing the devices in this system. """
        return dbus.Array(list(self._dbus_devices.keys()), signature='o')

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='s', out_signature='o')
    def ResolveDevice(self, spec):
        """ Return a string describing the device the given specifier resolves to. """
        device = self._blivet.devicetree.resolve_device(spec)
        object_path = ""
        if device is None:
            raise dbus.exceptions.DBusException('%s.DeviceLookupFailed' % BUS_NAME,
                                                'No device was found that matches the device '
                                                'descriptor "%s".' % spec)

        object_path = next(p for (p, d) in self._dbus_devices.items() if d._device == device)
        return object_path

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='o')
    def RemoveDevice(self, object_path):
        """ Remove a device and all devices built on it. """
        dbus_device = self._dbus_devices[object_path]
        self._blivet.devicetree.recursive_remove(dbus_device._device)

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='o')
    def InitializeDisk(self, object_path):
        """ Clear a disk and create a disklabel on it. """
        dbus_device = self._dbus_devices[object_path]
        self.RemoveDevice(object_path)
        self._blivet.initialize_disk(dbus_device._device)
