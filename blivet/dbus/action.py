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

from .constants import ACTION_INTERFACE, ACTION_OBJECT_PATH_BASE
from .device import DBusDevice
from .format import DBusFormat
from .object import DBusObject


class DBusAction(DBusObject):
    def __init__(self, action):
        self._action = action
        self._object_path = self.get_object_path_by_id(self._action.id)
        super().__init__()

    @property
    def id(self):
        return self._action.id

    @property
    def object_path(self):
        return self._object_path

    @staticmethod
    def get_object_path_by_id(object_id):
        return "%s/%d" % (ACTION_OBJECT_PATH_BASE, object_id)

    @property
    def interface(self):
        return ACTION_INTERFACE

    @property
    def properties(self):
        props = {"Description": str(self._action),
                 "Device": dbus.ObjectPath(DBusDevice.get_object_path_by_id(self._action.device.id),
                 "Format": dbus.ObjectPath(DBusDevice.get_object_path_by_id(self._action.format.id),
                 "Type": "%s %s" % (self._action.type_string, self._action.object_string),
                 "ID": self._action.id}
        return props
