# devicefactory.py
# Creation of devices based on a top-down specification.
#
# Copyright (C) 2012, 2013  Red Hat, Inc.
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

from storage_log import log_method_call
from errors import *
from devices import LUKSDevice
from formats import getFormat
from devicelibs.mdraid import get_member_space
from devicelibs.mdraid import raidLevelString
from devicelibs.lvm import get_pv_space
from .partitioning import SameSizeSet
from .partitioning import TotalSizeSet
from .partitioning import doPartitioning

import gettext
_ = lambda x: gettext.ldgettext("anaconda", x)

import logging
log = logging.getLogger("storage")

DEVICE_TYPE_LVM = 0
DEVICE_TYPE_MD = 1
DEVICE_TYPE_PARTITION = 2
DEVICE_TYPE_BTRFS = 3
DEVICE_TYPE_DISK = 4

def get_device_type(device):
    device_types = {"partition": DEVICE_TYPE_PARTITION,
                    "lvmlv": DEVICE_TYPE_LVM,
                    "btrfs subvolume": DEVICE_TYPE_BTRFS,
                    "btrfs volume": DEVICE_TYPE_BTRFS,
                    "mdarray": DEVICE_TYPE_MD}

    use_dev = device
    if isinstance(device, LUKSDevice):
        use_dev = device.slave

    if use_dev.isDisk:
        device_type = DEVICE_TYPE_DISK
    else:
        device_type = device_types.get(use_dev.type)

    return device_type

def get_raid_level(device):
    # TODO: move this into StorageDevice
    use_dev = device
    if isinstance(device, LUKSDevice):
        use_dev = device.slave

    # TODO: lvm and perhaps pulling raid level from md pvs
    raid_level = None
    if hasattr(use_dev, "level"):
        raid_level = raidLevelString(use_dev.level)
    elif hasattr(use_dev, "dataLevel"):
        raid_level = use_dev.dataLevel or "single"
    elif hasattr(use_dev, "volume"):
        raid_level = use_dev.volume.dataLevel or "single"

    return raid_level

def get_device_factory(blivet, device_type, size, **kwargs):
    """ Return a suitable DeviceFactory instance for device_type. """
    disks = kwargs.get("disks", [])
    raid_level = kwargs.get("raid_level")
    encrypted = kwargs.get("encrypted", False)

    class_table = {DEVICE_TYPE_LVM: LVMFactory,
                   DEVICE_TYPE_BTRFS: BTRFSFactory,
                   DEVICE_TYPE_PARTITION: PartitionFactory,
                   DEVICE_TYPE_MD: MDFactory,
                   DEVICE_TYPE_DISK: DiskFactory}

    factory_class = class_table[device_type]
    log.debug("instantiating %s: %r, %s, %s, %s" % (factory_class,
                blivet, size, [d.name for d in disks], raid_level))
    return factory_class(blivet, size, disks, raid_level, encrypted)

class DeviceFactory(object):
    type_desc = None
    member_format = None        # format type for member devices
    new_container_attr = None   # name of Blivet method to create a container
    new_device_attr = None      # name of Blivet method to create a device
    container_list_attr = None  # name of Blivet attribute to list containers
    encrypt_members = False
    encrypt_leaves = True

    def __init__(self, storage, size, disks, raid_level, encrypted):
        self.storage = storage          # the Blivet instance
        self.size = size                # the requested size for this device
        self.disks = disks              # the set of disks to allocate from
        self.raid_level = raid_level
        self.encrypted = encrypted

        # this is a list of member devices, used to short-circuit the logic in
        # set_container_members for case of a partition
        self.member_list = None

        # choose a size set class for member partition allocation
        if raid_level is not None and raid_level.startswith("raid"):
            self.set_class = SameSizeSet
        else:
            self.set_class = TotalSizeSet

    @property
    def container_list(self):
        """ A list of containers of the type used by this device. """
        if not self.container_list_attr:
            return []

        return getattr(self.storage, self.container_list_attr)

    def new_container(self, *args, **kwargs):
        """ Return the newly created container for this device. """
        return getattr(self.storage, self.new_container_attr)(*args, **kwargs)

    def new_device(self, *args, **kwargs):
        """ Return the newly created device. """
        return getattr(self.storage, self.new_device_attr)(*args, **kwargs)

    def post_create(self):
        """ Perform actions required after device creation. """
        pass

    def container_size_func(self, container, device=None):
        """ Return the total space needed for the specified container. """
        size = container.size
        size += self.device_size
        if device:
            size -= device.size

        return size

    @property
    def device_size(self):
        """ The total disk space required for this device. """
        return self.size

    def set_device_size(self, container, device=None):
        return self.size

    def set_container_members(self, container, members=None, device=None):
        """ Set up and return the container's member partitions. """
        log_members = []
        if members:
            log_members = [str(m) for m in members]
        log_method_call(self, container=container,
                        members=log_members, device=device)
        if self.member_list is not None:
            # short-circuit the logic below for partitions
            return self.member_list

        if container and container.exists:
            # don't try to modify an existing container
            return container.parents

        if self.container_size_func is None:
            return []

        # set up member devices
        container_size = self.device_size
        add_disks = []
        remove_disks = []

        if members is None:
            members = []

        if container:
            members = container.parents[:]
        elif members:
            # mdarray
            container = device

        # XXX how can we detect/handle failure to use one or more of the disks?
        if members and device:
            # See if we need to add/remove any disks, but only if we are
            # adjusting a device. When adding a new device to a container we do
            # not want to modify the container's disk set.
            _disks = list(set([d for m in members for d in m.disks]))

            add_disks = [d for d in self.disks if d not in _disks]
            remove_disks = [d for d in _disks if d not in self.disks]
        elif not members:
            # new container, so use the factory's disk set
            add_disks = self.disks

        # drop any new disks that don't have free space
        min_free = min(500, self.size)
        add_disks = [d for d in add_disks if d.partitioned and
                                             d.format.free >= min_free]

        base_size = max(1, getFormat(self.member_format).minSize)

        # XXX TODO: multiple member devices per disk

        # prepare already-defined member partitions for reallocation
        for member in members[:]:
            if any([d in remove_disks for d in member.disks]):
                if isinstance(member, LUKSDevice):
                    if container:
                        container.removeMember(member)
                    self.storage.destroyDevice(member)
                    members.remove(member)
                    member = member.slave
                else:
                    if container:
                        container.removeMember(member)

                    members.remove(member)

                self.storage.destroyDevice(member)
                continue

            if isinstance(member, LUKSDevice):
                if not self.encrypted:
                    # encryption was toggled for the member devices
                    if container:
                        container.removeMember(member)

                    self.storage.destroyDevice(member)
                    members.remove(member)

                    self.storage.formatDevice(member.slave,
                                              getFormat(self.member_format))
                    members.append(member.slave)
                    if container:
                        container.addMember(member.slave)

                member = member.slave
            elif self.encrypted:
                # encryption was toggled for the member devices
                if container:
                    container.removeMember(member)

                members.remove(member)
                self.storage.formatDevice(member, getFormat("luks"))
                luks_member = LUKSDevice("luks-%s" % member.name,
                                    parents=[member],
                                    format=getFormat(self.member_format))
                self.storage.createDevice(luks_member)
                members.append(luks_member)
                if container:
                    container.addMember(luks_member)

            member.req_base_size = base_size
            member.req_size = member.req_base_size
            member.req_grow = True

        # set up new members as needed to accommodate the device
        new_members = []
        for disk in add_disks:
            if self.encrypted and self.encrypt_members:
                luks_format = self.member_format
                member_format = "luks"
            else:
                member_format = self.member_format

            try:
                member = self.storage.newPartition(parents=[disk], grow=True,
                                           size=base_size,
                                           fmt_type=member_format)
            except StorageError as e:
                log.error("failed to create new member partition: %s" % e)
                continue

            self.storage.createDevice(member)
            if self.encrypted and self.encrypt_members:
                fmt = getFormat(luks_format)
                member = LUKSDevice("luks-%s" % member.name,
                                    parents=[member], format=fmt)
                self.storage.createDevice(member)

            members.append(member)
            new_members.append(member)
            if container:
                container.addMember(member)

        if container:
            log.debug("using container %s with %d devices" % (container.name,
                        len(self.storage.devicetree.getChildren(container))))
            container_size = self.container_size_func(container, device)
            log.debug("raw container size reported as %d" % container_size)

        log.debug("adding a %s with size %d" % (self.set_class.__name__,
                                                container_size))
        size_set = self.set_class(members, container_size)
        self.storage.size_sets.append(size_set)
        for member in members[:]:
            if isinstance(member, LUKSDevice):
                member = member.slave

            member.req_max_size = size_set.size

        try:
            self.allocate_partitions()
        except PartitioningError as e:
            # try to clean up by destroying all newly added members before re-
            # raising the exception
            self.storage._clean_up_member_devices(new_members,
                                                  container=container)
            raise

        return members

    def allocate_partitions(self):
        """ Allocate all requested partitions. """
        try:
            doPartitioning(self.storage)
        except StorageError as e:
            log.error("failed to allocate partitions: %s" % e)
            raise

    def get_container(self, device=None, name=None, existing=False):
        # XXX would it be useful to implement this as a series of fallbacks
        #     instead of mutually exclusive branches?
        container = None
        if name:
            container = self.storage.devicetree.getDeviceByName(name)
            if container and container not in self.container_list:
                log.debug("specified container name %s is wrong type (%s)"
                            % (name, container.type))
                container = None
        elif device:
            if hasattr(device, "vg"):
                container = device.vg
            elif hasattr(device, "volume"):
                container = device.volume
        else:
            containers = [c for c in self.container_list if not c.exists]
            if containers:
                container = containers[0]

        if container is None and existing:
            containers = [c for c in self.container_list if c.exists]
            if containers:
                containers.sort(key=lambda c: getattr(c, "freeSpace", c.size),
                                reverse=True)
                container = containers[0]

        return container

    def _clean_up_member_devices(self, members, container=None):
        for member in members:
            if container:
                container.removeMember(member)

            if isinstance(member, LUKSDevice):
                self.storage.destroyDevice(member)
                member = member.slave

            if not member.isDisk:
                self.storage.destroyDevice(member)

    def configure_device(self, device=None, container_name=None, name=None,
                         fstype=None, mountpoint=None, label=None):
        """ Schedule creation of a device based on a top-down specification.

            Keyword arguments:

                fstype              filesystem type
                mountpoint          filesystem mount point
                label               filesystem label text

                container_name      name of requested container
                name                name of requested device

                device              an already-defined but non-existent device
                                    to adjust instead of creating a new device


            Error handling:

                If device is None, meaning we're creating a device, the error
                handling aims to remove all evidence of the attempt to create a
                new device by removing unused container devices, reverting the
                size of container devices that contain other devices, &c.

                If the device is not None, meaning we're adjusting the size of
                a defined device, the error handling aims to revert the device
                and any container to it previous size.

                In either case, we re-raise the exception so the caller knows
                there was a failure. If we failed to clean up as described above
                we raise ErrorRecoveryFailure to alert the caller that things
                will likely be in an inconsistent state.
        """
        # we can't do anything with existing devices
        if device and device.exists:
            log.info("factoryDevice refusing to change device %s" % device)
            return

        if not fstype:
            fstype = self.storage.getFSType(mountpoint=mountpoint)
            if fstype == "swap":
                mountpoint = None

        fmt_args = {}
        if label:
            fmt_args["label"] = label

        container = self.get_container(device=device, name=container_name)

        # TODO: striping, mirroring, &c
        # TODO: non-partition members (pv-on-md)

        # set_container_members can modify these, so save them now
        old_size = None
        old_disks = []
        if device:
            old_size = device.size
            old_disks = device.disks[:]

        members = []
        if device and device.type == "mdarray":
            members = device.parents[:]

        try:
            parents = self.set_container_members(container,
                                                 members=members, device=device)
        except PartitioningError as e:
            # If this is a new device, just clean up and get out.
            if device:
                # If this is a defined device, try to clean up by reallocating
                # members as before and then get out.
                self.disks = device.disks
                self.size = device.size  # this should work

                if members:
                    # If this is an md array we have to reset its member set
                    # here.
                    # If there is a container device, its member set was reset
                    # in the exception handler in set_container_members.
                    device.parents = members

                try:
                    self.set_container_members(container,
                                               members=members,
                                               device=device)
                except StorageError as e:
                    log.error("failed to revert device size: %s" % e)
                    raise ErrorRecoveryFailure("failed to revert container")

            raise

        # set up container
        if not container and self.new_container_attr:
            if not parents:
                raise StorageError("not enough free space on disks")

            log.debug("creating new container")
            if container_name:
                kwa = {"name": container_name}
            else:
                kwa = {}
            try:
                container = self.new_container(parents=parents, **kwa)
            except StorageError as e:
                log.error("failed to create new device: %s" % e)
                # Clean up by destroying the newly created member devices.
                self._clean_up_member_devices(parents)
                raise

            self.storage.createDevice(container)
        elif container and not container.exists and \
             hasattr(container, "dataLevel"):
            container.dataLevel = self.raid_level

        if container:
            parents = [container]
            log.debug("%r" % container)

        # this will set the device's size if a device is passed in
        size = self.set_device_size(container, device=device)
        if device:
            # We are adjusting a defined device: size, disk set, encryption,
            # raid level, fstype. The StorageDevice instance exists, but the
            # underlying device does not.
            # TODO: handle toggling of encryption for leaf device
            e = None
            try:
                self.post_create()
            except StorageError as e:
                log.error("device post-create method failed: %s" % e)
            else:
                if device.size <= device.format.minSize:
                    e = StorageError("failed to adjust device -- not enough free space in specified disks?")

            if e:
                # Clean up by reverting the device to its previous size.
                self.size = old_size
                self.disks = old_disks
                try:
                    self.set_container_members(container,
                                               members=members, device=device)
                except StorageError as e:
                    # yes, we're replacing e here.
                    log.error("failed to revert device size: %s" % e)
                    raise ErrorRecoveryFailure("failed to revert device size")

                self.set_device_size(container, device=device)
                try:
                    self.post_create()
                except StorageError as e:
                    # yes, we're replacing e here.
                    log.error("failed to revert device size: %s" % e)
                    raise ErrorRecoveryFailure("failed to revert device size")

                raise(e)
        elif self.new_device_attr:
            log.debug("creating new device")
            if self.encrypted and self.encrypt_leaves:
                luks_fmt_type = fstype
                luks_fmt_args = fmt_args
                luks_mountpoint = mountpoint
                fstype = "luks"
                mountpoint = None
                fmt_args = {}

            def _container_post_error():
                # Clean up. If there is a container and it has other devices,
                # try to revert it. If there is a container and it has no other
                # devices, remove it. If there is not a container, remove all of
                # the parents.
                if container:
                    if container.kids:
                        self.size = 0
                        self.disks = container.disks
                        try:
                            self.set_container_members(container, factory)
                        except StorageError as e:
                            log.error("failed to revert container: %s" % e)
                            raise ErrorRecoveryFailure("failed to revert container")
                    else:
                        self.storage.destroyDevice(container)
                        self._clean_up_member_devices(container.parents)
                else:
                    self._clean_up_member_devices(parents)

            if name:
                kwa = {"name": name}
            else:
                kwa = {}

            try:
                device = self.new_device(parents=parents,
                                            size=size,
                                            fmt_type=fstype,
                                            mountpoint=mountpoint,
                                            fmt_args=fmt_args,
                                            **kwa)
            except (StorageError, ValueError) as e:
                log.error("device instance creation failed: %s" % e)
                _container_post_error()
                raise

            self.storage.createDevice(device)
            e = None
            try:
                self.post_create()
            except StorageError as e:
                log.error("device post-create method failed: %s" % e)
            else:
                if not device.size:
                    e = StorageError("failed to create device")

            if e:
                self.storage.destroyDevice(device)
                _container_post_error()
                raise StorageError(e)

            if self.encrypted and self.encrypt_leaves:
                fmt = getFormat(luks_fmt_type,
                                mountpoint=luks_mountpoint,
                                **luks_fmt_args)
                luks_device = LUKSDevice("luks-" + device.name,
                                         parents=[device], format=fmt)
                self.storage.createDevice(luks_device)


class DiskFactory(DeviceFactory):
    type_desc = "disk"
    # this is to protect against changes to these settings in the base class
    encrypt_members = False
    encrypt_leaves = True

class PartitionFactory(DeviceFactory):
    type_desc = "partition"
    new_device_attr = "newPartition"
    default_size = 1

    def __init__(self, storage, size, disks, raid_level, encrypted):
        super(PartitionFactory, self).__init__(storage, size, disks, raid_level,
                                               encrypted)
        self.member_list = self.disks

    def new_device(self, *args, **kwargs):
        grow = True
        max_size = kwargs.pop("size")
        kwargs["size"] = 1

        device = self.storage.newPartition(*args,
                                           grow=grow, maxsize=max_size,
                                           **kwargs)
        return device

    def post_create(self):
        self.allocate_partitions()

    def set_device_size(self, container, device=None):
        size = self.size
        if device:
            if size != device.size:
                log.info("adjusting device size from %.2f to %.2f"
                                % (device.size, size))

            base_size = max(PartitionFactory.default_size,
                            device.format.minSize)
            size = max(base_size, size)
            device.req_base_size = base_size
            device.req_size = base_size
            device.req_max_size = size
            device.req_grow = size > base_size

            # this probably belongs somewhere else but this is our chance to
            # update the disk set
            device.req_disks = self.disks[:]

        return size

class BTRFSFactory(DeviceFactory):
    type_desc = "btrfs"
    member_format = "btrfs"
    new_container_attr = "newBTRFS"
    new_device_attr = "newBTRFSSubVolume"
    container_list_attr = "btrfsVolumes"
    encrypt_members = True
    encrypt_leaves = False

    def __init__(self, storage, size, disks, raid_level, encrypted):
        super(BTRFSFactory, self).__init__(storage, size, disks, raid_level,
                                           encrypted)
        self.raid_level = raid_level or "single"

    def new_container(self, *args, **kwargs):
        """ Return the newly created container for this device. """
        kwargs["dataLevel"] = self.raid_level
        return getattr(self.storage, self.new_container_attr)(*args, **kwargs)

    def container_size_func(self, container, device=None):
        """ Return the total space needed for the specified container. """
        if container.exists:
            container_size = container.size
        else:
            container_size = sum([s.req_size for s in container.subvolumes])

        if device:
            size = self.device_size
        else:
            size = container_size + self.device_size

        return size

    @property
    def device_size(self):
        # until we get/need something better
        if self.raid_level in ("single", "raid0"):
            return self.size
        elif self.raid_level in ("raid1", "raid10"):
            return self.size * len(self.disks)

    def new_device(self, *args, **kwargs):
        kwargs["dataLevel"] = self.raid_level
        kwargs["metaDataLevel"] = self.raid_level
        return super(BTRFSFactory, self).new_device(*args, **kwargs)

class LVMFactory(DeviceFactory):
    type_desc = "lvm"
    member_format = "lvmpv"
    new_container_attr = "newVG"
    new_device_attr = "newLV"
    container_list_attr = "vgs"
    encrypt_members = True
    encrypt_leaves = False

    @property
    def device_size(self):
        size_func_kwargs = {}
        if self.raid_level in ("raid1", "raid10"):
            size_func_kwargs["mirrored"] = True
        if self.raid_level in ("raid0", "raid10"):
            size_func_kwargs["striped"] = True
        return get_pv_space(self.size, len(self.disks), **size_func_kwargs)

    def container_size_func(self, container, device=None):
        size = sum([p.size for p in container.parents])
        size -= container.freeSpace
        size += self.device_size
        if device:
            size -= get_pv_space(device.size, len(container.parents))

        return size

    def set_device_size(self, container, device=None):
        size = self.size
        free = container.freeSpace
        if device:
            free += device.size

        if free < size:
            log.info("adjusting device size from %.2f to %.2f so it fits "
                     "in container" % (size, free))
            size = free

        if device:
            if size != device.size:
                log.info("adjusting device size from %.2f to %.2f"
                                % (device.size, size))

            device.size = size

        return size

class MDFactory(DeviceFactory):
    type_desc = "md"
    member_format = "mdmember"
    new_container_attr = None
    new_device_attr = "newMDArray"

    @property
    def container_list(self):
        return []

    @property
    def device_size(self):
        return get_member_space(self.size, len(self.disks),
                                level=self.raid_level)

    def container_size_func(self, container, device=None):
        return get_member_space(self.size, len(container.parents),
                                level=self.raid_level)

    def new_device(self, *args, **kwargs):
        kwargs["level"] = self.raid_level
        kwargs["totalDevices"] = len(kwargs.get("parents"))
        kwargs["memberDevices"] = len(kwargs.get("parents"))
        return super(MDFactory, self).new_device(*args, **kwargs)
