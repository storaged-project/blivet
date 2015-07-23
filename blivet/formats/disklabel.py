# disklabel.py
# Device format classes for anaconda's storage configuration module.
#
# Copyright (C) 2009  Red Hat, Inc.
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

from ..storage_log import log_exception_info, log_method_call
import parted
import _ped
from ..errors import DiskLabelCommitError, InvalidDiskLabelError
from .. import arch
from .. import udev
from .. import util
from ..flags import flags
from ..i18n import _, N_
from . import DeviceFormat, register_device_format
from ..size import Size

import logging
log = logging.getLogger("blivet")


class DiskLabel(DeviceFormat):
    """ Disklabel """
    _type = "disklabel"
    _name = N_("partition table")
    _formattable = True                # can be formatted

    def __init__(self, **kwargs):
        """
            :keyword device: full path to the block device node
            :type device: str
            :keyword labelType: type of disklabel to create
            :type labelType: str
            :keyword exists: whether the formatting exists
            :type exists: bool
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        if not self.exists:
            self._labelType = kwargs.get("labelType", "msdos")
        else:
            self._labelType = ""

        self._size = Size(0)

        self._partedDevice = None
        self._partedDisk = None
        self._origPartedDisk = None
        self._alignment = None
        self._endAlignment = None

        if self.partedDevice:
            # set up the parted objects and raise exception on failure
            self.updateOrigPartedDisk()

    def __deepcopy__(self, memo):
        """ Create a deep copy of a Disklabel instance.

            We can't do copy.deepcopy on parted objects, which is okay.
        """
        return util.variable_copy(self, memo,
           shallow=('_partedDevice', '_alignment', '_endAlignment'),
           duplicate=('_partedDisk', '_origPartedDisk'))

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        if flags.testing:
            return s
        s += ("  type = %(type)s  partition count = %(count)s"
              "  sectorSize = %(sectorSize)s\n"
              "  align_offset = %(offset)s  align_grain = %(grain)s\n"
              "  partedDisk = %(disk)s\n"
              "  origPartedDisk = %(orig_disk)r\n"
              "  partedDevice = %(dev)s\n" %
              {"type": self.labelType, "count": len(self.partitions),
               "sectorSize": self.sectorSize,
               "offset": self.alignment.offset,
               "grain": self.alignment.grainSize,
               "disk": self.partedDisk, "orig_disk": self._origPartedDisk,
               "dev": self.partedDevice})
        return s

    @property
    def desc(self):
        return "%s %s" % (self.labelType, self.type)

    @property
    def dict(self):
        d = super(DiskLabel, self).dict
        if flags.testing:
            return d

        d.update({"labelType": self.labelType,
                  "partitionCount": len(self.partitions),
                  "sectorSize": self.sectorSize,
                  "offset": self.alignment.offset,
                  "grainSize": self.alignment.grainSize})
        return d

    def updateOrigPartedDisk(self):
        self._origPartedDisk = self.partedDisk.duplicate()

    def resetPartedDisk(self):
        """ Set this instance's partedDisk to reflect the disk's contents. """
        log_method_call(self, device=self.device)
        self._partedDisk = self._origPartedDisk

    def freshPartedDisk(self):
        """ Return a new, empty parted.Disk instance for this device. """
        log_method_call(self, device=self.device, labelType=self._labelType)
        return parted.freshDisk(device=self.partedDevice, ty=self._labelType)

    @property
    def partedDisk(self):
        if not self._partedDisk:
            if self.exists:
                try:
                    self._partedDisk = parted.Disk(device=self.partedDevice)
                except (_ped.DiskLabelException, _ped.IOException,
                        NotImplementedError) as e:
                    raise InvalidDiskLabelError(e)

                if self._partedDisk.type == "loop":
                    # When the device has no partition table but it has a FS,
                    # it will be created with label type loop.  Treat the
                    # same as if the device had no label (cause it really
                    # doesn't).
                    raise InvalidDiskLabelError()

                # here's where we correct the ctor-supplied disklabel type for
                # preexisting disklabels if the passed type was wrong
                self._labelType = self._partedDisk.type
            else:
                self._partedDisk = self.freshPartedDisk()

            # turn off cylinder alignment
            if self._partedDisk.isFlagAvailable(parted.DISK_CYLINDER_ALIGNMENT):
                self._partedDisk.unsetFlag(parted.DISK_CYLINDER_ALIGNMENT)

            # Set the boot flag on the GPT PMBR, this helps some BIOS systems boot
            if self._partedDisk.isFlagAvailable(parted.DISK_GPT_PMBR_BOOT):
                # MAC can boot as EFI or as BIOS, neither should have PMBR boot set
                if arch.isEfi() or arch.isMactel():
                    self._partedDisk.unsetFlag(parted.DISK_GPT_PMBR_BOOT)
                    log.debug("Clear pmbr_boot on %s", self._partedDisk)
                else:
                    self._partedDisk.setFlag(parted.DISK_GPT_PMBR_BOOT)
                    log.debug("Set pmbr_boot on %s", self._partedDisk)
            else:
                log.debug("Did not change pmbr_boot on %s", self._partedDisk)

        return self._partedDisk

    @property
    def partedDevice(self):
        if not self._partedDevice and self.device:
            if os.path.exists(self.device):
                # We aren't guaranteed to be able to get a device.  In
                # particular, built-in USB flash readers show up as devices but
                # do not always have any media present, so parted won't be able
                # to find a device.
                try:
                    self._partedDevice = parted.Device(path=self.device)
                except (_ped.IOException, _ped.DeviceException) as e:
                    log.error("DiskLabel.partedDevice: Parted exception: %s", e)
            else:
                log.info("DiskLabel.partedDevice: %s does not exist", self.device)

        if not self._partedDevice:
            log.info("DiskLabel.partedDevice returning None")
        return self._partedDevice

    @property
    def labelType(self):
        """ The disklabel type (eg: 'gpt', 'msdos') """
        try:
            lt = self.partedDisk.type
        except Exception: # pylint: disable=broad-except
            log_exception_info()
            lt = self._labelType
        return lt

    @property
    def sectorSize(self):
        try:
            return Size(self.partedDevice.sectorSize)
        except AttributeError:
            log_exception_info()
            return None

    @property
    def name(self):
        return "%s (%s)" % (_(self._name), self.labelType.upper())

    @property
    def size(self):
        size = self._size
        if not size:
            try:
                size = Size(self.partedDevice.getLength(unit="B"))
            except Exception: # pylint: disable=broad-except
                log_exception_info()
                size = Size(0)

        return size

    @property
    def status(self):
        """ Device status. """
        return False

    def _create(self, **kwargs):
        """ Create the device. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        # We're relying on someone having called resetPartedDisk -- we
        # could ensure a fresh disklabel by setting self._partedDisk to
        # None right before calling self.commit(), but that might hide
        # other problems.
        self.commit()

    def _destroy(self, **kwargs):
        """ Wipe the disklabel from the device. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        self.partedDevice.clobber()

    def commit(self):
        """ Commit the current partition table to disk and notify the OS. """
        log_method_call(self, device=self.device,
                        numparts=len(self.partitions))
        try:
            self.partedDisk.commit()
        except parted.DiskException as msg:
            raise DiskLabelCommitError(msg)
        else:
            self.updateOrigPartedDisk()
            udev.settle()

    def commitToDisk(self):
        """ Commit the current partition table to disk. """
        log_method_call(self, device=self.device,
                        numparts=len(self.partitions))
        try:
            self.partedDisk.commitToDevice()
        except parted.DiskException as msg:
            raise DiskLabelCommitError(msg)
        else:
            self.updateOrigPartedDisk()

    def addPartition(self, start, end, ptype=None):
        """ Add a partition to the disklabel.

            :param int start: start sector
            :param int end: end sector
            :param ptype: partition type or None
            :type ptype: int (parted partition type constant) or NoneType

            Partition type will default to either PARTITION_NORMAL or
            PARTITION_LOGICAL, depending on whether the start sector is within
            an extended partition.
        """
        if ptype is None:
            extended = self.extendedPartition
            if extended and extended.geometry.contains(start):
                ptype = parted.PARTITION_LOGICAL
            else:
                ptype = parted.PARTITION_NORMAL

        geometry = parted.Geometry(device=self.partedDevice,
                                   start=start, end=end)
        new_partition = parted.Partition(disk=self.partedDisk,
                                         type=ptype,
                                         geometry=geometry)

        constraint = parted.Constraint(exactGeom=geometry)
        self.partedDisk.addPartition(partition=new_partition,
                                     constraint=constraint)

    def removePartition(self, partition):
        """ Remove a partition from the disklabel.

            :param partition: the partition to remove
            :type partition: :class:`parted.Partition`
        """
        self.partedDisk.removePartition(partition)

    @property
    def extendedPartition(self):
        try:
            extended = self.partedDisk.getExtendedPartition()
        except Exception: # pylint: disable=broad-except
            log_exception_info()
            extended = None
        return extended

    @property
    def logicalPartitions(self):
        try:
            logicals = self.partedDisk.getLogicalPartitions()
        except Exception: # pylint: disable=broad-except
            log_exception_info()
            logicals = []
        return logicals

    @property
    def primaryPartitions(self):
        try:
            primaries = self.partedDisk.getPrimaryPartitions()
        except Exception: # pylint: disable=broad-except
            log_exception_info()
            primaries = []
        return primaries

    @property
    def firstPartition(self):
        try:
            part = self.partedDisk.getFirstPartition()
        except Exception: # pylint: disable=broad-except
            log_exception_info()
            part = None
        return part

    @property
    def partitions(self):
        return self.partedDisk.partitions

    @property
    def alignment(self):
        """ Alignment requirements for this device. """
        if not self._alignment:
            try:
                disklabel_alignment = self.partedDisk.partitionAlignment
            except _ped.CreateException:
                disklabel_alignment = parted.Alignment(offset=0, grainSize=1)

            try:
                optimum_device_alignment = self.partedDevice.optimumAlignment
            except _ped.CreateException:
                optimum_device_alignment = None

            try:
                minimum_device_alignment = self.partedDevice.minimumAlignment
            except _ped.CreateException:
                minimum_device_alignment = None

            try:
                a = optimum_device_alignment.intersect(disklabel_alignment)
            except (ArithmeticError, AttributeError):
                try:
                    a = minimum_device_alignment.intersect(disklabel_alignment)
                except (ArithmeticError, AttributeError):
                    a = disklabel_alignment

            self._alignment = a

        return self._alignment

    @property
    def endAlignment(self):
        if not self._endAlignment:
            self._endAlignment = parted.Alignment(
                                        offset = self.alignment.offset - 1,
                                        grainSize = self.alignment.grainSize)

        return self._endAlignment

    @property
    def free(self):
        return sum((Size(f.getLength(unit="B")) for f in self.partedDisk.getFreeSpacePartitions()), Size(0))

    @property
    def magicPartitionNumber(self):
        """ Number of disklabel-type-specific special partition. """
        if self.labelType == "mac":
            return 1
        elif self.labelType == "sun":
            return 3
        else:
            return 0

register_device_format(DiskLabel)
