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

from .constants import FORMAT_INTERFACE, FORMAT_OBJECT_PATH_BASE, FORMAT_REMOVED_OBJECT_PATH_BASE
from .object import DBusObject


class DBusFormat(DBusObject):
    def __init__(self, fmt, manager):
        self._format = fmt
        super(DBusFormat, self).__init__(manager)

    @property
    def id(self):
        return self._format.id

    @property
    def object_path(self):
        if self.present:
            base = FORMAT_OBJECT_PATH_BASE
        else:
            base = FORMAT_REMOVED_OBJECT_PATH_BASE

        return "%s/%s" % (base, self.id)

    @property
    def interface(self):
        return FORMAT_INTERFACE

    @property
    def properties(self):
        props = {"Device": self._format.device,
                 "Type": self._format.type or "Unknown",
                 "ID": self._format.id,
                 "UUID": self._format.uuid or "",
                 "Label": getattr(self._format, "label", "") or "",
                 "Mountable": dbus.Boolean(self._format.mountable),
                 "Mountpoint": getattr(self._format, "mountpoint", "") or "",
                 "Status": dbus.Boolean(self._format.status)}
        return props

    @dbus.service.method(dbus_interface=FORMAT_INTERFACE, in_signature='a{sv}')
    def Setup(self, kwargs):
        self._format.setup(**kwargs)

    @dbus.service.method(dbus_interface=FORMAT_INTERFACE)
    def Teardown(self):
        self._format.teardown()
