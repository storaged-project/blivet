"""

Canned device stacks:

    partition
        (luks-)partition
    btrfs
        btrfs-(luks-)partition
    md
        (luks-)md-partition
    lvm
        lv-vg-(luks-)partition
        lv-vg-(luks-)md-partition

    Partitions can always be encrypted unless they are md members?

    Should formatting be handled in make_whatever or by caller?

    Convenience functions:

        - possible size range based on device parameters and members/container
        - possible size range based on device parameters and disk set

    TODO

        - register actions or only collect and return them?
        - size set management
        - argument uniformity?
        - naming for lvs, mds, btrfs subvols
        - at what point are we going to allocate partitions?
            - doing it late means containers have to omit capacity checks when
              we allocate devices from them
            - doing it early means setting things up breadth-first since we'd
              need to know about all the partitions before running doPartitining

"""
from pyanaconda.storage.formats import getFormat
from pyanaconda.storage.devices import LUKSDevice

def make_format(storage, device, type, mountpoint=None):
    fmt = getFormat(type, device=device.path, mountpoint=mountpoint)

    # should we be returning a list of actions?
    storage.formatDevice(device, fmt)

def make_luks(storage, parent):
    # create the luks device
    make_format(storage, parent, "luks")
    device = LUKSDevice("luks%d" % storage.nextID, parents=[parent])
    return device

def make_partition(storage, disk, size=None):
    # create the partition
    device = storage.newPartition(parents=[disk], size=size)
    return device

def make_md(storage, name, size, level, disks):
    # figure out the size each member needs to be
    # XXX this probably won't work when also using existing member devices
    member_size = get_raid_member_size(level, size, disks=disks)

    members = []

    for disk in disks:
        member = make_partition(storage, disk, size=member_size))
        make_format(storage, member, "mdmember")
        members.append(member)

    # create the md
    device = storage.newMDArray(name, level=level, parents=members)
    return device

def make_vg(storage, name, size, disks, encrypted=False):
    # XXX TODO: determine member sizes
    members = []
    size = get_required_pv_space(size
    for disk in disks:
        member = make_partition(storage, disk, size=size)

        if encrypted:
            luksdev = make_luks(member)
            member = luksdev

        make_format(storage, member, "lvmpv")
        members.append(member)

    # create the vg
    device = storage.newVG(name, members)
    return device

def make_lv(storage, name, size, disks,
            encrypted=False, mirrors=0, container=None):
    member_size = get_required_pv_space()

    # adjustment of the container should be handled elsewhere
    if not container:
        container = make_vg(storage, None, size, disks, encrypted=encrypted)

    # create the lv
    device = storage.newLV(name, size, parents=[container])
    return device

def make_btrfs_volume(storage, size, disks,
                      data=None, meta=None, encrypted=False):
    if level is None:
        level = "single"

    # XXX TODO: determine member sizes

    members = []
    for disk in disks:
        member = make_partition(storage, disk)
        member.set_total = size

        if encrypted:
            luksdev = make_luks(member)
            member = luksdev

        make_format(storage, member, "btrfs")
        members.append(member)

    # create the volume
    device = storage.newBTRFS(parents=members,
                              dataLevel=data, metaDataLevel=meta)
    return device

def make_btrfs_subvolume(storage, size, disks,
                         data=None, meta=None, encrypted=False,
                         container=None):
    # adjustment of the container should be handled elsewhere
    if not container:
        container = make_btrfs_volume(storage, size, disks,
                                      data=data, meta=meta,
                                      encrypted=encrypted)

    # create the subvolume
    device = storage.newBTRFSSubVolume(parents=[container])
    return device

##
## container device convenience functions
##
def change_container_disks(container, new_disks):
    """ Change the set of disks from which a container may allocate members. """
    # this is going to contain the basic logic for deciding the various sizes
    # of the member devices across the disk set
    pass

def allocate_container_members(, disks):
    # collect information about free space on disks
    usage = [DiskUsage(d) for d in disks]

    # determine the required set or member sizes based on the container
    #
    # uniform: anything striped or mirrored
    # total: linear lvm, linear btrfs
    #
    total = 0
    member_size = 0



    # allocate the members
    #
    # Methodology for total size sets
    #
    # XXX To start, let's try just creating requests and calling doPartitioning
    #
    #   uniform
    #       easier to use doPartitioning
    #       allows for later conversion to add raid features
    #       less likely to succeed
    #
    #   greedy
    #       harder to use doPartitioning
    #       more flexible (most likely to succeed)
    #       may not use all disks
    #
    allocated = 0
    for u in usage:
        size = 0
        region = None
        for r in u.free_regions:

        allocated += size


def resize_container(container, new_size):
    """ Resize a container by resizing some of its constituent devices. """
    pass

def add_container_member(container, member):
    """ Add a new member device to a container. """
    pass

##
## disk free space information
##
class FreeRegion(object):
    def __init__(self, disk, start, end, resize=None):
        # we could just pass in a parted.Geometry if we weren't ever going to
        # modify them, eg: to add in some space gained by a resize
        self.disk = disk
        self.start = start
        self.end = end

        self.resize = resize

    @property
    def size(self):
        return Size(bytes=((self.end - self.start) * self.sector_size))

    @property
    def sector_size(self):
        return self.disk.partedDevice.sectorSize

    @property
    def in_extended(self):
        extended = self.disk.format.extendedPartition
        return (extended is not None and
                extended.geometry.containsSector(self.start))

    @property
    def bootable(self):
        return self.start < 2**32

class ResizeRegion(object):
    def __init__(self, device):
        self.device = device

    @property
    def size(self):
        size_mb = 0
        if self.device.resizable:
            size_mb = (self.device.currentSize - self.device.minSize)

        return Size(spec="%f MB" % size_mb)

class DiskUsage(object):
    def __init__(self, disk, devices=None):
        self.disk = disk
        self.free_regions = []
        self.devices = []

        if devices:
            self.set_device_list(devices)

        self.get_free_regions()

    def set_device_list(self, devices):
        self.devices = devices

        # the device list was updated so we should update the free regions also
        self.find_free_regions()

    @property
    def sector_size(self):
        return self.disk.partedDevice.sectorSize

    def find_free_regions(self):
        # XXX What's the minimum size we keep? For now, 2MB.
        self.free_regions = []

        partitions = {}
        for d in self.devices:
            try:
                end_sector = d.partedPartition.geometry.end
            except AttributeError:
                continue

            resize[end_sector] = ResizeRegion(d)

        free = self.disk.format.partedDisk.getFreeSpaceRegions()
        free.sort(key=lambda g: g.start)
        for f in free:
            self.free_regions.append(DiskRegion(self.disk, f.start, f.end,
                                                resize.get(f.start - 1)))


