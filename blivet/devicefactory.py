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

from six import raise_from

from .storage_log import log_method_call
from .errors import DeviceFactoryError, StorageError
from .devices import BTRFSDevice, DiskDevice
from .devices import LUKSDevice, LVMLogicalVolumeDevice
from .devices import PartitionDevice, MDRaidArrayDevice
from .devices.lvm import DEFAULT_THPOOL_RESERVE
from .formats import get_format
from .devicelibs import btrfs
from .devicelibs import mdraid
from .devicelibs import lvm
from .devicelibs import raid
from .devicelibs import crypto
from .partitioning import SameSizeSet
from .partitioning import TotalSizeSet
from .partitioning import do_partitioning
from .size import Size
from .static_data import luks_data

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

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
DEVICE_TYPE_LVM_THINP = 5


def is_supported_device_type(device_type):
    """ Return True if blivet supports this device type.

        :param device_type: an enumeration indicating the device type
        :type device_type: int

        :returns: True if this device type is supported
        :rtype: bool
    """
    devices = []
    if device_type == DEVICE_TYPE_BTRFS:
        devices = [BTRFSDevice]
    elif device_type == DEVICE_TYPE_DISK:
        devices = [DiskDevice]
    elif device_type in (DEVICE_TYPE_LVM, DEVICE_TYPE_LVM_THINP):
        devices = [LVMLogicalVolumeDevice]
    elif device_type == DEVICE_TYPE_PARTITION:
        devices = [PartitionDevice]
    elif device_type == DEVICE_TYPE_MD:
        devices = [MDRaidArrayDevice]

    return not any(c.unavailable_type_dependencies() for c in devices)


def get_supported_raid_levels(device_type):
    """ Return the supported raid levels for this device type.

        :param device_type: an enumeration indicating the device type
        :type device_type: int

        :returns: a set of supported raid levels for this device type
        :rtype: set of :class:`~.devicelibs.raid.RAIDLevel`
    """
    pkg = None
    if device_type == DEVICE_TYPE_BTRFS:
        pkg = btrfs
    elif device_type in (DEVICE_TYPE_LVM, DEVICE_TYPE_LVM_THINP):
        pkg = lvm
    elif device_type == DEVICE_TYPE_MD:
        pkg = mdraid

    if pkg and all(d.available for d in pkg.EXTERNAL_DEPENDENCIES):
        return set(pkg.raid_levels)
    else:
        return set()


def get_device_type(device):
    # the only time we should ever get a thin pool here is when we're removing
    # an empty pool after removing the last thin lv, so the only thing we'll be
    # doing with the factory is adjusting the vg to account for the pool's
    # removal
    device_types = {"partition": DEVICE_TYPE_PARTITION,
                    "lvmlv": DEVICE_TYPE_LVM,
                    "lvmthinlv": DEVICE_TYPE_LVM_THINP,
                    "lvmthinpool": DEVICE_TYPE_LVM,
                    "btrfs subvolume": DEVICE_TYPE_BTRFS,
                    "btrfs volume": DEVICE_TYPE_BTRFS,
                    "mdarray": DEVICE_TYPE_MD}

    use_dev = device.raw_device
    if use_dev.is_disk:
        device_type = DEVICE_TYPE_DISK
    else:
        device_type = device_types.get(use_dev.type)

    return device_type


def get_device_factory(blivet, device_type=DEVICE_TYPE_LVM, **kwargs):
    """ Return a suitable DeviceFactory instance for device_type. """
    class_table = {DEVICE_TYPE_LVM: LVMFactory,
                   DEVICE_TYPE_BTRFS: BTRFSFactory,
                   DEVICE_TYPE_PARTITION: PartitionFactory,
                   DEVICE_TYPE_MD: MDFactory,
                   DEVICE_TYPE_LVM_THINP: LVMThinPFactory,
                   DEVICE_TYPE_DISK: DeviceFactory}

    factory_class = class_table[device_type]
    log.debug("instantiating %s: %s, %s, %s", factory_class,
              blivet, [d.name for d in kwargs.get("disks", [])], kwargs)
    return factory_class(blivet, **kwargs)


class DeviceFactory(object):

    """ Class for creation of devices based on a top-down specification

        DeviceFactory instances can be combined/stacked to create more complex
        device stacks like lvm with md pvs.

        Simplified call trace for creation of a new LV in a new VG with
        partition PVs::

            LVMFactory.configure
                PartitionSetFactory.configure   # set up PVs on partitions
                LVMFactory._create_container    # create container device (VG)
                LVMFactory._create_device       # create leaf device (LV)


        Simplified call trace for creation of a new LV in a new VG with a single
        MD PV with member partitions on multiple disks::

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
        been written to disk it will be adjusted to hold the new logical volume::

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
                                                      Size("10000 MB"),
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
                                                      Size("20000 MB"),
                                                      disks,
                                                      fstype="xfs",
                                                      label="videos",
                                                      name="videos",
                                                      container_name="data")
            factory.configure()

            # Now change the size of the "music" LV and adjust the size of the
            # "data" VG accordingly.
            factory = blivet.devicefactory.LVMFactory(_blivet,
                                                      Size("15000 MB"),
                                                      disks,
                                                      device=music_lv)
            factory.configure()

            # Write the new devices to disk and create the filesystems they
            # contain.
            _blivet.do_it()


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

    # This is a bit tricky, the child factory creates devices on top of which
    # this (parent) factory builds its devices. E.g. partitions (as PVs) for a
    # VG. And such "underlying" devices are called "parent" devices in other
    # places in Blivet. So a child factory actually creates parent devices.
    child_factory_class = None
    child_factory_fstype = None
    size_set_class = TotalSizeSet
    _default_settings = {"size": None,  # the requested size for this device
                         "disks": [],  # the set of disks to allocate from
                         "mountpoint": None,
                         "label": None,
                         "device_name": None,
                         "raid_level": None,
                         "encrypted": None,
                         "container": None,
                         "device": None,
                         "container_name": None,
                         "container_size": SIZE_POLICY_AUTO,
                         "container_raid_level": None,
                         "container_encrypted": None}

    def __init__(self, storage, **kwargs):
        """
            :param storage: a Blivet instance
            :type storage: :class:`~.Blivet`
            :keyword size: the desired size for the device
            :type size: :class:`~.size.Size`
            :keyword disks: the set of disks to use
            :type disks: list of :class:`~.devices.StorageDevice`

            :keyword fstype: filesystem type
            :type fstype: str
            :keyword mountpoint: filesystem mount point
            :type mountpoint: str
            :keyword label: filesystem label text
            :type label: str

            :keyword raid_level: raid level descriptor
            :type raid_level: any valid RAID level descriptor
            :keyword encrypted: whether to encrypt (boolean)
            :type encrypted: bool
            :keyword name: name of requested device
            :type name: str

            :keyword device: an already-defined but non-existent device to
                             adjust instead of creating a new device
            :type device: :class:`~.devices.StorageDevice`

            .. note::

                any device passed must be of the appropriate type for the
                factory class it is passed to

            :keyword container_name: name of requested container
            :type container_name: str
            :keyword container_raid_level: raid level for container
            :type container_raid_level: any valid RAID level descriptor
            :keyword container_encrypted: whether to encrypt the container
            :type container_encrypted: bool
            :keyword container_size: requested container size
            :type container_size: :class:`~.size.Size`, :const:`SIZE_POLICY_AUTO` (the default),
                                  or :const:`SIZE_POLICY_MAX`
            :keyword min_luks_entropy: minimum entropy in bits required for
                                       LUKS format creation
            :type min_luks_entropy: int
            :keyword luks_version: luks format version ("luks1" or "luks2")
            :type luks_version: str
            :keyword pbkdf_args: optional arguments for LUKS2 key derivation function
            :type pbkdf_args: :class:`~.formats.luks.LUKS2PBKDFArgs`
            :keyword luks_sector_size: encryption sector size (use only with LUKS version 2)
            :type luks_sector_size: int

        """
        self.storage = storage  # a Blivet instance

        self._encrypted = None
        self._raid_level = None
        self._container_raid_level = None

        # Apply defaults.
        for setting, value in self._default_settings.items():
            setattr(self, setting, value)

        self.fstype = None  # not included in default_settings b/c of special handling below
        self.min_luks_entropy = kwargs.get("min_luks_entropy")

        if self.min_luks_entropy is None:
            self.min_luks_entropy = luks_data.min_entropy

        self.luks_version = kwargs.get("luks_version") or crypto.DEFAULT_LUKS_VERSION
        self.pbkdf_args = kwargs.get("pbkdf_args", None)
        self.luks_sector_size = kwargs.get("luks_sector_size") or 0

        # If a device was passed, update the defaults based on it.
        self.device = kwargs.get("device")
        self._update_defaults_from_device()

        # Map kwarg 'name' to attribute 'device_name'.
        if "name" in kwargs:
            kwargs["device_name"] = kwargs.pop("name")

        # Now override defaults with values passed via kwargs.
        for setting, value in kwargs.items():
            setattr(self, setting, value)

        self.original_size = self.size
        self.original_disks = self.disks[:]

        if not self.fstype:
            self.fstype = self.storage.get_fstype(mountpoint=self.mountpoint)
            if self.fstype == "swap":
                self.mountpoint = None

        self.child_factory = None       # factory creating the parent devices (e.g. PVs for a VG)
        self.parent_factory = None      # factory this factory is a child factory for (e.g. the one creating an LV in a VG)

        # used for error recovery
        self.__devices = []
        self.__actions = []
        self.__names = []
        self.__roots = []

    def _update_defaults_from_device(self):
        """ Update default settings based on passed in device, if provided. """
        if self.device is None:
            return

        self.size = getattr(self.device, "req_size", self.device.size)
        self.disks = getattr(self.device, "req_disks", self.device.disks[:])

        self.fstype = self.device.format.type
        self.mountpoint = getattr(self.device.format, "mountpoint", None)
        self.label = getattr(self.device.format, "label", None)

        # TODO: add a "raid_level" attribute to all relevant classes (or to RaidDevice)
        if hasattr(self.device, "level"):
            self.raid_level = self.device.level
        elif hasattr(self.device, "data_level"):
            self.raid_level = self.device.data_level

        self.encrypted = isinstance(self.device, LUKSDevice)
        self.device_name = getattr(self.device, "lvname", self.device.name)

        if self.device and hasattr(self.device, "container"):
            self.container_name = self.device.container.name
            self.container_size = self.device.container.size_policy
            if hasattr(self.device.container, "data_level"):
                self.container_raid_level = self.device.container.data_level
            elif (hasattr(self.device.container, "pvs") and
                  len(self.device.container.pvs) == 1 and
                  hasattr(self.device.container.pvs[0].raw_device, "level")):
                self.container_raid_level = self.device.container.pvs[0].raw_device.level
            self.container_encrypted = all(isinstance(p, LUKSDevice)
                                           for p in self.device.container.parents)

    @property
    def encrypted(self):
        return self._encrypted

    @encrypted.setter
    def encrypted(self, value):
        if not self.encrypted and value and self.size:
            # encrypted, bump size up with LUKS metadata size
            self.size += get_format("luks").min_size
        elif self.encrypted and not value and self.size:
            self.size -= get_format("luks").min_size

        self._encrypted = value

    @property
    def raid_level(self):
        return self._raid_level

    @raid_level.setter
    def raid_level(self, value):
        """ Sets the RAID level for the factory.

            :param value: new RAID level
            :param type: a valid RAID level descriptor
            :returns: None
        """
        # pylint: disable=attribute-defined-outside-init
        if value is None:
            self._raid_level = None
        else:
            self._raid_level = raid.get_raid_level(value)

    @property
    def container_raid_level(self):
        return self._container_raid_level

    @container_raid_level.setter
    def container_raid_level(self, value):
        """ Sets the RAID level for the factory.

            :param value: new RAID level
            :param type: a valid RAID level descriptor
            :returns: None
        """
        # pylint: disable=attribute-defined-outside-init
        if value is None:
            self._container_raid_level = None
        else:
            self._container_raid_level = raid.get_raid_level(value)
    #
    # methods related to device size and disk space requirements
    #

    def _get_free_disk_space(self):
        free_info = self.storage.get_free_space(disks=self.disks)
        return sum(d[0] for d in free_info.values())

    def _normalize_size(self):
        if self.size is None:
            self._handle_no_size()
        elif self.size == Size(0):
            # zero size means we're adjusting the container after removing
            # a device from it so we don't want to change the size here
            return

        size = self.size
        fmt = get_format(self.fstype)
        if size < fmt.min_size:
            size = fmt.min_size
        elif fmt.max_size and size > fmt.max_size:
            size = fmt.max_size

        if self.size != size:
            log.debug("adjusted size from %s to %s to honor format limits",
                      self.size, size)
            self.size = size  # pylint: disable=attribute-defined-outside-init

    def _handle_no_size(self):
        """ Set device size so that it grows to the largest size possible. """
        if self.size is not None:
            return

        self.size = self._get_free_disk_space()  # pylint: disable=attribute-defined-outside-init

        if self.device:
            self.size += self.device.size

        if self.container_size > 0:
            self.size = min(self.container_size, self.size)  # pylint: disable=attribute-defined-outside-init

    def _get_total_space(self):
        """ Return the total space need for this factory's device/container.

            This is used for the size argument to the child factory constructor
            and also to construct the size set in PartitionSetFactory.configure.
        """
        size = self._get_device_space()
        if self.container:
            size += self.container.size

        if self.device:
            size -= self.device.size

        return size

    def _get_device_space(self):
        """ The total disk space required for the factory device. """
        return self.size

    def _get_device_size(self):
        """ Return the factory device size including container limitations. """
        return self.size

    def _set_device_size(self):
        """ Set the size of the factory device. """

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
            elif hasattr(device, "subvolumes"):
                container = device
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
                containers.sort(key=lambda c: getattr(c, "free_space", c.size),
                                reverse=True)
                container = containers[0]

        return container

    def _set_container(self):
        """ Set this factory's container device. """
        # pylint: disable=attribute-defined-outside-init
        self.container = self.get_container(device=self.raw_device,
                                            name=self.container_name)

    def _create_container(self):
        """ Create the container device required by this factory device. """
        parents = self._get_parent_devices()
        # pylint: disable=attribute-defined-outside-init, assignment-from-no-return
        self.container = self._get_new_container(name=self.container_name,
                                                 parents=parents)
        self.storage.create_device(self.container)
        if self.container_name is None:
            self.container_name = self.container.name

    def _get_new_container(self, *args, **kwargs):
        """ Type-specific container device instantiation. """

    def _check_container_size(self):
        """ Raise an exception if the container cannot hold its devices. """

    def _reconfigure_container(self):
        """ Reconfigure a defined container required by this factory device. """
        if getattr(self.container, "exists", False):
            return

        self._set_container_members()
        self._set_container_raid_level()

        # check that the container is still large enough to contain whatever
        # other devices it previously contained
        if self.size > 0:
            # only do this check if we're not doing post-removal cleanup
            self._check_container_size()

    def _set_container_members(self):
        if not self.child_factory:
            return

        members = self.child_factory.devices
        log.debug("new member set: %s", [d.name for d in members])
        log.debug("old member set: %s", [d.name for d in self.container.parents])
        for member in self.container.parents[:]:
            if member not in members:
                self.container.parents.remove(member)

        for member in members:
            if member not in self.container.parents:
                self.container.parents.append(member)

    def _set_container_raid_level(self):
        pass

    #
    # properties and methods related to the factory device
    #
    @property
    def raw_device(self):
        """ If self.device is encrypted, this is its backing device. """
        return self.device.raw_device if self.device else None

    @property
    def devices(self):
        """ A list of this factory's product devices. """
        return [self.device]

    #
    # methods to configure the factory device(s)
    #
    def _create_device(self):
        """ Create the factory device. """
        if self.size == Size(0):
            # A factory with a size of zero means you're adjusting a container
            # after removing a device from it.
            return

        fmt_args = {}
        if self.encrypted:
            fstype = "luks"
            mountpoint = None
            fmt_args["min_luks_entropy"] = self.min_luks_entropy
            fmt_args["luks_version"] = self.luks_version
            fmt_args["pbkdf_args"] = self.pbkdf_args
            fmt_args["luks_sector_size"] = self.luks_sector_size
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
        if size <= Size(0):
            raise DeviceFactoryError("not enough free space for new device")

        parents = self._get_parent_devices()

        try:
            # pylint: disable=assignment-from-no-return
            device = self._get_new_device(parents=parents,
                                          size=size,
                                          fmt_type=fstype,
                                          mountpoint=mountpoint,
                                          fmt_args=fmt_args,
                                          **kwa)
        except (StorageError, ValueError) as e:
            log.error("device instance creation failed: %s", e)
            raise

        self.storage.create_device(device)
        try:
            self._post_create()
        except (StorageError, blockdev.BlockDevError) as e:
            log.error("device post-create method failed: %s", e)
            self.storage.destroy_device(device)
            raise_from(StorageError(e), e)
        else:
            if not device.size:
                self.storage.destroy_device(device)
                raise StorageError("failed to create device")

        ret = device
        if self.encrypted:
            fmt_args = {}
            if self.label:
                fmt_args["label"] = self.label

            fmt = get_format(self.fstype,
                             mountpoint=self.mountpoint,
                             **fmt_args)
            luks_device = LUKSDevice("luks-" + device.name,
                                     parents=[device], fmt=fmt)
            self.storage.create_device(luks_device)
            ret = luks_device

        self.device = ret

    def _get_new_device(self, *args, **kwargs):
        """ Type-specific device instantiation. """

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
        # reset the device's format before allocating partitions, &c
        if self.device.format.type != self.fstype:
            self.device.format = None

        # this is setting the device size based on the factory size and the
        # current size of the container
        self._set_device_size()

        try:
            self._post_create()
        except (StorageError, blockdev.BlockDevError) as e:
            log.error("device post-create method failed: %s", e)
            raise
        else:
            if (self.device.size < self.device.format.min_size or
                (self.device.size == self.device.format.min_size and
                 self.size > self.device.format.min_size)):
                raise StorageError("failed to adjust device -- not enough free space in specified disks?")

    def _set_format(self):
        current_format = self.device.format
        if current_format.type != self.fstype:
            new_format = get_format(self.fstype,
                                    mountpoint=self.mountpoint,
                                    label=self.label,
                                    exists=False)
            self.storage.format_device(self.device, new_format)
        else:
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
            orig_device = self.device
            raw_device = self.raw_device
            leaf_format = self.device.format
            if parent_container:
                parent_container.parents.remove(orig_device)
            self.storage.destroy_device(self.device)
            self.storage.format_device(self.raw_device, leaf_format)
            self.device = raw_device
            if parent_container:
                parent_container.parents.append(self.device)
        elif self.encrypted and not isinstance(self.device, LUKSDevice):
            orig_device = self.device
            leaf_format = self.device.format
            self.storage.format_device(self.device, get_format("luks",
                                                               min_luks_entropy=self.min_luks_entropy,
                                                               luks_version=self.luks_version,
                                                               pbkdf_args=self.pbkdf_args,
                                                               luks_sector_size=self.luks_sector_size))
            luks_device = LUKSDevice("luks-%s" % self.device.name,
                                     fmt=leaf_format,
                                     parents=self.device)
            self.storage.create_device(luks_device)
            self.device = luks_device
            if parent_container:
                parent_container.parents.append(self.device)
                parent_container.parents.remove(orig_device)

        if self.encrypted and isinstance(self.device, LUKSDevice) and \
                self.raw_device.format.luks_version != self.luks_version:
            self.raw_device.format.luks_version = self.luks_version

        if self.encrypted and isinstance(self.device, LUKSDevice) and \
                self.raw_device.format.luks_sector_size != self.luks_sector_size:
            self.raw_device.format.luks_sector_size = self.luks_sector_size

    def _set_name(self):
        if not self.device_name:
            # pylint: disable=attribute-defined-outside-init
            self.device_name = self.storage.suggest_device_name(
                parent=self.container,
                swap=(self.fstype == "swap"),
                mountpoint=self.mountpoint)

        safe_new_name = self.storage.safe_device_name(self.device_name,
                                                      get_device_type(self.device))
        if self.device.name != safe_new_name:
            if not safe_new_name:
                log.error("not renaming '%s' to invalid name '%s'",
                          self.device.name, self.device_name)
                return
            if safe_new_name in self.storage.names:
                log.error("not renaming '%s' to in-use name '%s'",
                          self.device.name, safe_new_name)
                return

            log.debug("renaming device '%s' to '%s'",
                      self.device.name, safe_new_name)
            self.raw_device.name = safe_new_name

    def _post_create(self):
        """ Hook for post-creation operations. """

    def _get_child_factory_args(self):
        return []

    def _get_child_factory_kwargs(self):
        return {"storage": self.storage,
                "size": self._get_total_space(),
                "disks": self.disks,
                "fstype": self.child_factory_fstype}

    def _set_up_child_factory(self):
        if self.child_factory or not self.child_factory_class or \
           self.container and self.container.exists:
            return

        args = self._get_child_factory_args()
        kwargs = self._get_child_factory_kwargs()
        log.debug("child factory class: %s", self.child_factory_class)
        log.debug("child factory args: %s", args)
        log.debug("child factory kwargs: %s", kwargs)
        factory = self.child_factory_class(*args, **kwargs)  # pylint: disable=not-callable
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
            log.error("failed to configure device factory: %s", e)
            if self.parent_factory is None:
                # only do the backup/restore error handling at the top-level
                self._revert_devicetree()

            if not isinstance(e, (StorageError, OverflowError)):
                raise_from(DeviceFactoryError(e), e)

            raise

    def _configure(self):
        self._set_container()
        if self.container and self.container.exists:
            self.disks = self.container.disks  # pylint: disable=attribute-defined-outside-init

        self._normalize_size()
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
            if level is None:
                continue

            disks = set(d for m in self._get_member_devices() for d in m.disks)
            if len(disks) < level.min_members:
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
        self.__roots = _blivet_copy.roots

    def _revert_devicetree(self):
        self.storage.devicetree._devices = self.__devices
        self.storage.devicetree._actions = self.__actions
        self.storage.roots = self.__roots


class PartitionFactory(DeviceFactory):

    """ Factory class for creating a partition. """
    #
    # methods related to device size and disk space requirements
    #

    def _get_base_size(self):
        if self.device:
            min_format_size = self.device.format.min_size
        else:
            min_format_size = get_format(self.fstype).min_size

        # min_format_size may be None here, make sure it is a number
        min_format_size = min_format_size or 0
        if self.encrypted:
            min_format_size += get_format("luks").min_size

        return max(Size("1MiB"), min_format_size)

    def _get_device_size(self):
        """ Return the factory device size including container limitations. """
        return max(self._get_base_size(), self.size)

    def _set_device_size(self):
        """ Set the size of a defined factory device. """
        if self.raw_device and self.size != self.raw_device.size:
            log.info("adjusting device size from %s to %s",
                     self.raw_device.size, self.size)

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

        device = self.storage.new_partition(*args,
                                            grow=True, maxsize=max_size,
                                            **kwargs)
        return device

    def _set_disks(self):
        self.raw_device.req_disks = self.disks[:]

    def _set_name(self):
        pass

    def _post_create(self):
        try:
            do_partitioning(self.storage)
        except (StorageError, blockdev.BlockDevError) as e:
            log.error("failed to allocate partitions: %s", e)
            raise


class PartitionSetFactory(PartitionFactory):

    """ Factory for creating a set of related partitions. """

    def __init__(self, storage, **kwargs):
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
        self._devices = kwargs.pop("devices", None) or []
        super(PartitionSetFactory, self).__init__(storage, **kwargs)

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
        log.debug("parent factory container: %s", self.parent_factory.container)
        if container:
            if container.exists:
                log.info("parent factory container exists -- nothing to do")
                return

            # update our device list from the parent factory's container members
            members = container.parents[:]
            self._devices = members

        log.debug("members: %s", [d.name for d in members])

        ##
        # Determine the target disk set.
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
        min_free = min(Size("500MiB"), self.parent_factory.size)
        add_disks = [d for d in add_disks if d.partitioned and
                     d.format.supported and d.format.free >= min_free]

        log.debug("add_disks: %s", [d.name for d in add_disks])
        log.debug("remove_disks: %s", [d.name for d in remove_disks])

        ##
        # Make a list of members we'll later remove from dropped disks.
        ##
        removed = []
        for member in members[:]:
            if any([d in remove_disks for d in member.disks]):
                removed.append(member)  # remove them after adding new ones
                members.remove(member)

        ##
        # Handle toggling of member encryption.
        ##
        for member in members[:]:
            member_encrypted = isinstance(member, LUKSDevice)
            if member_encrypted and not self.encrypted:
                if container:
                    container.parents.remove(member)
                self.storage.destroy_device(member)
                members.remove(member)
                self.storage.format_device(member.raw_device,
                                           get_format(self.fstype))
                members.append(member.raw_device)
                if container:
                    container.parents.append(member.raw_device)

                continue

            if not member_encrypted and self.encrypted:
                members.remove(member)
                self.storage.format_device(member, get_format("luks",
                                                              min_luks_entropy=self.min_luks_entropy,
                                                              luks_version=self.luks_version,
                                                              pbkdf_args=self.pbkdf_args,
                                                              luks_sector_size=self.luks_sector_size))
                luks_member = LUKSDevice("luks-%s" % member.name,
                                         parents=[member],
                                         fmt=get_format(self.fstype))
                self.storage.create_device(luks_member)
                members.append(luks_member)
                if container:
                    container.parents.append(luks_member)
                    container.parents.remove(member)

                continue

            if member_encrypted and self.encrypted and self.luks_version != member.raw_device.format.luks_version:
                member.raw_device.format.luks_version = self.luks_version
            if member_encrypted and self.encrypted and self.luks_sector_size != member.raw_device.format.luks_sector_size:
                member.raw_device.format.luks_sector_size = self.luks_sector_size

        ##
        # Prepare previously allocated member partitions for reallocation.
        ##
        base_size = self._get_base_size()
        for member in members[:]:
            member = member.raw_device

            # max size is set after instantiating the SizeSet below
            member.req_base_size = base_size
            member.req_size = member.req_base_size
            member.req_grow = True

        ##
        # Define members on added disks.
        ##
        new_members = []
        fmt_args = {}
        for disk in add_disks:
            if self.encrypted:
                member_format = "luks"
                fmt_args["luks_version"] = self.luks_version
                fmt_args["pbkdf_args"] = self.pbkdf_args
                fmt_args["luks_sector_size"] = self.luks_sector_size
            else:
                member_format = self.fstype

            try:
                member = self.storage.new_partition(parents=[disk], grow=True,
                                                    size=base_size,
                                                    fmt_type=member_format,
                                                    fmt_args=fmt_args)
            except (StorageError, blockdev.BlockDevError) as e:
                log.error("failed to create new member partition: %s", e)
                continue

            self.storage.create_device(member)
            if self.encrypted:
                fmt = get_format(self.fstype)
                member = LUKSDevice("luks-%s" % member.name,
                                    parents=[member], fmt=fmt)
                self.storage.create_device(member)

            members.append(member)
            new_members.append(member)
            if container:
                container.parents.append(member)

        ##
        # Remove members from dropped disks.
        ##
        # Do this last to prevent tripping raid level constraints on the number
        # of members.
        for member in removed:
            if container:
                container.parents.remove(member)

            if isinstance(member, LUKSDevice):
                self.storage.destroy_device(member)
                member = member.raw_device

            self.storage.destroy_device(member)

        ##
        # Determine target container size.
        ##
        total_space = self.parent_factory._get_total_space()

        ##
        # Set up SizeSet to manage growth of member partitions.
        ##
        log.debug("adding a %s with size %s",
                  self.parent_factory.size_set_class.__name__, total_space)
        size_set = self.parent_factory.size_set_class(members, total_space)
        self.storage.size_sets.append(size_set)
        for member in members[:]:
            member = member.raw_device
            member.req_max_size = size_set.size

        ##
        # Allocate the member partitions.
        ##
        self._post_create()


class LVMFactory(DeviceFactory):

    """ Factory for creating LVM logical volumes with partition PVs. """
    child_factory_class = PartitionSetFactory
    child_factory_fstype = "lvmpv"
    size_set_class = TotalSizeSet

    def __init__(self, storage, **kwargs):
        super(LVMFactory, self).__init__(storage, **kwargs)
        if self.container_raid_level:
            self.child_factory_class = MDFactory

    @property
    def vg(self):
        return self.container

    #
    # methods related to device size and disk space requirements
    #
    def _handle_no_size(self):
        """ Set device size so that it grows to the largest size possible. """
        if self.size is not None:
            return

        if self.container and (self.container.exists or
                               self.container_size != SIZE_POLICY_AUTO):
            self.size = self.container.free_space  # pylint: disable=attribute-defined-outside-init

            if self.container_size == SIZE_POLICY_MAX:
                self.size += self._get_free_disk_space()

            if self.device:
                self.size += self.device.size

            if self.size == Size(0):
                raise DeviceFactoryError("not enough free space for new device")
        else:
            super(LVMFactory, self)._handle_no_size()

    @property
    def _pe_size(self):
        if self.vg:
            return self.vg.pe_size
        else:
            return lvm.LVM_PE_SIZE

    def _get_device_space(self):
        """ The total disk space required for the factory device (LV). """
        return blockdev.lvm.get_lv_physical_size(self.size, self._pe_size)

    def _get_device_size(self):
        """ Return the factory device size including container limitations. """
        size = self.size
        free = self.vg.free_space
        if self.device:
            # self.raw_device == self.device.raw_device
            # (i.e. self.device or the backing device in case self.device is encrypted)
            free += self.raw_device.size

        if free < size:
            log.info("adjusting size from %s to %s so it fits "
                     "in container %s", size, free, self.vg.name)
            size = free

        return size

    def _set_device_size(self):
        """ Set the size of the factory device. """
        size = self._get_device_size()

        # self.raw_device == self.device.raw_device
        # (i.e. self.device or the backing device in case self.device is encrypted)
        if self.device and size != self.raw_device.size:
            log.info("adjusting device size from %s to %s",
                     self.raw_device.size, size)
            self.raw_device.size = size
            self.raw_device.req_grow = False

    def _get_total_space(self):
        """ Total disk space requirement for this device and its container. """
        space = Size(0)
        if self.vg and self.vg.exists:
            return space

        # unset the thpool_reserve here so that the previously reserved space is
        # considered free space (and thus swallowed) -> we will set it and
        # calculate an updated reserve below
        if self.vg:
            self.vg.thpool_reserve = None

        if self.container_size == SIZE_POLICY_AUTO:
            # automatic container size management
            if self.vg:
                space += sum(p.size for p in self.vg.parents)
                space -= self.vg.free_space
                # we need to account for the LVM metadata being placed somewhere
                space += self.vg.lvm_metadata_space
            else:
                # we need to account for the LVM metadata being placed on each disk
                # (and thus taking up to one extent from each disk)
                space += len(self.disks) * self._pe_size

            space += self._get_device_space()
            log.debug("size bumped to %s to include new device space", space)
            if self.device:
                space -= blockdev.lvm.round_size_to_pe(self.device.size, self._pe_size)
                log.debug("size cut to %s to omit old device space", space)

        elif self.container_size == SIZE_POLICY_MAX:
            # grow the container as large as possible
            if self.vg:
                space += sum(p.size for p in self.vg.parents)
                log.debug("size bumped to %s to include VG parents", space)

            space += self._get_free_disk_space()
            log.debug("size bumped to %s to include free disk space", space)
        else:
            # container_size is a request for a fixed size for the container
            space += blockdev.lvm.get_lv_physical_size(self.container_size, self._pe_size)

            # we need to account for the LVM metadata being placed on each disk
            # (and thus taking up to one extent from each disk)
            space += len(self.disks) * self._pe_size

        # make sure there's space reserved for a thin pool to grow in case thin provisioning is involved
        # XXX: This has to happen in this class because plain (non-thin) LVs are
        #      added through/by/with it even if the LVMThinPFactory class was
        #      used before to add some thin LVs. And the reserved space depends
        #      on the size of the VG, not on the thin pool's size.
        if self.vg and (any(lv.is_thin_pool for lv in self.vg.lvs) or isinstance(self, LVMThinPFactory)):
            self.vg.thpool_reserve = DEFAULT_THPOOL_RESERVE

        if (self.vg and self.vg.thpool_reserve) or isinstance(self, LVMThinPFactory):
            # black maths (to make sure there's DEFAULT_THPOOL_RESERVE.percent reserve)
            space_with_reserve = space.ensure_percent_reserve(DEFAULT_THPOOL_RESERVE.percent)
            reserve = space_with_reserve - space
            if reserve < DEFAULT_THPOOL_RESERVE.min:
                space = space + DEFAULT_THPOOL_RESERVE.min
            elif reserve < DEFAULT_THPOOL_RESERVE.max:
                space = space_with_reserve
            else:
                space = space + DEFAULT_THPOOL_RESERVE.max

        if self.container_encrypted:
            # Add space for LUKS metadata, each parent will be encrypted
            space += get_format("luks").min_size * len(self.disks)

        return space

    #
    # methods related to parent/container devices
    #
    @property
    def container_list(self):
        return self.storage.vgs[:]

    def _get_new_container(self, *args, **kwargs):
        return self.storage.new_vg(*args, **kwargs)

    def _check_container_size(self):
        """ Raise an exception if the container cannot hold its devices. """
        if not self.vg:
            return

        free_space = self.vg.free_space + getattr(self.device, "size", 0)
        if free_space < 0:
            raise DeviceFactoryError("container changes impossible due to "
                                     "the devices it already contains")

    #
    # methods to configure the factory's device
    #
    def _get_child_factory_kwargs(self):
        kwargs = super(LVMFactory, self)._get_child_factory_kwargs()
        kwargs["encrypted"] = self.container_encrypted
        kwargs["luks_version"] = self.luks_version

        if self.container_raid_level:
            # md pv
            kwargs["raid_level"] = self.container_raid_level
            if self.vg and self.vg.parents:
                kwargs["device"] = self.vg.parents[0]
                kwargs["name"] = self.vg.parents[0].name
            else:
                kwargs["name"] = self.storage.suggest_device_name(prefix="pv")

        return kwargs

    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        return self.storage.new_lv(*args, **kwargs)

    def _set_name(self):
        if not self.device_name:
            #  pylint: disable=attribute-defined-outside-init
            self.device_name = self.storage.suggest_device_name(
                parent=self.vg,
                swap=(self.fstype == "swap"),
                mountpoint=self.mountpoint)

        lvname = "%s-%s" % (self.vg.name, self.device_name)
        safe_new_name = self.storage.safe_device_name(lvname, DEVICE_TYPE_LVM)
        if self.device.name != safe_new_name:
            if safe_new_name in self.storage.names:
                log.error("not renaming '%s' to in-use name '%s'",
                          self.device.name, safe_new_name)
                return

            if not safe_new_name.startswith(self.vg.name):
                log.error("device rename failure (%s)", safe_new_name)
                return

            # strip off the vg name before setting
            safe_new_name = safe_new_name[len(self.vg.name) + 1:]
            log.debug("renaming device '%s' to '%s'",
                      self.device.name, safe_new_name)
            self.raw_device.name = safe_new_name

    def _configure(self):
        self._set_container()  # just sets self.container based on the specs
        if self.container and not self.container.exists:
            # If there's already a VG associated with this LV that doesn't have
            # MD PVs we need to remove the partition PVs.
            # Likewise, if there's already a VG whose PV is an MD we need to
            # remove it completely before proceeding.
            for member in self.container.parents[:]:
                use_dev = member.raw_device

                if ((self.container_raid_level and use_dev.type != "mdarray") or
                        (not self.container_raid_level and use_dev.type == "mdarray")):
                    self.container.parents.remove(member)
                    self.storage.destroy_device(member)
                    if member != use_dev:
                        self.storage.destroy_device(use_dev)

                    # for md pv we also need to remove the md member partitions
                    if not self.container_raid_level and \
                       use_dev.type == "mdarray":
                        for mdmember in use_dev.parents[:]:
                            self.storage.destroy_device(mdmember)

        super(LVMFactory, self)._configure()


class LVMThinPFactory(LVMFactory):

    """ Factory for creating LVM using thin provisioning.

        This class will be very similar to LVMFactory except that there are two
        layers of container: vg and thin pool (lv). We could make a separate
        factory class for creating and managing the thin pool, but we haven't
        used a separate factory for any of the other classes' containers.

          pv(s)
            vg
              pool
                thinlv(s)

        This is problematic in that there are two containers in this stack:
        the vg and thin pool.

        The thin pool does not need to be large enough to contain all of the
        thin lvs, so that check/adjust piece must be overridden/skipped here.

            XXX We aren't going to allow overcommitting initially, so that'll
                simplify things somewhat. That means we can manage the thin pool
                size automatically. We will need to handle overcommit in
                existing thinp setups in anaconda's UI.

        Because of the argument-passing madness that would ensue from being able
        to pass specs for two separate containers, the initial version of this
        class will only support auto-sized pools.

        Also, the initial version will only support one thin pool per vg.

        In summary:

            - one thin pool per vg
            - pools are auto-sized by anaconda/blivet
            - thinp setups created by the installer will not overcommit

        Where to manage the pool:

            - the pool will need to be adjusted on device removal, which means
              pool management must not be hidden in device management routines
    """

    def __init__(self, storage, **kwargs):
        # pool name is for identification -- not renaming
        self.pool_name = kwargs.pop("pool_name", None)
        super(LVMThinPFactory, self).__init__(storage, **kwargs)

        self.pool = None

    #
    # methods related to device size and disk space requirements
    #
    def _get_device_size(self):
        """ Calculate device size based on space in the pool. """
        pool_size = self.pool.size
        log.debug("pool size is %s", pool_size)
        free = pool_size - self.pool.used_space
        if self.device:
            free += self.raw_device.pool_space_used

        size = self.size
        if free < size:
            log.info("adjusting size from %s to %s so it fits "
                     "in pool %s", size, free, self.pool.name)
            size = free

        return size

    def _get_total_space(self):
        """ Calculate and return the total disk space needed for the vg.

            Our container (VG) will still be None if we are going to create it.
        """
        size = super(LVMThinPFactory, self)._get_total_space()
        # this does not apply if a specific container size was requested
        if self.container_size in (SIZE_POLICY_AUTO, SIZE_POLICY_MAX):
            if self.container_size == SIZE_POLICY_AUTO and \
               self.pool and not self.pool.exists and self.pool.free_space > 0:
                # this is mostly for cleaning up after removing a thin lv
                # we need to make sure the free space and its portion of the
                # reserved space in the VG are removed
                size -= self.pool.free_space

                # get the portion of the thpool reserve in the VG for the free
                # space
                reserve_portion = self.pool.free_space.ensure_percent_reserve(DEFAULT_THPOOL_RESERVE.percent) - self.pool.free_space

                # but we need to make sure at least DEFAULT_THPOOL_RESERVE.min
                # is kept as the reserve
                thpool_reserve = self.vg.size * (DEFAULT_THPOOL_RESERVE.percent / 100)
                if (thpool_reserve - reserve_portion) < DEFAULT_THPOOL_RESERVE.min:
                    reserve_portion -= DEFAULT_THPOOL_RESERVE.min - (thpool_reserve - reserve_portion)
                size -= reserve_portion
                log.debug("size cut to %s to omit pool free space (and its portion of the reserve)", size)

        return size

    @property
    def pool_list(self):
        return self.storage.thinpools

    def get_pool(self):
        if not self.vg:
            return None

        if self.device:
            return self.raw_device.pool

        # We're looking for a new pool in our vg to use. If there aren't any,
        # we're using one of the existing pools. Would it be better to always
        # create a new pool to allocate new devices from? Probably not, since
        # that would prevent users from setting up custom pools on tty2.
        pool = None
        pools = [p for p in self.pool_list if p.vg == self.vg]
        pools.sort(key=lambda p: p.free_space, reverse=True)
        if pools:
            new_pools = [p for p in pools if not p.exists]
            if new_pools:
                pool = new_pools[0]
            else:
                pool = pools[0]

        return pool

    def _get_new_pool(self, *args, **kwargs):
        kwargs["thin_pool"] = True
        return super(LVMThinPFactory, self)._get_new_device(*args, **kwargs)

    def _get_pool_size(self):
        """ Calculate and return the size for the thin pool.

            The vg size has already been set when this method is called. We have
            to figure out the size of the pool based on the vg's free space and
            the sizes of the thin lvs.

            Our container has been set by the time this method is called.
        """
        if self.pool and self.pool.exists:
            return self.pool.size

        log.debug("requested size is %s", self.size)
        size = self.size
        free = Size(0)  # total space within the vg that is available to us
        if self.pool:
            free += self.pool.free_space  # pools are always auto-sized
            # pool lv sizes go toward projected pool size and vg free space
            size += self.pool.used_space
            free += self.pool.used_space
            log.debug("increasing free and size by pool used (%s)", self.pool.used_space)
            if self.device:
                log.debug("reducing size by device space (%s)", self.raw_device.pool_space_used)
                size -= self.raw_device.pool_space_used   # don't count our device

        # round to nearest extent. free rounds down, size rounds up.
        free = self.vg.align(free + self.vg.free_space)
        size = self.vg.align(size, roundup=True)

        if free < size:
            size = free

        return size

    def _set_pool_size(self):
        new_size = self._get_pool_size()
        self.pool.size = new_size
        self.pool.req_grow = False
        self.pool.autoset_md_size(enforced=True)

    def _reconfigure_pool(self):
        """ Adjust the pool according to the set of devices it will contain. """
        self._set_pool_size()

    def _create_pool(self):
        """ Create a pool large enough to contain the new device. """
        if self.size == Size(0):
            return

        self.vg.thpool_reserve = DEFAULT_THPOOL_RESERVE
        size = self._get_pool_size()
        if size == Size(0):
            raise DeviceFactoryError("not enough free space for thin pool")

        self.pool = self._get_new_pool(size=size, parents=[self.vg])
        self.storage.create_device(self.pool)

        # reconfigure the pool here in case its presence in the VG has caused
        # some extra changes (e.g. reserving space for it to grow)
        self._reconfigure_pool()

    #
    # methods to configure the factory's container (both vg and pool)
    #
    def _set_container(self):
        """ Set this factory's container (VG) device. """
        super(LVMThinPFactory, self)._set_container()
        self.pool = self.get_pool()
        if self.pool:
            log.debug("pool is %s ; size: %s ; free: %s", self.pool.name,
                      self.pool.size,
                      self.pool.free_space)
            for lv in self.pool.lvs:
                log.debug("  %s size is %s", lv.name, lv.size)

    def _reconfigure_container(self):
        """ Reconfigure a defined container required by this factory device. """
        super(LVMThinPFactory, self)._reconfigure_container()
        if self.pool:
            self._reconfigure_pool()
        else:
            self._create_pool()

    def _create_container(self):
        """ Create the container device required by this factory device. """
        super(LVMThinPFactory, self)._create_container()
        self._create_pool()

    #
    # methods to configure the factory's device
    #
    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        kwargs["parents"] = [self.pool]
        kwargs["thin_volume"] = True
        return super(LVMThinPFactory, self)._get_new_device(*args, **kwargs)


class MDFactory(DeviceFactory):

    """ Factory for creating MD RAID devices. """
    child_factory_class = PartitionSetFactory
    child_factory_fstype = "mdmember"
    size_set_class = SameSizeSet

    def __init__(self, storage, **kwargs):
        super(MDFactory, self).__init__(storage, **kwargs)
        if not self.raid_level:
            raise DeviceFactoryError("MDFactory class must have some RAID level.")

    def _get_device_space(self):
        return self.raid_level.get_space(self.size,
                                         len(self._get_member_devices()),
                                         None,
                                         blockdev.md.get_superblock_size)

    def _get_total_space(self):
        return self._get_device_space()

    def _set_raid_level(self):
        # set the new level
        self.raw_device.level = self.raid_level

        # adjust the bitmap setting

    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        kwargs["level"] = self.raid_level
        kwargs["total_devices"] = len(kwargs.get("parents"))
        kwargs["member_devices"] = len(kwargs.get("parents"))
        return self.storage.new_mdarray(*args, **kwargs)

    @property
    def container_list(self):
        return self.storage.mdarrays[:]

    def get_container(self, device=None, name=None, allow_existing=False):
        return self.raw_device

    def _create_container(self):
        pass


class BTRFSFactory(DeviceFactory):

    """ BTRFS subvolume """
    child_factory_class = PartitionSetFactory
    child_factory_fstype = "btrfs"

    def __init__(self, storage, **kwargs):
        super(BTRFSFactory, self).__init__(storage, **kwargs)

        if self.encrypted:
            log.info("overriding encryption setting for btrfs factory")
            self.encrypted = False

        self.container_raid_level = self.container_raid_level or btrfs.raid_levels.raid_level("single")
        if self.container_raid_level.is_uniform:
            self.size_set_class = SameSizeSet
        else:
            self.size_set_class = TotalSizeSet

    def _handle_no_size(self):
        """ Set device size so that it grows to the largest size possible. """
        super(BTRFSFactory, self)._handle_no_size()
        if self.container and self.container.exists:
            self.size = self.container.size  # pylint: disable=attribute-defined-outside-init

    def _get_total_space(self):
        """ Return the total space needed for the specified container. """
        size = Size(0)
        if self.container and self.container.exists:
            return size

        if self.container_size == SIZE_POLICY_AUTO:
            # automatic
            if self.container and not self.device:
                if self.size != Size(0):
                    # For new subvols the size is in addition to the volume's size.
                    size += self.container.size
                else:
                    size += sum((s.req_size for s in self.container.subvolumes), Size(0))

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
        if self.container_raid_level in (raid.Single, raid.RAID0):
            return self.size
        elif self.container_raid_level in (raid.RAID1, raid.RAID10):
            return self.size * len(self._get_member_devices())

    @property
    def container_list(self):
        return self.storage.btrfs_volumes[:]

    def _get_new_container(self, *args, **kwargs):
        return self.storage.new_btrfs(*args, **kwargs)

    def _create_container(self):
        """ Create the container device required by this factory device. """
        parents = self._get_parent_devices()
        # pylint: disable=attribute-defined-outside-init
        self.container = self._get_new_container(name=self.container_name,
                                                 data_level=self.container_raid_level,
                                                 parents=parents)
        self.storage.create_device(self.container)

    def _set_container_raid_level(self):
        # TODO: write BTRFSVolumeDevice.set_raid_level
        # make sure the member count is adequate for the new level

        # set the new level
        self.container.data_level = self.container_raid_level

    def _get_child_factory_kwargs(self):
        kwargs = super(BTRFSFactory, self)._get_child_factory_kwargs()
        kwargs["encrypted"] = self.container_encrypted
        kwargs["luks_version"] = self.luks_version
        return kwargs

    def _get_new_device(self, *args, **kwargs):
        """ Create and return the factory device as a StorageDevice. """
        kwargs["data_level"] = self.container_raid_level
        kwargs["metadata_level"] = self.container_raid_level
        kwargs["subvol"] = True
        return self.storage.new_btrfs(*args, **kwargs)

    def _set_name(self):
        super(BTRFSFactory, self)._set_name()
        self.device.format.options = "subvol=" + self.device.name

    def _reconfigure_device(self):
        if self.device == self.container:
            # This is a btrfs volume -- the only thing not handled already is
            # updating the mountpoint.
            self.device.format.mountpoint = self.mountpoint
            return

        super(BTRFSFactory, self)._reconfigure_device()
