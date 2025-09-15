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

import json
import os

from dasbus.typing import UnixFD
from dasbus.unix import GLibClientUnix
from dasbus.error import DBusError

from ..errors import StratisError
from ..size import Size
from ..static_data import stratis_info
from ..tasks import availability
from .. import util


STRATIS_SERVICE = "org.storage.stratis3"
STRATIS_PATH = "/org/storage/stratis3"
STRATIS_POOL_INTF = STRATIS_SERVICE + ".pool.r0"
STRATIS_FILESYSTEM_INTF = STRATIS_SERVICE + ".filesystem.r0"
STRATIS_BLOCKDEV_INTF = STRATIS_SERVICE + ".blockdev.r0"
STRATIS_MANAGER_INTF = STRATIS_SERVICE + ".Manager.r0"
STRATIS_MANAGER_INTF_R8 = STRATIS_SERVICE + ".Manager.r8"

STRATIS_FS_SIZE = Size("1 TiB")

STRATIS_CALL_TIMEOUT = 120 * 1000  # 120 s (used by stratis-cli by default) in ms


safe_name_characters = "0-9a-zA-Z._-"


def pool_used(dev_sizes, encrypted=False):
    if not availability.STRATISPREDICTUSAGE_APP.available:
        raise StratisError("Utility for predicting stratis pool usage '%s' not available" % availability.STRATISPREDICTUSAGE_APP.name)

    cmd = [availability.STRATISPREDICTUSAGE_APP.name, "pool"]
    for size in dev_sizes:
        cmd.extend(["--device-size", str(size.get_bytes())])
    if encrypted:
        cmd.append("--encrypted")

    rc, out = util.run_program_and_capture_output(cmd, stderr_to_stdout=True)
    if rc:
        raise StratisError("Failed to predict usage for stratis pool")

    try:
        pred = json.loads(out)
    except json.JSONDecodeError as e:
        raise StratisError("Failed to get stratis pool usage") from e

    return Size(pred["used"])


def filesystem_md_size(fs_size):
    if not availability.STRATISPREDICTUSAGE_APP.available:
        raise StratisError("Utility for predicting stratis pool usage '%s' not available" % availability.STRATISPREDICTUSAGE_APP.name)

    rc, out = util.run_program_and_capture_output([availability.STRATISPREDICTUSAGE_APP.name, "filesystem",
                                                   "--filesystem-size",
                                                   str(fs_size.get_bytes())],
                                                  stderr_to_stdout=True)
    if rc:
        raise StratisError("Failed to predict usage for stratis filesystem: %s" % out)

    try:
        pred = json.loads(out)
    except json.JSONDecodeError as e:
        raise StratisError("Failed to get stratis filesystem usage") from e

    return Size(pred["used"])


def remove_pool(pool_uuid):
    if not availability.STRATIS_DBUS.available:
        raise StratisError("Stratis DBus service not available")

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    if pool_uuid not in stratis_info.pools.keys():
        raise StratisError("Stratis pool with UUID %s not found" % pool_uuid)

    pool_info = stratis_info.pools[pool_uuid]

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, STRATIS_PATH, STRATIS_MANAGER_INTF)
        (succ, _uuid), rc, err = proxy.DestroyPool(pool_info.object_path,
                                                   timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to remove stratis pool: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to remove stratis pool: %s (%d)" % (err, rc))


def remove_filesystem(pool_uuid, fs_uuid):
    if not availability.STRATIS_DBUS.available:
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
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, pool_info.object_path, STRATIS_POOL_INTF)
        (succ, _uuid), rc, err = proxy.DestroyFilesystems([fs_info.object_path],
                                                          timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to remove stratis filesystem: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to remove stratis filesystem: %s (%d)" % (err, rc))


def set_key(key_desc, passphrase, key_file):
    if passphrase:
        (read, write) = os.pipe()
        os.write(write, passphrase.encode("utf-8"))
        fd = read
    elif key_file:
        fd = os.open(key_file, os.O_RDONLY)
    else:
        raise RuntimeError("Passphrase or key file must be provided")

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, STRATIS_PATH, STRATIS_MANAGER_INTF,
                                         client=GLibClientUnix)
        ((_changed, _set), rc, err) = proxy.SetKey(key_desc, UnixFD(fd))
    except DBusError as e:
        raise StratisError("Failed to set key for new pool: %s" % str(e))
    else:
        if rc != 0:
            raise StratisError("Failed to set key for new pool: %s (%d)" % (err, rc))
    finally:
        if key_file:
            os.close(fd)
        if passphrase:
            os.close(write)


def _unlock_pool_old(pool_uuid, method=None, desc=None, passphrase=None, keyfile=None):
    if method == "keyring":
        set_key(desc, passphrase, keyfile)

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, STRATIS_PATH, STRATIS_MANAGER_INTF)
        (succ, err, _blockdevs) = proxy.UnlockPool(pool_uuid, method)
    except DBusError as e:
        raise StratisError("Failed to unlock pool: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to unlock pool: %s" % err)
    finally:
        # repopulate the stratis info cache so the started pool is in correct list of pools
        stratis_info.drop_cache()


def _unlock_pool_new(pool_uuid, method=None, passphrase=None, keyfile=None):
    if method == "keyring":
        if passphrase:
            (read, write) = os.pipe()
            os.write(write, passphrase.encode("utf-8"))
            fd = read
        elif keyfile:
            fd = os.open(keyfile, os.O_RDONLY)
        else:
            raise RuntimeError("Passphrase or key file must be provided")

        key_arg = (True, UnixFD(fd))
    else:
        key_arg = (False, -1)

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, STRATIS_PATH, STRATIS_MANAGER_INTF_R8,
                                         client=GLibClientUnix)
        (succ, err, _blockdevs) = proxy.StartPool(pool_uuid, "uuid", (True, (False, 0)), key_arg,
                                                  timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to unlock pool: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to unlock pool: %s" % err)
    finally:
        if keyfile:
            os.close(fd)
        if passphrase:
            os.close(write)
        # repopulate the stratis info cache so the started pool is in correct list of pools
        stratis_info.drop_cache()


def unlock_pool(pool_uuid, method, desc=None, passphrase=None, keyfile=None):
    if not availability.STRATIS_DBUS.available:
        raise StratisError("Stratis DBus service not available")

    ret = util.check_object_available(STRATIS_SERVICE, STRATIS_PATH,
                                      iface=STRATIS_MANAGER_INTF_R8)
    if ret:
        return _unlock_pool_new(pool_uuid, method, passphrase, keyfile)
    else:
        return _unlock_pool_old(pool_uuid, method, desc, passphrase, keyfile)


def create_pool(name, devices, encrypted, passphrase, key_file, clevis):
    if not availability.STRATIS_DBUS.available:
        raise StratisError("Stratis DBus service not available")

    if encrypted and not (passphrase or key_file):
        raise StratisError("Passphrase or key file must be specified for encrypted pool")

    raid_opt = (False, 0)

    if encrypted:
        key_desc = "blivet-%s" % name  # XXX what would be a good key description?
        set_key(key_desc, passphrase, key_file)
        key_opt = (True, key_desc)
        if clevis:
            clevis_config = {"url": clevis.tang_url}
            if clevis.tang_thumbprint:
                clevis_config["thp"] = clevis.tang_thumbprint
            else:
                clevis_config["stratis:tang:trust_url"] = True
            clevis_opt = (True, (clevis.pin, json.dumps(clevis_config)))
        else:
            clevis_opt = (False, ("", ""))
    else:
        key_opt = (False, "")
        clevis_opt = (False, ("", ""))

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, STRATIS_PATH, STRATIS_MANAGER_INTF)
        ((succ, _paths), rc, err) = proxy.CreatePool(name, raid_opt, devices, key_opt, clevis_opt,
                                                     timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to create stratis pool: %s" % str(e))
    else:
        if not succ:
            raise StratisError("Failed to create stratis pool: %s (%d)" % (err, rc))

    # repopulate the stratis info cache so the new pool will be added
    stratis_info.drop_cache()


def create_filesystem(name, pool_uuid, fs_size=None):
    if not availability.STRATIS_DBUS.available:
        raise StratisError("Stratis DBus service not available")

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    if pool_uuid not in stratis_info.pools.keys():
        raise StratisError("Stratis pool with UUID %s not found" % pool_uuid)

    pool_info = stratis_info.pools[pool_uuid]
    if fs_size:
        size_opt = (True, str(fs_size.get_bytes()))
    else:
        size_opt = (False, "")

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, pool_info.object_path, STRATIS_POOL_INTF)
        ((succ, _paths), rc, err) = proxy.CreateFilesystems([(name, size_opt), ],
                                                            timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to create stratis filesystem on '%s': %s" % (pool_info.name, str(e)))
    else:
        if not succ:
            raise StratisError("Failed to create stratis filesystem on '%s': %s (%d)" % (pool_info.name, err, rc))

    # repopulate the stratis info cache so the new filesystem will be added
    stratis_info.drop_cache()


def add_device(pool_uuid, device):
    if not availability.STRATIS_DBUS.available:
        raise StratisError("Stratis DBus service not available")

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    pool_info = stratis_info.pools[pool_uuid]

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, pool_info.object_path, STRATIS_POOL_INTF)
        ((succ, _paths), rc, err) = proxy.AddDataDevs([device], timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to create stratis filesystem on '%s': %s" % (pool_info.name, str(e)))
    else:
        if not succ:
            raise StratisError("Failed to create stratis filesystem on '%s': %s (%d)" % (pool_info.name, err, rc))

    # repopulate the stratis info cache so the new filesystem will be added
    stratis_info.drop_cache()


def stop_pool(pool_uuid):
    if not availability.STRATIS_DBUS.available:
        raise StratisError("Stratis DBus service not available")

    ret = util.check_object_available(STRATIS_SERVICE, STRATIS_PATH,
                                      iface=STRATIS_MANAGER_INTF_R8)
    if not ret:
        raise StratisError("DBus interface %s not available" % STRATIS_MANAGER_INTF_R8)

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    pool_info = stratis_info.pools[pool_uuid]

    if not pool_info:
        raise StratisError("Stratis pool %s not found" % pool_uuid)

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, STRATIS_PATH, STRATIS_MANAGER_INTF_R8)
        ((succ, _uuid), rc, err) = proxy.StopPool(pool_uuid, "uuid", timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to stop stratis pool '%s': %s" % (pool_info.name, str(e)))
    else:
        if not succ:
            raise StratisError("Failed to stop stratis pool '%s': %s (%d)" % (pool_info.name, err, rc))

    # repopulate the stratis info cache so the stopped pool is in correct list of pools
    stratis_info.drop_cache()


def start_pool(pool_uuid):
    if not availability.STRATIS_DBUS.available:
        raise StratisError("Stratis DBus service not available")

    ret = util.check_object_available(STRATIS_SERVICE, STRATIS_PATH,
                                      iface=STRATIS_MANAGER_INTF_R8)
    if not ret:
        raise StratisError("DBus interface %s not available" % STRATIS_MANAGER_INTF_R8)

    # repopulate the stratis info cache just to be sure all values are still valid
    stratis_info.drop_cache()

    try:
        proxy = util.SystemBus.get_proxy(STRATIS_SERVICE, STRATIS_PATH, STRATIS_MANAGER_INTF_R8)
        ((succ, _uuid), rc, err) = proxy.StartPool(pool_uuid, "uuid", (False, (False, 0)), (False, -1),
                                                   timeout=STRATIS_CALL_TIMEOUT)
    except DBusError as e:
        raise StratisError("Failed to start stratis pool '%s': %s" % (pool_uuid, str(e)))
    else:
        if not succ:
            raise StratisError("Failed to start stratis pool '%s': %s (%d)" % (pool_uuid, err, rc))

    # repopulate the stratis info cache so the started pool is in correct list of pools
    stratis_info.drop_cache()
