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

"""This module provides functions related to OS installation."""

import shlex
import os
import stat
import time

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from . import util
from . import getSysroot, getTargetPhysicalRoot, errorHandler, ERROR_RAISE
from .util import open  # pylint: disable=redefined-builtin

from .storage_log import log_exception_info
from .devices import FileDevice, NFSDevice, NoDevice, OpticalDevice, NetworkStorageDevice, DirectoryDevice
from .errors import FSTabTypeMismatchError, UnrecognizedFSTabEntryError, StorageError, FSResizeError, UnknownSourceDeviceError
from .formats import get_device_format_class
from .formats import getFormat
from .flags import flags
from .platform import platform as _platform
from .platform import EFI

from .i18n import _

import logging
log = logging.getLogger("blivet")

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
        relArch = util.capture_output(["arch"], root=getSysroot()).strip()
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

def parseFSTab(devicetree, chroot=None):
    """ parse /etc/fstab and return a tuple of a mount dict and swap list """
    if not chroot or not os.path.isdir(chroot):
        chroot = getSysroot()

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

def findExistingInstallations(devicetree, teardown_all=True):
    """Find existing GNU/Linux installations on devices from the devicetree.
    :param devicetree: devicetree to find existing installations in
    :type devicetree: :class:`~.devicetree.DeviceTree`
    :param bool teardown_all: whether to tear down all devices in the
                              devicetree in the end
    :return: roots of all found installations
    :rtype: list of :class:`Root`

    """
    try:
        roots = _findExistingInstallations(devicetree)
        return roots
    except Exception: # pylint: disable=broad-except
        log_exception_info(log.info, "failure detecting existing installations")
    finally:
        if teardown_all:
            devicetree.teardownAll()

    return []

def _findExistingInstallations(devicetree):
    if not os.path.exists(getTargetPhysicalRoot()):
        util.makedirs(getTargetPhysicalRoot())

    roots = []
    for device in devicetree.leaves:
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
            util.umount(mountpoint=getSysroot())
            continue

        if not os.access(getSysroot() + "/etc/fstab", os.R_OK):
            util.umount(mountpoint=getSysroot())
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
            elif "linux" in product.lower():
                name = _("%(product)s %(version)s for %(arch)s") % \
                        {"product": product, "version": version, "arch": architecture}
            else:
                name = _("%(product)s Linux %(version)s for %(arch)s") % \
                        {"product": product, "version": version, "arch": architecture}

        (mounts, swaps) = parseFSTab(devicetree, chroot=getSysroot())
        util.umount(mountpoint=getSysroot())
        if not mounts and not swaps:
            # empty /etc/fstab. weird, but I've seen it happen.
            continue
        roots.append(Root(mounts=mounts, swaps=swaps, name=name))

    return roots

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
        if hasattr(fmt, "testMount") and fstype != "auto" and ftype != dtype:
            log.info("fstab says %s at %s is %s", dtype, mountpoint, ftype)
            if fmt.testMount():     # pylint: disable=no-member
                device.format = fmt
            else:
                device.teardown()
                raise FSTabTypeMismatchError("%s: detected as %s, fstab says %s"
                                             % (mountpoint, dtype, ftype))
        del ftype
        del dtype

        if hasattr(device.format, "mountpoint"):
            device.format.mountpoint = mountpoint

        device.format.options = options

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
            chroot = getSysroot()

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
                except (StorageError, blockdev.BlockDevError) as e:
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
        devices.sort(key=lambda d: getattr(d.format, "mountpoint", ""))

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
        devices.sort(key=lambda d: getattr(d.format, "mountpoint", ""))
        devices.reverse()
        for device in devices:
            if (not device.format.mountable) or \
               (device.format.type == "swap" and not swapoff):
                continue

            # Unmount the devices
            device.format.teardown()

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
        dev = "%s/%s" % (getSysroot(), root.path)
        if not os.path.exists("%s/dev/root" %(getSysroot(),)) and os.path.exists(dev):
            rdev = os.stat(dev).st_rdev
            util.eintr_retry_call(os.mknod, "%s/dev/root" % (getSysroot(),), stat.S_IFBLK | 0o600, rdev)

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
        fstab_path = os.path.normpath("%s/etc/fstab" % getSysroot())
        fstab = self.fstab()
        open(fstab_path, "w").write(fstab)

        # /etc/crypttab
        crypttab_path = os.path.normpath("%s/etc/crypttab" % getSysroot())
        crypttab = self.crypttab()
        origmask = os.umask(0o077)
        open(crypttab_path, "w").write(crypttab)
        os.umask(origmask)

        # /etc/mdadm.conf
        mdadm_path = os.path.normpath("%s/etc/mdadm.conf" % getSysroot())
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
        for name in list(self.cryptTab.mappings.keys()):
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
                    if root_on_netdev and mountpoint == "/var":
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

            options = device.format.options or ""

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
        device_name = blockdev.dm.name_from_node(device_name)

    return devicetree.getDeviceByName(device_name)

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

    backupPassphrase = blockdev.crypto.generate_backup_passphrase()

    try:
        escrowDir = getSysroot() + "/root"
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

def mountExistingSystem(fsset, rootDevice, readOnly=None):
    """ Mount filesystems specified in rootDevice's /etc/fstab file. """
    rootPath = getSysroot()

    readOnly = "ro" if readOnly else ""

    if rootDevice.protected and os.path.ismount("/mnt/install/isodir"):
        util.mount("/mnt/install/isodir",
                   rootPath,
                   fstype=rootDevice.format.type,
                   options="bind")
    else:
        rootDevice.setup()
        rootDevice.format.mount(chroot=rootPath,
                                mountpoint="/",
                                options=readOnly)

    fsset.parseFSTab()
    fsset.mountFilesystems(rootPath=rootPath, readOnly=readOnly, skipRoot=True)
