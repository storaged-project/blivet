#
# stratis.py
# stratis functions
#
# Copyright (C) 2020  Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author(s): Vojtech Trefny <vtrefny@redhat.com>
#

import gi
gi.require_version("GLib", "2.0")

from gi.repository import GLib

from ..errors import StratisError
from ..size import Size
from ..static_data import stratis_info
from .. import safe_dbus


STRATIS_SERVICE = "org.storage.stratis2"
STRATIS_PATH = "/org/storage/stratis2"
STRATIS_POOL_INTF = STRATIS_SERVICE + ".pool"
STRATIS_FILESYSTEM_INTF = STRATIS_SERVICE + ".filesystem"
STRATIS_BLOCKDEV_INTF = STRATIS_SERVICE + ".blockdev"
STRATIS_PROPS_INTF = STRATIS_SERVICE + ".FetchProperties"
STRATIS_MANAGER_INTF = STRATIS_SERVICE + ".Manager.r2"


STRATIS_FS_SIZE = Size("1 TiB")


safe_name_characters = "0-9a-zA-Z._-"


def remove_pool(pool_uuid):
    if not safe_dbus.check_object_available(STRATIS_SERVICE, STRATIS_PATH):
        raise StratisError("Stratis DBus service not available")

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    if pool_uuid not in stratis_info.pools.keys():
        raise StratisError("Stratis pool with UUID %s not found" % pool_uuid)

    pool_info = stratis_info.pools[pool_uuid]

    try:
        (succ, _uuid), rc, err = safe_dbus.call_sync(STRATIS_SERVICE,
                                                     STRATIS_PATH,
                                                     STRATIS_MANAGER_INTF,
                                                     "DestroyPool",
                                                     GLib.Variant("(o)", (pool_info.object_path,)))
    except safe_dbus.DBusCallError as e:
        raise StratisError("Failed to remove stratis pool: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to remove stratis pool: %s (%d)" % (err, rc))


def remove_filesystem(pool_uuid, fs_uuid):
    if not safe_dbus.check_object_available(STRATIS_SERVICE, STRATIS_PATH):
        raise StratisError("Stratis DBus service not available")

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    if pool_uuid not in stratis_info.pools.keys():
        raise StratisError("Stratis pool with UUID %s not found" % pool_uuid)
    if fs_uuid not in stratis_info.filesystems.keys():
        raise StratisError("Stratis filesystem with UUID %s not found" % fs_uuid)

    pool_info = stratis_info.pools[pool_uuid]
    fs_info = stratis_info.filesystems[fs_uuid]

    try:
        (succ, _uuid), rc, err = safe_dbus.call_sync(STRATIS_SERVICE,
                                                     pool_info.object_path,
                                                     STRATIS_POOL_INTF,
                                                     "DestroyFilesystems",
                                                     GLib.Variant("(ao)", ([fs_info.object_path],)))
    except safe_dbus.DBusCallError as e:
        raise StratisError("Failed to remove stratis filesystem: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to remove stratis filesystem: %s (%d)" % (err, rc))


def create_pool(name, devices):
    if not safe_dbus.check_object_available(STRATIS_SERVICE, STRATIS_PATH):
        raise StratisError("Stratis DBus service not available")

    raid_opt = GLib.Variant("(bq)", (False, 0))
    key_opt = GLib.Variant("(bs)", (False, ""))

    try:
        ((succ, _paths), rc, err) = safe_dbus.call_sync(STRATIS_SERVICE,
                                                        STRATIS_PATH,
                                                        STRATIS_MANAGER_INTF,
                                                        "CreatePool",
                                                        GLib.Variant("(s(bq)as(bs))", (name, raid_opt,
                                                                                       devices, key_opt)))
    except safe_dbus.DBusCallError as e:
        raise StratisError("Failed to create stratis pool: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to create stratis pool: %s (%d)" % (err, rc))


def create_filesystem(name, pool_uuid):
    if not safe_dbus.check_object_available(STRATIS_SERVICE, STRATIS_PATH):
        raise StratisError("Stratis DBus service not available")

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    if pool_uuid not in stratis_info.pools.keys():
        raise StratisError("Stratis pool with UUID %s not found" % pool_uuid)

    pool_info = stratis_info.pools[pool_uuid]

    try:
        ((succ, _paths), rc, err) = safe_dbus.call_sync(STRATIS_SERVICE,
                                                        pool_info.object_path,
                                                        STRATIS_POOL_INTF,
                                                        "CreateFilesystems",
                                                        GLib.Variant("(as)", ([name],)))
    except safe_dbus.DBusCallError as e:
        raise StratisError("Failed to create stratis filesystem on '%s': %s" % (pool_info.name, str(e)))
    else:
        if not succ:
            raise StratisError("Failed to create stratis filesystem on '%s': %s (%d)" % (pool_info.name, err, rc))
