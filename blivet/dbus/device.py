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

from .constants import DEVICE_INTERFACE, DEVICE_OBJECT_PATH_BASE
from .object import DBusObject


class DBusDevice(DBusObject):
    def __init__(self, device):
        self._device = device
        self._object_path = self.get_object_path_by_id(self._device.id)
        super().__init__()

    @staticmethod
    def get_object_path_by_id(object_id):
        return "%s/%d" % (DEVICE_OBJECT_PATH_BASE, object_id)

    @property
    def object_path(self):
        return self._object_path

    @property
    def interface(self):
        return DEVICE_INTERFACE

    @property
    def properties(self):
        props = {"Name": self._device.name,
                 "Path": self._device.path,
                 "Type": self._device.type,
                 "Size": dbus.UInt64(self._device.size),
                 "ID": self._device.id,
                 "UUID": self._device.uuid or "",
                 "Status": self._device.status or False,
                 "RaidLevel": self._get_raid_level(),
                 "Parents": dbus.Array((self.get_object_path_by_id(d.id) for d in self._device.parents), signature='o'),
                 "Children": dbus.Array((self.get_object_path_by_id(d.id) for d in self._device.children), signature='o'),
                 "FormatType": self._device.format.type or "",
                 "FormatUUID": self._device.format.uuid or "",
                 "FormatMountpoint": getattr(self._device.format, "mountpoint", "") or "",
                 "FormatLabel": getattr(self._device.format, "label", "") or "",
                 "FormatID": self._device.format.id,
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
