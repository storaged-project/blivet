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

import dbus.service

from blivet import Blivet
from .object import DBusObject

BLIVET_OBJECT_PATH = "/com/redhat/Blivet"
BLIVET_INTERFACE = "com.redhat.Blivet1"


class DBusBlivet(DBusObject):
    """ This class provides the main entry point to the Blivet1 service.

        It provides methods for controlling the blivet service and querying its
        state. It will eventually implement the org.freedesktop.DBus.ObjectManager
        interface once we export objects for devices, formats, and scheduled
        actions.
    """
    def __init__(self):
        super().__init__()
        self._blivet = Blivet()

    def _get_object_path(self):
        return BLIVET_OBJECT_PATH

    def _get_interface(self):
        return BLIVET_INTERFACE

    def _get_properties(self):
        props = {"devices": self.listDevices()}
        return props

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE)
    def reset(self):
        """ Reset the Blivet instance and populate the device tree. """
        self._blivet.reset()

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE)
    def exit(self):
        """ Stop the blivet service. """
        sys.exit(0)

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, out_signature='as')
    def listDevices(self):
        """ Return a list of strings describing the devices in this system. """
        return dbus.Array([str(d) for d in self._blivet.devices], signature='s')

    @dbus.service.method(dbus_interface=BLIVET_INTERFACE, in_signature='s', out_signature='s')
    def resolveDevice(self, spec):
        """ Return a string describing the device the given specifier resolves to. """
        return str(self._blivet.devicetree.resolve_device(spec) or "")
