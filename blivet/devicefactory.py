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
from devicelibs.mdraid import get_raid_min_members
from devicelibs.mdraid import raidLevelString
from devicelibs.mdraid import raidLevel
from devicelibs.lvm import get_pv_space
from devicelibs.lvm import LVM_PE_SIZE
from .partitioning import SameSizeSet
from .partitioning import TotalSizeSet
from .partitioning import doPartitioning

import gettext
_ = lambda x: gettext.ldgettext("blivet", x)

import logging
log = logging.getLogger("blivet")

# policy value of >0 is a fixed size request
SIZE_POLICY_MAX = -1
SIZE_POLICY_AUTO = 0

DEVICE_TYPE_LVM = 0
DEVICE_TYPE_MD = 1
DEVICE_TYPE_PARTITION = 2
DEVICE_TYPE_BTRFS = 3
DEVICE_TYPE_DISK = 4
DEVICE_TYPE_LVM_ON_MD = 5

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
    elif hasattr(use_dev, "lvs") and len(use_dev.parents) == 1:
        raid_level = get_raid_level(use_dev.parents[0])

    return raid_level

def get_device_factory(blivet, device_type, size, **kwargs):
    """ Return a suitable DeviceFactory instance for device_type. """
    disks = kwargs.pop("disks", [])

    class_table = {DEVICE_TYPE_LVM: LVMFactory,
                   DEVICE_TYPE_BTRFS: BTRFSFactory,
                   DEVICE_TYPE_PARTITION: PartitionFactory,
                   DEVICE_TYPE_MD: MDFactory,
                   DEVICE_TYPE_LVM_ON_MD: LVMOnMDFactory,
                   DEVICE_TYPE_DISK: DeviceFactory}

    factory_class = class_table[device_type]
    log.debug("instantiating %s: %s, %s, %s, %s" % (factory_class,
                blivet, size, [d.name for d in disks], kwargs))
    return factory_class(blivet, size, disks, **kwargs)


class DeviceFactory(object):
    """ Class for creation of devices based on a top-down specification

        DeviceFactory instances can be combined/stacked to create more complex
        device stacks like lvm with md pvs.

        Simplified call trace for creation of a new LV in a new VG with
        partition PVs:

            LVMFactory.configure
                PartitionSetFactory.configure   # set up PVs on partitions
                LVMFactory._create_container    # create container device (VG)
                LVMFactory._create_device       # create leaf device (LV)


        Simplified call trace for creation of a new LV in a new VG with a single
        MD PV with member partitions on multiple disks:

            LVMOnMDFactory.configure
                MDFactory.configure
                    PartitionSetFactory.configure   # create md partitions
                    MDFactory._create_device        # create PV on MD array
                LVMFactory._create_container        # create VG
                LVMFactory._create_device           # create LV

        The code below will create a volume group with the name "data" just
        large enough to contain a new logical volume named "music" with a size
        of 10000 MB. It will make one physical volume partition on each disk in
        "disks" that has space. If the resulting volume group is not large
        enough to contain a logical volume of the specified size, the logical
        volume will be created with a size that is as close as possible to the
        requested size. If there is already a non-existent volume group named
        "data" in the Blivet instance's device tree, that volume group will be
        used instead of creating a new one. If the already-defined "data" volume
        group exists on disk its size will not be changed, but if it has not
        been written to disk it will be adjusted to hold the new logical volume.

            import blivet

            _blivet = blivet.Blivet()
            _blivet.reset()
            disks = _blivet.partitioned

            # Create a new LV "music" to a VG named "data", which may or may not
            # exist. If the VG exists, the LV will be allocated from free space
            # in the VG. If the VG does not exist, one will be created using new
            # PVs on each of the specified disks. No free space is maintained in
            # new VGs by default.
            factory = blivet.devicefactory.LVMFactory(_blivet,
                                                      10000,
                                                      disks,
                                                      fstype="xfs",
                                                      label="music",
                                                      name="music",
                                                      container_name="data")
            factory.configure()
            music_lv = factory.device


            # Now add another LV to the "data" VG, adjusting the size of a non-
            # existent "data" VG so that it can contain the new LV.
            factory = blivet.devicefactory.LVMFactory(_blivet,
                                                      20000,
                                                      disks,
                                                      fstype="xfs",
                                                      label="videos",
                                                      name="videos",
                                                      container_name="data")
            factory.configure()

            # Now change the size of the "music" LV and adjust the size of the
            # "data" VG accordingly.
            factory = blivet.devicefactory.LVMFactory(_blivet,
                                                      15000,
                                                      disks,
                                                      device=music_lv)
            factory.configure()

            # Write the new devices to disk and create the filesystems they
            # contain.
            _blivet.doIt()


        Some operations (on non-existent devices) these classes do support:

            - create a device and a container to hold it
            - create a device within a defined container
            - create a device within an existing (on disk) container
            - change the set of disks from which partitions used by a factory
              can be allocated
            - change the size of a defined (but non-existent) device
            - toggle encryption of a leaf device or container member devices


        Some operations these classes do not support:

            - any modification to an existing leaf device
            - change an existing container's member device set
            - resize or rename an existing container
            - move a device from one container to another
            - change the type of a defined device
            - change the container member device type of a defined device

    """
    child_factory_class = None
    size_set_class = TotalSizeSet

    def __init__(self, storage, size, disks, fstype=None, mountpoint=None,
                 label=None, raid_level=None, encrypted=False,
                 container_encrypted=False, container_name=None,
                 container_raid_level=None, container_size=SIZE_POLICY_AUTO,
                 name=None, device=None):
        """ Create a new DeviceFactory instance.

            Arguments:

                storage             a Blivet instance
                size                the desired size for the device
                disks               the set of disks to use

            Keyword args:

                fstype              filesystem type
                mountpoint          filesystem mount point
                label               filesystem label text

                raid_level          raid level string, eg: "raid1"
                encrypted           whether to encrypt (boolean)
                name                name of requested device

                device              an already-defined but non-existent device
                                    to adjust instead of creating a new device

                container_name      name of requested container
                container_raid_level
                container_encrypted whether to encrypt the entire container
                container_size      requested container size
        """
        self.storage = storage          # a Blivet instance
        self.size = size                # the requested size for this device
        self.disks = disks              # the set of disks to allocate from

        self.original_size = size
        self.original_disks = disks[:]

        self.fstype = fstype
        self.mountpoint = mountpoint
        self.label = label

        self.raid_level = raid_level
        self.container_raid_level = container_raid_level

        self.encrypted = encrypted
        self.container_encrypted = container_encrypted

        self.container_name = container_name
        self.device_name = name

        self.container_size = container_size

        self.container = None
        self.device = device

        if not self.fstype:
            self.fstype = self.storage.getFSType(mountpoint=self.mountpoint)
            if fstype == "swap":
                self.mountpoint = None

        self.child_factory = None
        self.parent_factory = None

        # used for error recovery
        self.__devices = []
        self.__actions = []
        self.__names = []

    #
    # methods related to device size and disk space requirements
    #
    def _get_free_disk_space(self):
        free_info = self.storage.getFreeSpace(disks=self.disks)
        free = sum(d[0] for d in free_info.values())
        return int(free.convertTo(spec="mb"))

    def _handle_no_size(self):
        """ Set device size so that it grows to the largest size possible. """
        if self.size is not None:
            return

        self.size = self._get_free_disk_space()

        if self.device:
            self.size += self.device.size

        if self.container_size > 0:
            self.size = min(self.container_size, self.size)

    def _get_total_space(self):
        """ Return the total space need for this factory's device/container.

            This is used for the size argument to the child factory constructor
            and also to construct the size set in PartitionSetFactory.configure.
        """
        size = self._get_device_space()
        if self.container:
            size += container.size

        if self.device:
            size -= self.device.size

        return size

    def _get_device_space(self):
        """ The total disk space required for this device. """
        return self.size

    def _get_device_size(self):
        """ Return the factory device size including container limitations. """
        return self.size

    def _set_device_size(self):
        """ Set the size of a defined factory device. """
        pass

    #
    # methods related to container/parent devices
    #
    def _get_parent_devices(self):
        """ Return the list of parent devices for this factory's device. """
        # TODO: maintain something like a state machine to ensure context for
        #       methods like this one
        if self.container:
            parents = [self.container]
        elif self.child_factory:
            parents = self.child_factory.devices
        else:
            parents = []

        return parents

    def _get_member_devices(self):
        """ Return a list of member devices.

            This is only used by classes like lvm and md where there is a set of
            member devices, the length of which can affect disk space
            requirements (per-member metadata).

            We want this to be as up-to-date as is possible.

            Our container's parent list is not used here. Prior to configuring
            the child factory it is no more accurate than our disk list.
            Afterwards, it is no more accurate than the child factory's device
            list.
        """
        members = self.disks    # fallback/default if we're called very early
        if self.child_factory:
            # the child factory's device list what our container's is based on
            members = self.child_factory.devices

        return members

    @property
    def container_list(self):
        """ List of containers of the appropriate type for this class. """
        return []

    # FIXME: This is nuts. Move specifics into the appropriate classes.
    def get_container(self, device=None, name=None, allow_existing=False):
        """ Return the best choice of container for this factory.

            Keyword arguments:

                device -- a defined factory device
                name -- a specific container name to look for
                allow_existing -- whether to allow selection of preexisting
                                  containers

        """
        # XXX would it be useful to implement this as a series of fallbacks
        #     instead of mutually exclusive branches?
        if self.device and not device:
            device = self.device

        if self.container_name and not name:
            name = self.container_name

        container = None
        if device:
            if hasattr(device, "vg"):
                container = device.vg
            elif hasattr(device, "volume"):
                container = device.volume
        elif name:
            for c in self.storage.devices:
                if c.name == name and c in self.container_list:
                    container = c
                    break
        else:
            containers = [c for c in self.container_list
                            if allow_existing or not c.exists]
            if containers:
                # XXX All containers should have a "free" attribute
                containers.sort(key=lambda c: getattr(c, "freeSpace", c.size),
                                reverse=True)
                container = containers[0]

        return container

    def _set_container(self):
        """ Set this factory's container device. """
        self.container = self.get_container(device=self.raw_device,
                                            name=self.container_name)


    def _create_container(self):
        """ Create the container device required by this factory device. """
        parents = self._get_parent_devices()
        self.container = self._get_new_container(name=self.container_name,
                                                 parents=parents)
        self.storage.createDevice(self.container)
        if self.container_name is None:
            self.container_name = self.container.name

    def _get_new_container(self, *args, **kwargs):
        """ Type-specific container device instantiation. """
        pass

    def _check_container_size(self):
        """ Raise an exception if the container cannot hold its devices. """
        pass

    def _reconfigure_container(self):
        """ Reconfigure a defined container required by this factory device. """
        if getattr(self.container, "exists", False):
            return

        self._set_container_members()
        self._set_container_raid_level()

        # check that the container is still large enough to contain whatever
        # other devices it previously contained
        self._check_container_size()

    def _set_container_members(self):
        if not self.child_factory:
            return

        members = self.child_factory.devices
        log.debug("new member set: %s" % [d.name for d in members])
        log.debug("old member set: %s" % [d.name for d in self.container.parents])
        for member in self.container.parents[:]:
            if member not in members:
                self.container.removeMember(member)

        for member in members:
            if member not in self.container.parents:
                self.container.addMember(member)

    def _set_container_raid_level(self):
        pass

    #
    # properties and methods related to the factory device
    #
    @property
    def raw_device(self):
        """ If self.device is encrypted, this is its backing device. """
        use_dev = None
        if self.device:
            if isinstance(self.device, LUKSDevice):
                use_dev = self.device.slave
            else:
                use_dev = self.device

        return use_dev

    @property
    def devices(self):
        """ A list of this factory's product devices. """
        return [self.device]

    #
    # methods to configure the factory device(s)
    #
    def _create_device(self):
        """ Create the factory device. """
        if self.size == 0:
            # A factory with a size of zero means you're adjusting a container
            # after removing a device from it.
            return

        fmt_args = {}
        if self.encrypted:
            fstype = "luks"
            mountpoint = None
        else:
            fstype = self.fstype
            mountpoint = self.mountpoint
            fmt_args = {}
            if self.label:
                fmt_args["label"] = self.label

        if self.device_name:
            kwa = {"name": self.device_name}
        else:
            kwa = {}

        # this gets us a size value that takes into account the actual size of
        # the container
        size = self._get_device_size()

        parents = self._get_parent_devices()

        try:
            device = self._get_new_device(parents=parents,
                                          size=size,
                                          fmt_type=fstype,
                                          mountpoint=mountpoint,
                                          fmt_args=fmt_args,
                                          **kwa)
        except (StorageError, ValueError) as e:
            log.error("device instance creation failed: %s" % e)
            raise

        self.storage.createDevice(device)
        e = None
        try:
            self._post_create()
        except StorageError as e:
            log.error("device post-create method failed: %s" % e)
        else:
            if not device.size:
                e = StorageError("failed to create device")

        if e:
            self.storage.destroyDevice(device)
            raise StorageError(e)

        ret = device
        if self.encrypted:
            fmt_args = {}
            if self.label:
                fmt_args["label"] = self.label

            fmt = getFormat(self.fstype,
                            mountpoint=self.mountpoint,
                            **fmt_args)
            luks_device = LUKSDevice("luks-" + device.name,
                                     parents=[device], format=fmt)
            self.storage.createDevice(luks_device)
            ret = luks_device

        self.device = ret

    def _get_new_device(self, *args, **kwargs):
        """ Type-specific device instantiation. """
        pass

    def _reconfigure_device(self):
        """ Reconfigure a defined factory device. """
        # We are adjusting a defined device: size, disk set, container
        # member encryption, container raid level. The StorageDevice
        # instance exists, but the underlying device does not.
        self._set_disks()
        self._set_raid_level()
        self._set_size()
        self._set_encryption()
        self._set_format()
        self._set_name()

    def _set_disks(self):
        pass

    def _set_raid_level(self):
        pass

    def _set_size(self):
        # this is setting the device size based on the factory size and the
        # current size of the container
        self._set_device_size()

        e = None
        try:
            self._post_create()
        except StorageError as e:
            log.error("device post-create method failed: %s" % e)
        else:
            if self.device.size <= self.device.format.minSize:
                e = StorageError("failed to adjust device -- not enough free space in specified disks?")

        if e:
            raise(e)

    def _set_format(self):
        current_format = self.device.format
        if current_format.type != self.fstype:
            new_format = getFormat(self.fstype,
                                   mountpoint=self.mountpoint,
                                   label=self.label,
                                   exists=False)
            self.storage.formatDevice(self.device, new_format)
        else:
            current_mountpoint = getattr(current_format, "mountpoint", None)
            if (hasattr(current_format, "mountpoint") and
                current_format.mountpoint != self.mountpoint):
                current_format.mountpoint = self.mountpoint

            if (hasattr(current_format, "label") and
                current_format.label != self.label):
                current_format.label = self.label

    def _set_encryption(self):
        # toggle encryption of the leaf device as needed
        parent_container = getattr(self.parent_factory, "container", None)
        if isinstance(self.device, LUKSDevice) and not self.encrypted:
            raw_device = self.raw_device
            leaf_format = self.device.format
            if parent_container:
                parent_container.removeMember(self.device)
            self.storage.destroyDevice(self.device)
            self.storage.formatDevice(self.raw_device, leaf_format)
            self.device = raw_device
            if parent_container:
                parent_container.addMember(self.device)
        elif self.encrypted and not isinstance(self.device, LUKSDevice):
            if parent_container:
                parent_container.removeMember(self.device)
            leaf_format = self.device.format
            self.storage.formatDevice(self.device, getFormat("luks"))
            luks_device = LUKSDevice("luks-%s" % self.device.name,
                                     format=leaf_format,
                                     parents=self.device)
            self.storage.createDevice(luks_device)
            self.device = luks_device
            if parent_container:
                parent_container.addMember(self.device)

    def _set_name(self):
        if self.device_name is None:
            return

        # TODO: write a StorageDevice.name setter
        safe_new_name = self.storage.safeDeviceName(self.device_name)
        if self.device.name != safe_new_name:
            if safe_new_name in self.storage.names:
                log.error("not renaming '%s' to in-use name '%s'"
                            % (self.device._name, safe_new_name))
                return

            log.debug("renaming device '%s' to '%s'"
                        % (self.device._name, safe_new_name))
            self.device._name = safe_new_name

    def _post_create(self):
        """ Hook for post-creation operations. """
        pass

    def _get_child_factory_args(self):
        return [self.storage, self._get_total_space(), self.disks]

    def _get_child_factory_kwargs(self):
        return {"fstype": self.child_factory_fstype}

    def _set_up_child_factory(self):
        if self.child_factory or not self.child_factory_class:
            return

        args = self._get_child_factory_args()
        kwargs = self._get_child_factory_kwargs()
        log.debug("child factory class: %s" % self.child_factory_class)
        log.debug("child factory args: %s" % args)
        log.debug("child factory kwargs: %s" % kwargs)
        factory = self.child_factory_class(*args, **kwargs)
        self.child_factory = factory
        factory.parent_factory = self

    def configure(self):
        """ Configure the factory's device(s).

            Keyword arguments:

            An example of the parent_factory is the LVMOnMDFactory creating and
            then using an MDFactory to manage the volume group's single MD PV.

            Another example is the MDFactory creating and then using a
            PartitionSetFactory to manage the set of member partitions.
        """
        log_method_call(self, parent_factory=self.parent_factory)

        if self.parent_factory is None:
            # only do the backup/restore error handling in the top-level factory
            self._save_devicetree()

        try:
            self._configure()
        except Exception as e:
            log.error("failed to configure device factory: %s" % e)
            if self.parent_factory is None:
                # only do the backup/restore error handling at the top-level
                self._revert_devicetree()

            if not isinstance(e, (StorageError, OverflowError)):
                e = DeviceFactoryError(str(e))

            raise(e)

    def _configure(self):
        self._set_container()
        self._handle_no_size()
        self._set_up_child_factory()

        # Configure any devices this device will use as building blocks, except
        # for type-specific container devices. In the LVM example, this will
        # configure the PVs.
        if self.child_factory:
            self.child_factory.configure()

        # Make sure that there are enough disks involved for any specified
        # device or container raid level.
        for level_attr in ["raid_level", "container_raid_level"]:
            level = getattr(self, level_attr, None)
            if level in [None, "single"]:
                continue

            md_level = raidLevel(level)
            min_disks = get_raid_min_members(md_level)
            disks = set(d for m in self._get_member_devices() for d in m.disks)
            if len(disks) < min_disks:
                raise DeviceFactoryError("Not enough disks for %s" % level)

        # Configure any type-specific container device. The obvious example of
        # this is the LVMFactory, which will configure its VG in this step.
        if self.container:
            self._reconfigure_container()
        else:
            self._create_container()

        if self.container and hasattr(self.container, "size_policy") and \
           not self.container.exists:
            self.container.size_policy = self.container_size

        # Configure this factory's leaf device, eg, for LVMFactory: the LV.
        if self.device:
            self._reconfigure_device()
        else:
            self._create_device()

    #
    # methods for error recovery
    #
    def _save_devicetree(self):
        _blivet_copy = self.storage.copy()
        self.__devices = _blivet_copy.devicetree._devices
        self.__actions = _blivet_copy.devicetree._actions
        self.__names = _blivet_copy.devicetree.names

    def _revert_devicetree(self):
        self.storage.devicetree._devices = self.__devices
        self.storage.devicetree._actions = self.__actions
        self.storage.devicetree.names = self.__names

class PartitionFactory(DeviceFactory):
    """ Factory class for creating a partition. """
    #
    # methods related to device size and disk space requirements
    #
    def _get_base_size(self):
        if self.device:
            min_format_size = self.device.format.minSize
        else:
            # this is a little dirty, but cache the DeviceFormat so we only
            # instantiate one of them
            self.__fmt = getattr(self, "__fmt", getFormat(self.fstype))
            min_format_size = self.__fmt.minSize

        return max(1, min_format_size)

    def _get_device_size(self):
        """ Return the factory device size including container limitations. """
        return max(self._get_base_size(), self.size)

    def _set_device_size(self):
        """ Set the size of a defined factory device. """
        if self.device and self.size != self.raw_device.size:
            log.info("adjusting device size from %.2f to %.2f"
                            % (self.raw_device.size, self.size))

            base_size = self._get_base_size()
            size = self._get_device_size()
            self.raw_device.req_base_size = base_size
            self.raw_device.req_size = base_size
            self.raw_device.req_max_size = size
            self.raw_device.req_grow = size > base_size

    #
    # methods related to container/parent devices
    #
    def get_container(self, device=None, name=None, allow_existing=False):
        return None

    def _create_container(self):
        pass

    def _get_parent_devices(self):
        """ Return the list of parent devices for this factory's device. """
        return self.disks

    #
    # methods to configure the factory device
    #
    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        max_size = kwargs.pop("size")
        kwargs["size"] = self._get_base_size()

        device = self.storage.newPartition(*args,
                                           grow=True, maxsize=max_size,
                                           **kwargs)
        return device

    def _set_disks(self):
        self.raw_device.req_disks = self.disks[:]

    def _set_name(self):
        pass

    def _post_create(self):
        try:
            doPartitioning(self.storage)
        except StorageError as e:
            log.error("failed to allocate partitions: %s" % e)
            raise

class PartitionSetFactory(PartitionFactory):
    """ Factory for creating a set of related partitions. """
    def __init__(self, storage, size, disks, fstype=None, encrypted=False,
                 devices=None):
        """ Create a new DeviceFactory instance.

            Arguments:

                storage             a Blivet instance
                size                the desired size for the device
                disks               the set of disks to use

            Keyword args:

                fstype              filesystem type
                encrypted           whether to encrypt (boolean)

                devices             an initial set of devices
        """
        super(PartitionSetFactory, self).__init__(storage, size, disks,
                                                     fstype=fstype,
                                                     encrypted=encrypted)
        self._devices = []
        if devices:
            self._devices = devices

    @property
    def devices(self):
        return self._devices

    def configure(self):
        """ Configure the factory's device set.

            This factory class will always have a parent factory.
        """
        log_method_call(self, parent_factory=self.parent_factory)

        # list of disks to add/remove member devices to/from
        add_disks = []
        remove_disks = []

        # We want to keep self.devices updated so it is accurate when we call
        # the parent factory's _get_total_space method, which should base size
        # calculations on the length of self.devices.
        #
        # The parent factory's container's member set will be updated later to
        # reflect the results of this method.

        # Grab the starting member list from the parent factory.
        members = self._devices
        container = self.parent_factory.container
        log.debug("parent factory container: %s" % self.parent_factory.container)
        if container:
            if container.exists:
                log.info("parent factory container exists -- nothing to do")
                return

            # update our device list from the parent factory's container members
            members = container.parents[:]
            self._devices = members

        log.debug("members: %s" % [d.name for d in members])

        ##
        ## Determine the target disk set.
        ##
        # XXX how can we detect/handle failure to use one or more of the disks?
        if self.parent_factory.device:
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
        min_free = min(500, self.parent_factory.size)
        add_disks = [d for d in add_disks if d.partitioned and
                                             d.format.free >= min_free]

        log.debug("add_disks: %s" % [d.name for d in add_disks])
        log.debug("remove_disks: %s" % [d.name for d in remove_disks])

        ##
        ## Remove members from dropped disks.
        ##
        for member in members[:]:
            if any([d in remove_disks for d in member.disks]):
                if container:
                    container.removeMember(member)

                if isinstance(member, LUKSDevice):
                    self.storage.destroyDevice(member)
                    members.remove(member)
                    member = member.slave
                else:
                    members.remove(member)

                self.storage.destroyDevice(member)

        ##
        ## Handle toggling of member encryption.
        ##
        for member in members[:]:
            member_encrypted = isinstance(member, LUKSDevice)
            if member_encrypted and not self.encrypted:
                if container:
                    container.removeMember(member)

                self.storage.destroyDevice(member)
                members.remove(member)
                self.storage.formatDevice(member.slave,
                                          getFormat(self.fstype))
                members.append(member.slave)
                if container:
                    container.addMember(member.slave)

                continue

            if not member_encrypted and self.encrypted:
                members.remove(member)
                if container:
                    container.removeMember(member)

                self.storage.formatDevice(member, getFormat("luks"))
                luks_member = LUKSDevice("luks-%s" % member.name,
                                    parents=[member],
                                    format=getFormat(self.fstype))
                self.storage.createDevice(luks_member)
                members.append(luks_member)
                if container:
                    container.addMember(luks_member)

                continue

        ##
        ## Prepare previously allocated member partitions for reallocation.
        ##
        base_size = self._get_base_size()
        for member in members[:]:
            if isinstance(member, LUKSDevice):
                member = member.slave

            # max size is set after instantiating the SizeSet below
            member.req_base_size = base_size
            member.req_size = member.req_base_size
            member.req_grow = True

        ##
        ## Define members on added disks.
        ##
        new_members = []
        for disk in add_disks:
            if self.encrypted:
                member_format = "luks"
            else:
                member_format = self.fstype

            try:
                member = self.storage.newPartition(parents=[disk], grow=True,
                                           size=base_size,
                                           fmt_type=member_format)
            except StorageError as e:
                log.error("failed to create new member partition: %s" % e)
                continue

            self.storage.createDevice(member)
            if self.encrypted:
                fmt = getFormat(self.fstype)
                member = LUKSDevice("luks-%s" % member.name,
                                    parents=[member], format=fmt)
                self.storage.createDevice(member)

            members.append(member)
            new_members.append(member)
            if container:
                container.addMember(member)

        ##
        ## Determine target container size.
        ##
        total_space = self.parent_factory._get_total_space()

        ##
        ## Set up SizeSet to manage growth of member partitions.
        ##
        log.debug("adding a %s with size %d"
                  % (self.parent_factory.size_set_class.__name__, total_space))
        size_set = self.parent_factory.size_set_class(members, total_space)
        self.storage.size_sets.append(size_set)
        for member in members[:]:
            if isinstance(member, LUKSDevice):
                member = member.slave

            member.req_max_size = size_set.size

        ##
        ## Allocate the member partitions.
        ##
        self._post_create()

class LVMFactory(DeviceFactory):
    """ Factory for creating LVM logical volumes with partition PVs. """
    child_factory_class = PartitionSetFactory
    child_factory_fstype = "lvmpv"
    size_set_class = TotalSizeSet

    #
    # methods related to device size and disk space requirements
    #
    def _handle_no_size(self):
        """ Set device size so that it grows to the largest size possible. """
        if self.size is not None:
            return

        if self.container and (self.container.exists or
                               self.container_size > 0):
            self.size = self.container.freeSpace

            if self.device:
                self.size += self.device.size
        else:
            super(LVMFactory, self)._handle_no_size()

    @property
    def size_func_kwargs(self):
        kwargs = {}
        if self.raid_level in ("raid1", "raid10"):
            kwargs["mirrored"] = True
        if self.raid_level in ("raid0", "raid10"):
            kwargs["striped"] = True

        return kwargs

    def _get_device_space(self):
        return get_pv_space(self.size,
                            len(self._get_member_devices()),
                            **self.size_func_kwargs)

    def _get_device_size(self):
        size = self.size
        free = self.container.freeSpace
        if self.device:
            free += self.raw_device.size

        if free < size:
            log.info("adjusting size from %.2f to %.2f so it fits "
                     "in container %s" % (size, free, self.container.name))
            size = free

        return size

    def _set_device_size(self):
        size = self._get_device_size()
        if self.device and size != self.raw_device.size:
            log.info("adjusting device size from %.2f to %.2f"
                            % (self.raw_device.size, size))
            self.raw_device.size = size

    def _get_total_space(self):
        """ Total disk space requirement for this device and its container. """
        size = 0
        if self.container and self.container.exists:
            return size

        if self.container_size == 0:
            # automatic container size management
            if self.container:
                size += sum([p.size for p in self.container.parents])
                size -= self.container.freeSpace
        elif self.container_size == SIZE_POLICY_MAX:
            # grow the container as large as possible
            if self.container:
                size += sum(p.size for p in self.container.parents)
                log.debug("size bumped to %d to include container parents" % size)

            size += self._get_free_disk_space()
            log.debug("size bumped to %d to include free disk space" % size)
        else:
            # container_size is a request for a fixed size for the container
            size += get_pv_space(self.container_size, len(self.disks))

        # this does not apply if a specific container size was requested
        if self.container_size in [SIZE_POLICY_AUTO, SIZE_POLICY_MAX]:
            size += self._get_device_space()
            log.debug("size bumped to %d to include new device space" % size)
            if self.device and self.container_size == SIZE_POLICY_AUTO:
                # The member count here uses the container's current member set
                # since that's the basis for the current device's disk space
                # usage.
                size -= get_pv_space(self.device.size,
                                     len(self.container.parents),
                                     **self.size_func_kwargs)
                log.debug("size cut to %d to omit old device space" % size)

        return size

    #
    # methods related to parent/container devices
    #
    @property
    def container_list(self):
        return self.storage.vgs[:]

    def _get_new_container(self, *args, **kwargs):
        return self.storage.newVG(*args, **kwargs)

    def _check_container_size(self):
        """ Raise an exception if the container cannot hold its devices. """
        if not self.container:
            return

        free_space = self.container.freeSpace + getattr(self.device, "size", 0)
        if free_space < 0:
            raise DeviceFactoryError("container changes impossible due to "
                                     "the devices it already contains")

    #
    # methods to configure the factory's device
    #
    def _get_child_factory_kwargs(self):
        kwargs = super(LVMFactory, self)._get_child_factory_kwargs()
        kwargs["encrypted"] = self.container_encrypted
        return kwargs

    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        return self.storage.newLV(*args, **kwargs)

    def _set_name(self):
        if self.device_name is None:
            return

        # TODO: write a StorageDevice.name setter
        lvname = "%s-%s" % (self.container.name, self.device_name)
        safe_new_name = self.storage.safeDeviceName(lvname)
        if self.device.name != safe_new_name:
            if safe_new_name in self.storage.names:
                log.error("not renaming '%s' to in-use name '%s'"
                            % (self.device._name, safe_new_name))
                return

            if not safe_new_name.startswith(self.container.name):
                log.error("device rename failure (%s)" % safe_new_name)
                return

            # strip off the vg name before setting
            safe_new_name = safe_new_name[len(self.container.name)+1:]
            log.debug("renaming device '%s' to '%s'"
                        % (self.device._name, safe_new_name))
            self.device._name = safe_new_name

class MDFactory(DeviceFactory):
    """ Factory for creating MD RAID devices. """
    child_factory_class = PartitionSetFactory
    child_factory_fstype = "mdmember"
    size_set_class = SameSizeSet

    def _get_device_space(self):
        return get_member_space(self.size, len(self._get_member_devices()),
                                level=self.raid_level)

    def _get_total_space(self):
        return self._get_device_space()

    def _set_raid_level(self):
        # TODO: write MDRaidArrayDevice.setRAIDLevel
        # make sure the member count is adequate for the new level

        # set the new level
        self.device.level = raidLevel(self.raid_level)

        # adjust the bitmap setting

    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        kwargs["level"] = self.raid_level
        kwargs["totalDevices"] = len(kwargs.get("parents"))
        kwargs["memberDevices"] = len(kwargs.get("parents"))
        return self.storage.newMDArray(*args, **kwargs)

    @property
    def container_list(self):
        return self.storage.mdarrays[:]

    def get_container(self, device=None, name=None, allow_existing=False):
        return self.raw_device

    def _create_container(self, *args, **kwargs):
        pass

class LVMOnMDFactory(LVMFactory):
    """ LVM logical volume with single md physical volume.

        The specified raid level applies to the md layer -- not the lvm layer.
    """
    child_factory_class = MDFactory

    def _get_total_space(self):
        base = super(LVMOnMDFactory, self)._get_total_space()
        # add one extent per disk to account for mysterious space requirements
        base += LVM_PE_SIZE * len(self.disks)
        return base

    def _get_child_factory_kwargs(self):
        kwargs = super(LVMOnMDFactory, self)._get_child_factory_kwargs()
        kwargs["raid_level"] = self.container_raid_level
        if self.container and self.container.parents:
            kwargs["device"] = self.container.parents[0]
        else:
            kwargs["name"] = self.storage.suggestDeviceName(prefix="pv")

        return kwargs

    def _configure(self):
        # If there's already a VG associated with this LV that doesn't have MD
        # PVs we need to remove the partition PVs.
        self._set_container()
        if self.container:
            for member in self.container.parents[:]:
                use_dev = member
                if isinstance(member, LUKSDevice):
                    use_dev = member.slave

                if use_dev.type != "mdarray":
                    self.container.removeMember(member)
                    self.storage.destroyDevice(member)
                    if member != use_dev:
                        self.storage.destroyDevice(use_dev)

        super(LVMOnMDFactory, self)._configure()

class BTRFSFactory(DeviceFactory):
    """ BTRFS subvolume """
    child_factory_class = PartitionSetFactory
    child_factory_fstype = "btrfs"

    def __init__(self, storage, size, disks, **kwargs):
        super(BTRFSFactory, self).__init__(storage, size, disks, **kwargs)

        if self.encrypted:
            log.info("overriding encryption setting for btrfs factory")
            self.encrypted = False

        self.container_raid_level = self.container_raid_level or "single"
        if self.container_raid_level == "single":
            self.size_set_class = TotalSizeSet
        else:
            self.size_set_class = SameSizeSet

    def _handle_no_size(self):
        """ Set device size so that it grows to the largest size possible. """
        super(BTRFSFactory, self)._handle_no_size()
        if self.container and self.container.exists:
            self.size = self.container.size

    def _get_total_space(self):
        """ Return the total space needed for the specified container. """
        size = 0
        if self.container and self.container.exists:
            return size

        if self.container_size == SIZE_POLICY_AUTO:
            # automatic
            if self.container and not self.device:
                # For new subvols the size is in addition to the volume's size.
                size += sum(s.req_size for s in self.container.subvolumes)

            size += self._get_device_space()
        elif self.container_size == SIZE_POLICY_MAX:
            # as large as possible
            if self.container:
                size += self.container.size

            size += self._get_free_disk_space()
        else:
            # fixed-size request
            size = self.container_size

        return size

    def _get_device_space(self):
        # until we get/need something better
        if self.container_raid_level in ("single", "raid0"):
            return self.size
        elif self.container_raid_level in ("raid1", "raid10"):
            return self.size * len(self._get_member_devices())

    @property
    def container_list(self):
        return self.storage.btrfsVolumes[:]

    def _get_new_container(self, *args, **kwargs):
        return self.storage.newBTRFS(*args, **kwargs)

    def _create_container(self):
        """ Create the container device required by this factory device. """
        parents = self._get_parent_devices()
        self.container = self._get_new_container(name=self.container_name,
                                                 dataLevel=self.container_raid_level,
                                                 parents=parents)
        self.storage.createDevice(self.container)

    def _set_container_raid_level(self):
        # TODO: write BTRFSVolumeDevice.setRAIDLevel
        # make sure the member count is adequate for the new level

        # set the new level
        self.container.dataLevel = self.container_raid_level

    def _get_child_factory_kwargs(self):
        kwargs = super(BTRFSFactory, self)._get_child_factory_kwargs()
        kwargs["encrypted"] = self.container_encrypted
        return kwargs

    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        kwargs["dataLevel"] = self.container_raid_level
        kwargs["metaDataLevel"] = self.container_raid_level
        kwargs["subvol"] = True
        return self.storage.newBTRFS(*args, **kwargs)

    def _set_name(self):
        super(BTRFSFactory, self)._set_name()
        if self.device_name is None:
            return

        self.device.format.options = "subvol=" + self.device.name
