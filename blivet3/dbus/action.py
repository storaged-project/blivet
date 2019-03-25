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
from .object import DBusObject


class DBusAction(DBusObject):
    def __init__(self, action, manager):
        self._action = action
        super(DBusAction, self).__init__(manager)

    @property
    def id(self):
        return self._action.id

    @property
    def object_path(self):
        return "%s/%d" % (ACTION_OBJECT_PATH_BASE, self.id)

    @property
    def interface(self):
        return ACTION_INTERFACE

    @property
    def properties(self):
        props = {"Description": str(self._action),
                 "Device": dbus.ObjectPath(self._manager.get_object_by_id(self._action.device.id).object_path),
                 "Format": dbus.ObjectPath(self._manager.get_object_by_id(self._action.format.id).object_path),
                 "Type": "%s %s" % (self._action.type_string, self._action.object_string),
                 "ID": self._action.id}
        return props
