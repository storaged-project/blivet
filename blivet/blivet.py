#
# Copyright (C) 2009-2015  Red Hat, Inc.
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
#

import os
import copy
import tempfile
import re
import shelve
import contextlib
import time
import parted
import functools

from pykickstart.constants import AUTOPART_TYPE_LVM, CLEARPART_TYPE_ALL, CLEARPART_TYPE_LINUX, CLEARPART_TYPE_LIST, CLEARPART_TYPE_NONE

from .storage_log import log_method_call, log_exception_info
from .devices import BTRFSDevice, BTRFSSubVolumeDevice, BTRFSVolumeDevice
from .devices import LVMLogicalVolumeDevice, LVMVolumeGroupDevice
from .devices import MDRaidArrayDevice, PartitionDevice, TmpFSDevice, device_path_to_name
from .deviceaction import ActionCreateDevice, ActionCreateFormat, ActionDestroyDevice
from .deviceaction import ActionDestroyFormat, ActionResizeDevice, ActionResizeFormat
from .devicelibs.edd import get_edd_dict
from .devicelibs.btrfs import MAIN_VOLUME_ID
from .errors import StorageError
from .size import Size
from .devicetree import DeviceTree
from .formats import get_default_filesystem_type
from .flags import flags
from .platform import platform as _platform
from .formats import get_format
from .osinstall import FSSet, find_existing_installations
from . import arch
from .iscsi import iscsi
from . import fcoe
from . import zfcp
from . import devicefactory
from . import get_bootloader, get_sysroot, short_product_name, __version__
from .threads import SynchronizedMeta
from .util import open  # pylint: disable=redefined-builtin

from .i18n import _

import logging
log = logging.getLogger("blivet")


def empty_device(device):
    empty = True
    if device.partitioned:
        partitions = device.children
        empty = all([p.is_magic for p in partitions])
    else:
        empty = (device.format.type is None)

    return empty


class StorageDiscoveryConfig(object):

    """ Class to encapsulate various detection/initialization parameters. """

    def __init__(self):
        # storage configuration variables
        self.ignore_disk_interactive = False
        self.ignored_disks = []
        self.exclusive_disks = []
        self.clear_part_type = None
        self.clear_part_disks = []
        self.clear_part_devices = []
        self.initialize_disks = False
        self.protected_dev_specs = []
        self.disk_images = {}
        self.zero_mbr = False

        # Whether clear_partitions removes scheduled/non-existent devices and
        # disklabels depends on this flag.
        self.clear_non_existent = False

    def update(self, ksdata):
        """ Update configuration from ksdata source.

            :param ksdata: kickstart data used as data source
            :type ksdata: :class:`pykickstart.Handler`
        """
        self.ignored_disks = ksdata.ignoredisk.ignoredisk[:]
        self.exclusive_disks = ksdata.ignoredisk.onlyuse[:]
        self.clear_part_type = ksdata.clearpart.type
        self.clear_part_disks = ksdata.clearpart.drives[:]
        self.clear_part_devices = ksdata.clearpart.devices[:]
        self.initialize_disks = ksdata.clearpart.init_all
        self.zero_mbr = ksdata.zerombr.zerombr


class Blivet(object, metaclass=SynchronizedMeta):

    """ Top-level class for managing storage configuration. """

    def __init__(self, ksdata=None):
        """
            :keyword ksdata: kickstart data store
            :type ksdata: :class:`pykickstart.Handler`
        """
        self.ksdata = ksdata
        self._bootloader = None

        self.config = StorageDiscoveryConfig()

        # storage configuration variables
        self.do_autopart = False
        self.clear_part_choice = None
        self.encrypted_autopart = False
        self.autopart_type = AUTOPART_TYPE_LVM
        self.encryption_passphrase = None
        self.encryption_cipher = None
        self.escrow_certificates = {}
        self.autopart_escrow_cert = None
        self.autopart_add_backup_passphrase = False
        self.autopart_requests = []
        self.edd_dict = {}

        self.__luks_devs = {}
        self.size_sets = []
        self.set_default_fstype(get_default_filesystem_type())
        self._default_boot_fstype = None

        self.fcoe = fcoe.fcoe()
        self.zfcp = zfcp.ZFCP()

        self._next_id = 0
        self._dump_file = "%s/storage.state" % tempfile.gettempdir()

        # these will both be empty until our reset method gets called
        self.devicetree = DeviceTree(conf=self.config,
                                     passphrase=self.encryption_passphrase,
                                     luks_dict=self.__luks_devs)
        self.fsset = FSSet(self.devicetree)
        self.roots = []
        self.services = set()
        self._free_space_snapshot = None

    def do_it(self, callbacks=None):
        """
        Commit queued changes to disk.

        :param callbacks: callbacks to be invoked when actions are executed
        :type callbacks: return value of the :func:`~.callbacks.create_new_callbacks_register`

        """

        self.devicetree.actions.process(callbacks=callbacks, devices=self.devices)
        if not flags.installer_mode:
            return

        # now set the boot partition's flag
        if self.bootloader and not self.bootloader.skip_bootloader:
            if self.bootloader.stage2_bootable:
                boot = self.boot_device
            else:
                boot = self.boot_loader_device

            if boot.type == "mdarray":
                boot_devs = boot.parents
            else:
                boot_devs = [boot]

            for dev in boot_devs:
                if not hasattr(dev, "bootable"):
                    log.info("Skipping %s, not bootable", dev)
                    continue

                # Dos labels can only have one partition marked as active
                # and unmarking ie the windows partition is not a good idea
                skip = False
                if dev.disk.format.parted_disk.type == "msdos":
                    for p in dev.disk.format.parted_disk.partitions:
                        if p.type == parted.PARTITION_NORMAL and \
                           p.getFlag(parted.PARTITION_BOOT):
                            skip = True
                            break

                # GPT labeled disks should only have bootable set on the
                # EFI system partition (parted sets the EFI System GUID on
                # GPT partitions with the boot flag)
                if dev.disk.format.label_type == "gpt" and \
                   dev.format.type not in ["efi", "macefi"]:
                    skip = True

                if skip:
                    log.info("Skipping %s", dev.name)
                    continue

                # hfs+ partitions on gpt can't be marked bootable via parted
                if dev.disk.format.parted_disk.type != "gpt" or \
                        dev.format.type not in ["hfs+", "macefi"]:
                    log.info("setting boot flag on %s", dev.name)
                    dev.bootable = True

                # Set the boot partition's name on disk labels that support it
                if dev.parted_partition.disk.supportsFeature(parted.DISK_TYPE_PARTITION_NAME):
                    ped_partition = dev.parted_partition.getPedPartition()
                    ped_partition.setName(dev.format.name)
                    log.info("Setting label on %s to '%s'", dev, dev.format.name)

                dev.disk.setup()
                dev.disk.format.commit_to_disk()

        if flags.installer_mode:
            self.dump_state("final")

    @property
    def next_id(self):
        """ Used for creating unique placeholder names. """
        newid = self._next_id
        self._next_id += 1
        return newid

    def shutdown(self):
        """ Deactivate all devices (installer_mode only). """
        if not flags.installer_mode:
            return

        try:
            self.devicetree.teardown_all()
        except Exception:  # pylint: disable=broad-except
            log_exception_info(log.error, "failure tearing down device tree")

    def reset(self, cleanup_only=False):
        """ Reset storage configuration to reflect actual system state.

            This will cancel any queued actions and rescan from scratch but not
            clobber user-obtained information like passphrases, iscsi config, &c

            :keyword cleanup_only: prepare the tree only to deactivate devices
            :type cleanup_only: bool

            See :meth:`devicetree.Devicetree.populate` for more information
            about the cleanup_only keyword argument.
        """
        log.info("resetting Blivet (version %s) instance %s", __version__, self)
        if flags.installer_mode:
            # save passphrases for luks devices so we don't have to reprompt
            self.encryption_passphrase = None
            for device in self.devices:
                if device.format.type == "luks" and device.format.exists:
                    self.save_passphrase(device)

        if self.ksdata:
            self.config.update(self.ksdata)

        if flags.installer_mode and not flags.image_install:
            iscsi.startup()
            self.fcoe.startup()
            self.zfcp.startup()

        self.devicetree.reset(conf=self.config,
                              passphrase=self.encryption_passphrase,
                              luks_dict=self.__luks_devs)
        self.devicetree.populate(cleanup_only=cleanup_only)
        self.fsset = FSSet(self.devicetree)
        self.edd_dict = get_edd_dict(self.partitioned)
        self.devicetree.edd_dict = self.edd_dict
        if self.bootloader:
            # clear out bootloader attributes that refer to devices that are
            # no longer in the tree
            self.bootloader.reset()

        self.roots = []
        if flags.installer_mode:
            self.roots = find_existing_installations(self.devicetree)
            self.dump_state("initial")

        if not flags.installer_mode:
            self.devicetree.handle_nodev_filesystems()

        self.update_boot_loader_disk_list()

    @property
    def unused_devices(self):
        used_devices = []
        for root in self.roots:
            for device in list(root.mounts.values()) + root.swaps:
                if device not in self.devices:
                    continue

                used_devices.extend(device.ancestors)

        for new in [d for d in self.devicetree.leaves if not d.format.exists]:
            if new.format.mountable and not new.format.mountpoint:
                continue

            used_devices.extend(new.ancestors)

        for device in self.partitions:
            if getattr(device, "is_logical", False):
                extended = device.disk.format.extended_partition.path
                used_devices.append(self.devicetree.get_device_by_path(extended))

        used = set(used_devices)
        _all = set(self.devices)
        return list(_all.difference(used))

    @property
    def devices(self):
        """ A list of all the devices in the device tree. """
        devices = self.devicetree.devices
        devices.sort(key=lambda d: d.name)
        return devices

    @property
    def disks(self):
        """ A list of the disks in the device tree.

            Ignored disks are excluded, as are disks with no media present.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        disks = []
        for device in self.devicetree.devices:
            if device.is_disk:
                if not device.media_present:
                    log.info("Skipping disk: %s: No media present", device.name)
                    continue
                disks.append(device)
        disks.sort(key=self.compare_disks_key)
        return disks

    @property
    def partitioned(self):
        """ A list of the partitioned devices in the device tree.

            Ignored devices are not included, nor disks with no media present.

            Devices of types for which partitioning is not supported are also
            not included.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        partitioned = []
        for device in self.devicetree.devices:
            if not device.partitioned:
                continue

            if not device.media_present:
                log.info("Skipping device: %s: No media present", device.name)
                continue

            partitioned.append(device)

        partitioned.sort(key=lambda d: d.name)
        return partitioned

    @property
    def partitions(self):
        """ A list of the partitions in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        partitions = self.devicetree.get_devices_by_instance(PartitionDevice)
        partitions.sort(key=lambda d: d.name)
        return partitions

    @property
    def vgs(self):
        """ A list of the LVM Volume Groups in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        vgs = self.devicetree.get_devices_by_type("lvmvg")
        vgs.sort(key=lambda d: d.name)
        return vgs

    @property
    def lvs(self):
        """ A list of the LVM Logical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        lvs = (d for d in self.devices if d.type in ("lvmlv", "lvmthinpool", "lvmthinlv"))
        return sorted(lvs, key=lambda d: d.name)

    @property
    def thinlvs(self):
        """ A list of the LVM Thin Logical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        thin = self.devicetree.get_devices_by_type("lvmthinlv")
        thin.sort(key=lambda d: d.name)
        return thin

    @property
    def thinpools(self):
        """ A list of the LVM Thin Pool Logical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        pools = self.devicetree.get_devices_by_type("lvmthinpool")
        pools.sort(key=lambda d: d.name)
        return pools

    @property
    def pvs(self):
        """ A list of the LVM Physical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        devices = self.devicetree.devices
        pvs = [d for d in devices if d.format.type == "lvmpv"]
        pvs.sort(key=lambda d: d.name)
        return pvs

    @property
    def mdarrays(self):
        """ A list of the MD arrays in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        arrays = self.devicetree.get_devices_by_type("mdarray")
        arrays.sort(key=lambda d: d.name)
        return arrays

    @property
    def mdcontainers(self):
        """ A list of the MD containers in the device tree. """
        arrays = self.devicetree.get_devices_by_type("mdcontainer")
        arrays.sort(key=lambda d: d.name)
        return arrays

    @property
    def mdmembers(self):
        """ A list of the MD member devices in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        devices = self.devicetree.devices
        members = [d for d in devices if d.format.type == "mdmember"]
        members.sort(key=lambda d: d.name)
        return members

    @property
    def btrfs_volumes(self):
        """ A list of the BTRFS volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        return sorted(self.devicetree.get_devices_by_type("btrfs volume"),
                      key=lambda d: d.name)

    @property
    def swaps(self):
        """ A list of the swap devices in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        devices = self.devicetree.devices
        swaps = [d for d in devices if d.format.type == "swap"]
        swaps.sort(key=lambda d: d.name)
        return swaps

    def should_clear(self, device, **kwargs):
        """ Return True if a clearpart settings say a device should be cleared.

            :param device: the device (required)
            :type device: :class:`~.devices.StorageDevice`
            :keyword clear_part_type: overrides :attr:`self.config.clear_part_type`
            :type clear_part_type: int
            :keyword clear_part_disks: overrides
                                     :attr:`self.config.clear_part_disks`
            :type clear_part_disks: list
            :keyword clear_part_devices: overrides
                                       :attr:`self.config.clear_part_devices`
            :type clear_part_devices: list
            :returns: whether or not clear_partitions should remove this device
            :rtype: bool
        """
        clear_part_type = kwargs.get("clear_part_type", self.config.clear_part_type)
        clear_part_disks = kwargs.get("clear_part_disks",
                                      self.config.clear_part_disks)
        clear_part_devices = kwargs.get("clear_part_devices",
                                        self.config.clear_part_devices)

        for disk in device.disks:
            # this will not include disks with hidden formats like multipath
            # and firmware raid member disks
            if clear_part_disks and disk.name not in clear_part_disks:
                return False

        if not self.config.clear_non_existent:
            if (device.is_disk and not device.format.exists) or \
               (not device.is_disk and not device.exists):
                return False

        # the only devices we want to clear when clear_part_type is
        # CLEARPART_TYPE_NONE are uninitialized disks, or disks with no
        # partitions, in clear_part_disks, and then only when we have been asked
        # to initialize disks as needed
        if clear_part_type in [CLEARPART_TYPE_NONE, None]:
            if not self.config.initialize_disks or not device.is_disk:
                return False

            if not empty_device(device):
                return False

        if isinstance(device, PartitionDevice):
            # Never clear the special first partition on a Mac disk label, as
            # that holds the partition table itself.
            # Something similar for the third partition on a Sun disklabel.
            if device.is_magic:
                return False

            # We don't want to fool with extended partitions, freespace, &c
            if not device.is_primary and not device.is_logical:
                return False

            if clear_part_type == CLEARPART_TYPE_LINUX and \
               not device.format.linux_native and \
               not device.get_flag(parted.PARTITION_LVM) and \
               not device.get_flag(parted.PARTITION_RAID) and \
               not device.get_flag(parted.PARTITION_SWAP):
                return False
        elif device.is_disk:
            if device.partitioned and clear_part_type != CLEARPART_TYPE_ALL:
                # if clear_part_type is not CLEARPART_TYPE_ALL but we'll still be
                # removing every partition from the disk, return True since we
                # will want to be able to create a new disklabel on this disk
                if not empty_device(device):
                    return False

            # Never clear disks with hidden formats
            if device.format.hidden:
                return False

            # When clear_part_type is CLEARPART_TYPE_LINUX and a disk has non-
            # linux whole-disk formatting, do not clear it. The exception is
            # the case of an uninitialized disk when we've been asked to
            # initialize disks as needed
            if (clear_part_type == CLEARPART_TYPE_LINUX and
                not ((self.config.initialize_disks and
                      empty_device(device)) or
                     (not device.partitioned and device.format.linux_native))):
                return False

        # Don't clear devices holding install media.
        descendants = self.devicetree.get_dependent_devices(device)
        if device.protected or any(d.protected for d in descendants):
            return False

        if clear_part_type == CLEARPART_TYPE_LIST and \
           device.name not in clear_part_devices:
            return False

        return True

    def recursive_remove(self, device):
        """ Remove a device after removing its dependent devices.

            If the device is not a leaf, all of its dependents are removed
            recursively until it is a leaf device. At that point the device is
            removed, unless it is a disk. If the device is a disk, its
            formatting is removed by no attempt is made to actually remove the
            disk device.
        """
        self.devicetree.recursive_remove(device)

    def clear_partitions(self):
        """ Clear partitions and dependent devices from disks.

            This is also where zerombr is handled.
        """
        # Sort partitions by descending partition number to minimize confusing
        # things like multiple "destroy sda5" actions due to parted renumbering
        # partitions. This can still happen through the UI but it makes sense to
        # avoid it where possible.
        partitions = sorted(self.partitions,
                            key=lambda p: p.parted_partition.number,
                            reverse=True)
        for part in partitions:
            log.debug("clearpart: looking at %s", part.name)
            if not self.should_clear(part):
                continue

            self.recursive_remove(part)
            log.debug("partitions: %s", [p.getDeviceNodeName() for p in part.parted_partition.disk.partitions])

        # now remove any empty extended partitions
        self.remove_empty_extended_partitions()

        # ensure all disks have appropriate disklabels
        for disk in self.disks:
            zerombr = (self.config.zero_mbr and disk.format.type is None)
            should_clear = self.should_clear(disk)
            if should_clear:
                self.recursive_remove(disk)

            if zerombr or should_clear:
                log.debug("clearpart: initializing %s", disk.name)
                self.initialize_disk(disk)

        self.update_boot_loader_disk_list()

    def initialize_disk(self, disk):
        """ (Re)initialize a disk by creating a disklabel on it.

            The disk should not contain any partitions except perhaps for a
            magic partitions on mac and sun disklabels. If the disk does contain
            partitions other than the disklabel-type-specific "magic" partitions
            ValueError will be raised.

            :param disk: the disk to initialize
            :type disk: :class:`~.devices.StorageDevice`
            :returns None:
            :raises: ValueError
        """
        # first, remove magic mac/sun partitions from the parted Disk
        if disk.partitioned:
            magic = disk.format.magic_partition_number
            expected = 0
            if magic:
                expected = 1
                # remove the magic partition
                for part in disk.children:
                    if part.parted_partition.number == magic:
                        log.debug("removing %s", part.name)
                        # We can't schedule the magic partition for removal
                        # because parted will not allow us to remove it from the
                        # disk. Still, we need it out of the devicetree.
                        self.devicetree._remove_device(part, modparent=False)

            if len(disk.format.partitions) > expected:
                raise ValueError("cannot initialize a disk that has partitions")

        # remove existing formatting from the disk
        destroy_action = ActionDestroyFormat(disk)
        self.devicetree.actions.add(destroy_action)

        label_type = _platform.best_disklabel_type(disk)

        # create a new disklabel on the disk
        new_label = get_format("disklabel", device=disk.path,
                               label_type=label_type)
        create_action = ActionCreateFormat(disk, fmt=new_label)
        self.devicetree.actions.add(create_action)

    def remove_empty_extended_partitions(self):
        for disk in self.partitioned:
            log.debug("checking whether disk %s has an empty extended", disk.name)
            extended = disk.format.extended_partition
            logical_parts = disk.format.logical_partitions
            log.debug("extended is %s ; logicals is %s", extended, [p.getDeviceNodeName() for p in logical_parts])
            if extended and not logical_parts:
                log.debug("removing empty extended partition from %s", disk.name)
                extended_name = device_path_to_name(extended.getDeviceNodeName())
                extended = self.devicetree.get_device_by_name(extended_name)
                self.destroy_device(extended)

    def get_free_space(self, disks=None, clear_part_type=None):
        """ Return a dict with free space info for each disk.

            The dict values are 2-tuples: (disk_free, fs_free). fs_free is
            space available by shrinking filesystems. disk_free is space not
            allocated to any partition.

            disks and clear_part_type allow specifying a set of disks other than
            self.disks and a clear_part_type value other than
            self.config.clear_part_type.

            :keyword disks: overrides :attr:`disks`
            :type disks: list
            :keyword clear_part_type: overrides :attr:`self.config.clear_part_type`
            :type clear_part_type: int
            :returns: dict with disk name keys and tuple (disk, fs) free values
            :rtype: dict

            .. note::

                The free space values are :class:`~.size.Size` instances.

        """
        if disks is None:
            disks = self.disks

        if clear_part_type is None:
            clear_part_type = self.config.clear_part_type

        free = {}
        for disk in disks:
            should_clear = self.should_clear(disk, clear_part_type=clear_part_type,
                                             clear_part_disks=[disk.name])
            if should_clear:
                free[disk.name] = (disk.size, Size(0))
                continue

            disk_free = Size(0)
            fs_free = Size(0)
            if disk.partitioned:
                disk_free = disk.format.free
                for partition in [p for p in self.partitions if p.disk == disk]:
                    # only check actual filesystems since lvm &c require a bunch of
                    # operations to translate free filesystem space into free disk
                    # space
                    should_clear = self.should_clear(partition,
                                                     clear_part_type=clear_part_type,
                                                     clear_part_disks=[disk.name])
                    if should_clear:
                        disk_free += partition.size
                    elif hasattr(partition.format, "free"):
                        fs_free += partition.format.free
            elif hasattr(disk.format, "free"):
                fs_free = disk.format.free
            elif disk.format.type is None:
                disk_free = disk.size

            free[disk.name] = (disk_free, fs_free)

        return free

    @property
    def names(self):
        """ A list of all of the known in-use device names. """
        return self.devicetree.names

    def device_deps(self, device):
        """ Return a list of the devices that depend on the specified device.

            :param device: the subtree root device
            :type device: :class:`~.devices.StorageDevice`
            :returns: list of dependent devices
            :rtype: list
        """
        return self.devicetree.get_dependent_devices(device)

    def new_partition(self, *args, **kwargs):
        """ Return a new (unallocated) PartitionDevice instance.

            :keyword fmt_type: format type
            :type fmt_type: str
            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str

            All other arguments are passed on to the
            :class:`~.devices.PartitionDevice` constructor.
        """
        if 'fmt_type' in kwargs:
            kwargs["fmt"] = get_format(kwargs.pop("fmt_type"),
                                       mountpoint=kwargs.pop("mountpoint",
                                                             None),
                                       **kwargs.pop("fmt_args", {}))

        if 'name' in kwargs:
            name = kwargs.pop("name")
        else:
            name = "req%d" % self.next_id

        if "weight" not in kwargs:
            fmt = kwargs.get("fmt")
            if fmt:
                mountpoint = getattr(fmt, "mountpoint", None)

                kwargs["weight"] = _platform.weight(mountpoint=mountpoint,
                                                    fstype=fmt.type)

        return PartitionDevice(name, *args, **kwargs)

    def new_mdarray(self, *args, **kwargs):
        """ Return a new MDRaidArrayDevice instance.

            :keyword fmt_type: format type
            :type fmt_type: str
            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :returns: the new md array device
            :rtype: :class:`~.devices.MDRaidArrayDevice`

            All other arguments are passed on to the
            :class:`~.devices.MDRaidArrayDevice` constructor.

            If a name is not specified, one will be generated based on the
            format type, mountpoint, hostname, and/or product name.
        """
        if 'fmt_type' in kwargs:
            kwargs["fmt"] = get_format(kwargs.pop("fmt_type"),
                                       mountpoint=kwargs.pop("mountpoint",
                                                             None),
                                       **kwargs.pop("fmt_args", {}))

        name = kwargs.pop("name", None)
        if name:
            safe_name = self.safe_device_name(name)
            if safe_name != name:
                log.warning("using '%s' instead of specified name '%s'",
                            safe_name, name)
                name = safe_name
        else:
            swap = getattr(kwargs.get("fmt"), "type", None) == "swap"
            mountpoint = getattr(kwargs.get("fmt"), "mountpoint", None)
            name = self.suggest_device_name(prefix=short_product_name,
                                            swap=swap,
                                            mountpoint=mountpoint)

        return MDRaidArrayDevice(name, *args, **kwargs)

    def new_vg(self, *args, **kwargs):
        """ Return a new LVMVolumeGroupDevice instance.

            :returns: the new volume group device
            :rtype: :class:`~.devices.LVMVolumeGroupDevice`

            All arguments are passed on to the
            :class:`~.devices.LVMVolumeGroupDevice` constructor.

            If a name is not specified, one will be generated based on the
            hostname, and/or product name.
        """
        pvs = kwargs.pop("parents", [])
        for pv in pvs:
            if pv not in self.devices:
                raise ValueError("pv is not in the device tree")

        name = kwargs.pop("name", None)
        if name:
            safe_name = self.safe_device_name(name)
            if safe_name != name:
                log.warning("using '%s' instead of specified name '%s'",
                            safe_name, name)
                name = safe_name
        else:
            hostname = ""
            if self.ksdata and self.ksdata.network.hostname is not None:
                hostname = self.ksdata.network.hostname

            name = self.suggest_container_name(hostname=hostname)

        if name in self.names:
            raise ValueError("name already in use")

        return LVMVolumeGroupDevice(name, pvs, *args, **kwargs)

    def new_lv(self, *args, **kwargs):
        """ Return a new LVMLogicalVolumeDevice instance.

            :keyword fmt_type: format type
            :type fmt_type: str
            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :keyword thin_pool: whether to create a thin pool
            :type thin_pool: bool
            :keyword thin_volume: whether to create a thin volume
            :type thin_volume: bool
            :returns: the new device
            :rtype: :class:`~.devices.LVMLogicalVolumeDevice`

            All other arguments are passed on to the appropriate
            :class:`~.devices.LVMLogicalVolumeDevice` constructor.

            If a name is not specified, one will be generated based on the
            format type and/or mountpoint.

            .. note::

                If you are creating a thin volume, the parents kwarg should
                contain the pool -- not the vg.
        """
        thin_volume = kwargs.pop("thin_volume", False)
        thin_pool = kwargs.pop("thin_pool", False)
        parent = kwargs.get("parents", [None])[0]
        if thin_volume and parent:
            # kwargs["parents"] will contain the pool device, so...
            vg = parent.vg
        else:
            vg = parent

        if thin_volume:
            kwargs["seg_type"] = "thin"
        if thin_pool:
            kwargs["seg_type"] = "thin-pool"

        mountpoint = kwargs.pop("mountpoint", None)
        if 'fmt_type' in kwargs:
            kwargs["fmt"] = get_format(kwargs.pop("fmt_type"),
                                       mountpoint=mountpoint,
                                       **kwargs.pop("fmt_args", {}))

        name = kwargs.pop("name", None)
        if name:
            # make sure the specified name is sensible
            safe_vg_name = self.safe_device_name(vg.name)
            full_name = "%s-%s" % (safe_vg_name, name)
            safe_name = self.safe_device_name(full_name)
            if safe_name != full_name:
                new_name = safe_name[len(safe_vg_name) + 1:]
                log.warning("using '%s' instead of specified name '%s'",
                            new_name, name)
                name = new_name
        else:
            if kwargs.get("fmt") and kwargs["fmt"].type == "swap":
                swap = True
            else:
                swap = False

            prefix = ""
            if thin_pool:
                prefix = "pool"

            name = self.suggest_device_name(parent=vg,
                                            swap=swap,
                                            mountpoint=mountpoint,
                                            prefix=prefix)

        if "%s-%s" % (vg.name, name) in self.names:
            raise ValueError("name already in use")

        if thin_pool or thin_volume:
            cache_req = kwargs.pop("cache_request", None)
            if cache_req:
                raise ValueError("Creating cached thin volumes and pools is not supported")

        return LVMLogicalVolumeDevice(name, *args, **kwargs)

    def new_btrfs(self, *args, **kwargs):
        """ Return a new BTRFSVolumeDevice or BRFSSubVolumeDevice.

            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :keyword subvol: whether this is a subvol (as opposed to a volume)
            :type subvol: bool
            :returns: the new device
            :rtype: :class:`~.devices.BTRFSDevice`

            All other arguments are passed on to the appropriate
            :class:`~.devices.BTRFSDevice` constructor.

            For volumes, the label is the same as the name. If a name/label is
            not specified, one will be generated based on the hostname and/or
            product name.

            .. note::

                If you are creating a subvolume, the parents kwarg should
                contain the volume you want to contain the subvolume.

        """
        log.debug("new_btrfs: args = %s ; kwargs = %s", args, kwargs)
        name = kwargs.pop("name", None)
        if args:
            name = args[0]

        mountpoint = kwargs.pop("mountpoint", None)

        fmt_args = kwargs.pop("fmt_args", {})
        fmt_args.update({"mountpoint": mountpoint})

        if kwargs.pop("subvol", False):
            dev_class = BTRFSSubVolumeDevice

            # set up the subvol name, using mountpoint if necessary
            if not name:
                # for btrfs this only needs to ensure the subvol name is not
                # already in use within the parent volume
                name = self.suggest_device_name(mountpoint=mountpoint)
            fmt_args["mountopts"] = "subvol=%s" % name
            fmt_args["subvolspec"] = name
            kwargs.pop("metadata_level", None)
            kwargs.pop("data_level", None)
            kwargs.pop("create_options", None)
        else:
            dev_class = BTRFSVolumeDevice
            # set up the volume label, using hostname if necessary
            if not name:
                hostname = ""
                if self.ksdata and self.ksdata.network.hostname is not None:
                    hostname = self.ksdata.network.hostname

                name = self.suggest_container_name(hostname=hostname)
            if "label" not in fmt_args:
                fmt_args["label"] = name
            fmt_args["subvolspec"] = MAIN_VOLUME_ID

        # discard fmt_type since it's btrfs always
        kwargs.pop("fmt_type", None)

        # this is to avoid auto-scheduled format create actions
        device = dev_class(name, **kwargs)
        device.format = get_format("btrfs", **fmt_args)
        return device

    def new_btrfs_sub_volume(self, *args, **kwargs):
        """ Return a new BRFSSubVolumeDevice.

            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :returns: the new device
            :rtype: :class:`~.devices.BTRFSSubVolumeDevice`

            All other arguments are passed on to the
            :class:`~.devices.BTRFSSubVolumeDevice` constructor.

            .. note::

                Since you are creating a subvolume, the parents kwarg should
                contain the volume you want to contain the subvolume.

        """
        kwargs["subvol"] = True
        return self.new_btrfs(*args, **kwargs)

    def new_tmp_fs(self, *args, **kwargs):
        """ Return a new TmpFSDevice. """
        return TmpFSDevice(*args, **kwargs)

    def create_device(self, device):
        """ Schedule creation of a device.

            :param device: the device to schedule creation of
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        self.devicetree.actions.add(ActionCreateDevice(device))
        if device.format.type and not device.format_immutable:
            self.devicetree.actions.add(ActionCreateFormat(device))

    def destroy_device(self, device):
        """ Schedule destruction of a device.

            :param device: the device to schedule destruction of
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        if device.protected:
            raise ValueError("cannot modify protected device")

        if device.format.exists and device.format.type and \
           not device.format_immutable:
            # schedule destruction of any formatting while we're at it
            self.devicetree.actions.add(ActionDestroyFormat(device))

        action = ActionDestroyDevice(device)
        self.devicetree.actions.add(action)

    def format_device(self, device, fmt):
        """ Schedule formatting of a device.

            :param device: the device to create the formatting on
            :type device: :class:`~.devices.StorageDevice`
            :param fmt: the format to create on the device
            :type format: :class:`~.formats.DeviceFormat`
            :rtype: None

            A format destroy action will be scheduled first, so it is not
            necessary to create and schedule an
            :class:`~.deviceaction.ActionDestroyFormat` prior to calling this
            method.
        """
        if device.protected:
            raise ValueError("cannot modify protected device")

        self.devicetree.actions.add(ActionDestroyFormat(device))
        self.devicetree.actions.add(ActionCreateFormat(device, fmt))

    def reset_device(self, device):
        """ Cancel all scheduled actions and reset formatting.

            :param device: the device to reset
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        actions = self.devicetree.actions.find(device=device)
        for action in reversed(actions):
            self.devicetree.actions.remove(action)

        # make sure any random overridden attributes are reset
        device.format = copy.deepcopy(device.original_format)

    def resize_device(self, device, new_size):
        """ Schedule a resize of a device and its formatting, if any.

            :param device: the device to resize
            :type device: :class:`~.devices.StorageDevice`
            :param new_size: the new target size for the device
            :type new_size: :class:`~.size.Size`
            :rtype: None

            If the device has formatting that is recognized as being resizable
            an action will be scheduled to resize it as well.
        """
        if device.protected:
            raise ValueError("cannot modify protected device")

        classes = []
        if device.resizable:
            classes.append(ActionResizeDevice)

        if device.format.resizable:
            classes.append(ActionResizeFormat)

        if not classes:
            raise ValueError("device cannot be resized")

        # if this is a shrink, schedule the format resize first
        if new_size < device.size:
            classes.reverse()

        for action_class in classes:
            self.devicetree.actions.add(action_class(device, new_size))

    def format_by_default(self, device):
        """Return whether the device should be reformatted by default."""
        formatlist = ['/boot', '/var', '/tmp', '/usr']
        exceptlist = ['/home', '/usr/local', '/opt', '/var/www']

        if not device.format.linux_native:
            return False

        if device.format.mountable:
            if not device.format.mountpoint:
                return False

            if device.format.mountpoint == "/" or \
               device.format.mountpoint in formatlist:
                return True

            for p in formatlist:
                if device.format.mountpoint.startswith(p):
                    for q in exceptlist:
                        if device.format.mountpoint.startswith(q):
                            return False
                    return True
        elif device.format.type == "swap":
            return True

        # be safe for anything else and default to off
        return False

    def must_format(self, device):
        """ Return a string explaining why the device must be reformatted.

            Return None if the device need not be reformatted.
        """
        if device.format.mountable and device.format.mountpoint == "/":
            return _("You must create a new filesystem on the root device.")

        return None

    def safe_device_name(self, name):
        """ Convert a device name to something safe and return that.

            LVM limits lv names to 128 characters. I don't know the limits for
            the other various device types, so I'm going to pick a number so
            that we don't have to have an entire fucking library to determine
            device name limits.
        """
        max_len = 96    # No, you don't need longer names than this. Really.
        tmp = name.strip()
        tmp = tmp.replace("/", "_")
        tmp = re.sub("[^0-9a-zA-Z._-]", "", tmp)

        # Remove any '-' or '_' prefixes
        tmp = re.sub("^[-_]*", "", tmp)

        # If all that's left is . or .., give up
        if tmp == "." or tmp == "..":
            return ""

        if len(tmp) > max_len:
            tmp = tmp[:max_len]

        return tmp

    def suggest_container_name(self, hostname=None, prefix=""):
        """ Return a reasonable, unused device name.

            :keyword hostname: the system's hostname
            :keyword prefix: a prefix for the container name
            :returns: the suggested name
            :rtype: str
        """
        if not prefix:
            prefix = short_product_name

        # try to create a device name incorporating the hostname
        if hostname not in (None, "", 'localhost', 'localhost.localdomain'):
            template = "%s_%s" % (prefix, hostname.split('.')[0].lower())
            template = self.safe_device_name(template)
        else:
            template = prefix

        if flags.image_install:
            template = "%s_image" % template

        names = self.names
        name = template
        if name in names:
            name = None
            for i in range(100):
                tmpname = "%s%02d" % (template, i,)
                if tmpname not in names:
                    name = tmpname
                    break

            if not name:
                log.error("failed to create device name based on prefix "
                          "'%s' and hostname '%s'", prefix, hostname)
                raise RuntimeError("unable to find suitable device name")

        return name

    def suggest_device_name(self, parent=None, swap=None,
                            mountpoint=None, prefix=""):
        """ Return a suitable, unused name for a new device.

            :keyword parent: the parent device
            :type parent: :class:`~.devices.StorageDevice`
            :keyword swap: will this be a swap device
            :type swap: bool
            :keyword mountpoint: the device's mountpoint
            :type mountpoint: str
            :keyword prefix: device name prefix
            :type prefix: str
            :returns: the suggested name
            :rtype: str
        """
        body = ""
        if mountpoint:
            if mountpoint == "/":
                body = "root"
            else:
                body = mountpoint[1:].replace("/", "_")
        elif swap:
            body = "swap"

        if prefix and body:
            body = "_" + body

        template = self.safe_device_name(prefix + body)
        names = self.names
        name = template

        def full_name(name, parent):
            full = ""
            if parent:
                full = "%s-" % parent.name
            full += name
            return full

        # also include names of any lvs in the parent for the case of the
        # temporary vg in the lvm dialogs, which can contain lvs that are
        # not yet in the devicetree and therefore not in self.names
        if full_name(name, parent) in names or not body:
            for i in range(100):
                name = "%s%02d" % (template, i)
                if full_name(name, parent) not in names:
                    break
                else:
                    name = ""

            if not name:
                log.error("failed to create device name based on parent '%s', "
                          "prefix '%s', mountpoint '%s', swap '%s'",
                          parent.name, prefix, mountpoint, swap)
                raise RuntimeError("unable to find suitable device name")

        return name

    def save_passphrase(self, device):
        """ Save a device's LUKS passphrase in case of reset. """
        passphrase = device.format._LUKS__passphrase
        if passphrase:
            self.__luks_devs[device.format.uuid] = passphrase
            self.devicetree.save_luks_passphrase(device)

    def setup_disk_images(self):
        self.devicetree.set_disk_images(self.config.disk_images)
        self.devicetree.setup_disk_images()

    @property
    def file_system_free_space(self):
        """ Combined free space in / and /usr as :class:`~.size.Size`. """
        mountpoints = ["/", "/usr"]
        free = Size(0)
        btrfs_volumes = []
        for mountpoint in mountpoints:
            device = self.mountpoints.get(mountpoint)
            if not device:
                continue

            # don't count the size of btrfs volumes repeatedly when multiple
            # subvolumes are present
            if isinstance(device, BTRFSSubVolumeDevice):
                if device.volume in btrfs_volumes:
                    continue
                else:
                    btrfs_volumes.append(device.volume)

            if device.format.exists:
                free += device.format.free
            else:
                free += device.format.free_space_estimate(device.size)

        return free

    def dump_state(self, suffix):
        """ Dump the current device list to the storage shelf. """
        key = "devices.%d.%s" % (time.time(), suffix)
        with contextlib.closing(shelve.open(self._dump_file)) as shelf:
            try:
                shelf[key] = [d.dict for d in self.devices]
            except AttributeError:
                log_exception_info()

    @property
    def packages(self):
        pkgs = set()
        pkgs.update(_platform.packages)

        # install support packages for all devices in the system
        for device in self.devices:
            # this takes care of device and filesystem packages
            pkgs.update(device.packages)

        return list(pkgs)

    def write(self):
        """ Write out all storage-related configuration files. """
        if not os.path.isdir("%s/etc" % get_sysroot()):
            os.mkdir("%s/etc" % get_sysroot())

        self.fsset.write()
        self.make_mtab()
        iscsi.write(get_sysroot(), self)
        self.fcoe.write(get_sysroot())
        self.zfcp.write(get_sysroot())
        self.write_dasd_conf(get_sysroot())

    def write_dasd_conf(self, root):
        """ Write /etc/dasd.conf to target system for all DASD devices
            configured during installation.
        """
        dasds = self.devicetree.get_devices_by_type("dasd")
        dasds.sort(key=lambda d: d.name)
        if not (arch.is_s390() and dasds):
            return

        with open(os.path.realpath(root + "/etc/dasd.conf"), "w") as f:
            for dasd in dasds:
                fields = [dasd.busid] + dasd.get_opts()
                f.write("%s\n" % " ".join(fields),)

    def turn_on_swap(self):
        self.fsset.turn_on_swap(root_path=get_sysroot())

    def mount_filesystems(self, read_only=None, skip_root=False):
        self.fsset.mount_filesystems(root_path=get_sysroot(),
                                     read_only=read_only, skip_root=skip_root)

    def umount_filesystems(self, swapoff=True):
        self.fsset.umount_filesystems(swapoff=swapoff)

    def parse_fstab(self, chroot=None):
        self.fsset.parse_fstab(chroot=chroot)

    def mk_dev_root(self):
        self.fsset.mk_dev_root()

    def create_swap_file(self, device, size):
        self.fsset.create_swap_file(device, size)

    @property
    def bootloader(self):
        if self._bootloader is None and flags.installer_mode:
            self._bootloader = get_bootloader()

        return self._bootloader

    def update_boot_loader_disk_list(self):
        if not self.bootloader:
            return

        boot_disks = [d for d in self.disks if d.partitioned]
        boot_disks.sort(key=self.compare_disks_key)
        self.bootloader.set_disk_list(boot_disks)

    def set_up_boot_loader(self, early=False):
        """ Propagate ksdata into BootLoader.

            :keyword bool early: Set to True to skip stage1_device setup

            :raises BootloaderError: if stage1 setup fails

            If this needs to be run early, eg. to setup stage1_disk but
            not stage1_device 'early' should be set True to prevent
            it from raising BootloaderError
        """
        if not self.bootloader or not self.ksdata:
            log.warning("either ksdata or bootloader data missing")
            return

        if self.bootloader.skip_bootloader:
            log.info("user specified that bootloader install be skipped")
            return

        # Need to make sure bootDrive has been setup from the latest information
        self.ksdata.bootloader.execute(self, self.ksdata, None)
        self.bootloader.stage1_disk = self.devicetree.resolve_device(self.ksdata.bootloader.bootDrive)
        self.bootloader.stage2_device = self.boot_device
        if not early:
            self.bootloader.set_stage1_device(self.devices)

    @property
    def boot_disk(self):
        disk = None
        if self.ksdata:
            spec = self.ksdata.bootloader.bootDrive
            disk = self.devicetree.resolve_device(spec)
        return disk

    @property
    def boot_device(self):
        dev = None
        if self.fsset:
            dev = self.mountpoints.get("/boot", self.root_device)
        return dev

    @property
    def boot_loader_device(self):
        return getattr(self.bootloader, "stage1_device", None)

    @property
    def boot_fstypes(self):
        """A list of all valid filesystem types for the boot partition."""
        fstypes = []
        if self.bootloader:
            fstypes = self.bootloader.stage2_format_types
        return fstypes

    @property
    def default_boot_fstype(self):
        """The default filesystem type for the boot partition."""
        if self._default_boot_fstype:
            return self._default_boot_fstype

        fstype = None
        if self.bootloader:
            fstype = self.boot_fstypes[0]
        return fstype

    def _check_valid_fstype(self, newtype):
        """ Check the fstype to see if it is valid

            Raise ValueError on invalid input.
        """
        fmt = get_format(newtype)
        if fmt.type is None:
            raise ValueError("unrecognized value %s for new default fs type" % newtype)

        if (not fmt.mountable or not fmt.formattable or not fmt.supported or
                not fmt.linux_native):
            log.debug("invalid default fstype (%s): %r", newtype, fmt)
            raise ValueError("new value %s is not valid as a default fs type" % newtype)

        self._default_fstype = newtype  # pylint: disable=attribute-defined-outside-init

    def set_default_boot_fstype(self, newtype):
        """ Set the default /boot fstype for this instance.

            Raise ValueError on invalid input.
        """
        log.debug("trying to set new default /boot fstype to '%s'", newtype)
        # This will raise ValueError if it isn't valid
        self._check_valid_fstype(newtype)
        self._default_boot_fstype = newtype

    @property
    def default_fstype(self):
        return self._default_fstype

    def set_default_fstype(self, newtype):
        """ Set the default fstype for this instance.

            Raise ValueError on invalid input.
        """
        log.debug("trying to set new default fstype to '%s'", newtype)
        # This will raise ValueError if it isn't valid
        self._check_valid_fstype(newtype)
        self._default_fstype = newtype  # pylint: disable=attribute-defined-outside-init

    @property
    def mountpoints(self):
        return self.fsset.mountpoints

    @property
    def root_device(self):
        return self.fsset.root_device

    def make_mtab(self):
        path = "/etc/mtab"
        target = "/proc/self/mounts"
        path = os.path.normpath("%s/%s" % (get_sysroot(), path))

        if os.path.islink(path):
            # return early if the mtab symlink is already how we like it
            current_target = os.path.normpath(os.path.dirname(path) +
                                              "/" + os.readlink(path))
            if current_target == target:
                return

        if os.path.exists(path):
            os.unlink(path)

        os.symlink(target, path)

    def compare_disks(self, first, second):
        if not isinstance(first, str):
            first = first.name
        if not isinstance(second, str):
            second = second.name

        if first in self.edd_dict and second in self.edd_dict:
            one = self.edd_dict[first]
            two = self.edd_dict[second]
            if (one < two):
                return -1
            elif (one > two):
                return 1

        # if one is in the BIOS and the other not prefer the one in the BIOS
        if first in self.edd_dict:
            return -1
        if second in self.edd_dict:
            return 1

        if first.startswith("hd"):
            type1 = 0
        elif first.startswith("sd"):
            type1 = 1
        elif (first.startswith("vd") or first.startswith("xvd")):
            type1 = -1
        else:
            type1 = 2

        if second.startswith("hd"):
            type2 = 0
        elif second.startswith("sd"):
            type2 = 1
        elif (second.startswith("vd") or second.startswith("xvd")):
            type2 = -1
        else:
            type2 = 2

        if (type1 < type2):
            return -1
        elif (type1 > type2):
            return 1
        else:
            len1 = len(first)
            len2 = len(second)

            if (len1 < len2):
                return -1
            elif (len1 > len2):
                return 1
            else:
                if (first < second):
                    return -1
                elif (first > second):
                    return 1

        return 0

    @property
    def compare_disks_key(self):
        return functools.cmp_to_key(self.compare_disks)

    def get_fstype(self, mountpoint=None):
        """ Return the default filesystem type based on mountpoint. """
        fstype = self.default_fstype
        if not mountpoint:
            # just return the default
            pass
        elif mountpoint.lower() in ("swap", "biosboot", "prepboot"):
            fstype = mountpoint.lower()
        elif mountpoint == "/boot":
            fstype = self.default_boot_fstype
        elif mountpoint == "/boot/efi":
            if arch.is_mactel():
                fstype = "macefi"
            else:
                fstype = "efi"

        return fstype

    def factory_device(self, device_type, size, **kwargs):
        """ Schedule creation of a device based on a top-down specification.

            :param device_type: device type constant
            :type device_type: int (:const:`~.devicefactory.DEVICE_TYPE_*`)
            :param size: requested size
            :type size: :class:`~.size.Size`
            :returns: the newly configured device
            :rtype: :class:`~.devices.StorageDevice`

            See :class:`~.devicefactory.DeviceFactory` for possible kwargs.

        """
        log_method_call(self, device_type, size, **kwargs)

        # we can't do anything with existing devices
        # if device and device.exists:
        #    log.info("factory_device refusing to change device %s", device)
        #    return

        if not kwargs.get("fstype"):
            kwargs["fstype"] = self.get_fstype(mountpoint=kwargs.get("mountpoint"))
            if kwargs["fstype"] == "swap":
                kwargs["mountpoint"] = None

        if kwargs["fstype"] == "swap" and \
           device_type == devicefactory.DEVICE_TYPE_BTRFS:
            device_type = devicefactory.DEVICE_TYPE_PARTITION

        factory = devicefactory.get_device_factory(self, device_type, size,
                                                   **kwargs)

        if not factory.disks:
            raise StorageError("no disks specified for new device")

        self.size_sets = []  # clear this since there are no growable reqs now
        factory.configure()
        return factory.device

    def copy(self):
        log.debug("starting Blivet copy")
        new = copy.deepcopy(self)
        # go through and re-get parted_partitions from the disks since they
        # don't get deep-copied
        hidden_partitions = [d for d in new.devicetree._hidden
                             if isinstance(d, PartitionDevice)]
        for partition in new.partitions + hidden_partitions:
            if not partition._parted_partition:
                continue

            # update the refs in req_disks as well
            req_disks = (new.devicetree.get_device_by_id(disk.id) for disk in partition.req_disks)
            partition.req_disks = [disk for disk in req_disks if disk is not None]

            p = partition.disk.format.parted_disk.getPartitionByPath(partition.path)
            partition.parted_partition = p

        for root in new.roots:
            root.swaps = [new.devicetree.get_device_by_id(d.id, hidden=True) for d in root.swaps]
            root.swaps = [s for s in root.swaps if s]

            removed = set()
            for (mountpoint, old_dev) in root.mounts.items():
                if old_dev is None:
                    continue

                new_dev = new.devicetree.get_device_by_id(old_dev.id, hidden=True)
                if new_dev is None:
                    # if the device has been removed don't include this
                    # mountpoint at all
                    removed.add(mountpoint)
                else:
                    root.mounts[mountpoint] = new_dev

            for mnt in removed:
                del root.mounts[mnt]

        log.debug("finished Blivet copy")
        return new

    def update_ksdata(self):
        """ Update ksdata to reflect the settings of this Blivet instance. """
        if not self.ksdata or not self.mountpoints:
            return

        # clear out whatever was there before
        self.ksdata.partition.partitions = []
        self.ksdata.logvol.lvList = []
        self.ksdata.raid.raidList = []
        self.ksdata.volgroup.vgList = []
        self.ksdata.btrfs.btrfsList = []

        # iscsi?
        # fcoe?
        # zfcp?
        # dmraid?

        # bootloader

        # ignoredisk
        if self.config.ignored_disks:
            self.ksdata.ignoredisk.drives = self.config.ignored_disks[:]
        elif self.config.exclusive_disks:
            self.ksdata.ignoredisk.onlyuse = self.config.exclusive_disks[:]

        # autopart
        self.ksdata.autopart.autopart = self.do_autopart
        self.ksdata.autopart.type = self.autopart_type
        self.ksdata.autopart.encrypted = self.encrypted_autopart

        # clearpart
        self.ksdata.clearpart.type = self.config.clear_part_type
        self.ksdata.clearpart.drives = self.config.clear_part_disks[:]
        self.ksdata.clearpart.devices = self.config.clear_part_devices[:]
        self.ksdata.clearpart.init_all = self.config.initialize_disks
        if self.ksdata.clearpart.type == CLEARPART_TYPE_NONE:
            # Make a list of initialized disks and of removed partitions. If any
            # partitions were removed from disks that were not completely
            # cleared we'll have to use CLEARPART_TYPE_LIST and provide a list
            # of all removed partitions. If no partitions were removed from a
            # disk that was not cleared/reinitialized we can use
            # CLEARPART_TYPE_ALL.
            self.ksdata.clearpart.devices = []
            self.ksdata.clearpart.drives = []
            fresh_disks = [d.name for d in self.disks if d.partitioned and
                           not d.format.exists]

            destroy_actions = self.devicetree.actions.find(action_type="destroy",
                                                           object_type="device")

            cleared_partitions = []
            partial = False
            for action in destroy_actions:
                if action.device.type == "partition":
                    if action.device.disk.name not in fresh_disks:
                        partial = True

                    cleared_partitions.append(action.device.name)

            if not destroy_actions:
                pass
            elif partial:
                # make a list of removed partitions
                self.ksdata.clearpart.type = CLEARPART_TYPE_LIST
                self.ksdata.clearpart.devices = cleared_partitions
            else:
                # if they didn't partially clear any disks, use the shorthand
                self.ksdata.clearpart.type = CLEARPART_TYPE_ALL
                self.ksdata.clearpart.drives = fresh_disks

        if self.do_autopart:
            return

        self._update_custom_storage_ksdata()

    def _update_custom_storage_ksdata(self):
        """ Update KSData for custom storage. """

        # custom storage
        ks_map = {PartitionDevice: ("PartData", "partition"),
                  TmpFSDevice: ("PartData", "partition"),
                  LVMLogicalVolumeDevice: ("LogVolData", "logvol"),
                  LVMVolumeGroupDevice: ("VolGroupData", "volgroup"),
                  MDRaidArrayDevice: ("RaidData", "raid"),
                  BTRFSDevice: ("BTRFSData", "btrfs")}

        # make a list of ancestors of all used devices
        devices = list(set(a for d in list(self.mountpoints.values()) + self.swaps
                           for a in d.ancestors))

        # devices which share information with their distinct raw device
        complementary_devices = [d for d in devices if d.raw_device is not d]

        devices.sort(key=lambda d: len(d.ancestors))
        for device in devices:
            cls = next((c for c in ks_map if isinstance(device, c)), None)
            if cls is None:
                log.info("omitting ksdata: %s", device)
                continue

            class_attr, list_attr = ks_map[cls]

            cls = getattr(self.ksdata, class_attr)
            data = cls()    # all defaults

            complements = [d for d in complementary_devices if d.raw_device is device]

            if len(complements) > 1:
                log.warning("omitting ksdata for %s, found too many (%d) complementary devices", device, len(complements))
                continue

            device = complements[0] if complements else device

            device.populate_ksdata(data)

            parent = getattr(self.ksdata, list_attr)
            parent.dataList().append(data)

    @property
    def free_space_snapshot(self):
        # if no snapshot is available, do it now and return it
        self._free_space_snapshot = self._free_space_snapshot or self.get_free_space()

        return self._free_space_snapshot

    def create_free_space_snapshot(self):
        self._free_space_snapshot = self.get_free_space()

        return self._free_space_snapshot

    def add_fstab_swap(self, device):
        """
        Add swap device to the list of swaps that should appear in the fstab.

        :param device: swap device that should be added to the list
        :type device: blivet.devices.StorageDevice instance holding a swap format

        """

        self.fsset.add_fstab_swap(device)

    def remove_fstab_swap(self, device):
        """
        Remove swap device from the list of swaps that should appear in the fstab.

        :param device: swap device that should be removed from the list
        :type device: blivet.devices.StorageDevice instance holding a swap format

        """

        self.fsset.remove_fstab_swap(device)

    def set_fstab_swaps(self, devices):
        """
        Set swap devices that should appear in the fstab.

        :param devices: iterable providing devices that should appear in the fstab
        :type devices: iterable providing blivet.devices.StorageDevice instances holding
                       a swap format

        """

        self.fsset.set_fstab_swaps(devices)
