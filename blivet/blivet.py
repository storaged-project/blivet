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
from .devices import LVMLogicalVolumeDevice, LVMThinLogicalVolumeDevice, LVMThinPoolDevice, LVMVolumeGroupDevice
from .devices import MDRaidArrayDevice, PartitionDevice, TmpFSDevice, devicePathToName
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
from .formats import getFormat
from .osinstall import FSSet, findExistingInstallations
from . import arch
from . import iscsi
from . import fcoe
from . import zfcp
from . import devicefactory
from . import get_bootloader, getSysroot, shortProductName, __version__
from .util import open  # pylint: disable=redefined-builtin

from .i18n import _

import logging
log = logging.getLogger("blivet")

def empty_device(device, devicetree):
    empty = True
    if device.partitioned:
        partitions = devicetree.getChildren(device)
        empty = all([p.isMagic for p in partitions])
    else:
        empty = (device.format.type is None)

    return empty

class StorageDiscoveryConfig(object):
    """ Class to encapsulate various detection/initialization parameters. """
    def __init__(self):
        # storage configuration variables
        self.ignoreDiskInteractive = False
        self.ignoredDisks = []
        self.exclusiveDisks = []
        self.clearPartType = None
        self.clearPartDisks = []
        self.clearPartDevices = []
        self.initializeDisks = False
        self.protectedDevSpecs = []
        self.diskImages = {}
        self.zeroMbr = False

        # Whether clearPartitions removes scheduled/non-existent devices and
        # disklabels depends on this flag.
        self.clearNonExistent = False

    def update(self, ksdata):
        """ Update configuration from ksdata source.

            :param ksdata: kickstart data used as data source
            :type ksdata: :class:`pykickstart.Handler`
        """
        self.ignoredDisks = ksdata.ignoredisk.ignoredisk[:]
        self.exclusiveDisks = ksdata.ignoredisk.onlyuse[:]
        self.clearPartType = ksdata.clearpart.type
        self.clearPartDisks = ksdata.clearpart.drives[:]
        self.clearPartDevices = ksdata.clearpart.devices[:]
        self.initializeDisks = ksdata.clearpart.initAll
        self.zeroMbr = ksdata.zerombr.zerombr

class Blivet(object):
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
        self.doAutoPart = False
        self.clearPartChoice = None
        self.encryptedAutoPart = False
        self.autoPartType = AUTOPART_TYPE_LVM
        self.encryptionPassphrase = None
        self.encryptionCipher = None
        self.escrowCertificates = {}
        self.autoPartEscrowCert = None
        self.autoPartAddBackupPassphrase = False
        self.autoPartitionRequests = []
        self.eddDict = {}
        self.dasd = []

        self.__luksDevs = {}
        self.size_sets = []
        self.setDefaultFSType(get_default_filesystem_type())
        self._defaultBootFSType = None

        self.iscsi = iscsi.iscsi()
        self.fcoe = fcoe.fcoe()
        self.zfcp = zfcp.ZFCP()

        self._nextID = 0
        self._dumpFile = "%s/storage.state" % tempfile.gettempdir()

        # these will both be empty until our reset method gets called
        self.devicetree = DeviceTree(conf=self.config,
                                     passphrase=self.encryptionPassphrase,
                                     luksDict=self.__luksDevs,
                                     iscsi=self.iscsi,
                                     dasd=self.dasd)
        self.fsset = FSSet(self.devicetree)
        self.roots = []
        self.services = set()
        self._free_space_snapshot = None

    def doIt(self, callbacks=None):
        """
        Commit queued changes to disk.

        :param callbacks: callbacks to be invoked when actions are executed
        :type callbacks: return value of the :func:`~.callbacks.create_new_callbacks_register`

        """

        self.devicetree.processActions(callbacks=callbacks)
        if not flags.installer_mode:
            return

        # now set the boot partition's flag
        if self.bootloader and not self.bootloader.skip_bootloader:
            if self.bootloader.stage2_bootable:
                boot = self.bootDevice
            else:
                boot = self.bootLoaderDevice

            if boot.type == "mdarray":
                bootDevs = boot.parents
            else:
                bootDevs = [boot]

            for dev in bootDevs:
                if not hasattr(dev, "bootable"):
                    log.info("Skipping %s, not bootable", dev)
                    continue

                # Dos labels can only have one partition marked as active
                # and unmarking ie the windows partition is not a good idea
                skip = False
                if dev.disk.format.partedDisk.type == "msdos":
                    for p in dev.disk.format.partedDisk.partitions:
                        if p.type == parted.PARTITION_NORMAL and \
                           p.getFlag(parted.PARTITION_BOOT):
                            skip = True
                            break

                # GPT labeled disks should only have bootable set on the
                # EFI system partition (parted sets the EFI System GUID on
                # GPT partitions with the boot flag)
                if dev.disk.format.labelType == "gpt" and \
                   dev.format.type not in ["efi", "macefi"]:
                    skip = True

                if skip:
                    log.info("Skipping %s", dev.name)
                    continue

                # hfs+ partitions on gpt can't be marked bootable via parted
                if dev.disk.format.partedDisk.type != "gpt" or \
                        dev.format.type not in ["hfs+", "macefi"]:
                    log.info("setting boot flag on %s", dev.name)
                    dev.bootable = True

                # Set the boot partition's name on disk labels that support it
                if dev.partedPartition.disk.supportsFeature(parted.DISK_TYPE_PARTITION_NAME):
                    ped_partition = dev.partedPartition.getPedPartition()
                    ped_partition.set_name(dev.format.name)
                    log.info("Setting label on %s to '%s'", dev, dev.format.name)

                dev.disk.setup()
                dev.disk.format.commitToDisk()

        if flags.installer_mode:
            self.dumpState("final")

    @property
    def nextID(self):
        """ Used for creating unique placeholder names. """
        newid = self._nextID
        self._nextID += 1
        return newid

    def shutdown(self):
        """ Deactivate all devices (installer_mode only). """
        if not flags.installer_mode:
            return

        try:
            self.devicetree.teardownAll()
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.error, "failure tearing down device tree")

    def reset(self, cleanupOnly=False):
        """ Reset storage configuration to reflect actual system state.

            This will cancel any queued actions and rescan from scratch but not
            clobber user-obtained information like passphrases, iscsi config, &c

            :keyword cleanupOnly: prepare the tree only to deactivate devices
            :type cleanupOnly: bool

            See :meth:`devicetree.Devicetree.populate` for more information
            about the cleanupOnly keyword argument.
        """
        log.info("resetting Blivet (version %s) instance %s", __version__, self)
        if flags.installer_mode:
            # save passphrases for luks devices so we don't have to reprompt
            self.encryptionPassphrase = None
            for device in self.devices:
                if device.format.type == "luks" and device.format.exists:
                    self.__luksDevs[device.format.uuid] = device.format._LUKS__passphrase

        if self.ksdata:
            self.config.update(self.ksdata)

        if flags.installer_mode and not flags.image_install:
            self.iscsi.startup()
            self.fcoe.startup()
            self.zfcp.startup()
            self.dasd = self.devicetree.make_dasd_list(self.dasd, self.devices)

        if self.dasd:
            # Reset the internal dasd list (823534)
            self.dasd = []

        self.devicetree.reset(conf=self.config,
                              passphrase=self.encryptionPassphrase,
                              luksDict=self.__luksDevs,
                              iscsi=self.iscsi,
                              dasd=self.dasd)
        self.devicetree.populate(cleanupOnly=cleanupOnly)
        self.fsset = FSSet(self.devicetree)
        self.eddDict = get_edd_dict(self.partitioned)
        if self.bootloader:
            # clear out bootloader attributes that refer to devices that are
            # no longer in the tree
            self.bootloader.reset()

        self.roots = []
        if flags.installer_mode:
            try:
                self.roots = findExistingInstallations(self.devicetree)
            except Exception: # pylint: disable=broad-except
                log_exception_info(log.info, "failure detecting existing installations")

            self.dumpState("initial")

        if not flags.installer_mode:
            self.devicetree.handleNodevFilesystems()

        self.updateBootLoaderDiskList()

    @property
    def unusedDevices(self):
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
            if getattr(device, "isLogical", False):
                extended = device.disk.format.extendedPartition.path
                used_devices.append(self.devicetree.getDeviceByPath(extended))

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
            if device.isDisk:
                if not device.mediaPresent:
                    log.info("Skipping disk: %s: No media present", device.name)
                    continue
                disks.append(device)
        disks.sort(key=self.compareDisksKey)
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

            if not device.mediaPresent:
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
        partitions = self.devicetree.getDevicesByInstance(PartitionDevice)
        partitions.sort(key=lambda d: d.name)
        return partitions

    @property
    def vgs(self):
        """ A list of the LVM Volume Groups in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        vgs = self.devicetree.getDevicesByType("lvmvg")
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
        thin = self.devicetree.getDevicesByType("lvmthinlv")
        thin.sort(key=lambda d: d.name)
        return thin

    @property
    def thinpools(self):
        """ A list of the LVM Thin Pool Logical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        pools = self.devicetree.getDevicesByType("lvmthinpool")
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
        arrays = self.devicetree.getDevicesByType("mdarray")
        arrays.sort(key=lambda d: d.name)
        return arrays

    @property
    def mdcontainers(self):
        """ A list of the MD containers in the device tree. """
        arrays = self.devicetree.getDevicesByType("mdcontainer")
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
    def btrfsVolumes(self):
        """ A list of the BTRFS volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        return sorted(self.devicetree.getDevicesByType("btrfs volume"),
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

    def shouldClear(self, device, **kwargs):
        """ Return True if a clearpart settings say a device should be cleared.

            :param device: the device (required)
            :type device: :class:`~.devices.StorageDevice`
            :keyword clearPartType: overrides :attr:`self.config.clearPartType`
            :type clearPartType: int
            :keyword clearPartDisks: overrides
                                     :attr:`self.config.clearPartDisks`
            :type clearPartDisks: list
            :keyword clearPartDevices: overrides
                                       :attr:`self.config.clearPartDevices`
            :type clearPartDevices: list
            :returns: whether or not clearPartitions should remove this device
            :rtype: bool
        """
        clearPartType = kwargs.get("clearPartType", self.config.clearPartType)
        clearPartDisks = kwargs.get("clearPartDisks",
                                    self.config.clearPartDisks)
        clearPartDevices = kwargs.get("clearPartDevices",
                                      self.config.clearPartDevices)

        for disk in device.disks:
            # this will not include disks with hidden formats like multipath
            # and firmware raid member disks
            if clearPartDisks and disk.name not in clearPartDisks:
                return False

        if not self.config.clearNonExistent:
            if (device.isDisk and not device.format.exists) or \
               (not device.isDisk and not device.exists):
                return False

        # the only devices we want to clear when clearPartType is
        # CLEARPART_TYPE_NONE are uninitialized disks, or disks with no
        # partitions, in clearPartDisks, and then only when we have been asked
        # to initialize disks as needed
        if clearPartType in [CLEARPART_TYPE_NONE, None]:
            if not self.config.initializeDisks or not device.isDisk:
                return False

            if not empty_device(device, self.devicetree):
                return False

        if isinstance(device, PartitionDevice):
            # Never clear the special first partition on a Mac disk label, as
            # that holds the partition table itself.
            # Something similar for the third partition on a Sun disklabel.
            if device.isMagic:
                return False

            # We don't want to fool with extended partitions, freespace, &c
            if not device.isPrimary and not device.isLogical:
                return False

            if clearPartType == CLEARPART_TYPE_LINUX and \
               not device.format.linuxNative and \
               not device.getFlag(parted.PARTITION_LVM) and \
               not device.getFlag(parted.PARTITION_RAID) and \
               not device.getFlag(parted.PARTITION_SWAP):
                return False
        elif device.isDisk:
            if device.partitioned and clearPartType != CLEARPART_TYPE_ALL:
                # if clearPartType is not CLEARPART_TYPE_ALL but we'll still be
                # removing every partition from the disk, return True since we
                # will want to be able to create a new disklabel on this disk
                if not empty_device(device, self.devicetree):
                    return False

            # Never clear disks with hidden formats
            if device.format.hidden:
                return False

            # When clearPartType is CLEARPART_TYPE_LINUX and a disk has non-
            # linux whole-disk formatting, do not clear it. The exception is
            # the case of an uninitialized disk when we've been asked to
            # initialize disks as needed
            if (clearPartType == CLEARPART_TYPE_LINUX and
                not ((self.config.initializeDisks and
                      empty_device(device, self.devicetree)) or
                     (not device.partitioned and device.format.linuxNative))):
                return False

        # Don't clear devices holding install media.
        descendants = self.devicetree.getDependentDevices(device)
        if device.protected or any(d.protected for d in descendants):
            return False

        if clearPartType == CLEARPART_TYPE_LIST and \
           device.name not in clearPartDevices:
            return False

        return True

    def recursiveRemove(self, device):
        """ Remove a device after removing its dependent devices.

            If the device is not a leaf, all of its dependents are removed
            recursively until it is a leaf device. At that point the device is
            removed, unless it is a disk. If the device is a disk, its
            formatting is removed by no attempt is made to actually remove the
            disk device.
        """
        self.devicetree.recursiveRemove(device)

    def clearPartitions(self):
        """ Clear partitions and dependent devices from disks.

            This is also where zerombr is handled.
        """
        # Sort partitions by descending partition number to minimize confusing
        # things like multiple "destroy sda5" actions due to parted renumbering
        # partitions. This can still happen through the UI but it makes sense to
        # avoid it where possible.
        partitions = sorted(self.partitions,
                            key=lambda p: p.partedPartition.number,
                            reverse=True)
        for part in partitions:
            log.debug("clearpart: looking at %s", part.name)
            if not self.shouldClear(part):
                continue

            self.recursiveRemove(part)
            log.debug("partitions: %s", [p.getDeviceNodeName() for p in part.partedPartition.disk.partitions])

        # now remove any empty extended partitions
        self.removeEmptyExtendedPartitions()

        # ensure all disks have appropriate disklabels
        for disk in self.disks:
            zerombr = (self.config.zeroMbr and disk.format.type is None)
            should_clear = self.shouldClear(disk)
            if should_clear:
                self.recursiveRemove(disk)

            if zerombr or should_clear:
                log.debug("clearpart: initializing %s", disk.name)
                self.initializeDisk(disk)

        self.updateBootLoaderDiskList()

    def initializeDisk(self, disk):
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
            magic = disk.format.magicPartitionNumber
            expected = 0
            if magic:
                expected = 1
                # remove the magic partition
                for part in self.devicetree.getChildren(disk):
                    if part.partedPartition.number == magic:
                        log.debug("removing %s", part.name)
                        # We can't schedule the magic partition for removal
                        # because parted will not allow us to remove it from the
                        # disk. Still, we need it out of the devicetree.
                        self.devicetree._removeDevice(part, modparent=False)

            if len(disk.format.partitions) > expected:
                raise ValueError("cannot initialize a disk that has partitions")

        # remove existing formatting from the disk
        destroy_action = ActionDestroyFormat(disk)
        self.devicetree.registerAction(destroy_action)

        labelType = _platform.bestDiskLabelType(disk)

        # create a new disklabel on the disk
        newLabel = getFormat("disklabel", device=disk.path,
                             labelType=labelType)
        create_action = ActionCreateFormat(disk, fmt=newLabel)
        self.devicetree.registerAction(create_action)

    def removeEmptyExtendedPartitions(self):
        for disk in self.partitioned:
            log.debug("checking whether disk %s has an empty extended", disk.name)
            extended = disk.format.extendedPartition
            logical_parts = disk.format.logicalPartitions
            log.debug("extended is %s ; logicals is %s", extended, [p.getDeviceNodeName() for p in logical_parts])
            if extended and not logical_parts:
                log.debug("removing empty extended partition from %s", disk.name)
                extended_name = devicePathToName(extended.getDeviceNodeName())
                extended = self.devicetree.getDeviceByName(extended_name)
                self.destroyDevice(extended)

    def getFreeSpace(self, disks=None, clearPartType=None):
        """ Return a dict with free space info for each disk.

            The dict values are 2-tuples: (disk_free, fs_free). fs_free is
            space available by shrinking filesystems. disk_free is space not
            allocated to any partition.

            disks and clearPartType allow specifying a set of disks other than
            self.disks and a clearPartType value other than
            self.config.clearPartType.

            :keyword disks: overrides :attr:`disks`
            :type disks: list
            :keyword clearPartType: overrides :attr:`self.config.clearPartType`
            :type clearPartType: int
            :returns: dict with disk name keys and tuple (disk, fs) free values
            :rtype: dict

            .. note::

                The free space values are :class:`~.size.Size` instances.

        """
        if disks is None:
            disks = self.disks

        if clearPartType is None:
            clearPartType = self.config.clearPartType

        free = {}
        for disk in disks:
            should_clear = self.shouldClear(disk, clearPartType=clearPartType,
                                            clearPartDisks=[disk.name])
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
                    should_clear = self.shouldClear(partition,
                                                    clearPartType=clearPartType,
                                                    clearPartDisks=[disk.name])
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

    def deviceDeps(self, device):
        """ Return a list of the devices that depend on the specified device.

            :param device: the subtree root device
            :type device: :class:`~.devices.StorageDevice`
            :returns: list of dependent devices
            :rtype: list
        """
        return self.devicetree.getDependentDevices(device)

    def newPartition(self, *args, **kwargs):
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
            kwargs["fmt"] = getFormat(kwargs.pop("fmt_type"),
                                         mountpoint=kwargs.pop("mountpoint",
                                                               None),
                                         **kwargs.pop("fmt_args", {}))

        if 'name' in kwargs:
            name = kwargs.pop("name")
        else:
            name = "req%d" % self.nextID

        if "weight" not in kwargs:
            fmt = kwargs.get("fmt")
            if fmt:
                mountpoint = getattr(fmt, "mountpoint", None)

                kwargs["weight"] = _platform.weight(mountpoint=mountpoint,
                                                        fstype=fmt.type)


        return PartitionDevice(name, *args, **kwargs)

    def newMDArray(self, *args, **kwargs):
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
            kwargs["fmt"] = getFormat(kwargs.pop("fmt_type"),
                                         mountpoint=kwargs.pop("mountpoint",
                                                               None),
                                         **kwargs.pop("fmt_args", {}))

        name = kwargs.pop("name", None)
        if name:
            safe_name = self.safeDeviceName(name)
            if safe_name != name:
                log.warning("using '%s' instead of specified name '%s'",
                                safe_name, name)
                name = safe_name
        else:
            swap = getattr(kwargs.get("fmt"), "type", None) == "swap"
            mountpoint = getattr(kwargs.get("fmt"), "mountpoint", None)
            name = self.suggestDeviceName(prefix=shortProductName,
                                          swap=swap,
                                          mountpoint=mountpoint)

        return MDRaidArrayDevice(name, *args, **kwargs)

    def newVG(self, *args, **kwargs):
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
            safe_name = self.safeDeviceName(name)
            if safe_name != name:
                log.warning("using '%s' instead of specified name '%s'",
                                safe_name, name)
                name = safe_name
        else:
            hostname = ""
            if self.ksdata and self.ksdata.network.hostname is not None:
                hostname = self.ksdata.network.hostname

            name = self.suggestContainerName(hostname=hostname)

        if name in self.names:
            raise ValueError("name already in use")

        return LVMVolumeGroupDevice(name, pvs, *args, **kwargs)

    def newLV(self, *args, **kwargs):
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
        vg = kwargs.get("parents", [None])[0]
        if thin_volume and vg:
            # kwargs["parents"] will contain the pool device, so...
            vg = vg.vg

        mountpoint = kwargs.pop("mountpoint", None)
        if 'fmt_type' in kwargs:
            kwargs["fmt"] = getFormat(kwargs.pop("fmt_type"),
                                         mountpoint=mountpoint,
                                         **kwargs.pop("fmt_args", {}))

        name = kwargs.pop("name", None)
        if name:
            # make sure the specified name is sensible
            safe_vg_name = self.safeDeviceName(vg.name)
            full_name = "%s-%s" % (safe_vg_name, name)
            safe_name = self.safeDeviceName(full_name)
            if safe_name != full_name:
                new_name = safe_name[len(safe_vg_name)+1:]
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

            name = self.suggestDeviceName(parent=vg,
                                          swap=swap,
                                          mountpoint=mountpoint,
                                          prefix=prefix)

        if "%s-%s" % (vg.name, name) in self.names:
            raise ValueError("name already in use")

        if thin_pool:
            device_class = LVMThinPoolDevice
        elif thin_volume:
            device_class = LVMThinLogicalVolumeDevice
        else:
            device_class = LVMLogicalVolumeDevice

        return device_class(name, *args, **kwargs)

    def newBTRFS(self, *args, **kwargs):
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
        log.debug("newBTRFS: args = %s ; kwargs = %s", args, kwargs)
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
                name = self.suggestDeviceName(mountpoint=mountpoint)
            fmt_args["mountopts"] = "subvol=%s" % name
            fmt_args["subvolspec"] = name
            kwargs.pop("metaDataLevel", None)
            kwargs.pop("dataLevel", None)
        else:
            dev_class = BTRFSVolumeDevice
            # set up the volume label, using hostname if necessary
            if not name:
                hostname = ""
                if self.ksdata and self.ksdata.network.hostname is not None:
                    hostname = self.ksdata.network.hostname

                name = self.suggestContainerName(hostname=hostname)
            if "label" not in fmt_args:
                fmt_args["label"] = name
            fmt_args["subvolspec"] = MAIN_VOLUME_ID

        # discard fmt_type since it's btrfs always
        kwargs.pop("fmt_type", None)

        # this is to avoid auto-scheduled format create actions
        device = dev_class(name, **kwargs)
        device.format = getFormat("btrfs", **fmt_args)
        return device

    def newBTRFSSubVolume(self, *args, **kwargs):
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
        return self.newBTRFS(*args, **kwargs)

    def newTmpFS(self, *args, **kwargs):
        """ Return a new TmpFSDevice. """
        return TmpFSDevice(*args, **kwargs)

    def createDevice(self, device):
        """ Schedule creation of a device.

            :param device: the device to schedule creation of
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        self.devicetree.registerAction(ActionCreateDevice(device))
        if device.format.type and not device.formatImmutable:
            self.devicetree.registerAction(ActionCreateFormat(device))

    def destroyDevice(self, device):
        """ Schedule destruction of a device.

            :param device: the device to schedule destruction of
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        if device.protected:
            raise ValueError("cannot modify protected device")

        if device.format.exists and device.format.type and \
           not device.formatImmutable:
            # schedule destruction of any formatting while we're at it
            self.devicetree.registerAction(ActionDestroyFormat(device))

        action = ActionDestroyDevice(device)
        self.devicetree.registerAction(action)

    def formatDevice(self, device, fmt):
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

        self.devicetree.registerAction(ActionDestroyFormat(device))
        self.devicetree.registerAction(ActionCreateFormat(device, fmt))

    def resetDevice(self, device):
        """ Cancel all scheduled actions and reset formatting.

            :param device: the device to reset
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        actions = self.devicetree.findActions(device=device)
        for action in reversed(actions):
            self.devicetree.cancelAction(action)

        # make sure any random overridden attributes are reset
        device.format = copy.deepcopy(device.originalFormat)

    def resizeDevice(self, device, new_size):
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
            self.devicetree.registerAction(action_class(device, new_size))

    def formatByDefault(self, device):
        """Return whether the device should be reformatted by default."""
        formatlist = ['/boot', '/var', '/tmp', '/usr']
        exceptlist = ['/home', '/usr/local', '/opt', '/var/www']

        if not device.format.linuxNative:
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

    def mustFormat(self, device):
        """ Return a string explaining why the device must be reformatted.

            Return None if the device need not be reformatted.
        """
        if device.format.mountable and device.format.mountpoint == "/":
            return _("You must create a new filesystem on the root device.")

        return None

    def safeDeviceName(self, name):
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

    def suggestContainerName(self, hostname=None, prefix=""):
        """ Return a reasonable, unused device name.

            :keyword hostname: the system's hostname
            :keyword prefix: a prefix for the container name
            :returns: the suggested name
            :rtype: str
        """
        if not prefix:
            prefix = shortProductName

        # try to create a device name incorporating the hostname
        if hostname not in (None, "", 'localhost', 'localhost.localdomain'):
            template = "%s_%s" % (prefix, hostname.split('.')[0].lower())
            template = self.safeDeviceName(template)
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

    def suggestDeviceName(self, parent=None, swap=None,
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

        template = self.safeDeviceName(prefix + body)
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

    def savePassphrase(self, device):
        """ Save a device's LUKS passphrase in case of reset. """
        passphrase = device.format._LUKS__passphrase
        self.__luksDevs[device.format.uuid] = passphrase
        self.devicetree.saveLUKSpassphrase(device)

    def setupDiskImages(self):
        self.devicetree.setDiskImages(self.config.diskImages)
        self.devicetree.setupDiskImages()

    @property
    def fileSystemFreeSpace(self):
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
                free += device.size

        return free

    def dumpState(self, suffix):
        """ Dump the current device list to the storage shelf. """
        key = "devices.%d.%s" % (time.time(), suffix)
        with contextlib.closing(shelve.open(self._dumpFile)) as shelf:
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
        if not os.path.isdir("%s/etc" % getSysroot()):
            os.mkdir("%s/etc" % getSysroot())

        self.fsset.write()
        self.makeMtab()
        self.iscsi.write(getSysroot(), self)
        self.fcoe.write(getSysroot())
        self.zfcp.write(getSysroot())
        self.write_dasd_conf(self.dasd, getSysroot())

    def write_dasd_conf(self, disks, root):
        """ Write /etc/dasd.conf to target system for all DASD devices
            configured during installation.
        """
        if not (arch.isS390() and disks):
            return

        with open(os.path.realpath(root + "/etc/dasd.conf"), "w") as f:
            for dasd in sorted(disks, key=lambda d: d.name):
                fields = [dasd.busid] + dasd.getOpts()
                f.write("%s\n" % " ".join(fields),)

    def turnOnSwap(self):
        self.fsset.turnOnSwap(rootPath=getSysroot())

    def mountFilesystems(self, readOnly=None, skipRoot=False):
        self.fsset.mountFilesystems(rootPath=getSysroot(),
                                    readOnly=readOnly, skipRoot=skipRoot)

    def umountFilesystems(self, swapoff=True):
        self.fsset.umountFilesystems(swapoff=swapoff)

    def parseFSTab(self, chroot=None):
        self.fsset.parseFSTab(chroot=chroot)

    def mkDevRoot(self):
        self.fsset.mkDevRoot()

    def createSwapFile(self, device, size):
        self.fsset.createSwapFile(device, size)

    @property
    def bootloader(self):
        if self._bootloader is None and flags.installer_mode:
            self._bootloader = get_bootloader()

        return self._bootloader

    def updateBootLoaderDiskList(self):
        if not self.bootloader:
            return

        boot_disks = [d for d in self.disks if d.partitioned]
        boot_disks.sort(key=self.compareDisksKey)
        self.bootloader.set_disk_list(boot_disks)

    def setUpBootLoader(self, early=False):
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
        self.bootloader.stage1_disk = self.devicetree.resolveDevice(self.ksdata.bootloader.bootDrive)
        self.bootloader.stage2_device = self.bootDevice
        if not early:
            self.bootloader.set_stage1_device(self.devices)

    @property
    def bootDisk(self):
        disk = None
        if self.ksdata:
            spec = self.ksdata.bootloader.bootDrive
            disk = self.devicetree.resolveDevice(spec)
        return disk

    @property
    def bootDevice(self):
        dev = None
        if self.fsset:
            dev = self.mountpoints.get("/boot", self.rootDevice)
        return dev

    @property
    def bootLoaderDevice(self):
        return getattr(self.bootloader, "stage1_device", None)

    @property
    def bootFSTypes(self):
        """A list of all valid filesystem types for the boot partition."""
        fstypes = []
        if self.bootloader:
            fstypes = self.bootloader.stage2_format_types
        return fstypes

    @property
    def defaultBootFSType(self):
        """The default filesystem type for the boot partition."""
        if self._defaultBootFSType:
            return self._defaultBootFSType

        fstype = None
        if self.bootloader:
            fstype = self.bootFSTypes[0]
        return fstype

    def _check_valid_fstype(self, newtype):
        """ Check the fstype to see if it is valid

            Raise ValueError on invalid input.
        """
        fmt = getFormat(newtype)
        if fmt.type is None:
            raise ValueError("unrecognized value %s for new default fs type" % newtype)

        if (not fmt.mountable or not fmt.formattable or not fmt.supported or
            not fmt.linuxNative):
            log.debug("invalid default fstype: %r", fmt)
            raise ValueError("new value %s is not valid as a default fs type" % fmt)

        self._defaultFSType = newtype # pylint: disable=attribute-defined-outside-init

    def setDefaultBootFSType(self, newtype):
        """ Set the default /boot fstype for this instance.

            Raise ValueError on invalid input.
        """
        log.debug("trying to set new default /boot fstype to '%s'", newtype)
        # This will raise ValueError if it isn't valid
        self._check_valid_fstype(newtype)
        self._defaultBootFSType = newtype

    @property
    def defaultFSType(self):
        return self._defaultFSType

    def setDefaultFSType(self, newtype):
        """ Set the default fstype for this instance.

            Raise ValueError on invalid input.
        """
        log.debug("trying to set new default fstype to '%s'", newtype)
        # This will raise ValueError if it isn't valid
        self._check_valid_fstype(newtype)
        self._defaultFSType = newtype # pylint: disable=attribute-defined-outside-init

    @property
    def mountpoints(self):
        return self.fsset.mountpoints

    @property
    def rootDevice(self):
        return self.fsset.rootDevice

    def makeMtab(self):
        path = "/etc/mtab"
        target = "/proc/self/mounts"
        path = os.path.normpath("%s/%s" % (getSysroot(), path))

        if os.path.islink(path):
            # return early if the mtab symlink is already how we like it
            current_target = os.path.normpath(os.path.dirname(path) +
                                              "/" + os.readlink(path))
            if current_target == target:
                return

        if os.path.exists(path):
            os.unlink(path)

        os.symlink(target, path)

    def compareDisks(self, first, second):
        if not isinstance(first, str):
            first = first.name
        if not isinstance(second, str):
            second = second.name

        if first in self.eddDict and second in self.eddDict:
            one = self.eddDict[first]
            two = self.eddDict[second]
            if (one < two):
                return -1
            elif (one > two):
                return 1

        # if one is in the BIOS and the other not prefer the one in the BIOS
        if first in self.eddDict:
            return -1
        if second in self.eddDict:
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
    def compareDisksKey(self):
        return functools.cmp_to_key(self.compareDisks)

    def getFSType(self, mountpoint=None):
        """ Return the default filesystem type based on mountpoint. """
        fstype = self.defaultFSType
        if not mountpoint:
            # just return the default
            pass
        elif mountpoint.lower() in ("swap", "biosboot", "prepboot"):
            fstype = mountpoint.lower()
        elif mountpoint == "/boot":
            fstype = self.defaultBootFSType
        elif mountpoint == "/boot/efi":
            if arch.isMactel():
                fstype = "macefi"
            else:
                fstype = "efi"

        return fstype

    def factoryDevice(self, device_type, size, **kwargs):
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
        #if device and device.exists:
        #    log.info("factoryDevice refusing to change device %s", device)
        #    return

        if not kwargs.get("fstype"):
            kwargs["fstype"] = self.getFSType(mountpoint=kwargs.get("mountpoint"))
            if kwargs["fstype"] == "swap":
                kwargs["mountpoint"] = None

        if kwargs["fstype"] == "swap" and \
           device_type == devicefactory.DEVICE_TYPE_BTRFS:
            device_type = devicefactory.DEVICE_TYPE_PARTITION

        factory = devicefactory.get_device_factory(self, device_type, size,
                                                   **kwargs)

        if not factory.disks:
            raise StorageError("no disks specified for new device")

        self.size_sets = [] # clear this since there are no growable reqs now
        factory.configure()
        return factory.device

    def copy(self):
        log.debug("starting Blivet copy")
        new = copy.deepcopy(self)
        # go through and re-get partedPartitions from the disks since they
        # don't get deep-copied
        hidden_partitions = [d for d in new.devicetree._hidden
                                if isinstance(d, PartitionDevice)]
        for partition in new.partitions + hidden_partitions:
            if not partition._partedPartition:
                continue

            # update the refs in req_disks as well
            req_disks = (new.devicetree.getDeviceByID(disk.id) for disk in partition.req_disks)
            partition.req_disks = [disk for disk in req_disks if disk is not None]

            p = partition.disk.format.partedDisk.getPartitionByPath(partition.path)
            partition.partedPartition = p

        for root in new.roots:
            root.swaps = [new.devicetree.getDeviceByID(d.id, hidden=True) for d in root.swaps]
            root.swaps = [s for s in root.swaps if s]

            for (mountpoint, old_dev) in root.mounts.items():
                removed = set()
                if old_dev is None:
                    continue

                new_dev = new.devicetree.getDeviceByID(old_dev.id, hidden=True)
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

    def updateKSData(self):
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
        if self.config.ignoredDisks:
            self.ksdata.ignoredisk.drives = self.config.ignoredDisks[:]
        elif self.config.exclusiveDisks:
            self.ksdata.ignoredisk.onlyuse = self.config.exclusiveDisks[:]

        # autopart
        self.ksdata.autopart.autopart = self.doAutoPart
        self.ksdata.autopart.type = self.autoPartType
        self.ksdata.autopart.encrypted = self.encryptedAutoPart

        # clearpart
        self.ksdata.clearpart.type = self.config.clearPartType
        self.ksdata.clearpart.drives = self.config.clearPartDisks[:]
        self.ksdata.clearpart.devices = self.config.clearPartDevices[:]
        self.ksdata.clearpart.initAll = self.config.initializeDisks
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

            destroy_actions = self.devicetree.findActions(action_type="destroy",
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

        if self.doAutoPart:
            return

        self._updateCustomStorageKSData()

    def _updateCustomStorageKSData(self):
        """ Update KSData for custom storage. """

        # custom storage
        ksMap = {PartitionDevice: ("PartData", "partition"),
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
            cls = next((c for c in ksMap if isinstance(device, c)), None)
            if cls is None:
                log.info("omitting ksdata: %s", device)
                continue

            class_attr, list_attr = ksMap[cls]

            cls = getattr(self.ksdata, class_attr)
            data = cls()    # all defaults

            complements = [d for d in complementary_devices if d.raw_device is device]

            if len(complements) > 1:
                log.warning("omitting ksdata for %s, found too many (%d) complementary devices", device, len(complements))
                continue

            device = complements[0] if complements else device

            device.populateKSData(data)

            parent = getattr(self.ksdata, list_attr)
            parent.dataList().append(data)

    @property
    def freeSpaceSnapshot(self):
        # if no snapshot is available, do it now and return it
        self._free_space_snapshot = self._free_space_snapshot or self.getFreeSpace()

        return self._free_space_snapshot

    def createFreeSpaceSnapshot(self):
        self._free_space_snapshot = self.getFreeSpace()

        return self._free_space_snapshot

    def addFstabSwap(self, device):
        """
        Add swap device to the list of swaps that should appear in the fstab.

        :param device: swap device that should be added to the list
        :type device: blivet.devices.StorageDevice instance holding a swap format

        """

        self.fsset.addFstabSwap(device)

    def removeFstabSwap(self, device):
        """
        Remove swap device from the list of swaps that should appear in the fstab.

        :param device: swap device that should be removed from the list
        :type device: blivet.devices.StorageDevice instance holding a swap format

        """

        self.fsset.removeFstabSwap(device)

    def setFstabSwaps(self, devices):
        """
        Set swap devices that should appear in the fstab.

        :param devices: iterable providing devices that should appear in the fstab
        :type devices: iterable providing blivet.devices.StorageDevice instances holding
                       a swap format

        """

        self.fsset.setFstabSwaps(devices)

