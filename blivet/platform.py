#
# platform.py:  Architecture-specific information
#
# Copyright (C) 2009-2011
# Red Hat, Inc.  All rights reserved.
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
# Authors: Chris Lumens <clumens@redhat.com>
#
import logging
log = logging.getLogger("blivet")

import parted

from . import arch
from .devicelibs import raid
from .flags import flags
from .partspec import PartSpec
from .size import Size
from .i18n import _, N_


class Platform(object):

    """Platform

       A class containing platform-specific information and methods for use
       during installation.  The intent is to eventually encapsulate all the
       architecture quirks in one place to avoid lots of platform checks
       throughout anaconda."""
    _packages = []

    # requirements for bootloader stage1 devices
    _boot_stage1_device_types = []
    _boot_stage1_format_types = []
    _boot_stage1_mountpoints = []
    _boot_stage1_max_end = None
    _boot_stage1_raid_levels = []
    _boot_stage1_raid_metadata = []
    _boot_stage1_raid_member_types = []
    _boot_stage1_description = N_("bootloader device")
    _boot_stage1_missing_error = ""
    _boot_raid_description = N_("RAID Device")
    _boot_partition_description = N_("First sector of boot partition")
    _boot_descriptions = {}

    _disklabel_types = []
    _non_linux_format_types = []

    def __init__(self):
        """Creates a new Platform object.  This is basically an abstract class.
           You should instead use one of the platform-specific classes as
           returned by get_platform below.  Not all subclasses need to provide
           all the methods in this class."""

        self.update_from_flags()

    def update_from_flags(self):
        if flags.gpt:
            if not self.set_default_disklabel_type("gpt"):
                log.warn("GPT is not a supported disklabel on this platform. Using default "
                         "disklabel %s instead.", self.default_disklabel_type)

    def __call__(self):
        return self

    @property
    def disklabel_types(self):
        """A list of valid disklabel types for this architecture."""
        return self._disklabel_types

    @property
    def default_disklabel_type(self):
        """The default disklabel type for this architecture."""
        return self.disklabel_types[0]

    def set_default_disklabel_type(self, disklabel):
        """Make the disklabel the default

           :param str disklabel: The disklabel type to set as default
           :returns: True if successful False if disklabel not supported

           If the disklabel is not supported on the platform it will return
           False and make no change to the disklabel list.

           If it is supported it will move it to the start of the list,
           making it the default.
        """
        if disklabel not in self._disklabel_types:
            return False

        self._disklabel_types.remove(disklabel)
        self._disklabel_types.insert(0, disklabel)
        log.debug("Default disklabel has been set to %s", disklabel)
        return True

    @property
    def boot_stage1_constraint_dict(self):
        d = {"device_types": self._boot_stage1_device_types,
             "format_types": self._boot_stage1_format_types,
             "mountpoints": self._boot_stage1_mountpoints,
             "max_end": self._boot_stage1_max_end,
             "raid_levels": self._boot_stage1_raid_levels,
             "raid_metadata": self._boot_stage1_raid_metadata,
             "raid_member_types": self._boot_stage1_raid_member_types,
             "descriptions": dict((k, _(v)) for k, v in self._boot_descriptions.items())}
        return d

    def required_disklabel_type(self, device_type):
        # pylint: disable=unused-argument
        return None

    def best_disklabel_type(self, device):
        """The best disklabel type for the specified device."""
        if flags.testing:
            return self.default_disklabel_type

        parted_device = parted.Device(path=device.path)

        # if there's a required type for this device type, use that
        label_type = self.required_disklabel_type(parted_device.type)
        log.debug("required disklabel type for %s (%s) is %s",
                  device.name, parted_device.type, label_type)
        if not label_type:
            # otherwise, use the first supported type for this platform
            # that is large enough to address the whole device
            label_type = self.default_disklabel_type
            log.debug("default disklabel type for %s is %s", device.name,
                      label_type)
            for lt in self.disklabel_types:
                l = parted.freshDisk(device=parted_device, ty=lt)
                if l.maxPartitionStartSector > parted_device.length:
                    label_type = lt
                    log.debug("selecting %s disklabel for %s based on size",
                              label_type, device.name)
                    break

        return label_type

    @property
    def packages(self):
        _packages = self._packages
        if flags.boot_cmdline.get('fips', None) == '1':
            _packages.append('dracut-fips')
        return _packages

    def set_platform_bootloader_reqs(self):
        """Return the required platform-specific bootloader partition
           information.  These are typically partitions that do not get mounted,
           like biosboot or prepboot, but may also include the /boot/efi
           partition."""
        return []

    def set_platform_boot_partition(self):
        """Return the default /boot partition for this platform."""
        return [PartSpec(mountpoint="/boot", size=Size("500MiB"),
                         weight=self.weight(mountpoint="/boot"))]

    def set_default_partitioning(self):
        """Return the default platform-specific partitioning information."""
        return self.set_platform_bootloader_reqs() + self.set_platform_boot_partition()

    def weight(self, fstype=None, mountpoint=None):
        """ Given an fstype (as a string) or a mountpoint, return an integer
            for the base sorting weight.  This is used to modify the sort
            algorithm for partition requests, mainly to make sure bootable
            partitions and /boot are placed where they need to be."""
        # pylint: disable=unused-argument
        if mountpoint == "/boot":
            return 2000
        else:
            return 0

    @property
    def stage1MissingError(self):
        """A platform-specific error message to be shown if stage1 target
           selection fails."""
        return self._boot_stage1_missing_error


class X86(Platform):
    _boot_stage1_device_types = ["disk"]
    _boot_mbr_description = N_("Master Boot Record")
    _boot_descriptions = {"disk": _boot_mbr_description,
                          "partition": Platform._boot_partition_description,
                          "mdarray": Platform._boot_raid_description}

    _disklabel_types = ["msdos", "gpt"]
    # XXX hpfs, if reported by blkid/udev, will end up with a type of None
    _non_linux_format_types = ["vfat", "ntfs", "hpfs"]
    _boot_stage1_missing_error = N_("You must include at least one MBR- or "
                                    "GPT-formatted disk as an install target.")

    def __init__(self):
        super(X86, self).__init__()

    def set_platform_bootloader_reqs(self):
        """Return the default platform-specific partitioning information."""
        ret = Platform.set_platform_bootloader_reqs(self)
        ret.append(PartSpec(fstype="biosboot", size=Size("1MiB"),
                            weight=self.weight(fstype="biosboot")))
        return ret

    def weight(self, fstype=None, mountpoint=None):
        score = Platform.weight(self, fstype=fstype, mountpoint=mountpoint)
        if score:
            return score
        elif fstype == "biosboot":
            return 5000
        else:
            return 0


class EFI(Platform):

    _boot_stage1_format_types = ["efi"]
    _boot_stage1_device_types = ["partition", "mdarray"]
    _boot_stage1_mountpoints = ["/boot/efi"]
    _boot_stage1_raid_levels = [raid.RAID1]
    _boot_stage1_raid_metadata = ["1.0"]
    _boot_efi_description = N_("EFI System Partition")
    _boot_descriptions = {"partition": _boot_efi_description,
                          "mdarray": Platform._boot_raid_description}

    _disklabel_types = ["gpt"]
    # XXX hpfs, if reported by blkid/udev, will end up with a type of None
    _non_linux_format_types = ["vfat", "ntfs", "hpfs"]
    _boot_stage1_missing_error = N_("For a UEFI installation, you must include "
                                    "an EFI System Partition on a GPT-formatted "
                                    "disk, mounted at /boot/efi.")

    def set_platform_bootloader_reqs(self):
        ret = Platform.set_platform_bootloader_reqs(self)
        ret.append(PartSpec(mountpoint="/boot/efi", fstype="efi",
                            size=Size("20MiB"), max_size=Size("200MiB"),
                            grow=True, weight=self.weight(fstype="efi")))
        return ret

    def weight(self, fstype=None, mountpoint=None):
        score = Platform.weight(self, fstype=fstype, mountpoint=mountpoint)
        if score:
            return score
        elif fstype == "efi" or mountpoint == "/boot/efi":
            return 5000
        else:
            return 0


class MacEFI(EFI):
    _boot_stage1_format_types = ["macefi"]
    _boot_efi_description = N_("Apple EFI Boot Partition")
    _non_linux_format_types = ["macefi"]
    _packages = ["mactel-boot"]

    def set_platform_bootloader_reqs(self):
        ret = Platform.set_platform_bootloader_reqs(self)
        ret.append(PartSpec(mountpoint="/boot/efi", fstype="macefi",
                            size=Size("20MiB"), max_size=Size("200MiB"),
                            grow=True, weight=self.weight(mountpoint="/boot/efi")))
        return ret


class Aarch64EFI(EFI):
    _non_linux_format_types = ["vfat", "ntfs"]


class PPC(Platform):
    _ppc_machine = arch.get_ppc_machine()
    _boot_stage1_device_types = ["partition"]

    @property
    def ppc_machine(self):
        return self._ppc_machine


class IPSeriesPPC(PPC):
    _boot_stage1_format_types = ["prepboot"]
    _boot_stage1_max_end = Size("4 GiB")
    _boot_prep_description = N_("PReP Boot Partition")
    _boot_descriptions = {"partition": _boot_prep_description}
    _disklabel_types = ["msdos", "gpt"]
    _boot_stage1_missing_error = N_("You must include a PReP Boot Partition "
                                    "within the first 4GiB of an MBR- "
                                    "or GPT-formatted disk.")

    def set_platform_bootloader_reqs(self):
        ret = PPC.set_platform_bootloader_reqs(self)
        ret.append(PartSpec(fstype="prepboot", size=Size("4MiB"),
                            weight=self.weight(fstype="prepboot")))
        return ret

    def weight(self, fstype=None, mountpoint=None):
        score = Platform.weight(self, fstype=fstype, mountpoint=mountpoint)
        if score:
            return score
        elif fstype == "prepboot":
            return 5000
        else:
            return 0


class NewWorldPPC(PPC):
    _boot_stage1_format_types = ["appleboot"]
    _boot_apple_description = N_("Apple Bootstrap Partition")
    _boot_descriptions = {"partition": _boot_apple_description}
    _disklabel_types = ["mac"]
    _non_linux_format_types = ["hfs", "hfs+"]
    _boot_stage1_missing_error = N_("You must include an Apple Bootstrap "
                                    "Partition on an Apple Partition Map-"
                                    "formatted disk.")

    def set_platform_bootloader_reqs(self):
        ret = Platform.set_platform_bootloader_reqs(self)
        ret.append(PartSpec(fstype="appleboot", size=Size("1MiB"),
                            weight=self.weight(fstype="appleboot")))
        return ret

    def weight(self, fstype=None, mountpoint=None):
        score = Platform.weight(self, fstype=fstype, mountpoint=mountpoint)
        if score:
            return score
        elif fstype == "appleboot":
            return 5000
        else:
            return 0


class PS3(PPC):
    pass


class S390(Platform):
    _packages = ["s390utils"]
    _disklabel_types = ["msdos", "dasd"]
    _boot_stage1_device_types = ["disk", "partition"]
    _boot_dasd_description = N_("DASD")
    _boot_mbr_description = N_("Master Boot Record")
    _boot_zfcp_description = N_("zFCP")
    _boot_descriptions = {"dasd": _boot_dasd_description,
                          "zfcp": _boot_zfcp_description,
                          "disk": _boot_mbr_description,
                          "partition": Platform._boot_partition_description}
    _boot_stage1_missing_error = N_("You must include at least one MBR- or "
                                    "DASD-formatted disk as an install target.")

    def __init__(self):
        Platform.__init__(self)

    def set_platform_boot_partition(self):
        """Return the default platform-specific partitioning information."""
        return [PartSpec(mountpoint="/boot", size=Size("500MiB"),
                         weight=self.weight(mountpoint="/boot"), lv=False)]

    def required_disklabel_type(self, device_type):
        """The required disklabel type for the specified device type."""
        if device_type == parted.DEVICE_DASD:
            return "dasd"

        return super(S390, self).required_disklabel_type(device_type)


class ARM(Platform):
    _arm_machine = None
    _boot_stage1_device_types = ["disk"]
    _boot_mbr_description = N_("Master Boot Record")
    _boot_descriptions = {"disk": _boot_mbr_description,
                          "partition": Platform._boot_partition_description}

    _disklabel_types = ["msdos"]
    _boot_stage1_missing_error = N_("You must include at least one MBR-formatted "
                                    "disk as an install target.")

    @property
    def arm_machine(self):
        if not self._arm_machine:
            self._arm_machine = arch.get_arm_machine()
        return self._arm_machine

    def weight(self, fstype=None, mountpoint=None):
        """Return the ARM platform-specific weight for the / partition.
           On ARM images '/' must be the last partition, so we try to
           weight it accordingly."""
        if mountpoint == "/":
            return -100
        else:
            return Platform.weight(self, fstype=fstype, mountpoint=mountpoint)


class omapARM(ARM):
    _boot_stage1_format_types = ["vfat"]
    _boot_stage1_device_types = ["partition"]
    _boot_stage1_mountpoints = ["/boot/uboot"]
    _boot_uboot_description = N_("U-Boot Partition")
    _boot_descriptions = {"partition": _boot_uboot_description}
    _boot_stage1_missing_error = N_("You must include a U-Boot Partition on a "
                                    "FAT-formatted disk, mounted at /boot/uboot.")

    def set_platform_bootloader_reqs(self):
        """Return the ARM-OMAP platform-specific partitioning information."""
        ret = [PartSpec(mountpoint="/boot/uboot", fstype="vfat",
                        size=Size("20MiB"), max_size=Size("200MiB"),
                        grow=True,
                        weight=self.weight(fstype="vfat", mountpoint="/boot/uboot"))]
        return ret

    def set_default_partitioning(self):
        ret = ARM.set_default_partitioning(self)
        ret.append(PartSpec(mountpoint="/", fstype="ext4",
                            size=Size("2GiB"), max_size=Size("3GiB"),
                            weight=self.weight(mountpoint="/")))
        return ret

    def weight(self, fstype=None, mountpoint=None):
        """Return the ARM-OMAP platform-specific weights for the uboot
           and / partitions.  On OMAP, uboot must be the first partition,
           and '/' must be the last partition, so we try to weight them
           accordingly."""
        if fstype == "vfat" and mountpoint == "/boot/uboot":
            return 6000
        elif mountpoint == "/":
            return -100
        else:
            return Platform.weight(self, fstype=fstype, mountpoint=mountpoint)


def get_platform():
    """Check the architecture of the system and return an instance of a
       Platform subclass to match.  If the architecture could not be determined,
       raise an exception."""
    if arch.is_ppc():
        ppc_machine = arch.get_ppc_machine()

        if (ppc_machine == "PMac" and arch.get_ppc_mac_gen() == "NewWorld"):
            return NewWorldPPC()
        elif ppc_machine in ["iSeries", "pSeries"]:
            return IPSeriesPPC()
        elif ppc_machine == "PS3":
            return PS3()
        else:
            raise SystemError("Unsupported PPC machine type: %s" % ppc_machine)
    elif arch.is_s390():
        return S390()
    elif arch.is_efi():
        if arch.is_mactel():
            return MacEFI()
        elif arch.is_aarch64():
            return Aarch64EFI()
        else:
            return EFI()
    elif arch.is_x86():
        return X86()
    elif arch.is_arm():
        arm_machine = arch.get_arm_machine()
        if arm_machine == "omap":
            return omapARM()
        else:
            return ARM()
    else:
        raise SystemError("Could not determine system architecture.")

platform = get_platform()
