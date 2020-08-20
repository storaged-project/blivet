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

import gi
import os

gi.require_version("BlockDev", "2.0")
from gi.repository import BlockDev as blockdev

from ..storage_log import log_exception_info, log_method_call
import parted
import _ped
from ..errors import DiskLabelCommitError, InvalidDiskLabelError, AlignmentError
from .. import arch
from ..events.manager import event_manager
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
    _default_label_type = None

    def __init__(self, **kwargs):
        """
            :keyword device: full path to the block device node
            :type device: str
            :keyword str uuid: disklabel UUID
            :keyword label_type: type of disklabel to create
            :type label_type: str
            :keyword exists: whether the formatting exists
            :type exists: bool
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        self._label_type = ""
        if not self.exists:
            self._label_type = kwargs.get("label_type") or ""

        self._size = Size(0)

        self._parted_device = None
        self._parted_disk = None
        self._orig_parted_disk = None
        self._supported = True

        self._disk_label_alignment = None
        self._minimal_alignment = None
        self._optimal_alignment = None

        if self.parted_device:
            # set up the parted objects and raise exception on failure
            try:
                self.update_orig_parted_disk()
            except Exception as e:  # pylint: disable=broad-except
                self._supported = False
                self._label_type = kwargs.get("label_type") or ""
                log.warning("error setting up disklabel object on %s: %s", self.device, str(e))

    def __deepcopy__(self, memo):
        """ Create a deep copy of a Disklabel instance.

            We can't do copy.deepcopy on parted objects, which is okay.
        """
        return util.variable_copy(self, memo,
                                  shallow=('_parted_device', '_optimal_alignment', '_minimal_alignment',
                                           '_disk_label_alignment'),
                                  duplicate=('_parted_disk', '_orig_parted_disk'))

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        if flags.testing:
            return s
        s += ("  type = %(type)s  partition count = %(count)s"
              "  sector_size = %(sector_size)s\n"
              "  align_offset = %(offset)s  align_grain = %(grain)s\n"
              "  parted_disk = %(disk)s\n"
              "  orig_parted_disk = %(orig_disk)r\n"
              "  parted_device = %(dev)s\n" %
              {"type": self.label_type, "count": len(self.partitions),
               "sector_size": self.sector_size,
               "offset": self.get_alignment().offset,
               "grain": self.get_alignment().grainSize,
               "disk": self.parted_disk, "orig_disk": self._orig_parted_disk,
               "dev": self.parted_device})
        return s

    @property
    def desc(self):
        return "%s %s" % (self.label_type, self.type)

    @property
    def dict(self):
        d = super(DiskLabel, self).dict
        if flags.testing:
            return d

        d.update({"label_type": self.label_type,
                  "partition_count": len(self.partitions),
                  "sector_size": self.sector_size,
                  "offset": self.get_alignment().offset,
                  "grain_size": self.get_alignment().grainSize})
        return d

    @property
    def supported(self):
        return self._supported

    def update_parted_disk(self):
        """ re-read the disklabel from the device """
        self._parted_disk = None
        mask = event_manager.add_mask(device=os.path.basename(self.device), partitions=True)
        self.update_orig_parted_disk()
        udev.settle()
        event_manager.remove_mask(mask)

    def update_orig_parted_disk(self):
        self._orig_parted_disk = self.parted_disk.duplicate()

    def reset_parted_disk(self):
        """ Set this instance's parted_disk to reflect the disk's contents. """
        log_method_call(self, device=self.device)
        self._parted_disk = self._orig_parted_disk

    def fresh_parted_disk(self):
        """ Return a new, empty parted.Disk instance for this device. """
        log_method_call(self, device=self.device, label_type=self.label_type)
        return parted.freshDisk(device=self.parted_device, ty=self.label_type)

    @property
    def parted_disk(self):
        if not self.parted_device:
            return None

        if not self._parted_disk and self.supported:
            if self.exists:
                try:
                    self._parted_disk = parted.Disk(device=self.parted_device)
                except (_ped.DiskLabelException, _ped.IOException, NotImplementedError):
                    self._supported = False
                    return None

                if self._parted_disk.type == "loop":
                    # When the device has no partition table but it has a FS,
                    # it will be created with label type loop.  Treat the
                    # same as if the device had no label (cause it really
                    # doesn't).
                    raise InvalidDiskLabelError()
            else:
                self._parted_disk = self.fresh_parted_disk()

            # turn off cylinder alignment
            if self._parted_disk.isFlagAvailable(parted.DISK_CYLINDER_ALIGNMENT):
                self._parted_disk.unsetFlag(parted.DISK_CYLINDER_ALIGNMENT)

            # Set the boot flag on the GPT PMBR, this helps some BIOS systems boot
            if self._parted_disk.isFlagAvailable(parted.DISK_GPT_PMBR_BOOT):
                # MAC can boot as EFI or as BIOS, neither should have PMBR boot set
                if arch.is_efi() or arch.is_mactel():
                    self._parted_disk.unsetFlag(parted.DISK_GPT_PMBR_BOOT)
                    log.debug("Clear pmbr_boot on %s", self._parted_disk)
                else:
                    self._parted_disk.setFlag(parted.DISK_GPT_PMBR_BOOT)
                    log.debug("Set pmbr_boot on %s", self._parted_disk)
            else:
                log.debug("Did not change pmbr_boot on %s", self._parted_disk)

            udev.settle(quiet=True)
        return self._parted_disk

    @property
    def parted_device(self):
        if not self._parted_device and self.device:
            if os.path.exists(self.device):
                # We aren't guaranteed to be able to get a device.  In
                # particular, built-in USB flash readers show up as devices but
                # do not always have any media present, so parted won't be able
                # to find a device.
                try:
                    self._parted_device = parted.Device(path=self.device)
                except (_ped.IOException, _ped.DeviceException) as e:
                    log.error("DiskLabel.parted_device: Parted exception: %s", e)
            else:
                log.info("DiskLabel.parted_device: %s does not exist", self.device)

        if not self._parted_device:
            log.info("DiskLabel.parted_device returning None")
        return self._parted_device

    @classmethod
    def get_platform_label_types(cls):
        label_types = ["msdos", "gpt"]
        if arch.is_pmac():
            label_types = ["mac"]
        elif arch.is_aarch64():
            label_types = ["gpt", "msdos"]
        elif arch.is_efi() and arch.is_arm():
            label_types = ["msdos", "gpt"]
        elif arch.is_efi() and not arch.is_aarch64():
            label_types = ["gpt", "msdos"]
        elif arch.is_s390():
            label_types += ["dasd"]

        return label_types

    @classmethod
    def set_default_label_type(cls, labeltype):
        cls._default_label_type = labeltype
        log.debug("default disklabel has been set to %s", labeltype)

    def _label_type_size_check(self, label_type):
        if self.parted_device is None:
            return False

        label = parted.freshDisk(device=self.parted_device, ty=label_type)
        return self.parted_device.length < label.maxPartitionStartSector

    def _get_best_label_type(self):
        label_type = self._default_label_type
        label_types = self.get_platform_label_types()[:]
        if label_type in label_types:
            label_types.remove(label_type)
        if label_type:
            label_types.insert(0, label_type)

        if arch.is_s390():
            if blockdev.s390.dasd_is_fba(self.device):
                # the device is FBA DASD
                return "msdos"
            elif self.parted_device.type == parted.DEVICE_DASD:
                # the device is DASD
                return "dasd"
            elif util.detect_virt():
                # check for dasds exported into qemu as normal virtio/scsi disks
                try:
                    _parted_disk = parted.Disk(device=self.parted_device)
                except (_ped.DiskLabelException, _ped.IOException, NotImplementedError):
                    pass
                else:
                    if _parted_disk.type == "dasd":
                        return "dasd"

        for lt in label_types:
            if self._label_type_size_check(lt):
                log.debug("selecting %s disklabel for %s based on size",
                          label_type, os.path.basename(self.device))
                label_type = lt
                break

        return label_type

    @property
    def label_type(self):
        """ The disklabel type (eg: 'gpt', 'msdos') """
        if not self.supported:
            return self._label_type

        # For new disklabels, user-specified type overrides built-in logic.
        # XXX This determines the type we pass to parted.Disk
        if not self.exists and not self._parted_disk:
            if self._label_type:
                lt = self._label_type
            else:
                lt = self._get_best_label_type()

            return lt

        try:
            lt = self.parted_disk.type
        except Exception:  # pylint: disable=broad-except
            log_exception_info()
            lt = self._label_type
        return lt

    @property
    def sector_size(self):
        try:
            return Size(self.parted_device.sectorSize)
        except AttributeError:
            log_exception_info()
            return None

    @property
    def name(self):
        if self.supported:
            _str = "%(name)s (%(type)s)"
        else:
            # Translators: Name for an unsupported disklabel; e.g. "Unsupported partition table"
            _str = _("Unsupported %(name)s")

        return _str % {"name": _(self._name), "type": self.label_type.upper()}

    @property
    def size(self):
        size = self._size
        if not size:
            try:
                size = Size(self.parted_device.getLength(unit="B"))
            except Exception:  # pylint: disable=broad-except
                log_exception_info()
                size = Size(0)

        return size

    @property
    def status(self):
        """ Device status. """
        return False

    @property
    def supports_names(self):
        if not self.supported or not self.parted_disk:
            return False

        return self.parted_disk.supportsFeature(parted.DISK_TYPE_PARTITION_NAME)

    def _create(self, **kwargs):
        """ Create the device. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        # We're relying on someone having called reset_parted_disk -- we
        # could ensure a fresh disklabel by setting self._parted_disk to
        # None right before calling self.commit(), but that might hide
        # other problems.
        self.commit()

    def commit(self):
        """ Commit the current partition table to disk and notify the OS. """
        log_method_call(self, device=self.device,
                        numparts=len(self.partitions))
        try:
            self.parted_disk.commit()
        except parted.DiskException as msg:
            raise DiskLabelCommitError(msg)
        else:
            self.update_orig_parted_disk()
            udev.settle()

    def commit_to_disk(self):
        """ Commit the current partition table to disk. """
        log_method_call(self, device=self.device,
                        numparts=len(self.partitions))
        try:
            self.parted_disk.commitToDevice()
        except parted.DiskException as msg:
            raise DiskLabelCommitError(msg)
        else:
            self.update_orig_parted_disk()

    def add_partition(self, start, end, ptype=None):
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
            extended = self.extended_partition
            if extended and extended.geometry.contains(start):
                ptype = parted.PARTITION_LOGICAL
            else:
                ptype = parted.PARTITION_NORMAL

        geometry = parted.Geometry(device=self.parted_device,
                                   start=start, end=end)
        new_partition = parted.Partition(disk=self.parted_disk,
                                         type=ptype,
                                         geometry=geometry)

        constraint = parted.Constraint(exactGeom=geometry)
        self.parted_disk.addPartition(partition=new_partition,
                                      constraint=constraint)

    def remove_partition(self, partition):
        """ Remove a partition from the disklabel.

            :param partition: the partition to remove
            :type partition: :class:`parted.Partition`
        """
        self.parted_disk.removePartition(partition)

    @property
    def extended_partition(self):
        try:
            extended = self.parted_disk.getExtendedPartition()
        except Exception:  # pylint: disable=broad-except
            log_exception_info()
            extended = None
        return extended

    @property
    def logical_partitions(self):
        try:
            logicals = self.parted_disk.getLogicalPartitions()
        except Exception:  # pylint: disable=broad-except
            log_exception_info()
            logicals = []
        return logicals

    @property
    def primary_partitions(self):
        try:
            primaries = self.parted_disk.getPrimaryPartitions()
        except Exception:  # pylint: disable=broad-except
            log_exception_info()
            primaries = []
        return primaries

    @property
    def first_partition(self):
        try:
            part = self.parted_disk.getFirstPartition()
        except Exception:  # pylint: disable=broad-except
            log_exception_info()
            part = None
        return part

    @property
    def partitions(self):
        return getattr(self.parted_disk, "partitions", [])

    def _get_disk_label_alignment(self):
        """ Return the disklabel's required alignment for new partitions.

            :rtype: :class:`parted.Alignment`
        """
        if not self._disk_label_alignment:
            try:
                self._disk_label_alignment = self.parted_disk.partitionAlignment
            except (_ped.CreateException, AttributeError):
                self._disk_label_alignment = parted.Alignment(offset=0,
                                                              grainSize=1)

        return self._disk_label_alignment

    def get_minimal_alignment(self):
        """ Return the device's minimal alignment for new partitions.

            :rtype: :class:`parted.Alignment`
        """
        if not self._minimal_alignment:
            disklabel_alignment = self._get_disk_label_alignment()
            try:
                minimal_alignment = self.parted_device.minimumAlignment
            except (_ped.CreateException, AttributeError):
                # handle this in the same place we'd handle an ArithmeticError
                minimal_alignment = None

            try:
                alignment = minimal_alignment.intersect(disklabel_alignment)
            except (ArithmeticError, AttributeError):
                alignment = disklabel_alignment

            self._minimal_alignment = alignment

        return self._minimal_alignment

    def get_optimal_alignment(self):
        """ Return the device's optimal alignment for new partitions.

            :rtype: :class:`parted.Alignment`

            .. note::

                If there is no device-supplied optimal alignment this method
                returns the minimal device alignment.
        """
        if not self._optimal_alignment:
            disklabel_alignment = self._get_disk_label_alignment()
            try:
                optimal_alignment = self.parted_device.optimumAlignment
            except (_ped.CreateException, AttributeError):
                # if there is no optimal alignment, use the minimal alignment,
                # which has already been intersected with the disklabel
                # alignment
                alignment = self.get_minimal_alignment()
            else:
                try:
                    alignment = optimal_alignment.intersect(disklabel_alignment)
                except ArithmeticError:
                    alignment = disklabel_alignment

            self._optimal_alignment = alignment

        return self._optimal_alignment

    def get_alignment(self, size=None):
        """ Return an appropriate alignment for a new partition.

            :keyword size: proposed partition size (optional)
            :type size: :class:`~.size.Size`
            :returns: the appropriate alignment to use
            :rtype: :class:`parted.Alignment`
            :raises :class:`~.errors.AlignmentError`: if the partition is too
                                                         small to be aligned
        """
        # default to the optimal alignment
        alignment = self.get_optimal_alignment()
        if size is None:
            return alignment

        # use the minimal alignment if the requested size is smaller than the
        # optimal io size
        minimal_alignment = self.get_minimal_alignment()
        optimal_grain_size = Size(alignment.grainSize * self.sector_size)
        minimal_grain_size = Size(minimal_alignment.grainSize * self.sector_size)
        if size < minimal_grain_size:
            raise AlignmentError("requested size cannot be aligned")
        elif size < optimal_grain_size:
            alignment = minimal_alignment

        return alignment

    def get_end_alignment(self, size=None, alignment=None):
        """ Return an appropriate end-alignment for a new partition.

            :keyword size: proposed partition size (optional)
            :type size: :class:`~.size.Size`
            :keyword alignment: the start alignment (optional)
            :type alignment: :class:`parted.Alignment`
            :returns: the appropriate alignment to use
            :rtype: :class:`parted.Alignment`
            :raises :class:`~.errors.AlignmentError`: if the partition is too
                                                         small to be aligned
        """
        if alignment is None:
            alignment = self.get_alignment(size=size)

        return parted.Alignment(offset=alignment.offset - 1,
                                grainSize=alignment.grainSize)

    @property
    def alignment(self):
        return self.get_alignment()

    @property
    def end_alignment(self):
        return self.get_end_alignment()

    @property
    def free(self):
        if self.parted_disk is not None:
            free_areas = self.parted_disk.getFreeSpacePartitions()
        else:
            free_areas = []

        return sum((Size(f.getLength(unit="B")) for f in free_areas), Size(0))

    @property
    def magic_partition_number(self):
        """ Number of disklabel-type-specific special partition. """
        if self.label_type == "mac":
            return 1
        elif self.label_type == "sun":
            return 3
        else:
            return 0


register_device_format(DiskLabel)
