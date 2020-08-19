# udev.py
# Python module for querying the udev database for device information.
#
# Copyright (C) 2009, 2013  Red Hat, Inc.
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
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#                    Chris Lumens <clumens@redhat.com>
#

import os
import re
import subprocess
import logging
import pyudev

from . import util
from .size import Size
from .flags import flags

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

global_udev = pyudev.Context()
log = logging.getLogger("blivet")

ignored_device_names = []
""" device name regexes to ignore; this should be empty by default """


def device_to_dict(device):
    # Transform Device to dictionary
    # Originally it was possible to use directly Device where needed,
    # but it lead to unfixable excessive deprecation warnings from udev.
    # Sice blivet uses Device.properties only (with couple of exceptions)
    # this is a functional workaround. (japokorn May 2017)

    result = dict(device.properties)
    result["SYS_NAME"] = device.sys_name
    result["SYS_PATH"] = device.sys_path
    return result


def get_device(sysfs_path=None, device_node=None):
    try:
        if sysfs_path is not None:
            device = pyudev.Devices.from_sys_path(global_udev, sysfs_path)
        elif device_node is not None:
            device = pyudev.Devices.from_device_file(global_udev, device_node)
    except pyudev.DeviceNotFoundError as e:
        log.error(e)
        result = None
    else:
        result = device_to_dict(device)

    return result


def get_devices(subsystem="block"):
    if not flags.uevents:
        settle()

    result = []
    for device in global_udev.list_devices(subsystem=subsystem):
        if not __is_ignored_blockdev(device.sys_name):
            dev = device_to_dict(device)
            result.append(dev)

    return result


def settle(quiet=False):
    """ Wait for the udev queue to settle.

        :keyword bool quiet: bypass :meth:`blivet.util.run_program`
    """
    # wait maximal 300 seconds for udev to be done running blkid, lvm,
    # mdadm etc. This large timeout is needed when running on machines with
    # lots of disks, or with slow disks
    argv = ["udevadm", "settle", "--timeout=300"]
    if quiet:
        subprocess.call(argv, close_fds=True)
    else:
        util.run_program(argv)


def trigger(subsystem=None, action="add", name=None):
    argv = ["trigger", "--action=%s" % action]
    if subsystem:
        argv.append("--subsystem-match=%s" % subsystem)
    if name:
        argv.append("--sysname-match=%s" % name)

    util.run_program(["udevadm"] + argv)
    settle()


def resolve_devspec(devspec, sysname=False):
    if not devspec:
        return None

    # import devices locally to avoid cyclic import (devices <-> udev)
    from . import devices

    devname = devices.device_path_to_name(devspec)

    ret = None
    for dev in get_devices():
        if devspec.startswith("LABEL="):
            if device_get_label(dev) == devspec[6:]:
                ret = dev
                break
        elif devspec.startswith("UUID="):
            if device_get_uuid(dev) == devspec[5:]:
                ret = dev
                break
        elif device_get_name(dev) == devname or dev["SYS_NAME"] == devname:
            ret = dev
            break
        else:
            spec = devspec
            if not spec.startswith("/dev/"):
                spec = os.path.normpath("/dev/" + spec)

            for link in device_get_symlinks(dev):
                if spec == link:
                    ret = dev
                    break

    if ret:
        return ret["SYS_NAME"] if sysname else device_get_name(ret)


def resolve_glob(glob):
    """
    :param str glob: glob to match device **names** against
    :returns: list of udev info objects matching :param:`glob`

    .. note:: This function matches device **names** ("sda"), not paths ("/dev/sda").

    """
    import fnmatch
    ret = []

    if not glob:
        return ret

    for dev in get_devices():
        name = device_get_name(dev)
        path = device_get_devname(dev)

        if name and fnmatch.fnmatch(name, glob):
            ret.append(name)
        elif path and fnmatch.fnmatch(path, glob):
            ret.append(name)
        else:
            for link in device_get_symlinks(dev):
                if link and fnmatch.fnmatch(link, glob):
                    ret.append(name)

    return ret


def __is_ignored_blockdev(dev_name):
    """Is this a blockdev we never want for an install?"""
    if dev_name.startswith("ram") or dev_name.startswith("fd"):
        return True

    if ignored_device_names:
        if any(re.search(expr, dev_name) for expr in ignored_device_names):
            return True

    model_path = "/sys/class/block/%s/device/model" % dev_name
    if os.path.exists(model_path):
        model = open(model_path, encoding="utf-8", errors="replace").read()
        for bad in ("IBM *STMF KERNEL", "SCEI Flash-5", "DGC LUNZ"):
            if model.find(bad) != -1:
                log.info("ignoring %s with model %s", dev_name, model)
                return True

    return False

# These are functions for retrieving specific pieces of information from
# udev database entries.


def device_get_name(udev_info):
    """ Return the best name for a device based on the udev db data. """
    if "DM_NAME" in udev_info:
        name = udev_info["DM_NAME"]
    elif "MD_DEVNAME" in udev_info:
        mdname = udev_info["MD_DEVNAME"]
        if device_is_md(udev_info):
            # MD RAID array -> use MD_DEVNAME
            name = mdname
        elif device_get_format(udev_info) == "linux_raid_member":
            # MD RAID member -> use SYS_NAME
            name = udev_info["SYS_NAME"]
        elif device_is_partition(udev_info):
            # partition on RAID -> construct name from MD_DEVNAME + partition number
            # for partitions on named RAID we want to use the raid name, not
            # the node, e.g. "raid1" instead of "md127p1"
            partnum = udev_info["ID_PART_ENTRY_NUMBER"]
            if mdname[-1].isdigit():
                name = mdname + "p" + partnum
            else:
                name = mdname + partnum
        else:
            # something else -> default to MD_DEVNAME
            name = mdname
    else:
        name = udev_info["SYS_NAME"]

    return name


def device_get_format(udev_info):
    """ Return a device's format type as reported by udev. """
    return udev_info.get("ID_FS_TYPE")


def device_get_format_version(udev_info):
    """ Return a device's format version as reported by udev. """
    return udev_info.get("ID_FS_VERSION")


def device_get_uuid(udev_info):
    """ Get the UUID from the device's format as reported by udev.

        :param dict udev_info: dictionary of name-value pairs as strings
        :returns: a UUID or None
        :rtype: str or NoneType
    """
    return udev_info.get("ID_FS_UUID")


def device_get_label(udev_info):
    """ Get the label from the device's format as reported by udev. """
    return udev_info.get("ID_FS_LABEL")


def device_get_part_size(udev_info):
    """ Get size for specified partition as reported by udev. """
    return udev_info.get("ID_PART_ENTRY_SIZE")


def device_is_dm(info):
    """ Return True if the device is a device-mapper device. """
    dm_dir = os.path.join(device_get_sysfs_path(info), "dm")
    return 'DM_NAME' in info or os.path.exists(dm_dir)


def device_is_md(info):
    """ Return True if the device is a mdraid array device. """
    # Don't identify partitions on mdraid arrays as raid arrays
    if device_is_partition(info):
        return False

    # The udev information keeps shifting around. Only md arrays have a
    # /sys/class/block/<name>/md/ subdirectory.
    md_dir = device_get_sysfs_path(info) + "/md"
    return os.path.exists(md_dir)


def device_is_cciss(info):
    """ Return True if the device is a CCISS device. """
    return device_get_name(info).startswith("cciss")


def device_is_dasd(info):
    """ Return True if the device is a dasd device. """
    devname = info.get("DEVNAME", '').split("/")[-1]
    return devname.startswith("dasd")


def device_is_zfcp(info):
    """ Return True if the device is a zfcp device. """
    if info.get("DEVTYPE") != "disk":
        return False

    subsystem = device_get_sysfs_path(info)

    while True:
        topdir = os.path.realpath(os.path.dirname(subsystem))
        driver = "%s/driver" % (topdir,)

        if os.path.islink(driver):
            subsystemname = os.path.basename(os.readlink(subsystem))
            drivername = os.path.basename(os.readlink(driver))

            if subsystemname == 'ccw' and drivername == 'zfcp':
                return True

        newsubsystem = os.path.dirname(topdir)

        if newsubsystem == topdir:
            break

        subsystem = newsubsystem + "/subsystem"

    return False


def device_get_zfcp_attribute(info, attr=None):
    """ Return the value of the specified attribute of the zfcp device. """
    if not attr:
        log.debug("device_get_zfcp_attribute() called with attr=None")
        return None

    attribute = "%s/device/%s" % (device_get_sysfs_path(info), attr)
    attribute = os.path.realpath(attribute)

    if not os.path.isfile(attribute):
        log.warning("%s is not a valid zfcp attribute", attribute)
        return None

    return open(attribute, "r").read().strip()


def device_get_dasd_bus_id(info):
    """ Return the CCW bus ID of the dasd device. """
    return device_get_sysfs_path(info).split("/")[-3]


def device_get_dasd_flag(info, flag=None):
    """ Return the specified flag for the dasd device. """
    if flag is None:
        return None

    path = device_get_sysfs_path(info) + "/device/" + flag
    if not os.path.isfile(path):
        return None

    return open(path, 'r').read().strip()


def device_is_cdrom(info):
    """ Return True if the device is an optical drive. """
    # FIXME: how can we differentiate USB drives from CD-ROM drives?
    #         -- USB drives also generate a sd_x device.
    return info.get("ID_CDROM") == "1"


def device_is_disk(info):
    """ Return True if the device is a disk.

        Unfortunately, since so many things are represented as disks by
        udev/sysfs, we have to define what is a disk in terms of what is
        not a disk.
    """
    has_range = os.path.exists("%s/range" % device_get_sysfs_path(info))
    is_disk = info.get("DEVTYPE") == "disk" or has_range

    return (is_disk and
            not (device_is_cdrom(info) or
                 device_is_partition(info) or
                 device_is_dm_partition(info) or
                 device_is_dm_lvm(info) or
                 device_is_dm_crypt(info) or
                 (device_is_md(info) and
                  (not device_get_md_container(info) and not all(device_is_disk(d) for d in device_get_parents(info))))))


def device_is_partition(info):
    has_start = os.path.exists("%s/start" % device_get_sysfs_path(info))
    return info.get("DEVTYPE") == "partition" or has_start


def device_is_loop(info):
    """ Return True if the device is a loop device. """
    return device_get_name(info).startswith("loop")


def device_get_serial(udev_info):
    """ Get the serial number/UUID from the device as reported by udev. """
    return udev_info.get("ID_SERIAL_RAW", udev_info.get("ID_SERIAL", udev_info.get("ID_SERIAL_SHORT")))


def device_get_wwn(udev_info):
    """ Return the WWID as reported by udev without '0x' prefix. """
    wwn = udev_info.get("ID_WWN_WITH_EXTENSION")
    if wwn:
        wwn = wwn[2:]  # strip off the leading '0x'
    return wwn


def device_get_vendor(udev_info):
    """ Get the vendor of the device as reported by udev. """
    return udev_info.get("ID_VENDOR_FROM_DATABASE", udev_info.get("ID_VENDOR"))


def device_get_model(udev_info):
    """ Get the model of the device as reported by udev. """
    return udev_info.get("ID_MODEL_FROM_DATABASE", udev_info.get("ID_MODEL"))


def device_get_bus(udev_info):
    """ Get the bus a device is connected to the system by. """
    return udev_info.get("ID_BUS", "").upper()


def device_get_path(info):
    return info.get("ID_PATH", "")


def device_get_symlinks(info):
    """ Get an array of symbolic links for a device.

        :param info: a :class:`pyudev.Device` instance
        :returns: list of symbolic links
        :rtype: list of str
    """
    return info.get("DEVLINKS", "").split()


def device_get_by_path(info):
    for link in device_get_symlinks(info):
        if link.startswith('/dev/disk/by-path/'):
            return link

    return device_get_name(info)


def device_get_sysfs_path(info):
    return info["SYS_PATH"]


def device_get_major(info):
    return int(info["MAJOR"])


def device_get_minor(info):
    return int(info["MINOR"])


def device_get_devname(info):
    return info.get('DEVNAME')


def device_get_parents(info):
    """ Return a list of udev device objects representing this device's parents. """
    parents_dir = device_get_sysfs_path(info) + "/slaves/"
    names = list()
    if os.path.isdir(parents_dir):
        names = os.listdir(parents_dir)

    parents = list()
    for name in names:
        parents.append(get_device(device_node="/dev/" + name))

    return parents


def device_get_holders(info):
    """ Return a list of udev device objects representing this device's holders. """
    holders_dir = device_get_sysfs_path(info) + "/holders/"
    names = list()
    if os.path.isdir(holders_dir):
        names = os.listdir(holders_dir)

    holders = list()
    for name in names:
        holders.append(get_device(device_node="/dev/" + name))

    return holders


def device_get_md_level(info):
    """ Returns the RAID level of the array of which this device is a member.

        :param dict info: dictionary of name-value pairs as strings
        :returns: the RAID level of this device's md array
        :rtype: str or NoneType
    """
    # Value for MD_LEVEL known to be obtained from:
    #  * pyudev/libudev
    #  * mdraid/mdadm (all numeric metadata versions and container default)
    return info.get("MD_LEVEL")


def device_get_md_devices(info):
    """ Returns the number of active devices in this device's array.

        Active devices are devices that are not spares or failed.

        :param dict info: dictionary of name-value pairs as strings
        :returns: the number of devices belonging to this device's md array
        :rtype: int
        :raises: KeyError, ValueError
    """
    # Value for MD_DEVICES known to be obtained from:
    #  * pyudev/libudev
    #  * mdraid/mdadm (all numeric metadata versions and container default)
    return int(info["MD_DEVICES"])


def device_get_md_uuid(info):
    """ Returns the uuid of the array of which this device is a member.

        :param dict info: dictionary of name-value pairs as strings
        :returns: the UUID of this device's md array
        :rtype: str
        :raises: KeyError
    """
    # Value for MD_UUID known to be obtained from:
    #  * pyudev/libudev
    #  * mdraid/mdadm (all numeric metadata versions and container default)
    return util.canonicalize_UUID(info["MD_UUID"])


def device_get_md_container(info):
    """
        :param dict info: dictionary of name-value pairs as strings
        :rtype: str or NoneType
    """
    # Value for MD_CONTAINER known to be obtained from:
    #  * None
    return info.get("MD_CONTAINER")


def device_get_md_name(info):
    """ Returns the name of the array of which this device is a member.

        :param dict info: dictionary of name-value pairs as strings
        :returns: the name of this device's md array
        :rtype: str or NoneType
    """
    # Value for MD_DEVNAME known to be obtained from:
    #  * pyudev/libudev
    #  * No known metadata versions for mdraid/mdadm
    return info.get("MD_DEVNAME")


def device_get_md_metadata(info):
    """ Return the metadata version number.

        :param dict info: dictionary of name-value pairs as strings
        :returns: the metadata version number of the md array
        :rtype: str or NoneType
    """
    # Value for MD_METADATA known to be obtained from:
    #  * pyudev/libudev
    #  * mdraid/mdadm (not version numbers < 1)
    return info.get("MD_METADATA")


def device_get_md_device_uuid(info):
    """ Returns the uuid of a device which is a member of an md array.

        :param dict info: dictionary of name-value pairs as strings
        :returns: the uuid of this device (which is a member of an md array)
        :rtype: str or NoneType
    """
    # Value for MD_UUID known to be obtained from:
    #  * pyudev/libudev
    #  * mdraid/mdadm (only 1.x metadata versions)
    # Value for ID_FS_UUID_SUB known to be obtained from:
    #  * pyudev/libudev
    md_device_uuid = info.get('ID_FS_UUID_SUB') or info.get('MD_DEV_UUID')
    return util.canonicalize_UUID(md_device_uuid) if md_device_uuid else None


def device_get_vg_name(info):
    return info['LVM2_VG_NAME']


def device_get_lv_vg_name(info):
    return info['DM_VG_NAME']


def device_get_vg_uuid(info):
    return info['LVM2_VG_UUID']


def device_get_vg_size(info):
    # lvm's decmial precision is not configurable, so we tell it to use
    # KB.
    return Size("%s KiB" % info['LVM2_VG_SIZE'])


def device_get_vg_free(info):
    # lvm's decmial precision is not configurable, so we tell it to use
    # KB.
    return Size("%s KiB" % info['LVM2_VG_FREE'])


def device_get_vg_extent_size(info):
    return Size("%s KiB" % info['LVM2_VG_EXTENT_SIZE'])


def device_get_vg_extent_count(info):
    return int(info['LVM2_VG_EXTENT_COUNT'])


def device_get_vg_free_extents(info):
    return int(info['LVM2_VG_FREE_COUNT'])


def device_get_vg_pv_count(info):
    return int(info['LVM2_PV_COUNT'])


def device_get_pv_pe_start(info):
    return Size("%s KiB" % info['LVM2_PE_START'])


def device_get_lv_name(info):
    return info['LVM2_LV_NAME']


def device_get_lv_uuid(info):
    return info['LVM2_LV_UUID']


def device_get_lv_size(info):
    return Size("%s KiB" % info['LVM2_LV_SIZE'])


def device_get_lv_attr(info):
    return info['LVM2_LV_ATTR']


def device_get_lv_type(info):
    return info['LVM2_SEGTYPE']


def device_dm_subsystem_match(info, subsystem):
    """ Return True if the device matches a given device-mapper subsystem. """
    name = info.get("DM_NAME")
    if name is None:
        return False

    _subsystem = blockdev.dm.get_subsystem_from_name(name)
    if not _subsystem:
        return False

    return _subsystem.lower() == subsystem.lower()


def device_is_dm_lvm(info):
    """ Return True if the device is an LVM logical volume. """
    return device_dm_subsystem_match(info, "lvm")


def device_is_dm_crypt(info):
    """ Return True if the device is a mapped dm-crypt device. """
    return device_dm_subsystem_match(info, "crypt")


def device_is_dm_luks(info):
    """ Return True if the device is a mapped LUKS device. """
    is_crypt = device_dm_subsystem_match(info, "crypt")
    try:
        _type = info.get("DM_UUID", "").split("-")[1].lower()
    except IndexError:
        _type = ""

    return is_crypt and _type.startswith("luks")


def device_is_dm_integrity(info):
    """ Return True if the device is a mapped integrity device. """
    is_crypt = device_dm_subsystem_match(info, "crypt")
    if not is_crypt:
        return False

    try:
        _type = info.get("DM_UUID", "").split("-")[1].lower()
    except IndexError:
        _type = ""

    return _type.startswith("integrity")


def device_is_dm_raid(info):
    """ Return True if the device is a dmraid array device. """
    return device_dm_subsystem_match(info, "dmraid")


def device_is_dm_mpath(info):
    """ Return True if the device is a multipath device. """
    return device_dm_subsystem_match(info, "mpath")


def device_is_dm_anaconda(info):
    """ Return True if the device is an anaconda disk image. """
    return device_dm_subsystem_match(info, "anaconda")


def device_is_dm_livecd(info):
    """ Return True if the device is a livecd OS image. """
    # return device_dm_subsystem_match(info, "livecd")
    return (device_is_dm(info) and
            device_get_name(info).startswith("live"))


def device_is_biosraid_member(info):
    # Note that this function does *not* identify raid sets.
    # Tests to see if device is part of a dmraid set.
    # dmraid and mdraid have the same ID_FS_USAGE string, ID_FS_TYPE has a
    # string that describes the type of dmraid (isw_raid_member...),  I don't
    # want to maintain a list and mdraid's ID_FS_TYPE='linux_raid_member', so
    # dmraid will be everything that is raid and not linux_raid_member
    from .formats.dmraid import DMRaidMember
    from .formats.mdraid import MDRaidMember
    if 'ID_FS_TYPE' in info and \
            (info["ID_FS_TYPE"] in DMRaidMember._udev_types or
             info["ID_FS_TYPE"] in MDRaidMember._udev_types) and \
            info["ID_FS_TYPE"] != "linux_raid_member":
        return True

    return False


def device_get_partition_disk(info):
    """ Return the (friendly) name of the given partition's disk. """
    if not (device_is_partition(info) or device_is_dm_partition(info)):
        return None

    disk = None
    majorminor = info.get("ID_PART_ENTRY_DISK")
    sysfs_path = device_get_sysfs_path(info)
    parents_dir = "%s/slaves" % sysfs_path
    if majorminor:
        major, minor = majorminor.split(":")
        for device in get_devices():
            if device.get("MAJOR") == major and device.get("MINOR") == minor:
                disk = device_get_name(device)
                break
    elif device_is_dm_partition(info):
        if os.path.isdir(parents_dir):
            parents = os.listdir(parents_dir)
            if len(parents) == 1:
                disk = resolve_devspec(parents[0].replace('!', '/'))
    else:
        _disk = os.path.basename(os.path.dirname(sysfs_path).replace('!', '/'))
        if info["SYS_NAME"].startswith(_disk):
            disk = resolve_devspec(_disk)

    return disk


def device_is_dm_partition(info):
    return (device_is_dm(info) and
            info.get("DM_UUID", "").split("-")[0].startswith("part"))


def device_get_disklabel_type(info):
    """ Return the type of disklabel on the device or None. """
    if device_is_partition(info) or device_is_dm_partition(info):
        # For partitions, ID_PART_TABLE_TYPE is the disklabel type for the
        # partition's disk. It does not mean the partition contains a disklabel.
        return None

    return info.get("ID_PART_TABLE_TYPE")


def device_get_disklabel_uuid(info):
    return info.get("ID_PART_TABLE_UUID")


def device_get_partition_uuid(info):
    return info.get("ID_PART_ENTRY_UUID")

# iscsi disks' ID_PATH form depends on the driver:
# for software iscsi:
# ip-${iscsi_address}:${iscsi_port}-iscsi-${iscsi_tgtname}-lun-${lun}
# for partial offload iscsi:
# pci-${pci_address}-ip-${iscsi_address}:${iscsi_port}-iscsi-${iscsi_tgtname}-lun-${lun}
# Note that in the case of IPV6 iscsi_address itself can contain :
# too, but iscsi_port never contains :


def device_is_sw_iscsi(info):
    # software iscsi
    try:
        path_components = device_get_path(info).split("-")

        if info["ID_BUS"] == "scsi" and len(path_components) >= 6 and \
                path_components[0] == "ip" and path_components[2] == "iscsi":
            return True
    except KeyError:
        pass

    return False


def device_is_partoff_iscsi(info):
    # partial offload iscsi
    try:
        path_components = device_get_path(info).split("-")

        if info["ID_BUS"] == "scsi" and len(path_components) >= 8 and \
                path_components[2] == "ip" and path_components[4] == "iscsi":
            return True
    except KeyError:
        pass

    return False


def device_is_iscsi(info):
    return device_is_sw_iscsi(info) or device_is_partoff_iscsi(info)


def device_get_iscsi_name(info):
    name_field = 3
    if device_is_partoff_iscsi(info):
        name_field = 5

    path_components = device_get_path(info).split("-")

    # Tricky, the name itself contains atleast 1 - char
    return "-".join(path_components[name_field:len(path_components) - 2])


def device_get_iscsi_lun(info):
    lun = 0
    path_components = device_get_path(info).split("-")
    idx = list(reversed(path_components)).index("lun")
    if idx > 0:
        lun = path_components[-idx]

    return lun


def device_get_iscsi_address(info):
    address_field = 1
    if device_is_partoff_iscsi(info):
        address_field = 3

    path_components = device_get_path(info).split("-")

    # IPV6 addresses contain : within the address, so take everything
    # before the last : as address
    return ":".join(path_components[address_field].split(":")[:-1])


def device_get_iscsi_port(info):
    address_field = 1
    if device_is_partoff_iscsi(info):
        address_field = 3

    path_components = device_get_path(info).split("-")

    # IPV6 contains : within the address, the part after the last : is the port
    return path_components[address_field].split(":")[-1]


def device_get_iscsi_session(info):
    # '/devices/pci0000:00/0000:00:02.0/0000:09:00.0/0000:0a:01.0/0000:0e:00.2/host3/session1/target3:0:0/3:0:0:0/block/sda'
    # The position of sessionX part depends on device
    # (e.g. offload vs. sw; also varies for different offload devs)
    session = None
    match = re.match(r'/.*/(session\d+)', device_get_sysfs_path(info))
    if match:
        session = match.groups()[0]
    else:
        log.error("device_get_iscsi_session: session not found in %s", info)
    return session


def device_get_iscsi_nic(info):
    iface = None
    session = device_get_iscsi_session(info)
    if session:
        iface = open("/sys/class/iscsi_session/%s/ifacename" %
                     session).read().strip()
    return iface


def device_get_iscsi_initiator(info):
    initiator_name = None
    if device_is_partoff_iscsi(info):
        host = re.match(r'.*/(host\d+)', device_get_sysfs_path(info)).groups()[0]
        if host:
            initiator_file = "/sys/class/iscsi_host/%s/initiatorname" % host
            if os.access(initiator_file, os.R_OK):
                initiator = open(initiator_file, "rb").read().strip()
                initiator_name = initiator.decode("utf-8", errors="replace")
                log.debug("found offload iscsi initiatorname %s in file %s",
                          initiator_name, initiator_file)
                if initiator_name.lstrip("(").rstrip(")").lower() == "null":
                    initiator_name = None
    if initiator_name is None:
        session = device_get_iscsi_session(info)
        if session:
            initiator = open("/sys/class/iscsi_session/%s/initiatorname" %
                             session, "rb").read().strip()
            initiator_name = initiator.decode("utf-8", errors="replace")
            log.debug("found iscsi initiatorname %s", initiator_name)
    return initiator_name


# fcoe disks have ID_PATH in the form of:
# For FCoE directly over the NIC (so no VLAN and thus no DCB):
# pci-eth#-fc-${id}
# For FCoE over a VLAN (the DCB case)
# fc-${id}
# fcoe parts look like this:
# pci-eth#-fc-${id}-part#
# fc-${id}-part#

# For the FCoE over VLAN case we also do some checks on the sysfs_path as
# the ID_PATH does not contain all info we need there, the sysfs_path for
# an fcoe disk over VLAN looks like this:
# /devices/virtual/net/eth4.802-fcoe/host3/rport-3:0-4/target3:0:1/3:0:1:0/block/sde
# And for a partition:
# /devices/virtual/net/eth4.802-fcoe/host3/rport-3:0-4/target3:0:1/3:0:1:0/block/sde/sde1

# This is completely different for Broadcom FCoE devices (bnx2fc), where we use
# the sysfs path:
# /devices/pci0000:00/0000:00:03.0/0000:04:00.3/net/eth3/ctlr_0/host5/rport-5:0-3/target5:0:1/5:0:1:147/block/sdb
# and sometimes:
# /devices/virtual/net/p2p1.802-fcoe/ctlr_0/host7/rport-7:0-5/target7:0:2/7:0:2:0/block/sdb
# and find whether the host has 'fc_host' and if it the device has a bound
# Ethernet interface.

def _detect_broadcom_fcoe(info):
    re_pci_host = re.compile(r'(.*)/(host\d+)')
    match = re_pci_host.match(device_get_sysfs_path(info))
    if match:
        sysfs_pci, host = match.groups()
        if os.access('%s/%s/fc_host' % (sysfs_pci, host), os.X_OK) and \
                'net' in sysfs_pci:
            return (sysfs_pci, host)
    return (None, None)


def device_is_fcoe(info):
    if info.get("ID_BUS") != "scsi":
        return False

    path = info.get("ID_PATH", "")
    path_components = path.split("-")

    if path.startswith("pci-eth") and len(path_components) >= 4 and \
       path_components[2] == "fc":
        return True

    if path.startswith("fc-") and "fcoe" in device_get_sysfs_path(info):
        return True

    if _detect_broadcom_fcoe(info) != (None, None):
        return True

    return False


def device_get_fcoe_nic(info):
    path = info.get("ID_PATH", "")
    path_components = path.split("-")
    sysfs_path = device_get_sysfs_path(info)

    if path.startswith("pci-eth") and len(path_components) >= 4 and \
       path_components[2] == "fc":
        return path_components[1]

    if path.startswith("fc-") and "fcoe" in sysfs_path:
        return sysfs_path.split("/")[5].split(".")[0]

    (sysfs_pci, host) = _detect_broadcom_fcoe(info)
    if (sysfs_pci, host) != (None, None):
        net, iface = sysfs_path.split("/")[6:8]
        if net != "net":
            log.warning("unexpected sysfs_path of bnx2fc device: %s", sysfs_path)
            match = re.compile(r'.*/net/([^/]*)').match(sysfs_path)
            if match:
                return match.groups()[0].split(".")[0]
        else:
            return iface


def device_get_fcoe_identifier(info):
    path = info.get("ID_PATH", "")
    path_components = path.split("-")

    if path.startswith("pci-eth") and len(path_components) >= 4 and \
       path_components[2] == "fc":
        return path_components[3]

    if path.startswith("fc-") and "fcoe" in device_get_sysfs_path(info):
        return path_components[1]

    if device_is_fcoe(info) and len(path_components) >= 4 and \
       path_components[2] == 'fc':
        return path_components[3]


def device_is_nvdimm_namespace(info):
    if info.get("DEVTYPE") != "disk":
        return False

    if not blockdev.is_plugin_available(blockdev.Plugin.NVDIMM):
        # nvdimm plugin is not available -- even if this is an nvdimm device we
        # don't have tools to work with it, so we should pretend it's just a disk
        return False

    devname = info.get("DEVNAME", "")
    ninfo = blockdev.nvdimm_namespace_get_devname(devname)
    return ninfo is not None


def device_is_hidden(info):
    sysfs_path = device_get_sysfs_path(info)
    hidden = util.get_sysfs_attr(sysfs_path, "hidden")
    if not hidden or not hidden.isnumeric():
        return False

    return bool(int(hidden))
