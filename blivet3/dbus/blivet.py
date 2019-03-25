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
import sys

import dbus

from .. import Blivet
from ..callbacks import callbacks
from ..devicefactory import DEVICE_TYPE_PARTITION, DEVICE_TYPE_LVM, DEVICE_TYPE_LVM_THINP
from ..devicefactory import DEVICE_TYPE_MD, DEVICE_TYPE_BTRFS
from ..errors import StorageError
from ..size import Size
from ..util import ObjectID
from .action import DBusAction
from .constants import BLIVET_INTERFACE, BLIVET_OBJECT_PATH, BUS_NAME
from .device import DBusDevice
from .format import DBusFormat
from .object import DBusObject


def sorted_object_paths_from_list(obj_list):
    objects = sorted(obj_list, key=lambda o: o.id)
    return [o.object_path for o in objects]


class DBusBlivet(DBusObject):
    """ This class provides the main entry point to the Blivet1 service.

        It provides methods for controlling the blivet service and querying its
        state.
    """
    def __init__(self, manager):
        super(DBusBlivet, self).__init__(manager)
        self._blivet = Blivet()
        self._id = ObjectID().id
        self._manager.add_object(self)
        self._set_up_callbacks()

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
        props = {"Devices": self.ListDevices(),
                 "DEVICE_TYPE_LVM": DEVICE_TYPE_LVM,
                 "DEVICE_TYPE_LVM_THINP": DEVICE_TYPE_LVM_THINP,
                 "DEVICE_TYPE_PARTITION": DEVICE_TYPE_PARTITION,
                 "DEVICE_TYPE_MD": DEVICE_TYPE_MD,
                 "DEVICE_TYPE_BTRFS": DEVICE_TYPE_BTRFS}
        return props

    def _device_removed(self, device, keep=True):
        """ Update ObjectManager interface after a device is removed. """
        # Make sure the format gets removed in case the device was removed w/o
        # removing the format first.
        removed_fmt = self._manager.get_object_by_id(device.format.id)
        if removed_fmt and removed_fmt.present:
            self._format_removed(device, device.format, keep=keep)
        elif removed_fmt and not keep:
            self._format_removed(device, device.format, keep=False)

        removed = self._manager.get_object_by_id(device.id)
        self._manager.remove_object(removed)
        if keep:
            removed.present = False
            self._manager.add_object(removed)

    def _device_added(self, device):
        """ Update ObjectManager interface after a device is added. """
        added = self._manager.get_object_by_id(device.id)
        if added:
            # This device was previously removed. Restore it.
            added.present = True
        else:
            added = DBusDevice(device, self._manager)

        self._manager.add_object(added)

    def _format_removed(self, device, fmt, keep=True):  # pylint: disable=unused-argument
        removed = self._manager.get_object_by_id(fmt.id)
        if removed is None:
            return

        # We have to remove the object either way since its path will change.
        self._manager.remove_object(removed)
        if keep:
            removed.present = False
            self._manager.add_object(removed)

    def _format_added(self, device, fmt):  # pylint: disable=unused-argument
        added = self._manager.get_object_by_id(fmt.id)
        if added:
            # This format was previously removed. Restore it.
            added.present = True
        else:
            added = DBusFormat(fmt, self._manager)

        self._manager.add_object(added)

    def _action_removed(self, action):
        removed = self._manager.get_object_by_id(action.id)
        self._manager.remove_object(removed)

    def _action_added(self, action):
        added = DBusAction(action, self._manager)
        self._manager.add_object(added)

    def _action_executed(self, action):
        if action.is_destroy:
            if action.is_device:
                self._device_removed(action.device, keep=False)
            elif action.is_format:
                self._format_removed(action.device, action.format, keep=False)

        self._action_removed(action)

    def _list_dbus_devices(self, removed=False):
        dbus_devices = (d for d in self._manager.objects if isinstance(d, DBusDevice))
        return [d for d in dbus_devices if removed or d.present]

    def _get_device_by_object_path(self, object_path, removed=False):
        """ Return the StorageDevice corresponding to an object path. """
        dbus_device = self._manager.get_object_by_path(object_path)
        if dbus_device is None or not isinstance(dbus_device, DBusDevice):
            raise dbus.exceptions.DBusException('%s.DeviceNotFound' % BUS_NAME,
                                                'No device found with object path "%s".'
                                                % object_path)

        if not dbus_device.present and not removed:
            raise dbus.exceptions.DBusException('%s.DeviceNotFound' % BUS_NAME,
                                                'Device with object path "%s" has already been '
                                                'removed.' % object_path)

        return dbus_device._device

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE)
    def Reset(self):
        """ Reset the Blivet instance and populate the device tree. """
        old_devices = self._blivet.devices[:]
        for removed in old_devices:
            self._device_removed(device=removed, keep=False)

        for action in self._blivet.devicetree.actions:
            self._action_removed(action)

        self._blivet.reset()

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE)
    def Exit(self):
        """ Stop the blivet service. """
        sys.exit(0)

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, out_signature='ao')
    def ListDevices(self):
        """ Return a list of strings describing the devices in this system. """
        object_paths = sorted_object_paths_from_list(self._list_dbus_devices())
        return dbus.Array(object_paths, signature='o')

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='s', out_signature='o')
    def ResolveDevice(self, spec):
        """ Return a string describing the device the given specifier resolves to. """
        device = self._blivet.devicetree.resolve_device(spec)
        if device is None:
            raise dbus.exceptions.DBusException('%s.DeviceLookupFailed' % BUS_NAME,
                                                'No device was found that matches the device '
                                                'descriptor "%s".' % spec)

        return self._manager.get_object_by_id(device.id).object_path

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='o')
    def RemoveDevice(self, object_path):
        """ Remove a device and all devices built on it. """
        device = self._get_device_by_object_path(object_path)
        self._blivet.devicetree.recursive_remove(device)

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='o')
    def InitializeDisk(self, object_path):
        """ Clear a disk and create a disklabel on it. """
        self.RemoveDevice(object_path)
        device = self._get_device_by_object_path(object_path)
        self._blivet.initialize_disk(device)

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE)
    def Commit(self):
        """ Commit pending changes to disk. """
        try:
            self._blivet.do_it()
        except StorageError as e:
            raise dbus.exceptions.DBusException('%s.%s' % (BUS_NAME, e.__class__.__name__),
                                                "An error occured while committing the "
                                                "changes to disk: %s" % str(e))

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='a{sv}', out_signature='o')
    def Factory(self, kwargs):
        disks = [self._get_device_by_object_path(p) for p in kwargs.pop("disks", [])]
        kwargs["disks"] = disks

        dbus_device = kwargs.pop("device", None)
        if dbus_device:
            device = self._get_device_by_object_path(dbus_device)
            kwargs["device"] = device

        size = kwargs.pop("size", None)
        if size is not None:
            kwargs["size"] = Size(size)

        try:
            device = self._blivet.factory_device(**kwargs)
        except StorageError as e:
            raise dbus.exceptions.DBusException('%s.%s' % (BUS_NAME, e.__class__.__name__),
                                                "An error occured while configuring the "
                                                "device: %s" % str(e))

        if device is None:
            object_path = '/'
        else:
            object_path = self._manager.get_object_by_id(device.id).object_path

        return object_path
