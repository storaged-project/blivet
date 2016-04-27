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

BUS_NAME = "com.redhat.Blivet1"


class DBusObject(dbus.service.Object):
    """ Base class for dbus objects. """
    def __init__(self):
        super().__init__(bus_name=dbus.service.BusName(BUS_NAME, dbus.SystemBus()),
                         object_path=self._get_object_path())

    def _get_object_path(self):
        """ Return the dbus object path for this instance. """
        raise NotImplementedError()

    def _get_interface(self):
        """ Return the interface implemented by this class. """
        raise NotImplementedError()

    def _get_properties(self):
        """ Return a dict of property key/value pairs to export via dbus. """
        raise NotImplementedError()

    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface_name):
        if interface_name != self._get_interface():
            raise dbus.exceptions.DBusException(
                'com.redhat.Blivet1.UnknownInterface',
                'The %s object does not implement the %s interface'
                % (self.__class__.__name__, interface_name))

        return self._get_properties()

    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        return self.GetAll(interface_name)[property_name]
