# populator/helpers/boot.py
# Platform-specific boot format helpers for populating a DeviceTree.
#
# Copyright (C) 2009-2015  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from ... import formats
from ... import udev
from ...devices import PartitionDevice, MDRaidArrayDevice

from .formatpopulator import FormatPopulator


class BootFormatPopulator(FormatPopulator):
    priority = 500
    _base_type_specifier = None
    _bootable = False

    @classmethod
    def match(cls, data, device):
        if cls == BootFormatPopulator:
            return False

        fmt = formats.get_format(cls._type_specifier)
        return (udev.device_get_format(data) == cls._base_type_specifier and
                isinstance(device, (PartitionDevice, MDRaidArrayDevice)) and
                (device.bootable or not cls._bootable) and
                fmt.min_size <= device.size <= fmt.max_size)


class EFIFormatPopulator(BootFormatPopulator):
    _type_specifier = "efi"
    _base_type_specifier = "vfat"
    _bootable = True


class MacEFIFormatPopulator(BootFormatPopulator):
    _type_specifier = "macefi"
    _base_type_specifier = "hfsplus"

    @classmethod
    def match(cls, data, device):
        fmt = formats.get_format(cls._type_specifier)
        try:
            return (super(MacEFIFormatPopulator, MacEFIFormatPopulator).match(data, device) and
                    device.disk.format.supports_names and
                    device.parted_partition.name == fmt.name)
        except AttributeError:
            # just in case device.parted_partition has no name attr
            return False


class AppleBootFormatPopulator(BootFormatPopulator):
    _type_specifier = "appleboot"
    _base_type_specifier = "hfs"
    _bootable = True
