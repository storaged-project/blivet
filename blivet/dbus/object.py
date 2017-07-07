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
import dbus.service

from .constants import BUS_NAME


class DBusObject(dbus.service.Object):
    """ Base class for dbus objects. """
    def __init__(self, manager):
        # pylint: disable=super-init-not-called
        self._present = True
        self._init_dbus_object()
        self._manager = manager  # provides ObjectManager interface

    # This is here to make it easier to prevent the dbus.service.Object
    # constructor from running during unit testing.
    def _init_dbus_object(self):
        """ Initialize superclass. """
        super(DBusObject, self).__init__(bus_name=dbus.service.BusName(BUS_NAME, dbus.SystemBus()),
                                         object_path=self.object_path)

    @property
    def present(self):
        """ Is this object present in blivet's current view? """
        return self._present

    @present.setter
    def present(self, state):
        """ Indicate whether the object is in blivet's current view. """
        self._present = state

    def remove_from_connection(self, connection=None, path=None):
        super(DBusObject, self).remove_from_connection(connection=connection, path=path)
        self._object_path = None

    @property
    def id(self):
        """ The unique id of this instance. """
        raise NotImplementedError()

    @property
    def object_path(self):
        """ The dbus object path for this instance. """
        raise NotImplementedError()

    @property
    def interface(self):
        """ The interface implemented by this class. """
        raise NotImplementedError()

    @property
    def properties(self):
        """ dict of property key/value pairs to export via dbus. """
        raise NotImplementedError()

    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface_name):
        if interface_name != self.interface:
            raise dbus.exceptions.DBusException('%s.UnknownInterface' % BUS_NAME,
                                                'The %s object does not implement the %s interface'
                                                % (self.__class__.__name__, interface_name))

        return self.properties

    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        return self.GetAll(interface_name)[property_name]

    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface_name, property_name, new_value):
        if interface_name != self.interface:
            raise dbus.exceptions.DBusException('%s.UnknownInterface' % BUS_NAME,
                                                'The %s object does not implement the %s interface'
                                                % (self.__class__.__name__, interface_name))

        if property_name in self.properties:
            raise dbus.exceptions.DBusException('%s.ReadOnlyProperty' % BUS_NAME,
                                                'The %s property is read-only' % property_name)
        else:
            raise dbus.exceptions.DBusException('%s.UnknownProperty' % BUS_NAME,
                                                'The %s interface does not have %s property'
                                                % (interface_name, property_name))

        self.PropertiesChanged(interface_name, {property_name: new_value}, [])

    @dbus.service.signal(dbus_interface=dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
        pass
