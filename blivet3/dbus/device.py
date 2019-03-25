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
import dbus

from .constants import DEVICE_INTERFACE, DEVICE_OBJECT_PATH_BASE, DEVICE_REMOVED_OBJECT_PATH_BASE
from .object import DBusObject


class DBusDevice(DBusObject):
    def __init__(self, device, manager):
        self._device = device
        super(DBusDevice, self).__init__(manager)

    @property
    def id(self):
        return self._device.id

    @property
    def object_path(self):
        if self.present:
            base = DEVICE_OBJECT_PATH_BASE
        else:
            base = DEVICE_REMOVED_OBJECT_PATH_BASE

        return "%s/%s" % (base, self.id)

    @property
    def interface(self):
        return DEVICE_INTERFACE

    @property
    def properties(self):
        parents = (self._manager.get_object_by_id(d.id).object_path for d in self._device.parents)
        children = (self._manager.get_object_by_id(d.id).object_path for d in self._device.children)
        fmt = self._manager.get_object_by_id(self._device.format.id).object_path
        props = {"Name": self._device.name,
                 "Path": self._device.path,
                 "Type": self._device.type,
                 "Size": dbus.UInt64(self._device.size),
                 "ID": self._device.id,
                 "UUID": self._device.uuid or "",
                 "Status": self._device.status or False,
                 "RaidLevel": self._get_raid_level(),
                 "Parents": dbus.Array(parents, signature='o'),
                 "Children": dbus.Array(children, signature='o'),
                 "Format": dbus.ObjectPath(fmt)
                 }

        return props

    def _get_raid_level(self):
        level = ""
        if hasattr(self._device, "level"):
            level = str(self._device.level)
        elif hasattr(self._device, "data_level"):
            level = str(self._device.data_level)

        return level

    @dbus.service.method(dbus_interface=DEVICE_INTERFACE)
    def Setup(self):
        """ Activate this device. """
        self._device.setup()

    @dbus.service.method(dbus_interface=DEVICE_INTERFACE)
    def Teardown(self):
        """ Deactivate this device. """
        self._device.teardown()
