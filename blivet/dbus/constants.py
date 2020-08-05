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

BUS_NAME = "com.redhat.Blivet0"
BASE_OBJECT_PATH = "/com/redhat/Blivet0"
BLIVET_INTERFACE = "%s.Blivet" % BUS_NAME
BLIVET_OBJECT_PATH = "%s/Blivet" % BASE_OBJECT_PATH
DEVICE_INTERFACE = "%s.Device" % BUS_NAME
DEVICE_OBJECT_PATH_BASE = "%s/Devices" % BASE_OBJECT_PATH
DEVICE_REMOVED_OBJECT_PATH_BASE = "%s/RemovedDevices" % BASE_OBJECT_PATH
FORMAT_INTERFACE = "%s.Format" % BUS_NAME
FORMAT_OBJECT_PATH_BASE = "%s/Formats" % BASE_OBJECT_PATH
FORMAT_REMOVED_OBJECT_PATH_BASE = "%s/RemovedFormats" % BASE_OBJECT_PATH
ACTION_INTERFACE = "%s.Action" % BUS_NAME
ACTION_OBJECT_PATH_BASE = "%s/Actions" % BASE_OBJECT_PATH

OBJECT_MANAGER_PATH = BASE_OBJECT_PATH
OBJECT_MANAGER_INTERFACE = "org.freedesktop.DBus.ObjectManager"
