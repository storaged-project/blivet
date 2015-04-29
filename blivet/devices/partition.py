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

import block
import parted
import _ped

from .. import errors
from .. import util
from .. import arch
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..formats import DeviceFormat, getFormat
from ..size import Size, ROUND_DOWN

from ..devicelibs import dm

import logging
log = logging.getLogger("blivet")

from .device import Device
from .storage import StorageDevice
from .dm import DMDevice
from .lib import devicePathToName, deviceNameToDiskByPath

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
    defaultSize = DEFAULT_PART_SIZE

    def __init__(self, name, fmt=None,
                 size=None, grow=False, maxsize=None, start=None, end=None,
                 major=None, minor=None, bootable=None,
                 sysfsPath='', parents=None, exists=False,
                 partType=None, primary=False, weight=0):
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

            :keyword major: the device major
            :type major: long
            :keyword minor: the device minor
            :type minor: long
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str

            For non-existent partitions only:

            :keyword partType: parted type constant, eg:
                                :const:`parted.PARTITION_NORMAL`
            :type partType: parted partition type constant
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
            :type weight: int

            .. note::

                If a start sector is specified the partition will not be
                adjusted for optimal alignment. That is up to the caller.
        """
        self.req_disks = []
        self.req_partType = None
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

        # FIXME: Validate partType, but only if this is a new partition
        #        Otherwise, overwrite it with the partition's type.
        self._partType = None
        self._partedPartition = None
        self._origPath = None

        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               major=major, minor=minor, exists=exists,
                               sysfsPath=sysfsPath, parents=parents)

        if not exists:
            # this is a request, not a partition -- it has no parents
            self.req_disks = list(self.parents)
            self.parents = []

        # FIXME: Validate size, but only if this is a new partition.
        #        For existing partitions we will get the size from
        #        parted.

        # We can't rely on self.disk.format.supported because self.disk may get reformatted
        # in the course of things.
        self.disklabelSupported = True
        if self.exists and self.disk.partitioned and not self.disk.format.supported:
            log.info("partition %s disklabel is unsupported", self.name)
            self.disklabelSupported = False
        elif self.exists and not flags.testing:
            if not self.disk.partitioned:
                self.disklabelSupported = False
                raise errors.DeviceError("disk has wrong format '%s'" % self.disk.format.type)

            log.debug("looking up parted Partition: %s", self.path)
            self._partedPartition = self.disk.format.partedDisk.getPartitionByPath(self.path)
            if not self._partedPartition:
                raise errors.DeviceError("cannot find parted partition instance", self.name)

            self._origPath = self.path
            # collect information about the partition from parted
            self.probe()
            if self.getFlag(parted.PARTITION_PREP):
                # the only way to identify a PPC PReP Boot partition is to
                # check the partition type/flags, so do it here.
                self.format = getFormat("prepboot", device=self.path, exists=True)
            elif self.getFlag(parted.PARTITION_BIOS_GRUB):
                # the only way to identify a BIOS Boot partition is to
                # check the partition type/flags, so do it here.
                self.format = getFormat("biosboot", device=self.path, exists=True)
        else:
            # XXX It might be worthwhile to create a shit-simple
            #     PartitionRequest class and pass one to this constructor
            #     for new partitions.
            if not self._size:
                if start is not None and end is not None:
                    self._size = 0
                else:
                    # default size for new partition requests
                    self._size = self.defaultSize

            self.req_name = name
            self.req_partType = partType
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

        self._orig_size = self._size

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  grow = %(grow)s  max size = %(maxsize)s  bootable = %(bootable)s\n"
              "  part type = %(partType)s  primary = %(primary)s"
              "  start sector = %(start)s  end sector = %(end)s\n"
              "  partedPartition = %(partedPart)s\n"
              "  disk = %(disk)s\n" %
              {"grow": self.req_grow, "maxsize": self.req_max_size,
               "bootable": self.bootable, "partType": self.partType,
               "primary": self.req_primary,
               "start": self.req_start_sector, "end": self.req_end_sector,
               "partedPart": self.partedPartition, "disk": self.disk})

        if self.partedPartition:
            s += ("  start = %(start)s  end = %(end)s  length = %(length)s\n"
                  "  flags = %(flags)s" %
                  {"length": self.partedPartition.geometry.length,
                   "start": self.partedPartition.geometry.start,
                   "end": self.partedPartition.geometry.end,
                   "flags": self.partedPartition.getFlagsAsString()})

        return s

    @property
    def dict(self):
        d = super(PartitionDevice, self).dict
        d.update({"type": self.partType})
        if not self.exists:
            d.update({"grow": self.req_grow, "maxsize": self.req_max_size,
                      "bootable": self.bootable,
                      "primary": self.req_primary})

        if self.partedPartition:
            d.update({"length": self.partedPartition.geometry.length,
                      "start": self.partedPartition.geometry.start,
                      "end": self.partedPartition.geometry.end,
                      "flags": self.partedPartition.getFlagsAsString()})
        return d

    def alignTargetSize(self, newsize):
        """ Return newsize adjusted to allow for an end-aligned partition.

            :param :class:`~.Size` newsize: proposed/unaligned target size
            :raises _ped.CreateException: if the size extends beyond the end of
                                          the disk
            :returns: newsize modified to yield an end-aligned partition
            :rtype: :class:`~.Size`
        """
        if newsize == Size(0):
            return newsize

        (_constraint, geometry) = self._computeResize(self.partedPartition,
                                                      newsize=newsize)
        return Size(geometry.getLength(unit="B"))

    def _setTargetSize(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if newsize != self.size:
            try:
                aligned = self.alignTargetSize(newsize)
            except _ped.CreateException:
                # this gets handled in superclass setter, below
                aligned = newsize

            # reverting to unaligned original size is not an issue
            if aligned != newsize and newsize != self._orig_size:
                raise ValueError("new size will not yield an aligned partition")

            # change this partition's geometry in-memory so that other
            # partitioning operations can complete (e.g., autopart)
            super(PartitionDevice, self)._setTargetSize(newsize)
            disk = self.disk.format.partedDisk

            # resize the partition's geometry in memory
            (constraint, geometry) = self._computeResize(self.partedPartition)
            disk.setPartitionGeometry(partition=self.partedPartition,
                                      constraint=constraint,
                                      start=geometry.start, end=geometry.end)

    @property
    def path(self):
        if not self.parents:
            devDir = StorageDevice._devDir
        else:
            devDir = self.parents[0]._devDir

        return "%s/%s" % (devDir, self.name)

    @property
    def partType(self):
        """ Get the partition's type (as parted constant). """
        try:
            ptype = self.partedPartition.type
        except AttributeError:
            ptype = self._partType

        if not self.exists and ptype is None:
            ptype = self.req_partType

        return ptype

    @property
    def isExtended(self):
        return (self.partType is not None and
                self.partType & parted.PARTITION_EXTENDED)

    @property
    def isLogical(self):
        return (self.partType is not None and
                self.partType & parted.PARTITION_LOGICAL)

    @property
    def isPrimary(self):
        return (self.partType is not None and
                self.partType == parted.PARTITION_NORMAL)

    @property
    def isProtected(self):
        return (self.partType is not None and
                self.partType & parted.PARTITION_PROTECTED)

    @property
    def fstabSpec(self):
        spec = self.path
        if self.disk and self.disk.type == 'dasd':
            spec = deviceNameToDiskByPath(self.name)
        elif self.format and self.format.uuid:
            spec = "UUID=%s" % self.format.uuid
        return spec

    def _getPartedPartition(self):
        return self._partedPartition

    def _setPartedPartition(self, partition):
        """ Set this PartitionDevice's parted Partition instance. """
        log_method_call(self, self.name)

        if partition is not None and not isinstance(partition, parted.Partition):
            raise ValueError("partition must be None or a parted.Partition instance")

        log.debug("device %s new partedPartition %s", self.name, partition)
        self._partedPartition = partition
        self.updateName()

    partedPartition = property(lambda d: d._getPartedPartition(),
                               lambda d,p: d._setPartedPartition(p))

    def preCommitFixup(self):
        """ Re-get self.partedPartition from the original disklabel. """
        log_method_call(self, self.name)
        if not self.exists or not self.disklabelSupported:
            return

        # find the correct partition on the original parted.Disk since the
        # name/number we're now using may no longer match
        _disklabel = self.disk.originalFormat

        if self.isExtended:
            # getPartitionBySector doesn't work on extended partitions
            _partition = _disklabel.extendedPartition
            log.debug("extended lookup found partition %s",
                        devicePathToName(getattr(_partition, "path", None) or "(none)"))
        else:
            # lookup the partition by sector to avoid the renumbering
            # nonsense entirely
            _sector = self.partedPartition.geometry.start
            _partition = _disklabel.partedDisk.getPartitionBySector(_sector)
            log.debug("sector-based lookup found partition %s",
                        devicePathToName(getattr(_partition, "path", None) or "(none)"))

        self.partedPartition = _partition

    def _getWeight(self):
        return self.req_base_weight

    def _setWeight(self, weight):
        self.req_base_weight = weight

    weight = property(lambda d: d._getWeight(),
                      lambda d,w: d._setWeight(w))

    def _setName(self, value):
        self._name = value  # actual name setting is done by parted

    def updateName(self):
        if self.disk and not self.disklabelSupported:
            pass
        elif self.partedPartition is None:
            self.name = self.req_name
        else:
            self.name = \
                devicePathToName(self.partedPartition.getDeviceNodeName())

    def dependsOn(self, dep):
        """ Return True if this device depends on dep. """
        if isinstance(dep, PartitionDevice) and dep.isExtended and \
           self.isLogical and self.disk == dep.disk:
            return True

        return Device.dependsOn(self, dep)

    @property
    def isleaf(self):
        """ True if no other device depends on this one. """
        no_kids = super(PartitionDevice, self).isleaf
        # it is possible that the disk that originally contained this partition
        # no longer contains a disklabel, in which case we can assume that this
        # device is a leaf
        if self.disk and self.partedPartition and \
           self.disk.format.type == "disklabel" and \
           self.partedPartition in self.disk.format.partitions:
            disklabel = self.disk.format
        else:
            disklabel = None

        extended_has_logical = (self.isExtended and
                                (disklabel and disklabel.logicalPartitions))
        return (no_kids and not extended_has_logical)

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return self.isleaf and not self.isExtended

    def _setBootable(self, bootable):
        """ Set the bootable flag for this partition. """
        if self.partedPartition:
            if arch.isS390():
                return
            if self.flagAvailable(parted.PARTITION_BOOT):
                if bootable:
                    self.setFlag(parted.PARTITION_BOOT)
                else:
                    self.unsetFlag(parted.PARTITION_BOOT)
            else:
                raise errors.DeviceError("boot flag not available for this partition", self.name)

            self._bootable = bootable
        else:
            self.req_bootable = bootable

    def _getBootable(self):
        return self._bootable or self.req_bootable

    bootable = property(_getBootable, _setBootable)

    def flagAvailable(self, flag):
        if not self.partedPartition:
            return

        return self.partedPartition.isFlagAvailable(flag)

    def getFlag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.partedPartition or not self.flagAvailable(flag):
            return

        return self.partedPartition.getFlag(flag)

    def setFlag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.partedPartition or not self.flagAvailable(flag):
            return

        self.partedPartition.setFlag(flag)

    def unsetFlag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.partedPartition or not self.flagAvailable(flag):
            return

        self.partedPartition.unsetFlag(flag)

    @property
    def isMagic(self):
        if not self.disk or not self.disklabelSupported:
            return False

        number = getattr(self.partedPartition, "number", -1)
        magic = self.disk.format.magicPartitionNumber
        return (number == magic)

    def removeHook(self, modparent=True):
        if modparent and self.disklabelSupported:
            # if this partition hasn't been allocated it could not have
            # a disk attribute
            if not self.disk:
                return

            if self.partedPartition.type == parted.PARTITION_EXTENDED and \
                    len(self.disk.format.logicalPartitions) > 0:
                raise ValueError("Cannot remove extended partition %s.  "
                        "Logical partitions present." % self.name)

            self.disk.format.removePartition(self.partedPartition)

        super(PartitionDevice, self).removeHook(modparent=modparent)

    def addHook(self, new=True):
        super(PartitionDevice, self).addHook(new=new)
        if new:
            return

        if not self.disk or not self.partedPartition or \
           self.partedPartition in self.disk.format.partitions:
            return

        self.disk.format.addPartition(self.partedPartition.geometry.start,
                                      self.partedPartition.geometry.end,
                                      self.partedPartition.type)

        # Look up the path by start sector to deal with automatic renumbering of
        # logical partitions on msdos disklabels.
        if self.isExtended:
            partition = self.disk.format.extendedPartition
        else:
            start = self.partedPartition.geometry.start
            partition = self.disk.format.partedDisk.getPartitionBySector(start)

        self.partedPartition = partition

    def probe(self):
        """ Probe for any missing information about this device.

            size, partition type, flags
        """
        log_method_call(self, self.name, exists=self.exists)
        if not self.exists or not self.disklabelSupported:
            return

        self._size = Size(self.partedPartition.getLength(unit="B"))
        self.targetSize = self._size

        self._partType = self.partedPartition.type

        self._bootable = self.getFlag(parted.PARTITION_BOOT)

    def _wipe(self):
        """ Wipe the partition metadata. """
        log_method_call(self, self.name, status=self.status)

        start = self.partedPartition.geometry.start
        part_len = self.partedPartition.geometry.end - start
        bs = self.partedPartition.geometry.device.sectorSize
        device = self.partedPartition.geometry.device.path

        # Erase 1MiB or to end of partition
        count = int(Size("1 MiB") / bs)
        count = min(count, part_len)

        cmd = ["dd", "if=/dev/zero", "of=%s" % device, "bs=%s" % bs,
               "seek=%s" % start, "count=%s" % count]
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
        self.disk.format.addPartition(self.partedPartition.geometry.start,
                                      self.partedPartition.geometry.end,
                                      self.partedPartition.type)

        self._wipe()
        try:
            self.disk.format.commit()
        except errors.DiskLabelCommitError:
            part = self.disk.format.partedDisk.getPartitionByPath(self.path)
            self.disk.format.removePartition(part)
            raise

    def _postCreate(self):
        if self.isExtended:
            partition = self.disk.format.extendedPartition
        else:
            start = self.partedPartition.geometry.start
            partition = self.disk.format.partedDisk.getPartitionBySector(start)

        log.debug("post-commit partition path is %s", getattr(partition,
                                                             "path", None))
        self.partedPartition = partition
        if not self.isExtended:
            # Ensure old metadata which lived in freespace so did not get
            # explictly destroyed by a destroyformat action gets wiped
            DeviceFormat(device=self.path, exists=True).destroy()

        StorageDevice._postCreate(self)

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self._preCreate()
        try:
            self._create()
        except errors.DiskLabelCommitError as e:
            raise
        except Exception as e:
            raise errors.DeviceCreateError(str(e), self.name)
        else:
            self._postCreate()

    def _computeResize(self, partition, newsize=None):
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
            newsize = self.targetSize

        # compute new size for partition
        currentGeom = partition.geometry
        currentDev = currentGeom.device
        newLen = int(newsize) / currentDev.sectorSize
        newGeometry = parted.Geometry(device=currentDev,
                                      start=currentGeom.start,
                                      length=newLen)
        # and align the end sector
        if newGeometry.length < currentGeom.length:
            align = self.disk.format.endAlignment.alignUp
            alignGeom = currentGeom # we can align up into the old geometry
        else:
            align = self.disk.format.endAlignment.alignDown
            alignGeom = newGeometry

        newGeometry.end = align(alignGeom, newGeometry.end)
        constraint = parted.Constraint(exactGeom=newGeometry)

        return (constraint, newGeometry)

    def resize(self):
        log_method_call(self, self.name, status=self.status)
        self._preDestroy()

        # partedDisk has been restored to _origPartedDisk, so
        # recalculate resize geometry because we may have new
        # partitions on the disk, which could change constraints
        partedDisk = self.disk.format.partedDisk
        partition = partedDisk.getPartitionByPath(self.path)
        (constraint, geometry) = self._computeResize(partition)

        partedDisk.setPartitionGeometry(partition=partition,
                                        constraint=constraint,
                                        start=geometry.start,
                                        end=geometry.end)

        self.disk.format.commit()
        self.updateSize()

    def _preDestroy(self):
        StorageDevice._preDestroy(self)
        if not self.sysfsPath:
            return

        self.setupParents(orig=True)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        if not self.disklabelSupported:
            return

        # we should have already set self.partedPartition to point to the
        # partition on the original disklabel
        self.disk.originalFormat.removePartition(self.partedPartition)
        try:
            self.disk.originalFormat.commit()
        except errors.DiskLabelCommitError:
            self.disk.originalFormat.addPartition(
                                        self.partedPartition.geometry.start,
                                        self.partedPartition.geometry.end,
                                        self.partedPartition.type)
            self.partedPartition = self.disk.originalFormat.partedDisk.getPartitionByPath(self.path)
            raise

        if self.disk.format.exists and \
           self.disk.format.type == "disklabel" and \
           self.disk.format.partedDisk != self.disk.originalFormat.partedDisk:
            # If the new/current disklabel is the same as the original one, we
            # have to duplicate the removal on the other copy of the DiskLabel.
            part = self.disk.format.partedDisk.getPartitionByPath(self.path)
            self.disk.format.removePartition(part)
            self.disk.format.commit()

    def _postDestroy(self):
        if not self.disklabelSupported:
            return

        super(PartitionDevice, self)._postDestroy()
        if isinstance(self.disk, DMDevice):
            udev.settle()
            if self.status:
                try:
                    dm.dm_remove(self.name)
                except (errors.DMError, OSError):
                    pass

    def deactivate(self):
        """
        This is never called. For instructional purposes only.

        We do not want multipath partitions disappearing upon their teardown().
        """
        if self.parents[0].type == 'dm-multipath':
            devmap = block.getMap(major=self.major, minor=self.minor)
            if devmap:
                try:
                    block.removeDeviceMap(devmap)
                except Exception as e:
                    raise errors.DeviceTeardownError("failed to tear down device-mapper partition %s: %s" % (self.name, e))
            udev.settle()

    def _getSize(self):
        """ Get the device's size. """
        size = self._size
        if self.partedPartition:
            size = Size(self.partedPartition.getLength(unit="B"))
        return size

    def _setSize(self, newsize):
        """ Set the device's size.

            Most devices have two scenarios for setting a size:

                1) set actual/current size
                2) set target for resize

            Partitions have a third scenario:

                3) update size of an allocated-but-non-existent partition
        """
        log_method_call(self, self.name,
                        status=self.status, size=self._size, newsize=newsize)
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if not self.exists:
            # device does not exist (a partition request), just set basic values
            self._size = newsize
            self.req_size = newsize
            self.req_base_size = newsize

        if self.exists:
            super(PartitionDevice, self)._setSize(newsize)
            return

        # the rest is for changing the size of an allocated-but-not-existing
        # partition, which I'm not sure is advisable
        if self.disk and newsize > self.disk.size:
            raise ValueError("partition size would exceed disk size")

        if not self.partedPartition:
            log.warn("No partedPartition, not adjusting geometry")
            return

        maxAvailableSize = Size(self.partedPartition.getMaxAvailableSize(unit="B"))

        if newsize > maxAvailableSize:
            raise ValueError("new size is greater than available space")

         # now convert the size to sectors and update the geometry
        geometry = self.partedPartition.geometry
        physicalSectorSize = geometry.device.physicalSectorSize

        new_length = int(newsize) / physicalSectorSize
        geometry.length = new_length

    def _getDisk(self):
        """ The disk that contains this partition."""
        try:
            disk = self.parents[0]
        except IndexError:
            disk = None
        return disk

    def _setDisk(self, disk):
        """Change the parent.

        Setting up a disk is not trivial.  It has the potential to change
        the underlying object.  If necessary we must also change this object.
        """
        log_method_call(self, self.name, old=getattr(self.disk, "name", None),
                        new=getattr(disk, "name", None))
        self.parents = []
        if disk:
            self.parents.append(disk)

    disk = property(lambda p: p._getDisk(), lambda p,d: p._setDisk(d))

    @property
    def _unalignedMaxPartSize(self):
        """ Maximum size partition can grow to with unchanged start sector.

            :rtype: :class:`~.size.Size`
        """
        # XXX Only allow growth up to the amount of free space following this
        #     partition on disk. We don't care about leading free space --
        #     a filesystem cannot be relocated, so if you want to use space
        #     before and after your partition, remove it and create a new one.
        sector = self.partedPartition.geometry.end + 1
        maxPartSize = self.size
        try:
            partition = self.partedPartition.disk.getPartitionBySector(sector)
        except _ped.PartitionException:
            pass
        else:
            if partition.type == parted.PARTITION_FREESPACE:
                maxPartSize += Size(partition.getLength(unit="B"))

        return maxPartSize

    @property
    def minSize(self):
        min_size = super(PartitionDevice, self).minSize
        if self.resizable and min_size:
            # Adjust the min size as needed so that aligning the end sector
            # won't drive the actual size below the formatting's minimum.
            # align the end sector (up, if possible)
            aligned = self.alignTargetSize(min_size)
            if aligned < min_size:
                # If it aligned down, that must mean it cannot align up. Just
                # return our current size.
                log.debug("failed to align min size up; returning current size")
                min_size = self.currentSize

        return min_size

    @property
    def maxSize(self):
        """ The maximum size this partition can be. """
        maxPartSize = self._unalignedMaxPartSize
        maxFormatSize = self.format.maxSize
        unalignedMax = min(maxFormatSize, maxPartSize) if maxFormatSize else maxPartSize
        return self.alignTargetSize(unalignedMax)

    @property
    def resizable(self):
        return super(PartitionDevice, self).resizable and \
               self.disk.type != 'dasd' and self.disklabelSupported

    def checkSize(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.maxSize and self.size > self.format.maxSize:
            return 1
        elif (self.format.minSize and
              (not self.req_grow and
               self.size < self.format.minSize) or
              (self.req_grow and self.req_max_size and
               self.req_max_size < self.format.minSize)):
            return -1
        return 0

    def populateKSData(self, data):
        super(PartitionDevice, self).populateKSData(data)
        data.resize = (self.exists and self.targetSize and
                       self.targetSize != self.currentSize)
        if not self.exists:
            # round this to nearest MiB before doing anything else
            data.size = self.req_base_size.roundToNearest("MiB", rounding=ROUND_DOWN).convertTo(spec="MiB")
            data.grow = self.req_grow
            if self.req_grow:
                data.maxSizeMB = self.req_max_size.convertTo(spec="MiB")

            ##data.disk = self.disk.name                      # by-id
            if self.req_disks and len(self.req_disks) == 1:
                data.disk = self.disk.name
            data.primOnly = self.req_primary
        else:
            data.onPart = self.name                     # by-id

            if data.resize:
                # on s390x in particular, fractional sizes are reported, which
                # cause issues when writing to ks.cfg
                data.size = self.size.roundToNearest("MiB", rounding=ROUND_DOWN).convertTo(spec="MiB")
