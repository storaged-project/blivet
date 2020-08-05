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

from .constants import BUS_NAME, OBJECT_MANAGER_INTERFACE, OBJECT_MANAGER_PATH


class ObjectManager(dbus.service.Object):
    """ Class to implement org.freedesktop.DBus.ObjectManager interface.

        Blivet's ObjectManager interface will manage subtrees for objects that
        variously (and with mutual-exclusivity) implement blivet's Device,
        Format, Action interfaces.
    """
    def __init__(self):
        self._objects = list()
        self._by_id = dict()
        self._by_path = dict()
        super(ObjectManager, self).__init__(bus_name=dbus.service.BusName(BUS_NAME, dbus.SystemBus()),
                                            object_path=OBJECT_MANAGER_PATH)

    @dbus.service.method(dbus_interface=OBJECT_MANAGER_INTERFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        return dict((obj.object_path, {obj.interface: obj.properties}) for obj in self._objects)

    def remove_object(self, obj):
        self._objects.remove(obj)
        del self._by_id[obj.id]
        del self._by_path[obj.object_path]
        self.InterfacesRemoved(obj.object_path, [obj.interface])
        obj.remove_from_connection()

    def add_object(self, obj):
        self._objects.append(obj)
        self._by_id[obj.id] = obj
        self._by_path[obj.object_path] = obj
        self.InterfacesAdded(obj.object_path, {obj.interface: obj.properties})

    @property
    def objects(self):
        return self._objects

    def get_object_by_id(self, obj_id):
        return self._by_id.get(obj_id)

    def get_object_by_path(self, obj_path):
        return self._by_path.get(obj_path)

    @dbus.service.signal(dbus_interface=OBJECT_MANAGER_INTERFACE, signature='oa{sa{sv}}')
    def InterfacesAdded(self, object_path, ifaces_props_dict):
        pass

    @dbus.service.signal(dbus_interface=OBJECT_MANAGER_INTERFACE, signature='oas')
    def InterfacesRemoved(self, object_path, interfaces):
        pass
