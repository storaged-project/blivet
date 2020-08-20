# partitioning.py
# Disk partitioning functions.
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

from operator import gt, lt
from decimal import Decimal
import functools

import gi
gi.require_version("BlockDev", "2.0")

import parted
import _ped

from .errors import DeviceError, PartitioningError, AlignmentError
from .flags import flags
from .devices import Device, PartitionDevice, device_path_to_name
from .size import Size
from .i18n import _
from .util import stringize, unicodeize, compare

import logging
log = logging.getLogger("blivet")


def partition_compare(part1, part2):
    """ More specifically defined partitions come first.

        < 1 => x < y
          0 => x == y
        > 1 => x > y

        :param part1: the first partition
        :type part1: :class:`devices.PartitionDevice`
        :param part2: the other partition
        :type part2: :class:`devices.PartitionDevice`
        :return: see above
        :rtype: int
    """
    ret = 0

    # start sector overrides all other sorting factors
    part1_start = part1.req_start_sector
    part2_start = part2.req_start_sector
    if part1_start is not None and part2_start is None:
        return -1
    elif part1_start is None and part2_start is not None:
        return 1
    elif part1_start is not None and part2_start is not None:
        return compare(part1_start, part2_start)

    if part1.weight:
        ret -= part1.weight

    if part2.weight:
        ret += part2.weight

    # more specific disk specs to the front of the list
    # req_disks being empty is equivalent to it being an infinitely long list
    if part1.req_disks and not part2.req_disks:
        ret -= 500
    elif not part1.req_disks and part2.req_disks:
        ret += 500
    else:
        ret += compare(len(part1.req_disks), len(part2.req_disks)) * 500

    # primary-only to the front of the list
    ret -= compare(part1.req_primary, part2.req_primary) * 200

    # fixed size requests to the front
    ret += compare(part1.req_grow, part2.req_grow) * 100

    # larger requests go to the front of the list
    ret -= compare(part1.req_base_size, part2.req_base_size) * 50

    # potentially larger growable requests go to the front
    if part1.req_grow and part2.req_grow:
        if not part1.req_max_size and part2.req_max_size:
            ret -= 25
        elif part1.req_max_size and not part2.req_max_size:
            ret += 25
        else:
            ret -= compare(part1.req_max_size, part2.req_max_size) * 25

    # give a little bump based on mountpoint
    if hasattr(part1.format, "mountpoint") and \
       hasattr(part2.format, "mountpoint"):
        ret += compare(part1.format.mountpoint, part2.format.mountpoint) * 10

    if ret > 0:
        ret = 1
    elif ret < 0:
        ret = -1

    return ret


_partition_compare_key = functools.cmp_to_key(partition_compare)


def get_next_partition_type(disk, no_primary=None):
    """ Return the type of partition to create next on a disk.

        Return a parted partition type value representing the type of the
        next partition we will create on this disk.

        If there is only one free primary partition and we can create an
        extended partition, we do that.

        If there are free primary slots and an extended partition we will
        recommend creating a primary partition. This can be overridden
        with the keyword argument no_primary.

        :param disk: the disk from which a partition may be allocated
        :type disk: :class:`parted.Disk`
        :keyword no_primary: refuse to return :const:`parted.PARTITION_NORMAL`
        :returns: the chosen partition type
        :rtype: a parted PARTITION_* constant
    """
    part_type = None
    extended = disk.getExtendedPartition()
    supports_extended = disk.supportsFeature(parted.DISK_TYPE_EXTENDED)
    primary_count = disk.primaryPartitionCount

    if primary_count < disk.maxPrimaryPartitionCount:
        if primary_count == disk.maxPrimaryPartitionCount - 1:
            # can we make an extended partition? now's our chance.
            if not extended and supports_extended:
                part_type = parted.PARTITION_EXTENDED
            elif not extended:
                # extended partitions not supported. primary or nothing.
                if not no_primary:
                    part_type = parted.PARTITION_NORMAL
            else:
                # there is an extended and a free primary
                if not no_primary:
                    part_type = parted.PARTITION_NORMAL
                else:
                    # we have an extended, so use it.
                    part_type = parted.PARTITION_LOGICAL
        else:
            # there are two or more primary slots left. use one unless we're
            # not supposed to make primaries.
            if not no_primary:
                part_type = parted.PARTITION_NORMAL
            elif extended:
                part_type = parted.PARTITION_LOGICAL
    elif extended:
        part_type = parted.PARTITION_LOGICAL

    return part_type


def get_best_free_space_region(disk, part_type, req_size, start=None,
                               boot=None, best_free=None, grow=None,
                               alignment=None):
    """ Return the "best" free region on the specified disk.

        For non-boot partitions, we return the largest free region on the
        disk. For boot partitions, we return the first region that is
        large enough to hold the partition.

        Partition type (parted's PARTITION_NORMAL, PARTITION_LOGICAL) is
        taken into account when locating a suitable free region.

        For locating the best region from among several disks, the keyword
        argument best_free allows the specification of a current "best"
        free region with which to compare the best from this disk. The
        overall best region is returned.

        :param disk: the disk
        :type disk: :class:`parted.Disk`
        :param part_type: the type of partition we want to allocate
        :type part_type: one of parted's PARTITION_* constants
        :param req_size: the requested size of the partition in MiB
        :type req_size: :class:`~.size.Size`
        :keyword start: requested start sector for the partition
        :type start: int
        :keyword boot: whether this will be a bootable partition
        :type boot: bool
        :keyword best_free: current best free region for this partition
        :type best_free: :class:`parted.Geometry`
        :keyword grow: indicates whether this is a growable request
        :type grow: bool
        :keyword alignment: disk alignment requirements
        :type alignment: :class:`parted.Alignment`

    """
    log.debug("get_best_free_space_region: disk=%s part_type=%d req_size=%s "
              "boot=%s best=%s grow=%s start=%s",
              disk.device.path, part_type, req_size, boot, best_free, grow,
              start)
    extended = disk.getExtendedPartition()
    alignment = alignment or parted.Alignment(offset=0, grainSize=1)

    for free_geom in disk.getFreeSpaceRegions():
        # align the start sector of the free region since we will be aligning
        # the start sector of the partition
        if start is not None and \
           not alignment.isAligned(free_geom, free_geom.start):
            log.debug("aligning start sector of region %d-%d", free_geom.start,
                      free_geom.end)
            try:
                aligned_start = alignment.alignUp(free_geom, free_geom.start)
            except ArithmeticError:
                aligned_start = None
            else:
                # parted tends to align down when it cannot align up
                if aligned_start < free_geom.start:
                    aligned_start = None

            if aligned_start is None:
                log.debug("failed to align start sector -- skipping region")
                continue

            free_geom = parted.Geometry(device=free_geom.device,
                                        start=aligned_start,
                                        end=free_geom.end)

        log.debug("checking %d-%d (%s)", free_geom.start, free_geom.end,
                  Size(free_geom.getLength(unit="B")))
        if start is not None and not free_geom.containsSector(start):
            log.debug("free region does not contain requested start sector")
            continue

        if extended:
            in_extended = extended.geometry.contains(free_geom)
            if ((in_extended and part_type == parted.PARTITION_NORMAL) or
                    (not in_extended and part_type == parted.PARTITION_LOGICAL)):
                log.debug("free region not suitable for request")
                continue

        if free_geom.start > disk.maxPartitionStartSector:
            log.debug("free range start sector beyond max for new partitions")
            continue

        if boot:
            max_boot = Size("2 TiB")
            free_start = Size(free_geom.start * disk.device.sectorSize)
            req_end = free_start + req_size
            if req_end > max_boot:
                log.debug("free range position would place boot req above %s",
                          max_boot)
                continue

        log.debug("current free range is %d-%d (%s)", free_geom.start,
                  free_geom.end,
                  Size(free_geom.getLength(unit="B")))
        free_size = Size(free_geom.getLength(unit="B"))

        # For boot partitions, we want the first suitable region we find.
        # For growable or extended partitions, we want the largest possible
        # free region.
        # For all others, we want the smallest suitable free region.
        if grow or part_type == parted.PARTITION_EXTENDED:
            op = gt
        else:
            op = lt
        if req_size <= free_size:
            if not best_free or op(free_geom.length, best_free.length):
                best_free = free_geom

                if boot:
                    # if this is a bootable partition we want to
                    # use the first freespace region large enough
                    # to satisfy the request
                    break

    return best_free


def sectors_to_size(sectors, sector_size):
    """ Convert length in sectors to size.

        :param sectors: sector count
        :type sectors: int
        :param sector_size: sector size
        :type sector_size: :class:`~.size.Size`
        :returns: the size
        :rtype: :class:`~.size.Size`
    """
    return Size(sectors * sector_size)


def size_to_sectors(size, sector_size):
    """ Convert size to length in sectors.

        :param size: size
        :type size: :class:`~.size.Size`
        :param sector_size: sector size in bytes
        :type sector_size: :class:`~.size.Size`
        :returns: sector count
        :rtype: int
    """
    return int(size // sector_size)


def remove_new_partitions(disks, remove, all_partitions):
    """ Remove newly added partitions from disks.

        Remove all non-existent partitions from the disks in blivet's model.

        :param: disks: list of partitioned disks
        :type disks: list of :class:`~.devices.StorageDevice`
        :param remove: list of partitions to remove
        :type remove: list of :class:`~.devices.PartitionDevice`
        :param all_partitions: list of all partitions on the disks
        :type all_partitions: list of :class:`~.devices.PartitionDevice`
        :returns: None
        :rtype: NoneType
    """
    log.debug("removing all non-preexisting partitions %s from disk(s) %s",
              ["%s(id %d)" % (p.name, p.id) for p in remove],
              [d.name for d in disks])

    removed_logical = []
    for part in remove:
        if part.parted_partition and part.disk in disks:
            if part.exists:
                # we're only removing partitions that don't physically exist
                continue

            if part.is_extended:
                # these get removed last
                continue

            if part.is_logical:
                removed_logical.append(part)
            part.disk.format.parted_disk.removePartition(part.parted_partition)
            part.parted_partition = None
            part.disk = None

    def _remove_extended(disk, extended):
        """ We may want to remove extended partition from the disk too.
            This should happen if we don't have the PartitionDevice object
            or in installer_mode after we've removed all logical paritions.
        """

        if extended and not disk.format.logical_partitions:
            if extended not in (p.parted_partition for p in all_partitions):
                # extended partition is not in all_partitions -> remove it
                return True
            else:
                if flags.keep_empty_ext_partitions:
                    return False
                else:
                    if any(l.disk == extended.disk for l in removed_logical):
                        # we removed all logical paritions from this extended
                        # so we no longer need this one
                        return True
                    else:
                        return False

    for disk in disks:
        # remove empty extended so it doesn't interfere
        extended = disk.format.extended_partition
        if _remove_extended(disk, extended):
            log.debug("removing empty extended partition from %s", disk.name)
            disk.format.parted_disk.removePartition(extended)


def add_partition(disklabel, free, part_type, size, start=None, end=None):
    """ Add a new partition to a disk.

        :param disklabel: the disklabel to add the partition to
        :type disklabel: :class:`~.formats.DiskLabel`
        :param free: the free region in which to place the new partition
        :type free: :class:`parted.Geometry`
        :param part_type: the partition type
        :type part_type: a parted.PARTITION_* constant
        :param size: size of the new partition
        :type size: :class:`~.size.Size`
        :keyword start: starting sector for the partition
        :type start: int
        :keyword end: ending sector for the partition
        :type end: int
        :raises: :class:`~.errors.PartitioningError`
        :returns: the newly added partitions
        :rtype: :class:`parted.Partition`

        .. note::

            The new partition will be aligned using the kernel-provided optimal
            alignment unless a start sector is provided.

    """
    # get alignment information based on disklabel, device, and partition size
    if start is None:
        if size is None:
            # implicit request for extended partition (will use full free area)
            _size = sectors_to_size(free.length, disklabel.sector_size)
        else:
            _size = size

        try:
            alignment = disklabel.get_alignment(size=_size)
        except AlignmentError:
            alignment = disklabel.get_minimal_alignment()

        end_alignment = disklabel.get_end_alignment(alignment=alignment)
    else:
        alignment = parted.Alignment(grainSize=1, offset=0)
        end_alignment = parted.Alignment(grainSize=1, offset=-1)
    log.debug("using alignment: %s", alignment)

    sector_size = Size(disklabel.sector_size)
    if start is not None:
        if end is None:
            end = start + size_to_sectors(size, sector_size) - 1
    else:
        start = free.start

        if not alignment.isAligned(free, start):
            start = alignment.alignNearest(free, start)

        if disklabel.label_type == "sun" and start == 0:
            start = alignment.alignUp(free, start)

        if part_type == parted.PARTITION_LOGICAL:
            # make room for logical partition's metadata
            start += alignment.grainSize

        if start != free.start:
            log.debug("adjusted start sector from %d to %d", free.start, start)

        if part_type == parted.PARTITION_EXTENDED and not size:
            end = free.end
            length = end - start + 1
        else:
            length = size_to_sectors(size, sector_size)
            end = start + length - 1

        if not end_alignment.isAligned(free, end):
            end = end_alignment.alignUp(free, end)
            log.debug("adjusted length from %d to %d", length, end - start + 1)
            if start > end:
                raise PartitioningError(_("unable to allocate aligned partition"))

    new_geom = parted.Geometry(device=disklabel.parted_device,
                               start=start,
                               end=end)

    max_length = disklabel.parted_disk.maxPartitionLength
    if max_length and new_geom.length > max_length:
        raise PartitioningError(_("requested size exceeds maximum allowed"))

    # create the partition and add it to the disk
    partition = parted.Partition(disk=disklabel.parted_disk,
                                 type=part_type,
                                 geometry=new_geom)
    constraint = parted.Constraint(exactGeom=new_geom)

    try:
        disklabel.parted_disk.addPartition(partition=partition,
                                           constraint=constraint)
    except _ped.PartitionException as e:
        raise PartitioningError(_("failed to add partition to disk: %s") % str(e))

    return partition


def get_free_regions(disks, align=False):
    """ Return a list of free regions on the specified disks.

        :param disks: list of disks
        :type disks: list of :class:`~.devices.Disk`
        :param align: align the region length to disk grain_size
        :type align: bool
        :returns: list of free regions
        :rtype: list of :class:`parted.Geometry`

        Only free regions guaranteed to contain at least one aligned sector for
        both the start and end alignments in the
        :class:`~.formats.disklabel.DiskLabel` are returned.
    """
    free = []
    for disk in disks:
        for f in disk.format.parted_disk.getFreeSpaceRegions():
            grain_size = disk.format.alignment.grainSize
            if f.length >= grain_size:
                if align:
                    aligned_length = f.length - (f.length % grain_size)
                    log.debug("length of free region aligned from %d to %d",
                              f.length, aligned_length)
                    f.length = aligned_length
                free.append(f)

    return free


def update_extended_partitions(storage, disks):
    """ Reconcile extended partition changes with the DeviceTree.

        :param storage: the Blivet instance
        :type storage: :class:`~.Blivet`
        :param disks: list of disks
        :type disks: list of :class:`~.devices.StorageDevice`
        :returns: :const:`None`
        :rtype: NoneType
    """
    # XXX hack -- if we created any extended partitions we need to add
    #             them to the tree now
    for disk in disks:
        extended = disk.format.extended_partition
        if not extended:
            # remove any obsolete extended partitions
            for part in storage.partitions:
                if part.disk == disk and part.is_extended:
                    if part.exists:
                        storage.destroy_device(part)
                    else:
                        storage.devicetree._remove_device(part, modparent=False)
            continue

        extended_name = device_path_to_name(extended.getDeviceNodeName())
        device = storage.devicetree.get_device_by_name(extended_name)
        if device:
            if not device.exists:
                # created by us, update parted_partition
                device.parted_partition = extended

        # remove any obsolete extended partitions
        for part in storage.partitions:
            if part.disk == disk and part.is_extended and \
               part.parted_partition not in disk.format.partitions:
                if part.exists:
                    storage.destroy_device(part)
                else:
                    storage.devicetree._remove_device(part, modparent=False)

        if device:
            continue

        # This is a little odd because normally instantiating a partition
        # that does not exist means leaving self.parents empty and instead
        # populating self.req_disks. In this case, we need to skip past
        # that since this partition is already defined.
        device = PartitionDevice(extended_name, parents=disk)
        device.parents = [disk]
        device.parted_partition = extended
        # just add the device for now -- we'll handle actions at the last
        # moment to simplify things
        storage.devicetree._add_device(device)


def do_partitioning(storage, boot_disk=None):
    """ Allocate and grow partitions.

        When this function returns without error, all PartitionDevice
        instances must have their parents set to the disk they are
        allocated on, and their parted_partition attribute set to the
        appropriate parted.Partition instance from their containing
        disk. All req_xxxx attributes must be unchanged.

        :param storage: Blivet instance
        :type storage: :class:`~.Blivet`
        :param boot_disk: optional parameter, the disk the bootloader is on
        :type boot_device: :class:`~.devices.StorageDevice`
        :raises: :class:`~.errors.PartitioningError`
        :returns: :const:`None`
    """
    disks = [d for d in storage.partitioned if d.format.supported and not d.protected]
    for disk in disks:
        try:
            disk.setup()
        except DeviceError as e:
            log.error("failed to set up disk %s: %s", disk.name, e)
            raise PartitioningError(_("disk %s inaccessible") % disk.name)

    # Remove any extended partition that does not have an action associated.
    #
    # XXX This does not remove the extended from the parted.Disk, but it should
    #     cause remove_new_partitions to remove it since there will no longer be
    #     a PartitionDevice for it.
    for partition in storage.partitions:
        if not partition.exists and partition.is_extended and \
           not storage.devicetree.actions.find(device=partition, action_type="create"):
            storage.devicetree._remove_device(partition, modparent=False, force=True)

    partitions = storage.partitions[:]

    if boot_disk:
        # set the boot flag on boot device
        for part in storage.partitions:
            part.req_bootable = False
            if not part.exists:
                # start over with flexible-size requests
                part.req_size = part.req_base_size

        boot_device = storage.mountpoints.get("/boot", storage.mountpoints.get("/"))
        try:
            boot_device.req_bootable = True
        except AttributeError:
            # there's no stage2 device. hopefully it's temporary.
            pass

    remove_new_partitions(disks, partitions, partitions)
    free = get_free_regions(disks)
    try:
        allocate_partitions(storage, disks, partitions, free, boot_disk=boot_disk)
        grow_partitions(disks, partitions, free, size_sets=storage.size_sets)
    except Exception:  # pylint: disable=try-except-raise
        raise
    else:
        # Mark all growable requests as no longer growable.
        for partition in storage.partitions:
            log.debug("fixing size of %s", partition)
            partition.req_grow = False
            partition.req_base_size = partition.size
            partition.req_size = partition.size
    finally:
        # these are only valid for one allocation run
        storage.size_sets = []

        # The number and thus the name of partitions may have changed now,
        # allocate_partitions() takes care of this for new partitions, but not
        # for pre-existing ones, so we update the name of all partitions here
        for part in storage.partitions:
            # leave extended partitions as-is -- we'll handle them separately
            if part.is_extended:
                continue
            part.update_name()

        update_extended_partitions(storage, disks)

        for part in [p for p in storage.partitions if not p.exists]:
            problem = part.check_size()
            if problem < 0:
                raise PartitioningError(_("partition is too small for %(format)s formatting "
                                          "(allowable size is %(min_size)s to %(max_size)s)")
                                        % {"format": part.format.name, "min_size": part.format.min_size,
                                            "max_size": part.format.max_size})
            elif problem > 0:
                raise PartitioningError(_("partition is too large for %(format)s formatting "
                                          "(allowable size is %(min_size)s to %(max_size)s)")
                                        % {"format": part.format.name, "min_size": part.format.min_size,
                                            "max_size": part.format.max_size})


def align_size_for_disklabel(size, disklabel):
    # Align the base size to the disk's grain size.
    try:
        alignment = disklabel.get_alignment(size=size)
    except AlignmentError:
        alignment = disklabel.get_minimal_alignment()

    grain_size = Size(alignment.grainSize)
    grains, rem = divmod(size, grain_size)
    return (grains * grain_size) + (grain_size if rem else Size(0))


def resolve_disk_tags(disks, tags):
    """Resolve disk tags to a disk list.

        :param disks: available disks
        :type disks: list of :class:`~.devices.StorageDevice`
        :param tags: tags to select disks based on
        :type tags: list of str

        If tags contains multiple values it is interpeted as
        "include disks containing *any* of these tags".
    """
    return [disk for disk in disks if any(tag in disk.tags for tag in tags)]


def allocate_partitions(storage, disks, partitions, freespace, boot_disk=None):
    """ Allocate partitions based on requested features.

        :param storage: a Blivet instance
        :type storage: :class:`~.Blivet`
        :param disks: list of usable disks
        :type disks: list of :class:`~.devices.StorageDevice`
        :param partitions: list of partitions
        :type partitions: list of :class:`~.devices.PartitionDevice`
        :param freespace: list of free regions on disks
        :type freespace: list of :class:`parted.Geometry`
        :param boot_disk: optional parameter, the disk the bootloader is on
        :type boot_device: :class:`~.devices.StorageDevice`
        :raises: :class:`~.errors.PartitioningError`
        :returns: :const:`None`

        Non-existing partitions are sorted according to their requested
        attributes, and then allocated.

        The basic approach to sorting is that the more specifically-
        defined a request is, the earlier it will be allocated. See
        :func:`partitionCompare` for details of the sorting criteria.

        The :class:`~.devices.PartitionDevice` instances will have their name
        and parents attributes set once they have been allocated.
    """
    log.debug("allocate_partitions: disks=%s ; partitions=%s",
              [d.name for d in disks],
              ["%s(id %d)" % (p.name, p.id) for p in partitions])

    new_partitions = [p for p in partitions if not p.exists]
    new_partitions.sort(key=_partition_compare_key)

    # the following dicts all use device path strings as keys
    disklabels = {}     # DiskLabel instances for each disk
    all_disks = {}      # StorageDevice for each disk
    for disk in disks:
        if disk.path not in disklabels.keys():
            disklabels[disk.path] = disk.format
            all_disks[disk.path] = disk

    remove_new_partitions(disks, new_partitions, partitions)

    for _part in new_partitions:
        if _part.parted_partition and _part.is_extended:
            # ignore new extendeds as they are implicit requests
            continue

        # obtain the set of candidate disks
        req_disks = []
        if _part.req_disks:
            # use the requested disk set
            req_disks = _part.req_disks
        elif _part.req_disk_tags:
            req_disks = resolve_disk_tags(disks, _part.req_disk_tags)
        else:
            # no disks specified means any disk will do
            req_disks = disks

        req_disks.sort(key=storage.compare_disks_key)
        # make sure the boot disk is at the beginning of the disk list
        if boot_disk:
            for disk in req_disks[:]:
                if disk == boot_disk:
                    boot_index = req_disks.index(disk)
                    req_disks.insert(0, req_disks.pop(boot_index))

        boot = _part.weight > 1000

        log.debug("allocating partition: %s ; id: %d ; disks: %s ;\n"
                  "boot: %s ; primary: %s ; size: %s ; grow: %s ; "
                  "max_size: %s ; start: %s ; end: %s", _part.name, _part.id,
                  [d.name for d in req_disks],
                  boot, _part.req_primary,
                  _part.req_size, _part.req_grow,
                  _part.req_max_size, _part.req_start_sector,
                  _part.req_end_sector)
        free = None
        use_disk = None
        part_type = None
        growth = 0  # in sectors
        # loop through disks
        for _disk in req_disks:
            disklabel = disklabels[_disk.path]
            best = None
            current_free = free
            try:
                alignment = disklabel.get_alignment(size=_part.req_size)
            except AlignmentError:
                alignment = disklabel.get_minimal_alignment()

            # for growable requests, we don't want to pass the current free
            # geometry to get_best_free_region -- this allows us to try the
            # best region from each disk and choose one based on the total
            # growth it allows
            if _part.req_grow:
                current_free = None

            log.debug("checking freespace on %s", _disk.name)

            if _part.req_start_sector is None:
                req_size = align_size_for_disklabel(_part.req_size, disklabel)
            else:
                # don't align size if start sector was specified
                req_size = _part.req_size

            if req_size != _part.req_size:
                log.debug("size %s rounded up to %s for disk %s",
                          _part.req_size, req_size, _disk.name)

            new_part_type = get_next_partition_type(disklabel.parted_disk)
            if new_part_type is None:
                # can't allocate any more partitions on this disk
                log.debug("no free partition slots on %s", _disk.name)
                continue

            if _part.req_primary and new_part_type != parted.PARTITION_NORMAL:
                if (disklabel.parted_disk.primaryPartitionCount <
                        disklabel.parted_disk.maxPrimaryPartitionCount):
                    # don't fail to create a primary if there are only three
                    # primary partitions on the disk (#505269)
                    new_part_type = parted.PARTITION_NORMAL
                else:
                    # we need a primary slot and none are free on this disk
                    log.debug("no primary slots available on %s", _disk.name)
                    continue
            elif _part.req_part_type is not None and \
                    new_part_type != _part.req_part_type:
                new_part_type = _part.req_part_type

            best = get_best_free_space_region(disklabel.parted_disk,
                                              new_part_type,
                                              req_size,
                                              start=_part.req_start_sector,
                                              best_free=current_free,
                                              boot=boot,
                                              grow=_part.req_grow,
                                              alignment=alignment)

            if best == free and not _part.req_primary and \
               new_part_type == parted.PARTITION_NORMAL:
                # see if we can do better with a logical partition
                log.debug("not enough free space for primary -- trying logical")
                new_part_type = get_next_partition_type(disklabel.parted_disk,
                                                        no_primary=True)
                if new_part_type:
                    best = get_best_free_space_region(disklabel.parted_disk,
                                                      new_part_type,
                                                      req_size,
                                                      start=_part.req_start_sector,
                                                      best_free=current_free,
                                                      boot=boot,
                                                      grow=_part.req_grow,
                                                      alignment=alignment)

            if best and free != best:
                update = True
                allocated = new_partitions[:new_partitions.index(_part) + 1]
                if any([p.req_grow for p in allocated]):
                    log.debug("evaluating growth potential for new layout")
                    new_growth = 0
                    for disk_path in disklabels.keys():
                        log.debug("calculating growth for disk %s", disk_path)
                        # Now we check, for growable requests, which of the two
                        # free regions will allow for more growth.

                        # set up chunks representing the disks' layouts
                        temp_parts = []
                        for _p in new_partitions[:new_partitions.index(_part)]:
                            if _p.disk.path == disk_path:
                                temp_parts.append(_p)

                        # add the current request to the temp disk to set up
                        # its parted_partition attribute with a base geometry
                        if disk_path == _disk.path:
                            _part_type = new_part_type
                            _free = best
                            if new_part_type == parted.PARTITION_EXTENDED and \
                               new_part_type != _part.req_part_type:
                                add_partition(disklabel, best, new_part_type,
                                              None)

                                _part_type = parted.PARTITION_LOGICAL

                                _free = get_best_free_space_region(disklabel.parted_disk,
                                                                   _part_type,
                                                                   req_size,
                                                                   start=_part.req_start_sector,
                                                                   boot=boot,
                                                                   grow=_part.req_grow,
                                                                   alignment=alignment)
                                if not _free:
                                    log.info("not enough space after adding "
                                             "extended partition for growth test")
                                    if new_part_type == parted.PARTITION_EXTENDED:
                                        e = disklabel.extended_partition
                                        disklabel.parted_disk.removePartition(e)

                                    continue

                            temp_part = None
                            try:
                                temp_part = add_partition(disklabel,
                                                          _free,
                                                          _part_type,
                                                          req_size,
                                                          _part.req_start_sector,
                                                          _part.req_end_sector)
                            except ArithmeticError as e:
                                log.debug("failed to allocate aligned partition "
                                          "for growth test")
                                continue

                            _part.parted_partition = temp_part
                            _part.disk = _disk
                            temp_parts.append(_part)

                        chunks = get_disk_chunks(all_disks[disk_path],
                                                 temp_parts, freespace)

                        # grow all growable requests
                        disk_growth = 0  # in sectors
                        disk_sector_size = Size(disklabels[disk_path].sector_size)
                        for chunk in chunks:
                            chunk.grow_requests()
                            # record the growth for this layout
                            new_growth += chunk.growth
                            disk_growth += chunk.growth
                            for req in chunk.requests:
                                log.debug("request %d (%s) growth: %d (%s) "
                                          "size: %s",
                                          req.device.id,
                                          req.device.name,
                                          req.growth,
                                          sectors_to_size(req.growth,
                                                          disk_sector_size),
                                          sectors_to_size(req.growth + req.base,
                                                          disk_sector_size))
                        log.debug("disk %s growth: %d (%s)",
                                  disk_path, disk_growth,
                                  sectors_to_size(disk_growth,
                                                  disk_sector_size))

                    if temp_part:
                        disklabel.parted_disk.removePartition(temp_part)
                    _part.parted_partition = None
                    _part.disk = None

                    if new_part_type == parted.PARTITION_EXTENDED:
                        e = disklabel.extended_partition
                        disklabel.parted_disk.removePartition(e)

                    log.debug("total growth: %d sectors", new_growth)

                    # update the chosen free region unless the previous
                    # choice yielded greater total growth
                    if free is not None and new_growth <= growth:
                        log.debug("keeping old free: %d <= %d", new_growth,
                                  growth)
                        update = False
                    else:
                        growth = new_growth

                if update:
                    # now we know we are choosing a new free space,
                    # so update the disk and part type
                    log.debug("updating use_disk to %s, type: %s",
                              _disk.name, new_part_type)
                    part_type = new_part_type
                    use_disk = _disk
                    log.debug("new free: %d-%d / %s", best.start,
                              best.end,
                              Size(best.getLength(unit="B")))
                    log.debug("new free allows for %d sectors of growth", growth)
                    free = best

            if free and boot:
                # if this is a bootable partition we want to
                # use the first freespace region large enough
                # to satisfy the request
                log.debug("found free space for bootable request")
                break

        if free is None:
            raise PartitioningError(_("Unable to allocate requested partition scheme."))

        _disk = use_disk
        disklabel = _disk.format
        if _part.req_start_sector is None:
            aligned_size = align_size_for_disklabel(_part.req_size, disklabel)
        else:
            # not aligned
            aligned_size = _part.req_size

        # create the extended partition if needed
        if part_type == parted.PARTITION_EXTENDED and \
           part_type != _part.req_part_type:
            log.debug("creating extended partition")
            ext = add_partition(disklabel, free, part_type, None)

            # extedned partition took all free space - make the size request smaller
            if aligned_size > (ext.geometry.length - disklabel.alignment.grainSize) * disklabel.sector_size:
                log.debug("not enough free space after creating extended "
                          "partition - shrinking the logical partition")
                aligned_size = aligned_size - (disklabel.alignment.grainSize * disklabel.sector_size)

            # now the extended partition exists, so set type to logical
            part_type = parted.PARTITION_LOGICAL

            # recalculate freespace
            log.debug("recalculating free space")
            free = get_best_free_space_region(disklabel.parted_disk,
                                              part_type,
                                              aligned_size,
                                              start=_part.req_start_sector,
                                              boot=boot,
                                              grow=_part.req_grow,
                                              alignment=disklabel.alignment)
            if not free:
                raise PartitioningError(_("not enough free space after "
                                          "creating extended partition"))

        try:
            partition = add_partition(disklabel, free, part_type, aligned_size,
                                      _part.req_start_sector, _part.req_end_sector)
        except ArithmeticError:
            raise PartitioningError(_("failed to allocate aligned partition"))

        log.debug("created partition %s of %s and added it to %s",
                  partition.getDeviceNodeName(),
                  Size(partition.getLength(unit="B")),
                  disklabel.device)

        # this one sets the name
        _part.parted_partition = partition
        _part.disk = _disk

        # parted modifies the partition in the process of adding it to
        # the disk, so we need to grab the latest version...
        _part.parted_partition = disklabel.parted_disk.getPartitionByPath(_part.path)


class Request(object):

    """ A partition request.

        Request instances are used for calculating how much to grow
        partitions.
    """

    def __init__(self, device):
        """
            :param device: the device being requested
            :type device: :class:`~.devices.StorageDevice`
        """
        self.device = device
        self.growth = 0                     # growth in sectors
        self.max_growth = 0                 # max growth in sectors
        self.done = not getattr(device, "req_grow", True)  # can we grow this
        # request more?
        self.base = 0                       # base sectors

    @property
    def reserve_request(self):
        """ Requested reserved fixed extra space for the request (in sectors) """

        # generic requests don't need any such extra space
        return 0

    @property
    def growable(self):
        """ True if this request is growable. """
        return getattr(self.device, "req_grow", True)

    @property
    def id(self):
        """ The id of the Device instance this request corresponds to. """
        return self.device.id

    def __repr__(self):
        s = ("%(type)s instance --\n"
             "id = %(id)s  name = %(name)s  growable = %(growable)s\n"
             "base = %(base)d  growth = %(growth)d  max_grow = %(max_grow)d\n"
             "done = %(done)s" %
             {"type": self.__class__.__name__, "id": self.id,
              "name": self.device.name, "growable": self.growable,
              "base": self.base, "growth": self.growth,
              "max_grow": self.max_growth, "done": self.done})
        return s


class PartitionRequest(Request):

    def __init__(self, partition):
        """
            :param partition: the partition being requested
            :type partition: :class:`~.devices.PartitionDevice`
        """
        super(PartitionRequest, self).__init__(partition)
        self.base = partition.parted_partition.geometry.length   # base sectors

        sector_size = Size(partition.parted_partition.disk.device.sectorSize)

        if partition.req_grow:
            mins = [size for size in (partition.req_max_size, partition.format.max_size)
                    if size > 0]
            req_format_max_size = min(mins) if mins else Size(0)
            limits = [l for l in (size_to_sectors(req_format_max_size, sector_size),
                                  partition.parted_partition.disk.maxPartitionLength) if l > 0]

            if limits:
                max_sectors = min(limits)
                self.max_growth = max_sectors - self.base
                if self.max_growth <= 0:
                    # max size is less than or equal to base, so we're done
                    self.done = True


class LVRequest(Request):

    def __init__(self, lv):
        """
            :param lv: the logical volume being requested
            :type lv: :class:`~.devices.LVMLogicalVolumeDevice`
        """
        super(LVRequest, self).__init__(lv)

        # Round up to nearest pe. For growable requests this will mean that
        # first growth is to fill the remainder of any unused extent.
        self.base = int(lv.vg.align(lv.size, roundup=True) // lv.vg.pe_size)

        if lv.req_grow:
            limits = [int(l // lv.vg.pe_size) for l in
                      (lv.vg.align(lv.req_max_size),
                       lv.vg.align(lv.format.max_size)) if l > Size(0)]

            if limits:
                max_units = min(limits)
                self.max_growth = max_units - self.base
                if self.max_growth <= 0:
                    # max size is less than or equal to base, so we're done
                    self.done = True

    @property
    def reserve_request(self):
        lv = self.device
        reserve = super(LVRequest, self).reserve_request
        if lv.cached:
            reserve += int(lv.vg.align(lv.cache.size, roundup=True) / lv.vg.pe_size)
        reserve += int(lv.vg.align(lv.metadata_vg_space_used, roundup=True) / lv.vg.pe_size)
        return reserve


class Chunk(object):

    """ A free region from which devices will be allocated """

    def __init__(self, length, requests=None):
        """
            :param length: the length of the chunk (units vary with subclass)
            :type length: int
            :keyword requests: list of requests to add
            :type requests: list of :class:`Request`
        """
        if not hasattr(self, "path"):
            self.path = None
        self.length = length
        self.pool = length                  # free unit count
        self.base = 0                       # sum of growable requests' base
        # sizes
        self.requests = []                  # list of Request instances
        if isinstance(requests, list):
            for req in requests:
                self.add_request(req)

        self.skip_list = []

    def __repr__(self):
        s = ("%(type)s instance --\n"
             "device = %(device)s  length = %(length)d  size = %(size)s\n"
             "remaining = %(rem)d  pool = %(pool)d" %
             {"type": self.__class__.__name__, "device": self.path,
              "length": self.length, "size": self.length_to_size(self.length),
              "pool": self.pool, "rem": self.remaining})

        return s

    # Force str and unicode types in case path is unicode
    def _to_string(self):
        s = "%d on %s" % (self.length, self.path)
        return s

    def __str__(self):
        return stringize(self._to_string())

    def __unicode__(self):
        return unicodeize(self._to_string())

    def add_request(self, req):
        """ Add a request to this chunk.

            :param req: the request to add
            :type req: :class:`Request`
        """
        log.debug("adding request %d to chunk %s", req.device.id, self)

        self.requests.append(req)
        self.pool -= req.base
        self.pool -= req.reserve_request

        if not req.done:
            self.base += req.base

    def reclaim(self, request, amount):
        """ Reclaim units from a request and return them to the pool.

            :param request: the request to reclaim units from
            :type request: :class:`Request`
            :param amount: number of units to reclaim from the request
            :type amount: int
            :raises: ValueError
            :returns: None
        """
        log.debug("reclaim: %s %d (%s)", request, amount, self.length_to_size(amount))
        if request.growth < amount:
            log.error("tried to reclaim %d from request with %d of growth",
                      amount, request.growth)
            raise ValueError(_("cannot reclaim more than request has grown"))

        request.growth -= amount
        self.pool += amount

        # put this request in the skip list so we don't try to grow it the
        # next time we call grow_requests to allocate the newly re-acquired pool
        if request not in self.skip_list:
            self.skip_list.append(request)

    @property
    def growth(self):
        """ Sum of growth for all requests in this chunk. """
        return sum(r.growth for r in self.requests)

    @property
    def has_growable(self):
        """ True if this chunk contains at least one growable request. """
        for req in self.requests:
            if req.growable:
                return True
        return False

    @property
    def remaining(self):
        """ Number of requests still being grown in this chunk. """
        return len([d for d in self.requests if not d.done])

    @property
    def done(self):
        """ True if we are finished growing all requests in this chunk. """
        return self.remaining == 0 or self.pool == 0

    def max_growth(self, req):
        return req.max_growth

    def length_to_size(self, length):
        return length

    def size_to_length(self, size):
        return size

    def trim_over_grown_request(self, req, base=None):
        """ Enforce max growth and return extra units to the pool.

            :param req: the request to trim
            :type req: :class:`Request`
            :keyword base: base unit count to adjust if req is done growing
            :type base: int
            :returns: the new base or None if no base was given
            :rtype: int or None
        """
        max_growth = self.max_growth(req)
        if max_growth and req.growth >= max_growth:
            if req.growth > max_growth:
                # we've grown beyond the maximum. put some back.
                extra = req.growth - max_growth
                log.debug("taking back %d (%s) from %d (%s)",
                          extra, self.length_to_size(extra),
                          req.device.id, req.device.name)
                self.pool += extra
                req.growth = max_growth

            # We're done growing this request, so it no longer
            # factors into the growable base used to determine
            # what fraction of the pool each request gets.
            if base is not None:
                base -= req.base
            req.done = True

        return base

    def sort_requests(self):
        pass

    def grow_requests(self, uniform=False):
        """ Calculate growth amounts for requests in this chunk.

            :keyword uniform: grow requests uniformly instead of proportionally
            :type uniform: bool

            The default mode of growth is as follows: given a total number of
            available units, requests receive an allotment proportional to their
            base sizes. That means a request with base size 1000 will grow four
            times as fast as a request with base size 250.

            Under uniform growth, all requests receive an equal portion of the
            free units.
        """
        log.debug("Chunk.grow_requests: %r", self)

        self.sort_requests()
        for req in self.requests:
            log.debug("req: %r", req)

        # we use this to hold the base for the next loop through the
        # chunk's requests since we want the base to be the same for
        # all requests in any given growth iteration
        new_base = self.base
        last_pool = 0  # used to track changes to the pool across iterations
        while not self.done and self.pool and last_pool != self.pool:
            last_pool = self.pool    # to keep from getting stuck
            self.base = new_base
            if uniform:
                growth = int(last_pool / self.remaining)

            log.debug("%d requests and %s (%s) left in chunk",
                      self.remaining, self.pool, self.length_to_size(self.pool))
            for p in self.requests:
                if p.done or p in self.skip_list:
                    continue

                if not uniform:
                    # Each request is allocated free units from the pool
                    # based on the relative _base_ sizes of the remaining
                    # growable requests.
                    share = Decimal(p.base) / Decimal(self.base)
                    growth = int(share * last_pool)  # truncate, don't round

                p.growth += growth
                self.pool -= growth
                log.debug("adding %s (%s) to %d (%s)",
                          growth, self.length_to_size(growth),
                          p.device.id, p.device.name)

                new_base = self.trim_over_grown_request(p, base=new_base)
                log.debug("new grow amount for request %d (%s) is %s "
                          "units, or %s",
                          p.device.id, p.device.name, p.growth,
                          self.length_to_size(p.growth))

        if self.pool:
            # allocate any leftovers in pool to the first partition
            # that can still grow
            for p in self.requests:
                if p.done or p in self.skip_list:
                    continue

                growth = self.pool
                p.growth += growth
                self.pool = 0
                log.debug("adding %s (%s) to %d (%s)",
                          growth, self.length_to_size(growth),
                          p.device.id, p.device.name)

                self.trim_over_grown_request(p)
                log.debug("new grow amount for request %d (%s) is %s "
                          "units, or %s",
                          p.device.id, p.device.name, p.growth,
                          self.length_to_size(p.growth))

                if self.pool == 0:
                    break

        # requests that were skipped over this time through are back on the
        # table next time
        self.skip_list = []


class DiskChunk(Chunk):

    """ A free region on disk from which partitions will be allocated """

    def __init__(self, geometry, requests=None):
        """
            :param geometry: the free region this chunk represents
            :type geometry: :class:`parted.Geometry`
            :keyword requests: list of requests to add initially
            :type requests: list of :class:`PartitionRequest`

            .. note::

                We will limit partition growth based on disklabel limitations
                for partition end sector, so a 10TB disk with an msdos disklabel
                will be treated like a 2TiB disk.

            .. note::

                If you plan to allocate aligned partitions you should pass in an
                aligned geometry instance.

        """
        self.geometry = geometry            # parted.Geometry
        self.sector_size = Size(self.geometry.device.sectorSize)
        self.path = self.geometry.device.path
        super(DiskChunk, self).__init__(self.geometry.length, requests=requests)

    def __repr__(self):
        s = super(DiskChunk, self).__str__()
        s += (" start = %(start)d  end = %(end)d\n"
              "sector_size = %(sector_size)s\n" %
              {"start": self.geometry.start, "end": self.geometry.end,
               "sector_size": self.sector_size})
        return s

    # Force str and unicode types in case path is unicode
    def _to_string(self):
        s = "%d (%d-%d) on %s" % (self.length, self.geometry.start,
                                  self.geometry.end, self.path)
        return s

    def __str__(self):
        return stringize(self._to_string())

    def __unicode__(self):
        return unicodeize(self._to_string())

    def add_request(self, req):
        """ Add a request to this chunk.

            :param req: the request to add
            :type req: :class:`PartitionRequest`
        """
        if not isinstance(req, PartitionRequest):
            raise ValueError(_("DiskChunk requests must be of type "
                               "PartitionRequest"))

        if not self.requests:
            # when adding the first request to the chunk, adjust the pool
            # size to reflect any disklabel-specific limits on end sector
            max_sector = req.device.parted_partition.disk.maxPartitionStartSector
            chunk_end = min(max_sector, self.geometry.end)
            if chunk_end <= self.geometry.start:
                # this should clearly never be possible, but if the chunk's
                # start sector is beyond the maximum allowed end sector, we
                # cannot continue
                log.error("chunk start sector is beyond disklabel maximum")
                raise PartitioningError(_("partitions allocated outside "
                                          "disklabel limits"))

            new_pool = chunk_end - self.geometry.start + 1
            if new_pool != self.pool:
                log.debug("adjusting pool to %d based on disklabel limits", new_pool)
                self.pool = new_pool

        super(DiskChunk, self).add_request(req)

    def max_growth(self, req):
        """ Return the maximum possible growth for a request.

            :param req: the request
            :type req: :class:`PartitionRequest`
        """
        req_end = req.device.parted_partition.geometry.end
        req_start = req.device.parted_partition.geometry.start

        # Establish the current total number of sectors of growth for requests
        # that lie before this one within this chunk. We add the total count
        # to this request's end sector to obtain the end sector for this
        # request, including growth of earlier requests but not including
        # growth of this request. Maximum growth values are obtained using
        # this end sector and various values for maximum end sector.
        growth = 0
        for request in self.requests:
            if request.device.parted_partition.geometry.start < req_start:
                growth += request.growth
        req_end += growth

        # obtain the set of possible maximum sectors-of-growth values for this
        # request and use the smallest
        limits = []

        # disklabel-specific maximum sector
        max_sector = req.device.parted_partition.disk.maxPartitionStartSector
        limits.append(max_sector - req_end)

        # 2TB limit on bootable partitions, regardless of disklabel
        if req.device.req_bootable:
            max_boot = size_to_sectors(Size("2 TiB"), self.sector_size)
            limits.append(max_boot - req_end)

        # request-specific maximum (see Request.__init__, above, for details)
        if req.max_growth:
            limits.append(req.max_growth)

        max_growth = min(limits)
        return max_growth

    def length_to_size(self, length):
        return sectors_to_size(length, self.sector_size)

    def size_to_length(self, size):
        return size_to_sectors(size, self.sector_size)

    def sort_requests(self):
        # sort the partitions by start sector
        self.requests.sort(key=lambda r: r.device.parted_partition.geometry.start)


class VGChunk(Chunk):

    """ A free region in an LVM VG from which LVs will be allocated """

    def __init__(self, vg, requests=None):
        """
            :param vg: the volume group whose free space this chunk represents
            :type vg: :class:`~.devices.LVMVolumeGroupDevice`
            :keyword requests: list of requests to add initially
            :type requests: list of :class:`LVRequest`
        """
        self.vg = vg
        self.path = vg.path
        usable_extents = vg.extents - int(vg.align(vg.reserved_space, roundup=True) / vg.pe_size)
        super(VGChunk, self).__init__(usable_extents, requests=requests)

    def add_request(self, req):
        """ Add a request to this chunk.

            :param req: the request to add
            :type req: :class:`LVRequest`
        """
        if not isinstance(req, LVRequest):
            raise ValueError(_("VGChunk requests must be of type "
                               "LVRequest"))

        super(VGChunk, self).add_request(req)

    def length_to_size(self, length):
        return self.vg.pe_size * length

    def size_to_length(self, size):
        return int(size / self.vg.pe_size)

    def sort_requests(self):
        # sort the partitions by start sector
        self.requests.sort(key=_lv_compare_key)


class ThinPoolChunk(VGChunk):

    """ A free region in an LVM thin pool from which LVs will be allocated """

    def __init__(self, pool, requests=None):
        """
            :param pool: the thin pool whose free space this chunk represents
            :type pool: :class:`~.devices.LVMLogicalVolumeDevice`
            :keyword requests: list of requests to add initially
            :type requests: list of :class:`LVRequest`
        """
        self.vg = pool.vg   # only used for align, &c
        self.path = pool.path
        usable_extents = (pool.size / pool.vg.pe_size)
        super(VGChunk, self).__init__(usable_extents, requests=requests)  # pylint: disable=bad-super-call


def get_disk_chunks(disk, partitions, free):
    """ Return a list of Chunk instances representing a disk.

        :param disk: the disk
        :type disk: :class:`~.devices.StorageDevice`
        :param partitions: list of partitions
        :type partitions: list of :class:`~.devices.PartitionDevice`
        :param free: list of free regions
        :type free: list of :class:`parted.Geometry`
        :returns: list of chunks representing the disk
        :rtype: list of :class:`DiskChunk`

        Partitions and free regions not on the specified disk are ignored.

        Chunks contain an aligned version of the free region's geometry.
    """
    # list of all new partitions on this disk
    disk_parts = [p for p in partitions if p.disk == disk and not p.exists]
    disk_free = [f for f in free if f.device.path == disk.path]

    chunks = []
    for f in disk_free[:]:
        # Align the geometry so we have a realistic view of the free space.
        # alignUp and alignDown can align in the reverse direction if the only
        # aligned sector within the geometry is in that direction, so we have to
        # also check that the resulting aligned geometry has a non-zero length.
        # (It is possible that both will align to the same sector in a small
        #  enough region.)
        try:
            size = sectors_to_size(f.length, disk.format.sector_size)
            alignment = disk.format.get_alignment(size=size)
            end_alignment = disk.format.get_end_alignment(alignment=alignment)
        except AlignmentError:
            disk_free.remove(f)
            continue

        al_start = alignment.alignUp(f, f.start)
        al_end = end_alignment.alignDown(f, f.end)
        if al_start >= al_end:
            disk_free.remove(f)
            continue
        geom = parted.Geometry(device=f.device,
                               start=al_start,
                               end=al_end)
        if geom.length < alignment.grainSize:
            disk_free.remove(f)
            continue

        chunks.append(DiskChunk(geom))

    for p in disk_parts:
        if p.is_extended:
            # handle extended partitions specially since they are
            # indeed very special
            continue

        for i, f in enumerate(disk_free):
            if f.contains(p.parted_partition.geometry):
                chunks[i].add_request(PartitionRequest(p))
                break

    return chunks


class TotalSizeSet(object):

    """ Set of device requests with a target combined size.

        This will be handled by growing the requests until the desired combined
        size has been achieved.
    """

    def __init__(self, devices, size):
        """
            :param devices: the set of devices
            :type devices: list of :class:`~.devices.PartitionDevice`
            :param size: the target combined size
            :type size: :class:`~.size.Size`
        """
        self.devices = [d.raw_device for d in devices]
        self.size = size

        self.requests = []

        self.allocated = sum((d.req_base_size for d in self.devices), Size(0))
        log.debug("set.allocated = %d", self.allocated)

    def allocate(self, amount):
        log.debug("allocating %d to TotalSizeSet with %d/%d (%d needed)",
                  amount, self.allocated, self.size, self.needed)
        self.allocated += amount

    @property
    def needed(self):
        return self.size - self.allocated

    def deallocate(self, amount):
        log.debug("deallocating %d from TotalSizeSet with %d/%d (%d needed)",
                  amount, self.allocated, self.size, self.needed)
        self.allocated -= amount


class SameSizeSet(object):

    """ Set of device requests with a common target size. """

    def __init__(self, devices, size, grow=False, max_size=None):
        """
            :param devices: the set of devices
            :type devices: list of :class:`~.devices.PartitionDevice`
            :param size: target size for each device/request
            :type size: :class:`~.size.Size`
            :keyword grow: whether the devices can be grown
            :type grow: bool
            :keyword max_size: the maximum size for growable devices
            :type max_size: :class:`~.size.Size`
        """
        self.devices = [d.raw_device for d in devices]
        self.size = size / len(devices)
        self.grow = grow
        self.max_size = max_size

        self.requests = []


def manage_size_sets(size_sets, chunks):
    growth_by_request = {}
    requests_by_device = {}
    chunks_by_request = {}
    for chunk in chunks:
        for request in chunk.requests:
            requests_by_device[request.device] = request
            chunks_by_request[request] = chunk
            growth_by_request[request] = 0

    for i in range(2):
        reclaimed = dict([(chunk, 0) for chunk in chunks])
        for ss in size_sets:
            if isinstance(ss, TotalSizeSet):
                # TotalSizeSet members are trimmed to achieve the requested
                # total size
                log.debug("set: %s %d/%d", [d.name for d in ss.devices],
                          ss.allocated, ss.size)

                for device in ss.devices:
                    request = requests_by_device[device]
                    chunk = chunks_by_request[request]
                    new_growth = request.growth - growth_by_request[request]
                    ss.allocate(chunk.length_to_size(new_growth))

                # decide how much to take back from each request
                # We may assume that all requests have the same base size.
                # We're shooting for a roughly equal distribution by trimming
                # growth from the requests that have grown the most first.
                requests = sorted([requests_by_device[d] for d in ss.devices],
                                  key=lambda r: r.growth, reverse=True)
                needed = ss.needed
                for request in requests:
                    chunk = chunks_by_request[request]
                    log.debug("%s", request)
                    log.debug("needed: %d", ss.needed)

                    if ss.needed < 0:
                        # it would be good to take back some from each device
                        # instead of taking all from the last one(s)
                        extra = -chunk.size_to_length(needed) // len(ss.devices)
                        if extra > request.growth and i == 0:
                            log.debug("not reclaiming from this request")
                            continue
                        else:
                            extra = min(extra, request.growth)

                        reclaimed[chunk] += extra
                        chunk.reclaim(request, extra)
                        ss.deallocate(chunk.length_to_size(extra))

                    if ss.needed <= 0:
                        request.done = True

            elif isinstance(ss, SameSizeSet):
                # SameSizeSet members all have the same size as the smallest
                # member
                requests = [requests_by_device[d] for d in ss.devices]
                _min_growth = min([r.growth for r in requests])
                log.debug("set: %s %d", [d.name for d in ss.devices], ss.size)
                log.debug("min growth is %d", _min_growth)
                for request in requests:
                    chunk = chunks_by_request[request]
                    _max_growth = chunk.size_to_length(ss.size) - request.base
                    log.debug("max growth for %s is %d", request, _max_growth)
                    min_growth = max(min(_min_growth, _max_growth), 0)
                    if request.growth > min_growth:
                        extra = request.growth - min_growth
                        reclaimed[chunk] += extra
                        chunk.reclaim(request, extra)
                        request.done = True
                    elif request.growth == min_growth:
                        request.done = True

        # store previous growth amounts so we know how much was allocated in
        # the latest grow_requests call
        for request in growth_by_request.keys():
            growth_by_request[request] = request.growth

        for chunk in chunks:
            if reclaimed[chunk] and not chunk.done:
                chunk.grow_requests()


def grow_partitions(disks, partitions, free, size_sets=None):
    """ Grow all growable partition requests.

        Partitions have already been allocated from chunks of free space on
        the disks. This function does not modify the ordering of partitions
        or the free chunks from which they are allocated.

        Free space within a given chunk is allocated to each growable
        partition allocated from that chunk in an amount corresponding to
        the ratio of that partition's base size to the sum of the base sizes
        of all growable partitions allocated from the chunk.

        :param disks: all usable disks
        :type disks: list of :class:`~.devices.StorageDevice`
        :param partitions: all partitions
        :type partitions: list of :class:`~.devices.PartitionDevice`
        :param free: all free regions on disks
        :type free: list of :class:`parted.Geometry`
        :keyword size_sets: list of size-related partition sets
        :type size_sets: list of :class:`TotalSizeSet` or :class:`SameSizeSet`
        :returns: :const:`None`
    """
    log.debug("grow_partitions: disks=%s, partitions=%s",
              [d.name for d in disks],
              ["%s(id %d)" % (p.name, p.id) for p in partitions])
    all_growable = [p for p in partitions if p.req_grow]
    if not all_growable:
        log.debug("no growable partitions")
        return

    if size_sets is None:
        size_sets = []

    log.debug("growable partitions are %s", [p.name for p in all_growable])

    #
    # collect info about each disk and the requests it contains
    #
    chunks = []
    for disk in disks:
        # list of free space regions on this disk prior to partition allocation
        disk_free = [f for f in free if f.device.path == disk.path]
        if not disk_free:
            log.debug("no free space on %s", disk.name)
            continue

        disk_chunks = get_disk_chunks(disk, partitions, disk_free)
        log.debug("disk %s has %d chunks", disk.name, len(disk_chunks))
        chunks.extend(disk_chunks)

    #
    # grow the partitions in each chunk as a group
    #
    for chunk in chunks:
        if not chunk.has_growable:
            # no growable partitions in this chunk
            continue

        chunk.grow_requests()

    # adjust set members' growth amounts as needed
    manage_size_sets(size_sets, chunks)

    for disk in disks:
        log.debug("growing partitions on %s", disk.name)
        for chunk in chunks:
            if chunk.path != disk.path:
                continue

            if not chunk.has_growable:
                # no growable partitions in this chunk
                continue

            # recalculate partition geometries
            disklabel = disk.format
            start = chunk.geometry.start
            default_alignment = disklabel.get_alignment()

            # find any extended partition on this disk
            extended_geometry = getattr(disklabel.extended_partition,
                                        "geometry",
                                        None)  # parted.Geometry

            # align start sector as needed
            if not default_alignment.isAligned(chunk.geometry, start):
                start = default_alignment.alignUp(chunk.geometry, start)
            new_partitions = []
            for p in chunk.requests:
                ptype = p.device.parted_partition.type
                log.debug("partition %s (%d): %s", p.device.name,
                          p.device.id, ptype)
                if ptype == parted.PARTITION_EXTENDED:
                    continue

                new_length = p.base + p.growth
                alignment = disklabel.get_alignment(size=chunk.length_to_size(new_length))
                end_alignment = disklabel.get_end_alignment(alignment=alignment)
                # XXX since we need one metadata sector before each
                #     logical partition we burn one logical block to
                #     safely align the start of each logical partition
                if ptype == parted.PARTITION_LOGICAL:
                    start += alignment.grainSize

                end = start + new_length - 1
                # align end sector as needed
                if not end_alignment.isAligned(chunk.geometry, end):
                    end = end_alignment.alignDown(chunk.geometry, end)
                new_geometry = parted.Geometry(device=disklabel.parted_device,
                                               start=start,
                                               end=end)
                log.debug("new geometry for %s: %s", p.device.name,
                          new_geometry)
                start = end + 1
                new_partition = parted.Partition(disk=disklabel.parted_disk,
                                                 type=ptype,
                                                 geometry=new_geometry)
                new_partitions.append((new_partition, p.device))

            # remove all new partitions from this chunk
            remove_new_partitions([disk], [r.device for r in chunk.requests],
                                  partitions)
            log.debug("back from remove_new_partitions")

            # adjust the extended partition as needed
            # we will ony resize an extended partition that we created
            log.debug("extended: %s", extended_geometry)
            if extended_geometry and \
               chunk.geometry.contains(extended_geometry):
                log.debug("setting up new geometry for extended on %s", disk.name)
                ext_start = 0
                for (partition, device) in new_partitions:
                    if partition.type != parted.PARTITION_LOGICAL:
                        continue

                    if not ext_start or partition.geometry.start < ext_start:
                        # account for the logical block difference in start
                        # sector for the extended -v- first logical
                        # (partition.geometry.start is already aligned)
                        ext_start = partition.geometry.start - default_alignment.grainSize

                new_geometry = parted.Geometry(device=disklabel.parted_device,
                                               start=ext_start,
                                               end=chunk.geometry.end)
                log.debug("new geometry for extended: %s", new_geometry)
                new_extended = parted.Partition(disk=disklabel.parted_disk,
                                                type=parted.PARTITION_EXTENDED,
                                                geometry=new_geometry)
                ptypes = [p.type for (p, d) in new_partitions]
                for pt_idx, ptype in enumerate(ptypes):
                    if ptype == parted.PARTITION_LOGICAL:
                        new_partitions.insert(pt_idx, (new_extended, None))
                        break

            # add the partitions with their new geometries to the disk
            for (partition, device) in new_partitions:
                if device:
                    name = device.name
                else:
                    # If there was no extended partition on this disk when
                    # do_partitioning was called we won't have a
                    # PartitionDevice instance for it.
                    name = partition.getDeviceNodeName()

                log.debug("setting %s new geometry: %s", name,
                          partition.geometry)
                constraint = parted.Constraint(exactGeom=partition.geometry)
                disklabel.parted_disk.addPartition(partition=partition,
                                                   constraint=constraint)
                path = partition.path
                if device:
                    # set the device's name
                    device.parted_partition = partition
                    # without this, the path attr will be a basename. eek.
                    device.disk = disk

                    # make sure we store the disk's version of the partition
                    newpart = disklabel.parted_disk.getPartitionByPath(path)
                    device.parted_partition = newpart


def lv_compare(lv1, lv2):
    """ More specifically defined lvs come first.

        < 1 => x < y
          0 => x == y
        > 1 => x > y
    """
    if not isinstance(lv1, Device):
        lv1 = lv1.device
    if not isinstance(lv2, Device):
        lv2 = lv2.device

    ret = 0

    # larger requests go to the front of the list
    ret -= compare(lv1.size, lv2.size) * 100

    # fixed size requests to the front
    ret += compare(lv1.req_grow, lv2.req_grow) * 50

    # potentially larger growable requests go to the front
    if lv1.req_grow and lv2.req_grow:
        if not lv1.req_max_size and lv2.req_max_size:
            ret -= 25
        elif lv1.req_max_size and not lv2.req_max_size:
            ret += 25
        else:
            ret -= compare(lv1.req_max_size, lv2.req_max_size) * 25

    if ret > 0:
        ret = 1
    elif ret < 0:
        ret = -1

    return ret


_lv_compare_key = functools.cmp_to_key(lv_compare)


def _apply_chunk_growth(chunk):
    """ grow the lvs by the amounts the VGChunk calculated """
    for req in chunk.requests:
        if not req.device.req_grow:
            continue

        size = chunk.length_to_size(req.base + req.growth)

        # Base is pe, which means potentially rounded up by as much as
        # pesize-1. As a result, you can't just add the growth to the
        # initial size.
        req.device.size = size


def grow_lvm(storage):
    """ Grow LVs according to the sizes of the PVs.

        Strategy for growth involving thin pools:
            - Applies to device factory class as well.
            - Overcommit is not allowed.
            - Pool lv's base size includes sizes of thin lvs within it.
            - Pool is grown along with other non-thin lvs.
            - Thin lvs within each pool are grown separately using the
              ThinPoolChunk class.
    """
    for vg in storage.vgs:
        total_free = vg.free_space
        if total_free < 0:
            # by now we have allocated the PVs so if there isn't enough
            # space in the VG we have a real problem
            raise PartitioningError(_("not enough space for LVM requests"))
        elif not total_free:
            log.debug("vg %s has no free space", vg.name)
            continue

        log.debug("vg %s: %s free ; lvs: %s", vg.name, total_free,
                  [l.lvname for l in vg.lvs])

        # don't include thin lvs in the vg's growth calculation
        fatlvs = [lv for lv in vg.lvs if lv not in vg.thinlvs]
        requests = []
        for lv in fatlvs:
            if lv in vg.thinpools:
                # make sure the pool's base size is at least the sum of its lvs'
                lv.req_size = max(lv.min_size, lv.req_size, lv.used_space)
                lv.size = lv.req_size

        # establish sizes for the percentage-based requests (which are fixed)
        percentage_based_lvs = [lv for lv in vg.lvs if lv.req_percent]
        if sum(lv.req_percent for lv in percentage_based_lvs) > 100:
            raise ValueError("sum of percentages within a vg cannot exceed 100")

        percent_base = sum(vg.align(lv.req_size, roundup=False) / vg.pe_size
                           for lv in percentage_based_lvs)
        percentage_basis = vg.free_extents + percent_base
        for lv in percentage_based_lvs:
            new_extents = int(lv.req_percent * Decimal('0.01') * percentage_basis)
            # set req_size also so the request can also be growable if desired
            lv.size = lv.req_size = vg.pe_size * new_extents

        # grow regular lvs
        chunk = VGChunk(vg, requests=[LVRequest(l) for l in fatlvs])
        chunk.grow_requests()
        _apply_chunk_growth(chunk)

        # now that we have grown all thin pools (if any), let's calculate and
        # set their metadata size if not told otherwise
        for pool in vg.thinpools:
            orig_pmspare_size = vg.pmspare_size
            if not pool.exists and pool.metadata_size == Size(0):
                pool.autoset_md_size()
            if vg.pmspare_size != orig_pmspare_size:
                # pmspare size change caused by the above step, let's trade part
                # of pool's space for it
                pool.size -= vg.pmspare_size - orig_pmspare_size

        # now, grow thin lv requests within their respective pools
        for pool in vg.thinpools:
            requests = [LVRequest(l) for l in pool.lvs]
            thin_chunk = ThinPoolChunk(pool, requests)
            thin_chunk.grow_requests()
            _apply_chunk_growth(thin_chunk)
