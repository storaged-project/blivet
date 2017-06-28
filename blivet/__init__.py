# __init__.py
#
# Copyright (C) 2009, 2010, 2011, 2012, 2013  Red Hat, Inc.
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

__version__ = '0.61.15.65'

##
## Default stub values for installer-specific stuff that gets set up in
## enable_installer_mode.  These constants are only for use inside this file.
## For use in other blivet files, they must either be passed to the function
## in question or care must be taken so they are imported only after
## enable_installer_mode is called.
##
iutil = None
ROOT_PATH = '/'
_storageRoot = ROOT_PATH
_sysroot = ROOT_PATH
shortProductName = 'blivet'
productName = 'blivet'
ERROR_RAISE = 0
DEFAULT_HOSTNAME = "localhost.localdomain"

class ErrorHandler(object):
    def cb(self, exn):
        # pylint: disable=unused-argument
        return ERROR_RAISE

errorHandler = ErrorHandler()

get_bootloader = lambda: None
current_hostname = lambda: None

##
## end installer stubs
##

import os
from os import statvfs
import time
import stat
import errno
import sys
import copy
import tempfile
import shlex
import re

try:
    import nss.nss
except ImportError:
    nss = None

import parted

from pykickstart.constants import AUTOPART_TYPE_LVM, CLEARPART_TYPE_ALL, CLEARPART_TYPE_LINUX, CLEARPART_TYPE_LIST, CLEARPART_TYPE_NONE

from .storage_log import log_exception_info, log_method_call
from .errors import DeviceError, DirtyFSError, FSResizeError, FSTabTypeMismatchError, UnknownSourceDeviceError, StorageError, UnrecognizedFSTabEntryError
from .errors import UnknownSwapError
from .devices import BTRFSDevice, BTRFSSubVolumeDevice, BTRFSVolumeDevice, DirectoryDevice, FileDevice, LVMLogicalVolumeDevice, LVMThinLogicalVolumeDevice, LVMThinPoolDevice, LVMVolumeGroupDevice, MDRaidArrayDevice, NetworkStorageDevice, NFSDevice, NoDevice, OpticalDevice, PartitionDevice, TmpFSDevice, devicePathToName
from .devicetree import DeviceTree
from .deviceaction import ActionCreateDevice, ActionCreateFormat, ActionDestroyDevice, ActionDestroyFormat, ActionResizeDevice, ActionResizeFormat
from .formats import getFormat
from .formats import get_device_format_class
from .formats import get_default_filesystem_type
from . import devicefactory
from .devicelibs.dm import name_from_dm_node
from .devicelibs.crypto import generateBackupPassphrase
from .devicelibs.edd import get_edd_dict
from .devicelibs.dasd import make_dasd_list, write_dasd_conf
from . import udev
from . import iscsi
from . import fcoe
from . import zfcp
from . import util
from . import arch
from .flags import flags
from .platform import platform as _platform
from .platform import EFI
from .size import Size
from .i18n import _

import shelve
import contextlib

import logging
log = logging.getLogger("blivet")

def enable_installer_mode():
    """ Configure the module for use by anaconda (OS installer). """
    global iutil
    global ROOT_PATH
    global _storageRoot
    global _sysroot
    global shortProductName
    global productName
    global get_bootloader
    global errorHandler
    global ERROR_RAISE
    global DEFAULT_HOSTNAME
    global current_hostname

    from pyanaconda import iutil # pylint: disable=redefined-outer-name
    from pyanaconda.constants import shortProductName # pylint: disable=redefined-outer-name
    from pyanaconda.constants import productName # pylint: disable=redefined-outer-name
    from pyanaconda.bootloader import get_bootloader # pylint: disable=redefined-outer-name
    from pyanaconda.network import DEFAULT_HOSTNAME, current_hostname # pylint: disable=redefined-outer-name
    from pyanaconda.errors import errorHandler # pylint: disable=redefined-outer-name
    from pyanaconda.errors import ERROR_RAISE # pylint: disable=redefined-outer-name

    if hasattr(iutil, 'getTargetPhysicalRoot'):
        # For anaconda versions > 21.43
        _storageRoot = iutil.getTargetPhysicalRoot() # pylint: disable=no-name-in-module
        _sysroot = iutil.getSysroot()
    else:
        # For prior anaconda versions
        from pyanaconda.constants import ROOT_PATH # pylint: disable=redefined-outer-name,no-name-in-module
        _storageRoot = _sysroot = ROOT_PATH

    from pyanaconda.anaconda_log import program_log_lock
    util.program_log_lock = program_log_lock

    flags.installer_mode = True

def getSysroot():
    """Returns the path to the target OS installation.

    For traditional installations, this is the same as the physical
    storage root.
    """
    return _sysroot

def getTargetPhysicalRoot():
    """Returns the path to the "physical" storage root.

    This may be distinct from the sysroot, which could be a
    chroot-type subdirectory of the physical root.  This is used for
    example by all OSTree-based installations.
    """
    return _storageRoot

def setSysroot(storageRoot, sysroot=None):
    """Change the OS root path.
       :param storageRoot: The root of physical storage
       :param sysroot: An optional chroot subdirectory of storageRoot
    """
    global _storageRoot
    global _sysroot
    _storageRoot = _sysroot = storageRoot
    if sysroot is not None:
        _sysroot = sysroot

def storageInitialize(storage, ksdata, protected):
    """ Perform installer-specific storage initialization. """
    from pyanaconda.flags import flags as anaconda_flags
    flags.update_from_anaconda_flags(anaconda_flags)

    # Platform class setup depends on flags, re-initialize it.
    _platform.update_from_flags()

    storage.shutdown()

    # Before we set up the storage system, we need to know which disks to
    # ignore, etc.  Luckily that's all in the kickstart data.
    storage.config.update(ksdata)

    # Set up the protected partitions list now.
    if protected:
        storage.config.protectedDevSpecs.extend(protected)

    while True:
        try:
            storage.reset()
        except StorageError as e:
            if errorHandler.cb(e) == ERROR_RAISE:
                raise
            else:
                continue
        else:
            break

    if protected and not flags.live_install and \
       not any(d.protected for d in storage.devices):
        raise UnknownSourceDeviceError(protected)

    # kickstart uses all the disks
    if flags.automated_install:
        if not ksdata.ignoredisk.onlyuse:
            ksdata.ignoredisk.onlyuse = [d.name for d in storage.disks \
                                         if d.name not in ksdata.ignoredisk.ignoredisk]
            log.debug("onlyuse is now: %s", ",".join(ksdata.ignoredisk.onlyuse))

def turnOnFilesystems(storage, mountOnly=False, callbacks=None):
    """
    Perform installer-specific activation of storage configuration.

    :param callbacks: callbacks to be invoked when actions are executed
    :type callbacks: return value of the :func:`~.callbacks.create_new_callbacks_register`

    """

    if not flags.installer_mode:
        return

    if not mountOnly:
        if (flags.live_install and not flags.image_install and not storage.fsset.active):
            # turn off any swaps that we didn't turn on
            # needed for live installs
            util.run_program(["swapoff", "-a"])
        storage.devicetree.teardownAll()

        try:
            storage.doIt(callbacks)
        except FSResizeError as e:
            if errorHandler.cb(e) == ERROR_RAISE:
                raise
        except Exception as e:
            raise

        storage.turnOnSwap()
    # FIXME:  For livecd, skipRoot needs to be True.
    storage.mountFilesystems()

    if not mountOnly:
        writeEscrowPackets(storage)

def writeEscrowPackets(storage):
    escrowDevices = [d for d in storage.devices if d.format.type == 'luks' and
                     d.format.escrow_cert]

    if not escrowDevices:
        return

    log.debug("escrow: writeEscrowPackets start")

    if not nss:
        log.error("escrow: no nss python module -- aborting")
        return

    nss.nss.nss_init_nodb() # Does nothing if NSS is already initialized

    backupPassphrase = generateBackupPassphrase()

    try:
        escrowDir = _sysroot + "/root"
        log.debug("escrow: writing escrow packets to %s", escrowDir)
        util.makedirs(escrowDir)
        for device in escrowDevices:
            log.debug("escrow: device %s: %s",
                      repr(device.path), repr(device.format.type))
            device.format.escrow(escrowDir,
                                 backupPassphrase)

    except (IOError, RuntimeError) as e:
        # TODO: real error handling
        log.error("failed to store encryption key: %s", e)

    log.debug("escrow: writeEscrowPackets done")

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
        self.dasd = []

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

        self.devicetree.processActions(callbacks)
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
            self.dasd = make_dasd_list(self.dasd, self.devices)

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
            self.roots = findExistingInstallations(self.devicetree)
            self.dumpState("initial")

        if not flags.installer_mode:
            self.devicetree.getActiveMounts()

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
        disks.sort(key=lambda d: d.name, cmp=self.compareDisks)
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
        lvs = self.devicetree.getDevicesByType("lvmlv")
        lvs.sort(key=lambda d: d.name)
        return lvs

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
        log.debug("removing %s", device.name)
        devices = self.deviceDeps(device)

        # this isn't strictly necessary, but it makes the action list easier to
        # read when removing logical partitions because of the automatic
        # renumbering that happens if you remove them in ascending numerical
        # order
        devices.reverse()

        while devices:
            log.debug("devices to remove: %s", [d.name for d in devices])
            leaves = [d for d in devices if d.isleaf]
            log.debug("leaves to remove: %s", [d.name for d in leaves])
            for leaf in leaves:
                self.destroyDevice(leaf)
                devices.remove(leaf)

        if device.isDisk:
            self.devicetree.registerAction(ActionDestroyFormat(device))
        else:
            self.destroyDevice(device)

    def clearPartitions(self):
        """ Clear partitions and dependent devices from disks.

            This is also where zerombr is handled.
        """
        # Sort partitions by descending partition number to minimize confusing
        # things like multiple "destroy sda5" actions due to parted renumbering
        # partitions. This can still happen through the UI but it makes sense to
        # avoid it where possible.
        partitions = sorted(self.partitions,
                            key=lambda p: getattr(p.partedPartition, "number", 1),
                            reverse=True)
        for part in partitions:
            log.debug("clearpart: looking at %s", part.name)
            if not self.shouldClear(part):
                continue

            self.recursiveRemove(part)
            log.debug("partitions: %s", [p.name for p in self.devicetree.getChildren(part.disk)])

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
                if flags.installer_mode and hostname == DEFAULT_HOSTNAME:
                    hostname = current_hostname()

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

        if thin_pool or thin_volume:
            cache_req = kwargs.pop("cacheRequest", None)
            if cache_req:
                raise ValueError("Creating cached thin volumes and pools is not supported")

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
            kwargs.pop("metaDataLevel", None)
            kwargs.pop("dataLevel", None)
            kwargs.pop("createOptions", None)
        else:
            dev_class = BTRFSVolumeDevice
            # set up the volume label, using hostname if necessary
            if not name:
                hostname = ""
                if self.ksdata and self.ksdata.network.hostname is not None:
                    hostname = self.ksdata.network.hostname
                    if flags.installer_mode and hostname == DEFAULT_HOSTNAME:
                        hostname = current_hostname()

                name = self.suggestContainerName(hostname=hostname)
            if "label" not in fmt_args:
                fmt_args["label"] = name

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
        device.format = copy.copy(device.originalFormat)

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
        self.devicetree._DeviceTree__luksDevs[device.format.uuid] = passphrase
        self.devicetree._DeviceTree__passphrases.append(passphrase)

    def setupDiskImages(self):
        self.devicetree.setDiskImages(self.config.diskImages)
        self.devicetree.setupDiskImages()

    @property
    def fileSystemFreeSpace(self):
        """ Combined free space in / and /usr as :class:`~.size.Size`. """
        mountpoints = ["/", "/usr"]
        free = 0
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
        if not os.path.isdir("%s/etc" % _sysroot):
            os.mkdir("%s/etc" % _sysroot)

        self.fsset.write()
        self.makeMtab()
        self.iscsi.write(_sysroot, self)
        self.fcoe.write(_sysroot)
        self.zfcp.write(_sysroot, self.devicetree.getDevicesByType("zfcp"))
        write_dasd_conf(self.devicetree.dasd, _sysroot)

    def turnOnSwap(self):
        self.fsset.turnOnSwap(rootPath=_sysroot)

    def mountFilesystems(self, readOnly=None, skipRoot=False):
        self.fsset.mountFilesystems(rootPath=_sysroot,
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
        boot_disks.sort(cmp=self.compareDisks, key=lambda d: d.name)
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
        path = os.path.normpath("%s/%s" % (_sysroot, path))

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
                if old_dev is None:
                    continue

                new_dev = new.devicetree.getDeviceByID(old_dev.id, hidden=True)
                if new_dev is None:
                    # if the device has been removed don't include this
                    # mountpoint at all
                    del root.mounts[mountpoint]
                else:
                    root.mounts[mountpoint] = new_dev

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

        # list comprehension that builds device ancestors should not get None as a member
        # when searching for bootloader devices
        bootLoaderDevices = []
        if self.bootLoaderDevice is not None:
            bootLoaderDevices.append(self.bootLoaderDevice)

        # biosboot is a special case
        for device in self.devices:
            if device.format.type == 'biosboot':
                bootLoaderDevices.append(device)

        # make a list of ancestors of all used devices
        devices = list(set(a for d in list(self.mountpoints.values()) + self.swaps + bootLoaderDevices
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

def mountExistingSystem(fsset, rootDevice,
                        allowDirty=None, dirtyCB=None,
                        readOnly=None):
    """ Mount filesystems specified in rootDevice's /etc/fstab file. """
    rootPath = _sysroot
    if dirtyCB is None:
        dirtyCB = lambda l: False

    if readOnly:
        readOnly = "ro"
    else:
        readOnly = ""

    if rootDevice.protected and os.path.ismount("/mnt/install/isodir"):
        util.mount("/mnt/install/isodir",
                   rootPath,
                   fstype=rootDevice.format.type,
                   options="bind")
    else:
        rootDevice.setup()
        rootDevice.format.mount(chroot=rootPath,
                                mountpoint="/",
                                options="%s,%s" % (rootDevice.format.options, readOnly))

    fsset.parseFSTab()

    # check for dirty filesystems
    dirtyDevs = []
    for device in fsset.mountpoints.values():
        if not hasattr(device.format, "needsFSCheck"):
            continue

        try:
            device.setup()
        except DeviceError:
            # we'll catch this in the main loop
            continue

        if device.format.needsFSCheck:
            log.info("%s contains a dirty %s filesystem", device.path,
                                                          device.format.type)
            dirtyDevs.append(device.path)

    if dirtyDevs and (not allowDirty or dirtyCB(dirtyDevs)):
        raise DirtyFSError(dirtyDevs)

    fsset.mountFilesystems(rootPath=_sysroot, readOnly=readOnly, skipRoot=True)


class BlkidTab(object):
    """ Dictionary-like interface to blkid.tab with device path keys """
    def __init__(self, chroot=""):
        self.chroot = chroot
        self.devices = {}

    def parse(self):
        path = "%s/etc/blkid/blkid.tab" % self.chroot
        log.debug("parsing %s", path)
        with open(path) as f:
            for line in f.readlines():
                # this is pretty ugly, but an XML parser is more work than
                # is justifiable for this purpose
                if not line.startswith("<device "):
                    continue

                line = line[len("<device "):-len("</device>\n")]

                (data, _sep, device) = line.partition(">")
                if not device:
                    continue

                self.devices[device] = {}
                for pair in data.split():
                    try:
                        (key, value) = pair.split("=")
                    except ValueError:
                        continue

                    self.devices[device][key] = value[1:-1] # strip off quotes

    def __getitem__(self, key):
        return self.devices[key]

    def get(self, key, default=None):
        return self.devices.get(key, default)


class CryptTab(object):
    """ Dictionary-like interface to crypttab entries with map name keys """
    def __init__(self, devicetree, blkidTab=None, chroot=""):
        self.devicetree = devicetree
        self.blkidTab = blkidTab
        self.chroot = chroot
        self.mappings = {}

    def parse(self, chroot=""):
        """ Parse /etc/crypttab from an existing installation. """
        if not chroot or not os.path.isdir(chroot):
            chroot = ""

        path = "%s/etc/crypttab" % chroot
        log.debug("parsing %s", path)
        with open(path) as f:
            if not self.blkidTab:
                try:
                    self.blkidTab = BlkidTab(chroot=chroot)
                    self.blkidTab.parse()
                except Exception: # pylint: disable=broad-except
                    log_exception_info(fmt_str="failed to parse blkid.tab")
                    self.blkidTab = None

            for line in f.readlines():
                (line, _pound, _comment) = line.partition("#")
                fields = line.split()
                if not 2 <= len(fields) <= 4:
                    continue
                elif len(fields) == 2:
                    fields.extend(['none', ''])
                elif len(fields) == 3:
                    fields.append('')

                (name, devspec, keyfile, options) = fields

                # resolve devspec to a device in the tree
                device = self.devicetree.resolveDevice(devspec,
                                                       blkidTab=self.blkidTab)
                if device:
                    self.mappings[name] = {"device": device,
                                           "keyfile": keyfile,
                                           "options": options}

    def populate(self):
        """ Populate the instance based on the device tree's contents. """
        for device in self.devicetree.devices:
            # XXX should we put them all in there or just the ones that
            #     are part of a device containing swap or a filesystem?
            #
            #       Put them all in here -- we can filter from FSSet
            if device.format.type != "luks":
                continue

            key_file = device.format.keyFile
            if not key_file:
                key_file = "none"

            options = device.format.options
            if not options:
                options = ""

            self.mappings[device.format.mapName] = {"device": device,
                                                    "keyfile": key_file,
                                                    "options": options}

    def crypttab(self):
        """ Write out /etc/crypttab """
        crypttab = ""
        for name in self.mappings:
            entry = self[name]
            crypttab += "%s UUID=%s %s %s\n" % (name,
                                                entry['device'].format.uuid,
                                                entry['keyfile'],
                                                entry['options'])
        return crypttab

    def __getitem__(self, key):
        return self.mappings[key]

    def get(self, key, default=None):
        return self.mappings.get(key, default)

def get_containing_device(path, devicetree):
    """ Return the device that a path resides on. """
    if not os.path.exists(path):
        return None

    st = os.stat(path)
    major = os.major(st.st_dev)
    minor = os.minor(st.st_dev)
    link = "/sys/dev/block/%s:%s" % (major, minor)
    if not os.path.exists(link):
        return None

    try:
        device_name = os.path.basename(os.readlink(link))
    except Exception: # pylint: disable=broad-except
        log_exception_info(fmt_str="failed to find device name for path %s", fmt_args=[path])
        return None

    if device_name.startswith("dm-"):
        # have I told you lately that I love you, device-mapper?
        device_name = name_from_dm_node(device_name)

    return devicetree.getDeviceByName(device_name)


class FSSet(object):
    """ A class to represent a set of filesystems. """
    def __init__(self, devicetree):
        self.devicetree = devicetree
        self.cryptTab = None
        self.blkidTab = None
        self.origFStab = None
        self.active = False
        self._dev = None
        self._devpts = None
        self._sysfs = None
        self._proc = None
        self._devshm = None
        self._usb = None
        self._selinux = None
        self._run = None
        self._efivars = None
        self._fstab_swaps = set()
        self.preserveLines = []     # lines we just ignore and preserve

    @property
    def sysfs(self):
        if not self._sysfs:
            self._sysfs = NoDevice(fmt=getFormat("sysfs", device="sysfs", mountpoint="/sys"))
        return self._sysfs

    @property
    def dev(self):
        if not self._dev:
            self._dev = DirectoryDevice("/dev",
               fmt=getFormat("bind", device="/dev", mountpoint="/dev", exists=True),
               exists=True)

        return self._dev

    @property
    def devpts(self):
        if not self._devpts:
            self._devpts = NoDevice(fmt=getFormat("devpts", device="devpts", mountpoint="/dev/pts"))
        return self._devpts

    @property
    def proc(self):
        if not self._proc:
            self._proc = NoDevice(fmt=getFormat("proc", device="proc", mountpoint="/proc"))
        return self._proc

    @property
    def devshm(self):
        if not self._devshm:
            self._devshm = NoDevice(fmt=getFormat("tmpfs", device="tmpfs", mountpoint="/dev/shm"))
        return self._devshm

    @property
    def usb(self):
        if not self._usb:
            self._usb = NoDevice(fmt=getFormat("usbfs", device="usbfs", mountpoint="/proc/bus/usb"))
        return self._usb

    @property
    def selinux(self):
        if not self._selinux:
            self._selinux = NoDevice(fmt=getFormat("selinuxfs", device="selinuxfs", mountpoint="/sys/fs/selinux"))
        return self._selinux

    @property
    def efivars(self):
        if not self._efivars:
            self._efivars = NoDevice(fmt=getFormat("efivarfs", device="efivarfs", mountpoint="/sys/firmware/efi/efivars"))
        return self._efivars

    @property
    def run(self):
        if not self._run:
            self._run = DirectoryDevice("/run",
               fmt=getFormat("bind", device="/run", mountpoint="/run", exists=True),
               exists=True)

        return self._run

    @property
    def devices(self):
        return sorted(self.devicetree.devices, key=lambda d: d.path)

    @property
    def mountpoints(self):
        filesystems = {}
        for device in self.devices:
            if device.format.mountable and device.format.mountpoint:
                filesystems[device.format.mountpoint] = device
        return filesystems

    def _parseOneLine(self, devspec, mountpoint, fstype, options, _dump="0", _passno="0"):
        """Parse an fstab entry for a device, return the corresponding device.

           The parameters correspond to the items in a single entry in the
           order in which they occur in the entry.

           :returns: the device corresponding to the entry
           :rtype: :class:`devices.Device`
        """

        # no sense in doing any legwork for a noauto entry
        if "noauto" in options.split(","):
            log.info("ignoring noauto entry")
            raise UnrecognizedFSTabEntryError()

        # find device in the tree
        device = self.devicetree.resolveDevice(devspec,
                                               cryptTab=self.cryptTab,
                                               blkidTab=self.blkidTab,
                                               options=options)

        if device:
            # fall through to the bottom of this block
            pass
        elif devspec.startswith("/dev/loop"):
            # FIXME: create devices.LoopDevice
            log.warning("completely ignoring your loop mount")
        elif ":" in devspec and fstype.startswith("nfs"):
            # NFS -- preserve but otherwise ignore
            device = NFSDevice(devspec,
                               fmt=getFormat(fstype,
                                                exists=True,
                                                device=devspec))
        elif devspec.startswith("/") and fstype == "swap":
            # swap file
            device = FileDevice(devspec,
                                parents=get_containing_device(devspec, self.devicetree),
                                fmt=getFormat(fstype,
                                                 device=devspec,
                                                 exists=True),
                                exists=True)
        elif fstype == "bind" or "bind" in options:
            # bind mount... set fstype so later comparison won't
            # turn up false positives
            fstype = "bind"

            # This is probably not going to do anything useful, so we'll
            # make sure to try again from FSSet.mountFilesystems. The bind
            # mount targets should be accessible by the time we try to do
            # the bind mount from there.
            parents = get_containing_device(devspec, self.devicetree)
            device = DirectoryDevice(devspec, parents=parents, exists=True)
            device.format = getFormat("bind",
                                      device=device.path,
                                      exists=True)
        elif mountpoint in ("/proc", "/sys", "/dev/shm", "/dev/pts",
                            "/sys/fs/selinux", "/proc/bus/usb", "/sys/firmware/efi/efivars"):
            # drop these now -- we'll recreate later
            return None
        else:
            # nodev filesystem -- preserve or drop completely?
            fmt = getFormat(fstype)
            fmt_class = get_device_format_class("nodev")
            if devspec == "none" or \
               (fmt_class and isinstance(fmt, fmt_class)):
                device = NoDevice(fmt=fmt)

        if device is None:
            log.error("failed to resolve %s (%s) from fstab", devspec,
                                                              fstype)
            raise UnrecognizedFSTabEntryError()

        device.setup()
        fmt = getFormat(fstype, device=device.path, exists=True)
        if fstype != "auto" and None in (device.format.type, fmt.type):
            log.info("Unrecognized filesystem type for %s (%s)",
                     device.name, fstype)
            device.teardown()
            raise UnrecognizedFSTabEntryError()

        # make sure, if we're using a device from the tree, that
        # the device's format we found matches what's in the fstab
        ftype = getattr(fmt, "mountType", fmt.type)
        dtype = getattr(device.format, "mountType", device.format.type)
        if fstype != "auto" and ftype != dtype:
            log.info("fstab says %s at %s is %s", dtype, mountpoint, ftype)
            if fmt.testMount():
                device.format = fmt
            else:
                device.teardown()
                raise FSTabTypeMismatchError("%s: detected as %s, fstab says %s"
                                             % (mountpoint, dtype, ftype))
        del ftype
        del dtype

        if device.format.mountable:
            device.format.mountpoint = mountpoint
            device.format.mountopts = options

        # is this useful?
        try:
            device.format.options = options
        except AttributeError:
            pass

        return device

    def parseFSTab(self, chroot=None):
        """ parse /etc/fstab

            preconditions:
                all storage devices have been scanned, including filesystems
            postconditions:

            FIXME: control which exceptions we raise

            XXX do we care about bind mounts?
                how about nodev mounts?
                loop mounts?
        """
        if not chroot or not os.path.isdir(chroot):
            chroot = _sysroot

        path = "%s/etc/fstab" % chroot
        if not os.access(path, os.R_OK):
            # XXX should we raise an exception instead?
            log.info("cannot open %s for read", path)
            return

        blkidTab = BlkidTab(chroot=chroot)
        try:
            blkidTab.parse()
            log.debug("blkid.tab devs: %s", list(blkidTab.devices.keys()))
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.info, "error parsing blkid.tab")
            blkidTab = None

        cryptTab = CryptTab(self.devicetree, blkidTab=blkidTab, chroot=chroot)
        try:
            cryptTab.parse(chroot=chroot)
            log.debug("crypttab maps: %s", list(cryptTab.mappings.keys()))
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.info, "error parsing crypttab")
            cryptTab = None

        self.blkidTab = blkidTab
        self.cryptTab = cryptTab

        with open(path) as f:
            log.debug("parsing %s", path)

            lines = f.readlines()

            # save the original file
            self.origFStab = ''.join(lines)

            for line in lines:

                (line, _pound, _comment) = line.partition("#")
                fields = line.split()

                if not 4 <= len(fields) <= 6:
                    continue

                try:
                    device = self._parseOneLine(*fields)
                except UnrecognizedFSTabEntryError:
                    # just write the line back out as-is after upgrade
                    self.preserveLines.append(line)
                    continue

                if not device:
                    continue

                if device not in self.devicetree.devices:
                    try:
                        self.devicetree._addDevice(device)
                    except ValueError:
                        # just write duplicates back out post-install
                        self.preserveLines.append(line)

    def turnOnSwap(self, rootPath=""):
        """ Activate the system's swap space. """
        if not flags.installer_mode:
            return

        for device in self.swapDevices:
            if isinstance(device, FileDevice):
                # set up FileDevices' parents now that they are accessible
                targetDir = "%s/%s" % (rootPath, device.path)
                parent = get_containing_device(targetDir, self.devicetree)
                if not parent:
                    log.error("cannot determine which device contains "
                              "directory %s", device.path)
                    device.parents = []
                    self.devicetree._removeDevice(device)
                    continue
                else:
                    device.parents = [parent]

            while True:
                try:
                    device.setup()
                    device.format.setup()
                except UnknownSwapError as e:
                    log.warn("Failed to activate swap on %s, skipping it.", device.path)
                    break
                except StorageError as e:
                    if errorHandler.cb(e) == ERROR_RAISE:
                        raise
                else:
                    break

    def mountFilesystems(self, rootPath="", readOnly=None, skipRoot=False):
        """ Mount the system's filesystems.

            :param str rootPath: the root directory for this filesystem
            :param readOnly: read only option str for this filesystem
            :type readOnly: str or None
            :param bool skipRoot: whether to skip mounting the root filesystem
        """
        if not flags.installer_mode:
            return

        devices = list(self.mountpoints.values()) + self.swapDevices
        devices.extend([self.dev, self.devshm, self.devpts, self.sysfs,
                        self.proc, self.selinux, self.usb, self.run])
        if isinstance(_platform, EFI):
            devices.append(self.efivars)
        devices.sort(key=lambda d: getattr(d.format, "mountpoint", None))

        for device in devices:
            if not device.format.mountable or not device.format.mountpoint:
                continue

            if skipRoot and device.format.mountpoint == "/":
                continue

            options = device.format.options
            if "noauto" in options.split(","):
                continue

            if device.format.type == "bind" and device not in [self.dev, self.run]:
                # set up the DirectoryDevice's parents now that they are
                # accessible
                #
                # -- bind formats' device and mountpoint are always both
                #    under the chroot. no exceptions. none, damn it.
                targetDir = "%s/%s" % (rootPath, device.path)
                parent = get_containing_device(targetDir, self.devicetree)
                if not parent:
                    log.error("cannot determine which device contains "
                              "directory %s", device.path)
                    device.parents = []
                    self.devicetree._removeDevice(device)
                    continue
                else:
                    device.parents = [parent]

            try:
                device.setup()
            except Exception as e: # pylint: disable=broad-except
                log_exception_info(fmt_str="unable to set up device %s", fmt_args=[device])
                if errorHandler.cb(e) == ERROR_RAISE:
                    raise
                else:
                    continue

            if readOnly:
                options = "%s,%s" % (options, readOnly)

            try:
                device.format.setup(options=options,
                                    chroot=rootPath)
            except Exception as e: # pylint: disable=broad-except
                log_exception_info(log.error, "error mounting %s on %s", [device.path, device.format.mountpoint])
                if errorHandler.cb(e) == ERROR_RAISE:
                    raise

        self.active = True

    def umountFilesystems(self, swapoff=True):
        """ unmount filesystems, except swap if swapoff == False """
        devices = list(self.mountpoints.values()) + self.swapDevices
        devices.extend([self.dev, self.devshm, self.devpts, self.sysfs,
                        self.proc, self.usb, self.selinux, self.run])
        if isinstance(_platform, EFI):
            devices.append(self.efivars)
        devices.sort(key=lambda d: getattr(d.format, "mountpoint", None))
        devices.reverse()
        for device in devices:
            if (not device.format.mountable) or \
               (device.format.type == "swap" and not swapoff):
                continue

            device.format.teardown()
            device.teardown()

        self.active = False

    def createSwapFile(self, device, size):
        """ Create and activate a swap file under storage root. """
        filename = "/SWAP"
        count = 0
        basedir = os.path.normpath("%s/%s" % (getTargetPhysicalRoot(),
                                              device.format.mountpoint))
        while os.path.exists("%s/%s" % (basedir, filename)) or \
              self.devicetree.getDeviceByName(filename):
            count += 1
            filename = "/SWAP-%d" % count

        dev = FileDevice(filename,
                         size=size,
                         parents=[device],
                         fmt=getFormat("swap", device=filename))
        dev.create()
        dev.setup()
        dev.format.create()
        dev.format.setup()
        # nasty, nasty
        self.devicetree._addDevice(dev)

    def mkDevRoot(self):
        root = self.rootDevice
        dev = "%s/%s" % (_sysroot, root.path)
        if not os.path.exists("%s/dev/root" %(_sysroot,)) and os.path.exists(dev):
            rdev = os.stat(dev).st_rdev
            os.mknod("%s/dev/root" % (_sysroot,), stat.S_IFBLK | 0o600, rdev)

    @property
    def swapDevices(self):
        swaps = []
        for device in self.devices:
            if device.format.type == "swap":
                swaps.append(device)
        return swaps

    @property
    def rootDevice(self):
        for path in ["/", getTargetPhysicalRoot()]:
            for device in self.devices:
                try:
                    mountpoint = device.format.mountpoint
                except AttributeError:
                    mountpoint = None

                if mountpoint == path:
                    return device

    def write(self):
        """ write out all config files based on the set of filesystems """
        # /etc/fstab
        fstab_path = os.path.normpath("%s/etc/fstab" % _sysroot)
        fstab = self.fstab()
        open(fstab_path, "w").write(fstab)

        # /etc/crypttab
        crypttab_path = os.path.normpath("%s/etc/crypttab" % _sysroot)
        crypttab = self.crypttab()
        origmask = os.umask(0o077)
        open(crypttab_path, "w").write(crypttab)
        os.umask(origmask)

        # /etc/mdadm.conf
        mdadm_path = os.path.normpath("%s/etc/mdadm.conf" % _sysroot)
        mdadm_conf = self.mdadmConf()
        if mdadm_conf:
            open(mdadm_path, "w").write(mdadm_conf)

        # /etc/multipath.conf
        if self.devicetree.getDevicesByType("dm-multipath"):
            util.copy_to_system("/etc/multipath.conf")
            util.copy_to_system("/etc/multipath/wwids")
            util.copy_to_system("/etc/multipath/bindings")
        else:
            log.info("not writing out mpath configuration")

    def crypttab(self):
        # if we are upgrading, do we want to update crypttab?
        # gut reaction says no, but plymouth needs the names to be very
        # specific for passphrase prompting
        if not self.cryptTab:
            self.cryptTab = CryptTab(self.devicetree)
            self.cryptTab.populate()

        devices = list(self.mountpoints.values()) + self.swapDevices

        # prune crypttab -- only mappings required by one or more entries
        for name in self.cryptTab.mappings.keys():
            keep = False
            mapInfo = self.cryptTab[name]
            cryptoDev = mapInfo['device']
            for device in devices:
                if device == cryptoDev or device.dependsOn(cryptoDev):
                    keep = True
                    break

            if not keep:
                del self.cryptTab.mappings[name]

        return self.cryptTab.crypttab()

    def mdadmConf(self):
        """ Return the contents of mdadm.conf. """
        arrays = self.devicetree.getDevicesByType("mdarray")
        arrays.extend(self.devicetree.getDevicesByType("mdbiosraidarray"))
        arrays.extend(self.devicetree.getDevicesByType("mdcontainer"))
        # Sort it, this not only looks nicer, but this will also put
        # containers (which get md0, md1, etc.) before their members
        # (which get md127, md126, etc.). and lame as it is mdadm will not
        # assemble the whole stack in one go unless listed in the proper order
        # in mdadm.conf
        arrays.sort(key=lambda d: d.path)
        if not arrays:
            return ""

        conf = "# mdadm.conf written out by anaconda\n"
        conf += "MAILADDR root\n"
        conf += "AUTO +imsm +1.x -all\n"
        devices = list(self.mountpoints.values()) + self.swapDevices
        for array in arrays:
            for device in devices:
                if device == array or device.dependsOn(array):
                    conf += array.mdadmConfEntry
                    break

        return conf

    def fstab (self):
        fmt_str = "%-23s %-23s %-7s %-15s %d %d\n"
        fstab = """
#
# /etc/fstab
# Created by anaconda on %s
#
# Accessible filesystems, by reference, are maintained under '/dev/disk'
# See man pages fstab(5), findfs(8), mount(8) and/or blkid(8) for more info
#
""" % time.asctime()

        devices = sorted(self.mountpoints.values(),
                         key=lambda d: d.format.mountpoint)

        # filter swaps only in installer mode
        if flags.installer_mode:
            devices += [dev for dev in self.swapDevices
                        if dev in self._fstab_swaps]
        else:
            devices += self.swapDevices

        netdevs = self.devicetree.getDevicesByInstance(NetworkStorageDevice)

        rootdev = devices[0]
        root_on_netdev = any(rootdev.dependsOn(netdev) for netdev in netdevs)

        for device in devices:
            # why the hell do we put swap in the fstab, anyway?
            if not device.format.mountable and device.format.type != "swap":
                continue

            # Don't write out lines for optical devices, either.
            if isinstance(device, OpticalDevice):
                continue

            fstype = getattr(device.format, "mountType", device.format.type)
            if fstype == "swap":
                mountpoint = "swap"
                options = device.format.options
            else:
                mountpoint = device.format.mountpoint
                options = device.format.options
                if not mountpoint:
                    log.warning("%s filesystem on %s has no mountpoint",
                                                            fstype,
                                                            device.path)
                    continue

            options = options or "defaults"
            for netdev in netdevs:
                if device.dependsOn(netdev):
                    options = options + ",_netdev"
                    if root_on_netdev and mountpoint not in ["/", "/usr"]:
                        options = options + ",x-initrd.mount"
                    break
            if device.encrypted:
                options += ",x-systemd.device-timeout=0"
            devspec = device.fstabSpec
            dump = device.format.dump
            if device.format.check and mountpoint == "/":
                passno = 1
            elif device.format.check:
                passno = 2
            else:
                passno = 0
            fstab = fstab + device.fstabComment
            fstab = fstab + fmt_str % (devspec, mountpoint, fstype,
                                       options, dump, passno)

        # now, write out any lines we were unable to process because of
        # unrecognized filesystems or unresolveable device specifications
        for line in self.preserveLines:
            fstab += line

        return fstab

    def addFstabSwap(self, device):
        """
        Add swap device to the list of swaps that should appear in the fstab.

        :param device: swap device that should be added to the list
        :type device: blivet.devices.StorageDevice instance holding a swap format

        """

        self._fstab_swaps.add(device)

    def removeFstabSwap(self, device):
        """
        Remove swap device from the list of swaps that should appear in the fstab.

        :param device: swap device that should be removed from the list
        :type device: blivet.devices.StorageDevice instance holding a swap format

        """

        try:
            self._fstab_swaps.remove(device)
        except KeyError:
            pass

    def setFstabSwaps(self, devices):
        """
        Set swap devices that should appear in the fstab.

        :param devices: iterable providing devices that should appear in the fstab
        :type devices: iterable providing blivet.devices.StorageDevice instances holding
                       a swap format

        """

        self._fstab_swaps = set(devices)

def releaseFromRedhatRelease(fn):
    """
    Attempt to identify the installation of a Linux distribution via
    /etc/redhat-release.  This file must already have been verified to exist
    and be readable.

    :param fn: an open filehandle on /etc/redhat-release
    :type fn: filehandle
    :returns: The distribution's name and version, or None for either or both
    if they cannot be determined
    :rtype: (string, string)
    """
    relName = None
    relVer = None

    with open(fn) as f:
        try:
            relstr = f.readline().strip()
        except (IOError, AttributeError):
            relstr = ""

    # get the release name and version
    # assumes that form is something
    # like "Red Hat Linux release 6.2 (Zoot)"
    (product, sep, version) = relstr.partition(" release ")
    if sep:
        relName = product
        relVer = version.split()[0]

    return (relName, relVer)

def releaseFromOsRelease(fn):
    """
    Attempt to identify the installation of a Linux distribution via
    /etc/os-release.  This file must already have been verified to exist
    and be readable.

    :param fn: an open filehandle on /etc/os-release
    :type fn: filehandle
    :returns: The distribution's name and version, or None for either or both
    if they cannot be determined
    :rtype: (string, string)
    """
    relName = None
    relVer = None

    with open(fn, "r") as f:
        parser = shlex.shlex(f)

        while True:
            key = parser.get_token()
            if key == parser.eof:
                break
            elif key == "NAME":
                # Throw away the "=".
                parser.get_token()
                relName = parser.get_token().strip("'\"")
            elif key == "VERSION_ID":
                # Throw away the "=".
                parser.get_token()
                relVer = parser.get_token().strip("'\"")

    return (relName, relVer)

def getReleaseString():
    """
    Attempt to identify the installation of a Linux distribution by checking
    a previously mounted filesystem for several files.  The filesystem must
    be mounted under the target physical root.

    :returns: The machine's arch, distribution name, and distribution version
    or None for any parts that cannot be determined
    :rtype: (string, string, string)
    """
    relName = None
    relVer = None

    try:
        relArch = util.capture_output(["arch"], root=_sysroot).strip()
    except OSError:
        relArch = None

    filename = "%s/etc/redhat-release" % getSysroot()
    if os.access(filename, os.R_OK):
        (relName, relVer) = releaseFromRedhatRelease(filename)
    else:
        filename = "%s/etc/os-release" % getSysroot()
        if os.access(filename, os.R_OK):
            (relName, relVer) = releaseFromOsRelease(filename)

    return (relArch, relName, relVer)

def findExistingInstallations(devicetree, teardown_all=True):
    """Find existing GNU/Linux installations on devices from the devicetree.
    :param devicetree: devicetree to find existing installations in
    :type devicetree: :class:`~.devicetree.DeviceTree`
    :param bool teardown_all: whether to tear down all devices in the
                              devicetree in the end

    """

    try:
        roots = _findExistingInstallations(devicetree)
        return roots
    except Exception: # pylint: disable=broad-except
        log_exception_info(log.info, "failure detecting existing installations")
    finally:
        if teardown_all:
            devicetree.teardownAll()

def _findExistingInstallations(devicetree):
    if not os.path.exists(getTargetPhysicalRoot()):
        util.makedirs(getTargetPhysicalRoot())

    roots = []

    direct_devices = (dev for dev in devicetree.devices if dev.direct)

    for device in direct_devices:
        if not device.format.linuxNative or not device.format.mountable or \
           not device.controllable:
            continue

        try:
            device.setup()
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.warning, "setup of %s failed", [device.name])
            continue

        options = device.format.options + ",ro"
        try:
            device.format.mount(options=options, mountpoint=getSysroot())
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.warning, "mount of %s as %s failed", [device.name, device.format.type])
            device.teardown()
            continue

        if not os.access(getSysroot() + "/etc/fstab", os.R_OK):
            device.teardown(recursive=True)
            continue

        try:
            (architecture, product, version) = getReleaseString()
        except ValueError:
            name = _("Linux on %s") % device.name
        else:
            # I'd like to make this finer grained, but it'd be very difficult
            # to translate.
            if not product or not version or not architecture:
                name = _("Unknown Linux")
            else:
                name = _("%(product)s Linux %(version)s for %(arch)s") % \
                        {"product": product, "version": version, "arch": architecture}

        (mounts, swaps) = parseFSTab(devicetree, chroot=_sysroot)
        device.teardown()
        if not mounts and not swaps:
            # empty /etc/fstab. weird, but I've seen it happen.
            continue
        roots.append(Root(mounts=mounts, swaps=swaps, name=name))

    return roots

class Root(object):
    """ A Root represents an existing OS installation. """
    def __init__(self, mounts=None, swaps=None, name=None):
        """
            :keyword mounts: mountpoint dict
            :type mounts: dict (mountpoint keys and :class:`~.devices.StorageDevice` values)
            :keyword swaps: swap device list
            :type swaps: list of :class:`~.devices.StorageDevice`
            :keyword name: name for this installed OS
            :type name: str
        """
        # mountpoint key, StorageDevice value
        if not mounts:
            self.mounts = {}
        else:
            self.mounts = mounts

        # StorageDevice
        if not swaps:
            self.swaps = []
        else:
            self.swaps = swaps

        self.name = name    # eg: "Fedora Linux 16 for x86_64", "Linux on sda2"

        if not self.name and "/" in self.mounts:
            self.name = self.mounts["/"].format.uuid

    @property
    def device(self):
        return self.mounts.get("/")

def parseFSTab(devicetree, chroot=None):
    """ parse /etc/fstab and return a tuple of a mount dict and swap list """
    if not chroot or not os.path.isdir(chroot):
        chroot = _sysroot

    mounts = {}
    swaps = []
    path = "%s/etc/fstab" % chroot
    if not os.access(path, os.R_OK):
        # XXX should we raise an exception instead?
        log.info("cannot open %s for read", path)
        return (mounts, swaps)

    blkidTab = BlkidTab(chroot=chroot)
    try:
        blkidTab.parse()
        log.debug("blkid.tab devs: %s", list(blkidTab.devices.keys()))
    except Exception: # pylint: disable=broad-except
        log_exception_info(log.info, "error parsing blkid.tab")
        blkidTab = None

    cryptTab = CryptTab(devicetree, blkidTab=blkidTab, chroot=chroot)
    try:
        cryptTab.parse(chroot=chroot)
        log.debug("crypttab maps: %s", list(cryptTab.mappings.keys()))
    except Exception: # pylint: disable=broad-except
        log_exception_info(log.info, "error parsing crypttab")
        cryptTab = None

    with open(path) as f:
        log.debug("parsing %s", path)
        for line in f.readlines():

            (line, _pound, _comment) = line.partition("#")
            fields = line.split(None, 4)

            if len(fields) < 5:
                continue

            (devspec, mountpoint, fstype, options, _rest) = fields

            # find device in the tree
            device = devicetree.resolveDevice(devspec,
                                              cryptTab=cryptTab,
                                              blkidTab=blkidTab,
                                              options=options)

            if device is None:
                continue

            if fstype != "swap":
                mounts[mountpoint] = device
            else:
                swaps.append(device)

    return (mounts, swaps)
