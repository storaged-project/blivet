# stratis_info.py
# Backend code for populating a DeviceTree.
#
# Copyright (C) 2020  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): Vojtech Trefny <vtrefny@redhat.com>
#

from collections import namedtuple

from .. import safe_dbus
from ..size import Size

import logging
log = logging.getLogger("blivet")


STRATIS_SERVICE = "org.storage.stratis2"
STRATIS_PATH = "/org/storage/stratis2"
STRATIS_POOL_INTF = STRATIS_SERVICE + ".pool"
STRATIS_FILESYSTEM_INTF = STRATIS_SERVICE + ".filesystem"
STRATIS_BLOCKDEV_INTF = STRATIS_SERVICE + ".blockdev"
STRATIS_PROPS_INTF = STRATIS_SERVICE + ".FetchProperties"


StratisPoolInfo = namedtuple("StratisPoolInfo", ["name", "uuid", "physical_size"])
StratisFilesystemInfo = namedtuple("StratisFilesystemInfo", ["name", "uuid", "pool_name", "pool_uuid"])
StratisBlockdevInfo = namedtuple("StratisBlockdevInfo", ["path", "uuid", "pool_name", "pool_uuid"])


class StratisInfo(object):
    """ Class to be used as a singleton.
        Maintains the Stratis devices info cache.
    """

    def __init__(self):
        self._info_cache = None

    def _get_pool_info(self, pool_path):
        try:
            properties = safe_dbus.get_properties_sync(STRATIS_SERVICE,
                                                       pool_path,
                                                       STRATIS_POOL_INTF)[0]
        except safe_dbus.DBusPropertyError as e:
            log.error("Error when getting DBus properties of '%s': %s",
                      pool_path, str(e))

        if not properties:
            log.error("Failed to get DBus properties of '%s'", pool_path)
            return None

        all_props = safe_dbus.call_sync(STRATIS_SERVICE,
                                        pool_path,
                                        STRATIS_PROPS_INTF,
                                        "GetAllProperties",
                                        None)[0]
        if all_props:
            valid, pool_size = all_props.get("TotalPhysicalSize",
                                             (False, "TotalPhysicalSize not available"))
            if not valid:
                log.warning("Failed to get Stratis pool physical size for %s: %s",
                            properties["Name"], pool_size)
                pool_size = 0
        else:
            log.error("Failed to get Stratis pool properties for %s.", properties["Name"])
            pool_size = 0

        return StratisPoolInfo(name=properties["Name"], uuid=properties["Uuid"],
                               physical_size=Size(pool_size))

    def _get_filesystem_info(self, filesystem_path):
        try:
            properties = safe_dbus.get_properties_sync(STRATIS_SERVICE,
                                                       filesystem_path,
                                                       STRATIS_FILESYSTEM_INTF)[0]
        except safe_dbus.DBusPropertyError as e:
            log.error("Error when getting DBus properties of '%s': %s",
                      filesystem_path, str(e))

        if not properties:
            log.error("Failed to get DBus properties of '%s'", filesystem_path)
            return None

        pool_info = self._get_pool_info(properties["Pool"])
        if not pool_info:
            return None

        return StratisFilesystemInfo(name=properties["Name"], uuid=properties["Uuid"],
                                     pool_name=pool_info.name, pool_uuid=pool_info.uuid)

    def _get_blockdev_info(self, blockdev_path):
        try:
            properties = safe_dbus.get_properties_sync(STRATIS_SERVICE,
                                                       blockdev_path,
                                                       STRATIS_BLOCKDEV_INTF)[0]
        except safe_dbus.DBusPropertyError as e:
            log.error("Error when getting DBus properties of '%s': %s",
                      blockdev_path, str(e))

        if not properties:
            log.error("Failed to get DBus properties of '%s'", blockdev_path)
            return None

        pool_path = properties["Pool"]
        if pool_path == "/":
            pool_name = ""
        else:
            pool_info = self._get_pool_info(properties["Pool"])
            if not pool_info:
                return None
            pool_name = pool_info.name

        return StratisBlockdevInfo(path=properties["Devnode"], uuid=properties["Uuid"],
                                   pool_name=pool_name, pool_uuid=pool_info.uuid)

    def _get_stratis_info(self):
        self._info_cache = dict()
        self._info_cache["pools"] = dict()
        self._info_cache["blockdevs"] = dict()
        self._info_cache["filesystems"] = dict()

        try:
            ret = safe_dbus.check_object_available(STRATIS_SERVICE, STRATIS_PATH)
        except safe_dbus.DBusCallError:
            log.warning("Stratis DBus service is not running")
            return
        else:
            if not ret:
                log.warning("Stratis DBus service is not available")

        objects = safe_dbus.call_sync(STRATIS_SERVICE,
                                      STRATIS_PATH,
                                      "org.freedesktop.DBus.ObjectManager",
                                      "GetManagedObjects",
                                      None)[0]

        for path, interfaces in objects.items():
            if STRATIS_POOL_INTF in interfaces.keys():
                pool_info = self._get_pool_info(path)
                if pool_info:
                    self._info_cache["pools"][pool_info.uuid] = pool_info

            if STRATIS_FILESYSTEM_INTF in interfaces.keys():
                fs_info = self._get_filesystem_info(path)
                if fs_info:
                    self._info_cache["filesystems"][fs_info.uuid] = fs_info

            if STRATIS_BLOCKDEV_INTF in interfaces.keys():
                bd_info = self._get_blockdev_info(path)
                if bd_info:
                    self._info_cache["blockdevs"][bd_info.uuid] = bd_info

    @property
    def pools(self):
        if self._info_cache is None:
            self._get_stratis_info()

        return self._info_cache["pools"]

    @property
    def filesystems(self):
        if self._info_cache is None:
            self._get_stratis_info()

        return self._info_cache["filesystems"]

    @property
    def blockdevs(self):
        if self._info_cache is None:
            self._get_stratis_info()

        return self._info_cache["blockdevs"]

    def drop_cache(self):
        self._info_cache = None


stratis_info = StratisInfo()
