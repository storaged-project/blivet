# Copyright (C) 2023  Red Hat, Inc.
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
# Red Hat Author(s): Todd Gill <tgill@redhat.com>
#

import dbus
import argparse

import blivet
import blivet.devicefactory
from blivet.devicefactory import (
    DEVICE_TYPE_LVM,
    DEVICE_TYPE_MD,
    DEVICE_TYPE_BTRFS,
    DEVICE_TYPE_STRATIS,
)

from sh import umount

OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
BUS = dbus.SystemBus()
BUS_NAME = "com.redhat.Blivet0"
TOP_OBJECT = "/com/redhat/Blivet0/Blivet"
REVISION_NUMBER = 1
REVISION = f"r{REVISION_NUMBER}"

MOUNT_POINT = "/testmount"

TIMEOUT = 10 * 1000

# TODO: Add revision to dbus interface.  Once completed, update to:
# f"{BUS_NAME}.Blivet.{REVISION}"
BLIVET_INTERFACE = f"{BUS_NAME}.Blivet"
DEVICE_INTERFACE = f"{BUS_NAME}.Device"
FORMAT_INTERFACE = f"{BUS_NAME}.Format"


def get_managed_objects():
    # TODO: GetManagedObjects is implemented at the /com/redhat/Blivet0 level.
    # The other methods are implemented at /com/redhat/Blivet0/Blivet.  Is
    # that intentional?
    object_manager = dbus.Interface(
        BUS.get_object(BUS_NAME, "/com/redhat/Blivet0"),
        OBJECT_MANAGER,
    )
    return object_manager.GetManagedObjects(timeout=TIMEOUT)


def commit(blivet_interface):
    return blivet_interface.Commit()


def remove_device(blivet_interface, object_path, disks):
    umount(MOUNT_POINT)
    blivet_interface.RemoveDevice(object_path)
    for disk in disks:
        blivet_interface.RemoveDevice(disk)

    commit(blivet_interface)


def initialize(blivet_interface, disk):
    return blivet_interface.InitializeDisk(disk)


def reset(blivet_interface):
    return blivet_interface.Reset()


def list_devices(blivet_interface):
    return blivet_interface.ListDevices()


def list_device_objects(blivet_interface):
    objects = get_managed_objects().items()

    device_objects = [
        obj_data[DEVICE_INTERFACE]
        for _, obj_data in objects
        if DEVICE_INTERFACE in obj_data
    ]
    device_objects


def print_dict(type, dict):
    print(type)
    for key, value in dict.items():
        print("    ", key, "\t: ", value)


def print_properties(object_path, interface):
    object = BUS.get_object(BUS_NAME, object_path)
    properties_interface = dbus.Interface(
        object, dbus_interface="org.freedesktop.DBus.Properties"
    )
    props = properties_interface.GetAll(interface)
    print_dict(interface, props)


def get_property(object_path, interface, value):
    object = BUS.get_object(BUS_NAME, object_path)
    properties_interface = dbus.Interface(
        object, dbus_interface="org.freedesktop.DBus.Properties"
    )
    props = properties_interface.GetAll(interface)
    return props[value]


def initialize_disks(blivet_interface, disks):
    for disk in disks:
        initialize(blivet_interface, disk)
    commit(blivet_interface)


def lvm_create(blivet_interface, disks, fs_name, size):
    kwargs = {
        "device_type": DEVICE_TYPE_LVM,
        "size": size,
        "disks": disks,
        "fstype": "xfs",
        "name": fs_name,
        "mountpoint": MOUNT_POINT,
        "raid_level": "raid1",
    }

    return blivet_interface.Factory(kwargs)


def btrfs_create(blivet_interface, disks, fs_name, size):
    kwargs = {
        "device_type": DEVICE_TYPE_BTRFS,
        "size": size,
        "disks": disks,
        "name": fs_name,
        "mountpoint": MOUNT_POINT,
        "raid_level": "raid1",
        "container_raid_level": "raid1",
        "fstype": "btrfs",
    }

    return blivet_interface.Factory(kwargs)


def md_create(blivet_interface, disks, fs_name, size):
    kwargs = {
        "device_type": DEVICE_TYPE_MD,
        "size": size,
        "disks": disks,
        "fstype": "xfs",
        "name": fs_name,
        "mountpoint": MOUNT_POINT,
        "raid_level": "raid1",
        "container_raid_level": "raid1",
    }

    return blivet_interface.Factory(kwargs)


def stratis_create(blivet_interface, disks, fs_name, size):
    kwargs = {
        "device_type": DEVICE_TYPE_STRATIS,
        "size": size,
        "disks": disks,
        "name": fs_name,
        "mountpoint": MOUNT_POINT,
    }

    return blivet_interface.Factory(kwargs)


def test_create_dev(blivet_interface, disks, storage_type, size):
    initialize_disks(blivet_interface, disks)

    newdev_object_path = None

    match storage_type:
        case blivet.devicefactory.DEVICE_TYPE_LVM:
            newdev_object_path = lvm_create(
                blivet_interface, disks, "test_lvm_filesystem", size
            )

        case blivet.devicefactory.DEVICE_TYPE_BTRFS:
            newdev_object_path = btrfs_create(
                blivet_interface, disks, "test_btrfs_filesystem", size
            )

        case blivet.devicefactory.DEVICE_TYPE_MD:
            newdev_object_path = md_create(
                blivet_interface, disks, "test_md_filesystem", size
            )

        case blivet.devicefactory.DEVICE_TYPE_STRATIS:
            newdev_object_path = stratis_create(
                blivet_interface, disks, "test_stratis_filesystem", size
            )
        case default:
            return None

    commit(blivet_interface)
    return newdev_object_path


if __name__ == "__main__":
    bus = dbus.SystemBus()

    parser = argparse.ArgumentParser()

    parser.add_argument("--blockdevs", dest="blockdevs", type=str, default="")
    args = parser.parse_args()

    # Accept a blockdev list in either "/dev/xxx,/dev/xxx" or [/dev/xxx /dev/xxx] format.
    blockdevs = (
        args.blockdevs.replace("'", "")
        .replace(" ", ",")
        .replace("[", "")
        .replace("]", "")
    )
    blockdevs_list = blockdevs.split(",")

    if len(blockdevs_list) < 2:
        print("test requires at least 2 block devices.")
        exit(1)

    # This adds a signal match so that the client gets signals sent by Blivet1's
    # ObjectManager. These signals are used to notify clients of changes to the
    # managed objects (for blivet, this will be devices, formats, and actions).
    # bus.add_match_string("type='signal',sender=" + BUS_NAME + ",path_namespace=" + TOP_OBJECT)

    top_object = bus.get_object(BUS_NAME, TOP_OBJECT)
    blivet_interface = dbus.Interface(
        top_object,
        BLIVET_INTERFACE,
    )

    size = "3g"
    reset(blivet_interface)

    objects = get_managed_objects()

    device_objects = list_device_objects(blivet_interface)
    disks = list()
    for object_path in list_devices(blivet_interface):
        device = objects[object_path][DEVICE_INTERFACE]
        print_properties(object_path, DEVICE_INTERFACE)
        print_properties(device["Format"], FORMAT_INTERFACE)

        # search for the disk object paths
        for to_use in blockdevs_list:
            if to_use == get_property(object_path, DEVICE_INTERFACE, "Path"):
                disks.append(str(object_path))

    print("To Use", disks)

    new_object_path = None

    new_object_path = test_create_dev(blivet_interface, disks, DEVICE_TYPE_LVM, size)
    if new_object_path != None:
        remove_device(blivet_interface, new_object_path, disks)

    new_object_path = test_create_dev(blivet_interface, disks, DEVICE_TYPE_BTRFS, size)
    if new_object_path != None:
        remove_device(blivet_interface, new_object_path, disks)

    new_object_path = test_create_dev(blivet_interface, disks, DEVICE_TYPE_MD, size)
    if new_object_path != None:
        remove_device(blivet_interface, new_object_path, disks)

    new_object_path = test_create_dev(
        blivet_interface, disks, DEVICE_TYPE_STRATIS, size
    )
    if new_object_path != None:
        remove_device(blivet_interface, new_object_path, disks)
