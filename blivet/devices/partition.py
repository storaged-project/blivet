# devices/partition.py
#
# Copyright (C) 2009-2014  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

import os
import parted
import _ped

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from .. import errors
from .. import util
from .. import arch
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..formats import DeviceFormat, get_format
from ..size import Size, MiB, ROUND_DOWN

import logging
log = logging.getLogger("blivet")

from .device import Device
from .storage import StorageDevice
from .dm import DMDevice
from .lib import device_path_to_name, device_name_to_disk_by_path, LINUX_SECTOR_SIZE

DEFAULT_PART_SIZE = Size("500MiB")

# in case the default partition size doesn't fit
FALLBACK_DEFAULT_PART_SIZE = Size("256MiB")


class PartitionDevice(StorageDevice):

    """ A disk partition.

        On types and flags...

        We don't need to deal with numerical partition types at all. The
        only type we are concerned with is primary/logical/extended. Usage
        specification is accomplished through the use of flags, which we
        will set according to the partition's format.
    """
    _type = "partition"
    _resizable = True
    default_size = DEFAULT_PART_SIZE

    def __init__(self, name, fmt=None, uuid=None,
                 size=None, grow=False, maxsize=None, start=None, end=None,
                 major=None, minor=None, bootable=None,
                 sysfs_path='', parents=None, exists=False,
                 part_type=None, primary=False, weight=None, disk_tags=None):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class::class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it

            For existing partitions only:

            :keyword str uuid: partition UUID (not filesystem UUID)
            :keyword major: the device major
            :type major: long
            :keyword minor: the device minor
            :type minor: long
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str

            For non-existent partitions only:

            :keyword part_type: parted type constant, eg:
                                :const:`parted.PARTITION_NORMAL`
            :type part_type: parted partition type constant
            :keyword grow: whether or not to grow the partition
            :type grow: bool
            :keyword maxsize: max size for growable partitions
            :type maxsize: :class:`~.size.Size`
            :keyword start: start sector (see note, below)
            :type start: long
            :keyword end: end sector (see note, below)
            :type end: long
            :keyword bootable: whether the partition is bootable
            :type bootable: bool
            :keyword weight: an initial sorting weight to assign
            :type weight: int or NoneType
            :keyword disk_tags: (str) tags defining candidate disk set
            :type disk_tags: iterable

            .. note::

                If a start sector is specified the partition will not be
                adjusted for optimal alignment. That is up to the caller.

            .. note::

                You can only pass one of parents or disk_tags when instantiating
                a non-existent partition. If both disk set and disk tags are
                specified, the explicit disk set will be used.

            .. note::

                Multiple disk tags will be combined using the logical "or" operation.

        """
        self.req_disks = []
        self.req_disk_tags = []
        self.req_part_type = None
        self.req_primary = None
        self.req_grow = None
        self.req_bootable = None
        self.req_size = Size(0)
        self.req_base_size = Size(0)
        self.req_max_size = Size(0)
        self.req_base_weight = 0
        self.req_start_sector = None
        self.req_end_sector = None
        self.req_name = None

        self._bootable = False

        # FIXME: Validate part_type, but only if this is a new partition
        #        Otherwise, overwrite it with the partition's type.
        self._part_type = None
        self._parted_partition = None
        self._orig_path = None

        if not exists and size is None:
            if start is not None and end is not None:
                size = Size(0)
            else:
                size = self.default_size

        StorageDevice.__init__(self, name, fmt=fmt, uuid=uuid, size=size,
                               major=major, minor=minor, exists=exists,
                               sysfs_path=sysfs_path, parents=parents)

        if not exists:
            # this is a request, not a partition -- it has no parents
            self.req_disks = list(self.parents)
            self.parents = []

        # FIXME: Validate size, but only if this is a new partition.
        #        For existing partitions we will get the size from
        #        parted.

        # We can't rely on self.disk.format.supported because self.disk may get reformatted
        # in the course of things.
        self.disklabel_supported = True
        if self.exists and self.disk.partitioned and not self.disk.format.supported:
            log.info("partition %s disklabel is unsupported", self.name)
            self.disklabel_supported = False
        elif self.exists and not flags.testing:
            if not self.disk.partitioned:
                self.disklabel_supported = False
                raise errors.DeviceError("disk has wrong format '%s'" % self.disk.format.type)

            log.debug("looking up parted Partition: %s", self.path)
            self._parted_partition = self.disk.format.parted_disk.getPartitionByPath(self.path)
            if not self._parted_partition:
                self.parents = []
                raise errors.DeviceError("cannot find parted partition instance", self.name)

            self._orig_path = self.path
            # collect information about the partition from parted
            self.probe()
            if self.get_flag(parted.PARTITION_PREP):
                # the only way to identify a PPC PReP Boot partition is to
                # check the partition type/flags, so do it here.
                self.format = get_format("prepboot", device=self.path, exists=True)
            elif self.get_flag(parted.PARTITION_BIOS_GRUB):
                # the only way to identify a BIOS Boot partition is to
                # check the partition type/flags, so do it here.
                self.format = get_format("biosboot", device=self.path, exists=True)
        else:
            # XXX It might be worthwhile to create a shit-simple
            #     PartitionRequest class and pass one to this constructor
            #     for new partitions.
            self.req_disk_tags = list(disk_tags) if disk_tags is not None else list()
            self.req_name = name
            self.req_part_type = part_type
            self.req_primary = primary
            self.req_max_size = Size(util.numeric_type(maxsize))
            self.req_grow = grow
            self.req_bootable = bootable

            # req_size may be manipulated in the course of partitioning
            self.req_size = self._size

            # req_base_size will always remain constant
            self.req_base_size = self._size

            self.req_base_weight = weight

            self.req_start_sector = start
            self.req_end_sector = end

        # update current_size again now when we have parted_partition and
        # information about part_type
        if self.exists and self.status:
            self.update_size()

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  grow = %(grow)s  max size = %(maxsize)s  bootable = %(bootable)s\n"
              "  part type = %(part_type)s  primary = %(primary)s"
              "  start sector = %(start)s  end sector = %(end)s\n"
              "  parted_partition = %(parted_part)s\n"
              "  disk = %(disk)s\n" %
              {"grow": self.req_grow, "maxsize": self.req_max_size,
               "bootable": self.bootable, "part_type": self.part_type,
               "primary": self.req_primary,
               "start": self.req_start_sector, "end": self.req_end_sector,
               "parted_part": self.parted_partition, "disk": self.disk})

        if self.parted_partition:
            s += ("  start = %(start)s  end = %(end)s  length = %(length)s\n"
                  "  flags = %(flags)s" %
                  {"length": self.parted_partition.geometry.length,
                   "start": self.parted_partition.geometry.start,
                   "end": self.parted_partition.geometry.end,
                   "flags": self.parted_partition.getFlagsAsString()})

        return s

    @property
    def dict(self):
        d = super(PartitionDevice, self).dict
        d.update({"type": self.part_type})
        if not self.exists:
            d.update({"grow": self.req_grow, "maxsize": self.req_max_size,
                      "bootable": self.bootable,
                      "primary": self.req_primary})

        if self.parted_partition:
            d.update({"length": self.parted_partition.geometry.length,
                      "start": self.parted_partition.geometry.start,
                      "end": self.parted_partition.geometry.end,
                      "flags": self.parted_partition.getFlagsAsString()})
        return d

    def align_target_size(self, newsize):
        """ Return newsize adjusted to allow for an end-aligned partition.

            :param :class:`~.Size` newsize: proposed/unaligned target size
            :raises _ped.CreateException: if the size extends beyond the end of
                                          the disk
            :returns: newsize modified to yield an end-aligned partition
            :rtype: :class:`~.Size`
        """
        if newsize == Size(0):
            return newsize

        (_constraint, geometry) = self._compute_resize(self.parted_partition,
                                                       newsize=newsize)
        return Size(geometry.getLength(unit="B"))

    def _set_target_size(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if newsize != self.size:
            try:
                aligned = self.align_target_size(newsize)
            except _ped.CreateException:
                # this gets handled in superclass setter, below
                aligned = newsize

            if aligned != newsize:
                raise ValueError("new size will not yield an aligned partition")

            # change this partition's geometry in-memory so that other
            # partitioning operations can complete (e.g., autopart)
            super(PartitionDevice, self)._set_target_size(newsize)
            disk = self.disk.format.parted_disk

            # resize the partition's geometry in memory
            (constraint, geometry) = self._compute_resize(self.parted_partition)
            disk.setPartitionGeometry(partition=self.parted_partition,
                                      constraint=constraint,
                                      start=geometry.start, end=geometry.end)

    @property
    def path(self):
        if not self.parents:
            dev_dir = StorageDevice._dev_dir
        else:
            dev_dir = self.parents[0]._dev_dir

        return "%s/%s" % (dev_dir, self.name)

    @property
    def part_type(self):
        """ Get the partition's type (as parted constant). """
        try:
            ptype = self.parted_partition.type
        except AttributeError:
            ptype = self._part_type

        if not self.exists and ptype is None:
            ptype = self.req_part_type

        return ptype

    @property
    def is_extended(self):
        return (self.part_type is not None and
                self.part_type & parted.PARTITION_EXTENDED)

    @property
    def is_logical(self):
        return (self.part_type is not None and
                self.part_type & parted.PARTITION_LOGICAL)

    @property
    def is_primary(self):
        return (self.part_type is not None and
                self.part_type == parted.PARTITION_NORMAL)

    @property
    def is_protected(self):
        return (self.part_type is not None and
                self.part_type & parted.PARTITION_PROTECTED)

    @property
    def fstab_spec(self):
        spec = self.path
        if self.disk and self.disk.type == 'dasd':
            spec = device_name_to_disk_by_path(self.name)
        elif self.format and self.format.uuid:
            spec = "UUID=%s" % self.format.uuid
        return spec

    def _get_parted_partition(self):
        return self._parted_partition

    def _set_parted_partition(self, partition):
        """ Set this PartitionDevice's parted Partition instance. """
        log_method_call(self, self.name)

        if partition is not None and not isinstance(partition, parted.Partition):
            raise ValueError("partition must be None or a parted.Partition instance")

        log.debug("device %s new parted_partition %s", self.name, partition)
        self._parted_partition = partition
        self.update_name()

    parted_partition = property(lambda d: d._get_parted_partition(),
                                lambda d, p: d._set_parted_partition(p))

    def pre_commit_fixup(self, current_fmt=False):
        """ Re-get self.parted_partition from the original disklabel. """
        log_method_call(self, self.name)
        if not self.exists or not self.disklabel_supported:
            return

        # find the correct partition on the original parted.Disk since the
        # name/number we're now using may no longer match
        if not current_fmt:
            _disklabel = self.disk.original_format
        else:
            _disklabel = self.disk.format

        if self.is_extended:
            # getPartitionBySector doesn't work on extended partitions
            _partition = _disklabel.extended_partition
            log.debug("extended lookup found partition %s",
                      device_path_to_name(getattr(_partition, "path", None) or "(none)"))
        else:
            # lookup the partition by sector to avoid the renumbering
            # nonsense entirely
            _sector = self.parted_partition.geometry.start
            _partition = _disklabel.parted_disk.getPartitionBySector(_sector)
            log.debug("sector-based lookup found partition %s",
                      device_path_to_name(getattr(_partition, "path", None) or "(none)"))

        self.parted_partition = _partition

    def _get_weight(self):
        if isinstance(self.req_base_weight, int):
            return self.req_base_weight

        # now we have the weights for varying mountpoints and fstypes by platform
        weight = 0
        if self.format.mountable and self.format.mountpoint == "/boot":
            weight = 2000
        elif (self.format.mountable and
              self.format.mountpoint == "/boot/efi" and
              self.format.type in ("efi", "macefi") and
              arch.is_efi()):
            weight = 5000
        elif arch.is_x86() and self.format.type == "biosboot" and not arch.is_efi():
            weight = 5000
        elif self.format.mountable and arch.is_arm():
            # On ARM images '/' must be the last partition.
            if self.format.mountpoint == "/":
                weight = -100
        elif arch.is_ppc():
            if arch.is_pmac() and self.format.type == "appleboot":
                weight = 5000
            elif arch.is_ipseries() and self.format.type == "prepboot":
                weight = 5000

        return weight

    def _set_weight(self, weight):
        self.req_base_weight = weight

    weight = property(lambda d: d._get_weight(),
                      lambda d, w: d._set_weight(w))

    def _set_name(self, value):
        self._name = value  # actual name setting is done by parted

    def update_name(self):
        if self.disk and not self.disklabel_supported:
            pass
        elif self.parted_partition is None:
            self.name = self.req_name
        else:
            self.name = device_path_to_name(self.parted_partition.path)

    def depends_on(self, dep):
        """ Return True if this device depends on dep. """
        if isinstance(dep, PartitionDevice) and dep.is_extended and \
           self.is_logical and self.disk == dep.disk:
            return True

        return Device.depends_on(self, dep)

    @property
    def isleaf(self):
        """ True if no other device depends on this one. """
        no_kids = super(PartitionDevice, self).isleaf
        # it is possible that the disk that originally contained this partition
        # no longer contains a disklabel, in which case we can assume that this
        # device is a leaf
        if self.disk and self.parted_partition and \
           self.disk.format.type == "disklabel" and \
           self.parted_partition in self.disk.format.partitions:
            disklabel = self.disk.format
        else:
            disklabel = None

        extended_has_logical = (self.is_extended and
                                (disklabel and disklabel.logical_partitions))
        return (no_kids and not extended_has_logical)

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return self.isleaf and not self.is_extended

    def _set_bootable(self, bootable):
        """ Set the bootable flag for this partition. """
        if self.parted_partition:
            if arch.is_s390():
                return
            if self.flag_available(parted.PARTITION_BOOT):
                if bootable:
                    self.set_flag(parted.PARTITION_BOOT)
                else:
                    self.unset_flag(parted.PARTITION_BOOT)
            else:
                raise errors.DeviceError("boot flag not available for this partition", self.name)

            self._bootable = bootable
        else:
            self.req_bootable = bootable

    def _get_bootable(self):
        return self._bootable or self.req_bootable

    bootable = property(_get_bootable, _set_bootable)

    def flag_available(self, flag):
        if not self.parted_partition:
            return

        return self.parted_partition.isFlagAvailable(flag)

    def get_flag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.parted_partition or not self.flag_available(flag):
            return

        return self.parted_partition.getFlag(flag)

    def set_flag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.parted_partition or not self.flag_available(flag):
            return

        self.parted_partition.setFlag(flag)

    def unset_flag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.parted_partition or not self.flag_available(flag):
            return

        self.parted_partition.unsetFlag(flag)

    @property
    def is_magic(self):
        if not self.disk or not self.disklabel_supported:
            return False

        number = getattr(self.parted_partition, "number", -1)
        magic = self.disk.format.magic_partition_number
        return (number == magic)

    def remove_hook(self, modparent=True):
        if modparent and self.disklabel_supported:
            # if this partition hasn't been allocated it could not have
            # a disk attribute
            if not self.disk:
                return

            if self.parted_partition.type == parted.PARTITION_EXTENDED and \
                    len(self.disk.format.logical_partitions) > 0:
                raise ValueError("Cannot remove extended partition %s.  "
                                 "Logical partitions present." % self.name)

            self.disk.format.remove_partition(self.parted_partition)

        super(PartitionDevice, self).remove_hook(modparent=modparent)

    def add_hook(self, new=True):
        super(PartitionDevice, self).add_hook(new=new)
        if new:
            return

        if not self.disk or not self.parted_partition or \
           self.parted_partition in self.disk.format.partitions:
            return

        self.disk.format.add_partition(self.parted_partition.geometry.start,
                                       self.parted_partition.geometry.end,
                                       self.parted_partition.type)

        # Look up the path by start sector to deal with automatic renumbering of
        # logical partitions on msdos disklabels.
        if self.is_extended:
            partition = self.disk.format.extended_partition
        else:
            start = self.parted_partition.geometry.start
            partition = self.disk.format.parted_disk.getPartitionBySector(start)

        self.parted_partition = partition

    def probe(self):
        """ Probe for any missing information about this device.

            size, partition type, flags
        """
        log_method_call(self, self.name, exists=self.exists)
        if not self.exists or not self.disklabel_supported:
            return

        self._size = Size(self.parted_partition.getLength(unit="B"))
        self.target_size = self._size

        self._part_type = self.parted_partition.type

        self._bootable = self.get_flag(parted.PARTITION_BOOT)

    def _wipe(self):
        """ Wipe the partition metadata.

            Assumes that the partition metadata is located at the start
            of the partition and occupies no more than 1 MiB.

            Erases in block increments. Erases the smallest number of blocks
            such that at least 1 MiB is erased or the whole partition is
            erased.
        """
        log_method_call(self, self.name, status=self.status)

        start = self.parted_partition.geometry.start
        part_len = self.parted_partition.geometry.end - start
        bs = Size(self.parted_partition.geometry.device.sectorSize)

        # Ensure that count is smallest value such that count * bs >= 1 MiB
        (count, rem) = divmod(Size("1 MiB"), bs)
        if rem:
            count += 1

        # Ensure that count <= part_len
        count = min(count, part_len)

        device = self.parted_partition.geometry.device.path
        cmd = ["dd", "if=/dev/zero", "of=%s" % device, "bs=%d" % bs,
               "seek=%d" % start, "count=%d" % count]
        try:
            util.run_program(cmd)
        except OSError as e:
            log.error(str(e))
        finally:
            # If a udev device is created with the watch option, then
            # a change uevent is synthesized and we need to wait for
            # things to settle.
            udev.settle()

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self.disk.format.add_partition(self.parted_partition.geometry.start,
                                       self.parted_partition.geometry.end,
                                       self.parted_partition.type)

        self._wipe()
        try:
            self.disk.format.commit()
        except errors.DiskLabelCommitError:
            part = self.disk.format.parted_disk.getPartitionByPath(self.path)
            self.disk.format.remove_partition(part)
            raise

    def _post_create(self):
        if self.is_extended:
            partition = self.disk.format.extended_partition
        else:
            start = self.parted_partition.geometry.start
            partition = self.disk.format.parted_disk.getPartitionBySector(start)

        log.debug("post-commit partition path is %s", getattr(partition,
                                                              "path", None))
        self.parted_partition = partition
        if not self.is_extended:
            # Ensure old metadata which lived in freespace so did not get
            # explictly destroyed by a destroyformat action gets wiped
            DeviceFormat(device=self.path, exists=True).destroy()

        StorageDevice._post_create(self)

    def _compute_resize(self, partition, newsize=None):
        """ Return a new constraint and end-aligned geometry for new size.

            :param :class:`parted.Partition` partition: the current partition
            :keyword :class:`~.size.Size` newsize: new partition size
            :return: a 2-tuple of constraint and geometry
            :raises _ped.CreateException: if the size extends beyond the end of
                                          the disk
            :raises _ped.CreateException: if newsize is 0

            If newsize is not specified, the current target size will be used.
        """
        log_method_call(self, self.name, status=self.status)

        if newsize is None:
            newsize = self.target_size

        # compute new size for partition
        current_geom = partition.geometry
        current_dev = current_geom.device
        new_len = int(Size(newsize) // Size(current_dev.sectorSize))
        new_geometry = parted.Geometry(device=current_dev,
                                       start=current_geom.start,
                                       length=new_len)
        # and align the end sector
        if new_geometry.length < current_geom.length:
            align = self.disk.format.end_alignment.alignUp
            align_geom = current_geom  # we can align up into the old geometry
        else:
            align = self.disk.format.end_alignment.alignDown
            align_geom = new_geometry

        new_geometry.end = align(align_geom, new_geometry.end)
        constraint = parted.Constraint(exactGeom=new_geometry)

        return (constraint, new_geometry)

    def resize(self):
        log_method_call(self, self.name, status=self.status)
        self._pre_resize()

        # parted_disk has been restored to _orig_parted_disk, so
        # recalculate resize geometry because we may have new
        # partitions on the disk, which could change constraints
        parted_disk = self.disk.format.parted_disk
        partition = parted_disk.getPartitionByPath(self.path)
        (constraint, geometry) = self._compute_resize(partition)

        parted_disk.setPartitionGeometry(partition=partition,
                                         constraint=constraint,
                                         start=geometry.start,
                                         end=geometry.end)

        self.disk.format.commit()
        self.update_size()

    @property
    def protected(self):
        protected = super(PartitionDevice, self).protected

        # extended partition is protected also when one of its logical partitions is protected
        if self.is_extended:
            return protected or any(part.protected for part in self.disk.children if part.is_logical)
        else:
            return protected

    @protected.setter
    def protected(self, value):
        self._protected = value

    @property
    def sector_size(self):
        if self.disk:
            return self.disk.sector_size

        return super(PartitionDevice, self).sector_size

    def _pre_resize(self):
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        # don't teardown when resizing luks
        if self.format.type == "luks" and self.children:
            self.children[0].format.teardown()
        else:
            self.teardown()

        if not self.sysfs_path:
            return

        self.setup_parents(orig=True)

    def _pre_destroy(self):
        StorageDevice._pre_destroy(self)
        if not self.sysfs_path:
            return

        self.setup_parents(orig=True)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        if not self.disklabel_supported:
            return

        # we should have already set self.parted_partition to point to the
        # partition on the original disklabel
        self.disk.original_format.remove_partition(self.parted_partition)
        try:
            self.disk.original_format.commit()
        except errors.DiskLabelCommitError:
            self.disk.original_format.add_partition(
                self.parted_partition.geometry.start,
                self.parted_partition.geometry.end,
                self.parted_partition.type)
            self.parted_partition = self.disk.original_format.parted_disk.getPartitionByPath(self.path)
            raise

        if self.disk.format.exists and \
           self.disk.format.type == "disklabel" and \
           self.disk.format.parted_disk != self.disk.original_format.parted_disk:
            # If the new/current disklabel is the same as the original one, we
            # have to duplicate the removal on the other copy of the DiskLabel.
            part = self.disk.format.parted_disk.getPartitionByPath(self.path)
            self.disk.format.remove_partition(part)
            self.disk.format.commit()

    def _post_destroy(self):
        if not self.disklabel_supported:
            return

        super(PartitionDevice, self)._post_destroy()
        if isinstance(self.disk, DMDevice):
            udev.settle()
            # self.exists has been unset, so don't use self.status
            if os.path.exists(self.path):
                try:
                    blockdev.dm.remove(self.name)
                except blockdev.DMError:
                    pass

    def _get_size(self):
        """ Get the device's size. """
        size = self._size
        if self.parted_partition:
            size = Size(self.parted_partition.getLength(unit="B"))
        return size

    def _set_size(self, newsize):
        """ Set the device's size.

            .. note::

                If you change the size of an allocated-but-not-existing
                partition, you are responsible for calling do_partitioning to
                reallocate it with the new size.

        """
        log_method_call(self, self.name,
                        status=self.status, size=self._size, newsize=newsize)
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        super(PartitionDevice, self)._set_size(newsize)
        if not self.exists:
            # also update size fields used for partition allocation
            self.req_size = newsize
            self.req_base_size = newsize

    def _get_disk(self):
        """ The disk that contains this partition."""
        try:
            disk = self.parents[0]
        except IndexError:
            disk = None
        return disk

    def _set_disk(self, disk):
        """Change the parent.

        Setting up a disk is not trivial.  It has the potential to change
        the underlying object.  If necessary we must also change this object.
        """
        log_method_call(self, self.name, old=getattr(self.disk, "name", None),
                        new=getattr(disk, "name", None))
        self.parents = []
        if disk:
            self.parents.append(disk)

    disk = property(lambda p: p._get_disk(), lambda p, d: p._set_disk(d))

    @property
    def _unaligned_max_part_size(self):
        """ Maximum size partition can grow to with unchanged start sector.

            :rtype: :class:`~.size.Size`
        """
        # XXX Only allow growth up to the amount of free space following this
        #     partition on disk. We don't care about leading free space --
        #     a filesystem cannot be relocated, so if you want to use space
        #     before and after your partition, remove it and create a new one.
        max_part_size = self.size

        if self.is_logical:
            # logical partition is at the very end of the extended partition
            extended = self.parted_partition.disk.getExtendedPartition()
            if self.parted_partition.geometry.end == extended.geometry.end:
                return max_part_size

        sector = self.parted_partition.geometry.end + 1
        try:
            partition = self.parted_partition.disk.getPartitionBySector(sector)
        except _ped.PartitionException:
            pass
        else:
            # next partition is free space or 'logical' free space
            if partition.type & parted.PARTITION_FREESPACE:
                max_part_size += Size(partition.getLength(unit="B"))

        return max_part_size

    def read_current_size(self):
        # sys reports wrong size for extended partitions (1 KiB)
        if self.is_extended:
            log_method_call(self, exists=self.exists, path=self.path,
                            sysfs_path=self.sysfs_path)
            size = Size(0)
            if self.exists and os.path.exists(self.path) and \
               os.path.isdir(self.sysfs_path):
                blocks = udev.device_get_part_size(udev.get_device(self.sysfs_path))
                if blocks:
                    size = Size(int(blocks) * LINUX_SECTOR_SIZE)

        else:
            size = super(PartitionDevice, self).read_current_size()

        return size

    @property
    def min_size(self):
        if self.is_extended:
            logicals = self.disk.format.logical_partitions
            if logicals:
                end_free = Size((self.parted_partition.geometry.end - logicals[-1].geometry.end) *
                                self.disk.format.sector_size)
                min_size = self.align_target_size(self.current_size - end_free)
            else:
                min_size = self.align_target_size(max(Size("1 KiB"), self.disk.format.alignment.grainSize))

        else:
            min_size = super(PartitionDevice, self).min_size

        if self.resizable and min_size:
            # Adjust the min size as needed so that aligning the end sector
            # won't drive the actual size below the formatting's minimum.
            # align the end sector (up, if possible)
            aligned = self.align_target_size(min_size)
            if aligned < min_size:
                # If it aligned down, that must mean it cannot align up. Just
                # return our current size.
                log.debug("failed to align min size up; returning current size")
                min_size = self.current_size

        return min_size

    @property
    def max_size(self):
        """ The maximum size this partition can be. """
        max_part_size = self._unaligned_max_part_size
        max_format_size = self.format.max_size
        unaligned_max = min(max_format_size, max_part_size) if max_format_size else max_part_size
        return self.align_target_size(unaligned_max)

    @property
    def resizable(self):
        if not self.exists:
            return False
        elif self.disk.type == 'dasd' or not self.disklabel_supported:
            return False
        elif self.is_extended:
            return True
        else:
            return super(PartitionDevice, self).resizable

    def check_size(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.max_size and self.size > self.format.max_size:
            return 1
        elif (self.format.min_size and
              (not self.req_grow and
               self.size < self.format.min_size) or
              (self.req_grow and self.req_max_size and
               self.req_max_size < self.format.min_size)):
            return -1
        return 0

    def populate_ksdata(self, data):
        super(PartitionDevice, self).populate_ksdata(data)
        data.resize = (self.exists and self.target_size and
                       self.target_size != self.current_size)
        if not self.exists:
            # round this to nearest MiB before doing anything else
            data.size = self.req_base_size.round_to_nearest(MiB, rounding=ROUND_DOWN).convert_to(spec=MiB)
            data.grow = self.req_grow
            if self.req_grow:
                data.max_size_mb = self.req_max_size.convert_to(MiB)

            # data.disk = self.disk.name                      # by-id
            if self.req_disks and len(self.req_disks) == 1:
                data.disk = self.disk.name
            data.prim_only = self.req_primary
        else:
            data.on_part = self.name                     # by-id

            if data.resize:
                # on s390x in particular, fractional sizes are reported, which
                # cause issues when writing to ks.cfg
                data.size = self.size.round_to_nearest(MiB, rounding=ROUND_DOWN).convert_to(spec=MiB)
