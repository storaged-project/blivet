#
# Copyright (C) 2009-2015  Red Hat, Inc.
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

import copy
import tempfile
import re
import shelve
import contextlib
import time
import functools
import six

from .storage_log import log_method_call, log_exception_info
from .devices import BTRFSSubVolumeDevice, BTRFSVolumeDevice
from .devices import LVMLogicalVolumeDevice, LVMVolumeGroupDevice
from .devices import MDRaidArrayDevice, PartitionDevice, TmpFSDevice, device_path_to_name
from .deviceaction import ActionCreateDevice, ActionCreateFormat, ActionDestroyDevice
from .deviceaction import ActionDestroyFormat, ActionResizeDevice, ActionResizeFormat
from .devicelibs.edd import get_edd_dict
from .devicelibs.btrfs import MAIN_VOLUME_ID
from .devicelibs.crypto import LUKS_METADATA_SIZE
from .errors import StorageError, DependencyError
from .size import Size
from .devicetree import DeviceTree
from .formats import get_default_filesystem_type
from .flags import flags
from .formats import get_format
from .util import capture_output
from . import arch
from . import devicefactory
from . import __version__
from . import devicelibs
from .threads import SynchronizedMeta
from .static_data import luks_data

import logging
log = logging.getLogger("blivet")


@six.add_metaclass(SynchronizedMeta)
class Blivet(object):

    """ Top-level class for managing storage configuration. """

    def __init__(self):
        # storage configuration variables
        self.encryption_passphrase = None
        self.edd_dict = {}

        self.ignored_disks = []
        self.exclusive_disks = []
        self.disk_images = {}

        self.__luks_devs = {}
        self.size_sets = []
        self.set_default_fstype(get_default_filesystem_type())

        self._short_product_name = 'blivet'

        self._next_id = 0
        self._dump_file = "%s/storage.state" % tempfile.gettempdir()

        try:
            options = "NAME,SIZE,OWNER,GROUP,MODE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINT"
            out = capture_output(["lsblk", "--bytes", "-a", "-o", options])
        except Exception:  # pylint: disable=broad-except
            pass
        else:
            log.debug("lsblk output:\n%s", out)

        # these will both be empty until our reset method gets called
        self.devicetree = DeviceTree(ignored_disks=self.ignored_disks,
                                     exclusive_disks=self.exclusive_disks,
                                     disk_images=self.disk_images)
        self.roots = []

    @property
    def short_product_name(self):
        return self._short_product_name

    @short_product_name.setter
    def short_product_name(self, name):
        """ Change the (short) product name.
        :param name: The product name.
        :type name: string
        """
        log.debug("new short product name: %s", name)
        self._short_product_name = name

    def do_it(self, callbacks=None):
        """
        Commit queued changes to disk.

        :param callbacks: callbacks to be invoked when actions are executed
        :type callbacks: return value of the :func:`~.callbacks.create_new_callbacks_register`

        """

        self.devicetree.actions.process(callbacks=callbacks, devices=self.devices)

    @property
    def next_id(self):
        """ Used for creating unique placeholder names. """
        newid = self._next_id
        self._next_id += 1
        return newid

    def reset(self, cleanup_only=False):
        """ Reset storage configuration to reflect actual system state.

            This will cancel any queued actions and rescan from scratch but not
            clobber user-obtained information like passphrases, iscsi config, &c

            :keyword cleanup_only: prepare the tree only to deactivate devices
            :type cleanup_only: bool

            See :meth:`devicetree.Devicetree.populate` for more information
            about the cleanup_only keyword argument.
        """
        log.info("resetting Blivet (version %s) instance %s", __version__, self)

        self.devicetree.reset(ignored_disks=self.ignored_disks,
                              exclusive_disks=self.exclusive_disks,
                              disk_images=self.disk_images)
        self.devicetree.populate(cleanup_only=cleanup_only)
        self.edd_dict = get_edd_dict(self.partitioned)
        self.devicetree.edd_dict = self.edd_dict

        if flags.include_nodev:
            self.devicetree.handle_nodev_filesystems()

    @property
    def devices(self):
        """ A list of all the devices in the device tree. """
        devices = self.devicetree.devices
        devices.sort(key=lambda d: d.name)
        return devices

    @property
    def disks(self):
        """ A list of the disks in the device tree.

            Ignored disks are excluded, as are disks with no media present.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        disks = []
        for device in self.devicetree.devices:
            if device.is_disk:
                if not device.media_present:
                    log.info("Skipping disk: %s: No media present", device.name)
                    continue
                disks.append(device)
        disks.sort(key=self.compare_disks_key)
        return disks

    @property
    def partitioned(self):
        """ A list of the partitioned devices in the device tree.

            Ignored devices are not included, nor disks with no media present.

            Devices of types for which partitioning is not supported are also
            not included.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        partitioned = []
        for device in self.devicetree.devices:
            if not device.partitioned:
                continue

            if not device.media_present:
                log.info("Skipping device: %s: No media present", device.name)
                continue

            partitioned.append(device)

        partitioned.sort(key=lambda d: d.name)
        return partitioned

    @property
    def partitions(self):
        """ A list of the partitions in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        partitions = [d for d in self.devices if isinstance(d, PartitionDevice)]
        partitions.sort(key=lambda d: d.name)
        return partitions

    @property
    def vgs(self):
        """ A list of the LVM Volume Groups in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        vgs = [d for d in self.devices if d.type == "lvmvg"]
        vgs.sort(key=lambda d: d.name)
        return vgs

    @property
    def lvs(self):
        """ A list of the LVM Logical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        lvs = (d for d in self.devices if d.type in ("lvmlv", "lvmthinpool", "lvmthinlv"))
        return sorted(lvs, key=lambda d: d.name)

    @property
    def thinlvs(self):
        """ A list of the LVM Thin Logical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        thin = [d for d in self.devices if d.type == "lvmthinlv"]
        thin.sort(key=lambda d: d.name)
        return thin

    @property
    def thinpools(self):
        """ A list of the LVM Thin Pool Logical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        pools = [d for d in self.devices if d.type == "lvmthinpool"]
        pools.sort(key=lambda d: d.name)
        return pools

    @property
    def pvs(self):
        """ A list of the LVM Physical Volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        devices = self.devicetree.devices
        pvs = [d for d in devices if d.format.type == "lvmpv"]
        pvs.sort(key=lambda d: d.name)
        return pvs

    @property
    def mdarrays(self):
        """ A list of the MD arrays in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        arrays = [d for d in self.devices if d.type == "mdarray"]
        arrays.sort(key=lambda d: d.name)
        return arrays

    @property
    def mdcontainers(self):
        """ A list of the MD containers in the device tree. """
        arrays = [d for d in self.devices if d.type == "mdcontainer"]
        arrays.sort(key=lambda d: d.name)
        return arrays

    @property
    def mdmembers(self):
        """ A list of the MD member devices in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        devices = self.devicetree.devices
        members = [d for d in devices if d.format.type == "mdmember"]
        members.sort(key=lambda d: d.name)
        return members

    @property
    def btrfs_volumes(self):
        """ A list of the BTRFS volumes in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        return sorted((d for d in self.devices if d.type == "btrfs volume"),
                      key=lambda d: d.name)

    @property
    def swaps(self):
        """ A list of the swap devices in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        devices = self.devicetree.devices
        swaps = [d for d in devices if d.format.type == "swap"]
        swaps.sort(key=lambda d: d.name)
        return swaps

    @property
    def encryption_passphrase(self):
        return luks_data.encryption_passphrase

    @encryption_passphrase.setter
    def encryption_passphrase(self, value):
        luks_data.encryption_passphrase = value

    def save_passphrase(self, device):
        luks_data.save_passphrase(device)

    def recursive_remove(self, device):
        """ Remove a device after removing its dependent devices.

            If the device is not a leaf, all of its dependents are removed
            recursively until it is a leaf device. At that point the device is
            removed, unless it is a disk. If the device is a disk, its
            formatting is removed by no attempt is made to actually remove the
            disk device.
        """
        self.devicetree.recursive_remove(device)

    def initialize_disk(self, disk):
        """ (Re)initialize a disk by creating a disklabel on it.

            The disk should not contain any partitions except perhaps for a
            magic partitions on mac and sun disklabels. If the disk does contain
            partitions other than the disklabel-type-specific "magic" partitions
            ValueError will be raised.

            :param disk: the disk to initialize
            :type disk: :class:`~.devices.StorageDevice`
            :returns None:
            :raises: ValueError
        """
        # first, remove magic mac/sun partitions from the parted Disk
        if disk.partitioned:
            magic = disk.format.magic_partition_number
            expected = 0
            if magic:
                expected = 1
                # remove the magic partition
                for part in disk.children:
                    if part.parted_partition.number == magic:
                        log.debug("removing %s", part.name)
                        # We can't schedule the magic partition for removal
                        # because parted will not allow us to remove it from the
                        # disk. Still, we need it out of the devicetree.
                        self.devicetree._remove_device(part, modparent=False)

            if len(disk.format.partitions) > expected:
                raise ValueError("cannot initialize a disk that has partitions")

        # remove existing formatting from the disk
        destroy_action = ActionDestroyFormat(disk)
        self.devicetree.actions.add(destroy_action)

        # create a new disklabel on the disk
        new_label = get_format("disklabel", device=disk.path)
        create_action = ActionCreateFormat(disk, fmt=new_label)
        self.devicetree.actions.add(create_action)

    def remove_empty_extended_partitions(self):
        for disk in self.partitioned:
            log.debug("checking whether disk %s has an empty extended", disk.name)
            extended = disk.format.extended_partition
            logical_parts = disk.format.logical_partitions
            log.debug("extended is %s ; logicals is %s", extended, [p.getDeviceNodeName() for p in logical_parts])
            if extended and not logical_parts:
                log.debug("removing empty extended partition from %s", disk.name)
                extended_name = device_path_to_name(extended.getDeviceNodeName())
                extended = self.devicetree.get_device_by_name(extended_name)
                self.destroy_device(extended)

    def get_free_space(self, disks=None, partitions=None):
        """ Return a dict with free space info for each disk.

            The dict values are 2-tuples: (disk_free, fs_free). fs_free is
            space available by shrinking filesystems. disk_free is space not
            allocated to any partition.

            disks and partitions allow specifying a set of disks other than
            self.disks and partition values other than self.parttions.

            :keyword disks: overrides :attr:`disks`
            :type disks: list
            :keyword partitions: overrides :attr:`partitions`
            :type partitions: list
            :returns: dict with disk name keys and tuple (disk, fs) free values
            :rtype: dict

            .. note::

                The free space values are :class:`~.size.Size` instances.

        """
        if disks is None:
            disks = self.disks

        if partitions is None:
            partitions = self.partitions

        free = {}
        for disk in disks:
            disk_free = Size(0)
            fs_free = Size(0)
            if disk.partitioned:
                disk_free = disk.format.free
                for partition in (p for p in partitions if p.disk == disk):
                    if partition.format.exists and hasattr(partition.format, "free"):
                        fs_free += partition.format.free
            elif disk.format.exists and hasattr(disk.format, "free"):
                fs_free = disk.format.free
            elif disk.format.type is None:
                disk_free = disk.size

            free[disk.name] = (disk_free, fs_free)

        return free

    @property
    def names(self):
        """ A list of all of the known in-use device names. """
        return self.devicetree.names

    def device_deps(self, device):
        """ Return a list of the devices that depend on the specified device.

            :param device: the subtree root device
            :type device: :class:`~.devices.StorageDevice`
            :returns: list of dependent devices
            :rtype: list
        """
        return self.devicetree.get_dependent_devices(device)

    def new_partition(self, *args, **kwargs):
        """ Return a new (unallocated) PartitionDevice instance.

            :keyword fmt_type: format type
            :type fmt_type: str
            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str

            All other arguments are passed on to the
            :class:`~.devices.PartitionDevice` constructor.
        """
        if 'fmt_type' in kwargs:
            kwargs["fmt"] = get_format(kwargs.pop("fmt_type"),
                                       mountpoint=kwargs.pop("mountpoint",
                                                             None),
                                       **kwargs.pop("fmt_args", {}))

        if 'name' in kwargs:
            name = kwargs.pop("name")
        else:
            name = "req%d" % self.next_id

        return PartitionDevice(name, *args, **kwargs)

    def new_mdarray(self, *args, **kwargs):
        """ Return a new MDRaidArrayDevice instance.

            :keyword fmt_type: format type
            :type fmt_type: str
            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :returns: the new md array device
            :rtype: :class:`~.devices.MDRaidArrayDevice`

            All other arguments are passed on to the
            :class:`~.devices.MDRaidArrayDevice` constructor.

            If a name is not specified, one will be generated based on the
            format type, mountpoint, hostname, and/or product name.
        """
        if 'fmt_type' in kwargs:
            kwargs["fmt"] = get_format(kwargs.pop("fmt_type"),
                                       mountpoint=kwargs.pop("mountpoint",
                                                             None),
                                       **kwargs.pop("fmt_args", {}))

        name = kwargs.pop("name", None)
        if name:
            safe_name = self.safe_device_name(name, devicefactory.DEVICE_TYPE_MD)
            if safe_name != name:
                log.warning("using '%s' instead of specified name '%s'",
                            safe_name, name)
                name = safe_name
        else:
            swap = getattr(kwargs.get("fmt"), "type", None) == "swap"
            mountpoint = getattr(kwargs.get("fmt"), "mountpoint", None)
            name = self.suggest_device_name(prefix=self.short_product_name,
                                            swap=swap,
                                            mountpoint=mountpoint)

        return MDRaidArrayDevice(name, *args, **kwargs)

    def new_vg(self, *args, **kwargs):
        """ Return a new LVMVolumeGroupDevice instance.

            :returns: the new volume group device
            :rtype: :class:`~.devices.LVMVolumeGroupDevice`

            All arguments are passed on to the
            :class:`~.devices.LVMVolumeGroupDevice` constructor.

            If a name is not specified, one will be generated based on the
            hostname, and/or product name.
        """
        pvs = kwargs.pop("parents", [])
        for pv in pvs:
            if pv not in self.devices:
                raise ValueError("pv is not in the device tree")

        name = kwargs.pop("name", None)
        if name:
            safe_name = self.safe_device_name(name, devicefactory.DEVICE_TYPE_LVM)
            if safe_name != name:
                log.warning("using '%s' instead of specified name '%s'",
                            safe_name, name)
                name = safe_name
        else:
            name = self.suggest_container_name()

        if name in self.names:
            raise ValueError("name already in use")

        return LVMVolumeGroupDevice(name, pvs, *args, **kwargs)

    def new_lv(self, *args, **kwargs):
        """ Return a new LVMLogicalVolumeDevice instance.

            :keyword fmt_type: format type
            :type fmt_type: str
            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :keyword thin_pool: whether to create a thin pool
            :type thin_pool: bool
            :keyword thin_volume: whether to create a thin volume
            :type thin_volume: bool
            :returns: the new device
            :rtype: :class:`~.devices.LVMLogicalVolumeDevice`

            All other arguments are passed on to the appropriate
            :class:`~.devices.LVMLogicalVolumeDevice` constructor.

            If a name is not specified, one will be generated based on the
            format type and/or mountpoint.

            .. note::

                If you are creating a thin volume, the parents kwarg should
                contain the pool -- not the vg.
        """
        thin_volume = kwargs.pop("thin_volume", False)
        thin_pool = kwargs.pop("thin_pool", False)
        parent = kwargs.get("parents", [None])[0]
        if thin_volume and parent:
            # kwargs["parents"] will contain the pool device, so...
            vg = parent.vg
        else:
            vg = parent

        if thin_volume:
            kwargs["seg_type"] = "thin"
        if thin_pool:
            kwargs["seg_type"] = "thin-pool"

        mountpoint = kwargs.pop("mountpoint", None)
        if 'fmt_type' in kwargs:
            kwargs["fmt"] = get_format(kwargs.pop("fmt_type"),
                                       mountpoint=mountpoint,
                                       **kwargs.pop("fmt_args", {}))

        name = kwargs.pop("name", None)
        if name:
            # make sure the specified name is sensible
            safe_vg_name = self.safe_device_name(vg.name, devicefactory.DEVICE_TYPE_LVM)
            full_name = "%s-%s" % (safe_vg_name, name)
            safe_name = self.safe_device_name(full_name, devicefactory.DEVICE_TYPE_LVM)
            if safe_name != full_name:
                new_name = safe_name[len(safe_vg_name) + 1:]
                log.warning("using '%s' instead of specified name '%s'",
                            new_name, name)
                name = new_name
        else:
            if kwargs.get("fmt") and kwargs["fmt"].type == "swap":
                swap = True
            else:
                swap = False

            prefix = ""
            if thin_pool:
                prefix = "pool"

            name = self.suggest_device_name(parent=vg,
                                            swap=swap,
                                            mountpoint=mountpoint,
                                            prefix=prefix)

        if "%s-%s" % (vg.name, name) in self.names:
            raise ValueError("name already in use")

        if thin_pool or thin_volume:
            cache_req = kwargs.pop("cache_request", None)
            if cache_req:
                raise ValueError("Creating cached thin volumes and pools is not supported")

        return LVMLogicalVolumeDevice(name, *args, **kwargs)

    def new_lv_from_lvs(self, vg, name, seg_type, from_lvs, **kwargs):
        """ Return a new LVMLogicalVolumeDevice created from other LVs

            :param vg: VG to create the new LV in
            :type vg: :class:`~.devices.lvm.LVMVolumeGroupDevice`
            :param str name: name of the new LV
            :param str seg_type: segment type of the new LV
            :param from_lvs: LVs to create the new LV from (in the (data_lv, metadata_lv) order)
            :type from_lvs: tuple of :class:`~.devices.lvm.LVMLogicalVolumeDevice`
            :rtype: :class:`~.devices.lvm.LVMLogicalVolumeDevice`

            All other arguments are passed on to the :class:`~.devices.lvm.LVMLogicalVolumeDevice`
            constructor.

        """
        # we need to remove the LVs from the devicetree because they are now
        # internal LVs of the new LV
        for lv in from_lvs:
            if lv in self.devicetree.devices:
                self.devicetree._remove_device(lv)
            else:
                raise ValueError("All LVs to construct a new one from have to be in the devicetree")

        return LVMLogicalVolumeDevice(name, parents=vg, seg_type=seg_type, from_lvs=from_lvs, **kwargs)

    def new_btrfs(self, *args, **kwargs):
        """ Return a new BTRFSVolumeDevice or BRFSSubVolumeDevice.

            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :keyword subvol: whether this is a subvol (as opposed to a volume)
            :type subvol: bool
            :returns: the new device
            :rtype: :class:`~.devices.BTRFSDevice`

            All other arguments are passed on to the appropriate
            :class:`~.devices.BTRFSDevice` constructor.

            For volumes, the label is the same as the name. If a name/label is
            not specified, one will be generated based on the hostname and/or
            product name.

            .. note::

                If you are creating a subvolume, the parents kwarg should
                contain the volume you want to contain the subvolume.

        """
        log.debug("new_btrfs: args = %s ; kwargs = %s", args, kwargs)
        name = kwargs.pop("name", None)
        if args:
            name = args[0]

        mountpoint = kwargs.pop("mountpoint", None)

        fmt_args = kwargs.pop("fmt_args", {})
        fmt_args.update({"mountpoint": mountpoint})

        if kwargs.pop("subvol", False):
            dev_class = BTRFSSubVolumeDevice

            # set up the subvol name, using mountpoint if necessary
            if not name:
                # for btrfs this only needs to ensure the subvol name is not
                # already in use within the parent volume
                name = self.suggest_device_name(mountpoint=mountpoint)
            fmt_args["mountopts"] = "subvol=%s" % name
            fmt_args["subvolspec"] = name
            kwargs.pop("metadata_level", None)
            kwargs.pop("data_level", None)
            kwargs.pop("create_options", None)
        else:
            dev_class = BTRFSVolumeDevice
            # set up the volume label, using hostname if necessary
            if not name:
                name = self.suggest_container_name()
            if "label" not in fmt_args:
                fmt_args["label"] = name
            fmt_args["subvolspec"] = MAIN_VOLUME_ID

        # discard fmt_type since it's btrfs always
        kwargs.pop("fmt_type", None)

        # this is to avoid auto-scheduled format create actions
        device = dev_class(name, **kwargs)
        device.format = get_format("btrfs", **fmt_args)
        return device

    def new_btrfs_sub_volume(self, *args, **kwargs):
        """ Return a new BRFSSubVolumeDevice.

            :keyword fmt_args: arguments for format constructor
            :type fmt_args: dict
            :keyword mountpoint: mountpoint for format (filesystem)
            :type mountpoint: str
            :returns: the new device
            :rtype: :class:`~.devices.BTRFSSubVolumeDevice`

            All other arguments are passed on to the
            :class:`~.devices.BTRFSSubVolumeDevice` constructor.

            .. note::

                Since you are creating a subvolume, the parents kwarg should
                contain the volume you want to contain the subvolume.

        """
        kwargs["subvol"] = True
        return self.new_btrfs(*args, **kwargs)

    def new_tmp_fs(self, *args, **kwargs):
        """ Return a new TmpFSDevice. """
        return TmpFSDevice(*args, **kwargs)

    def create_device(self, device):
        """ Schedule creation of a device.

            :param device: the device to schedule creation of
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        action_create_dev = ActionCreateDevice(device)
        self.devicetree.actions.add(action_create_dev)

        is_snapshot = isinstance(device, LVMLogicalVolumeDevice) and device.is_snapshot_lv

        if device.format.type and not device.format_immutable and not is_snapshot:
            action_create_fmt = None
            try:
                action_create_fmt = ActionCreateFormat(device)
            except (ValueError, DependencyError) as e:
                # revert devicetree changes done so far
                self.devicetree.actions.remove(action_create_dev)
                raise e
            self.devicetree.actions.add(action_create_fmt)

    def destroy_device(self, device):
        """ Schedule destruction of a device.

            :param device: the device to schedule destruction of
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        if device.protected:
            raise ValueError("cannot modify protected device")

        if device.format.exists and device.format.type and \
           not device.format_immutable:
            # schedule destruction of any formatting while we're at it
            self.devicetree.actions.add(ActionDestroyFormat(device))

        action = ActionDestroyDevice(device)
        self.devicetree.actions.add(action)

    def format_device(self, device, fmt):
        """ Schedule formatting of a device.

            :param device: the device to create the formatting on
            :type device: :class:`~.devices.StorageDevice`
            :param fmt: the format to create on the device
            :type format: :class:`~.formats.DeviceFormat`
            :rtype: None

            A format destroy action will be scheduled first, so it is not
            necessary to create and schedule an
            :class:`~.deviceaction.ActionDestroyFormat` prior to calling this
            method.
        """
        if device.protected:
            raise ValueError("cannot modify protected device")

        destroy_ac = ActionDestroyFormat(device)
        create_ac = ActionCreateFormat(device, fmt)

        self.devicetree.actions.add(destroy_ac)
        try:
            self.devicetree.actions.add(create_ac)
        except Exception as e:
            # creating the format failed, revert the destroy action too
            self.devicetree.actions.remove(destroy_ac)
            raise e

    def reset_device(self, device):
        """ Cancel all scheduled actions and reset formatting.

            :param device: the device to reset
            :type device: :class:`~.devices.StorageDevice`
            :rtype: None
        """
        actions = self.devicetree.actions.find(device=device)
        for action in reversed(actions):
            self.devicetree.actions.remove(action)

        # make sure any random overridden attributes are reset
        device.format = copy.deepcopy(device.original_format)

    def resize_device(self, device, new_size):
        """ Schedule a resize of a device and its formatting, if any.

            :param device: the device to resize
            :type device: :class:`~.devices.StorageDevice`
            :param new_size: the new target size for the device
            :type new_size: :class:`~.size.Size`
            :rtype: None

            If the device has formatting that is recognized as being resizable
            an action will be scheduled to resize it as well.
        """
        if device.protected:
            raise ValueError("cannot modify protected device")

        actions = []

        if device.resizable:
            actions.append(ActionResizeDevice(device, new_size))

        if device.format.resizable:
            if device.format.type == "luks" and device.children:
                # resize the luks format
                actions.append(ActionResizeFormat(device, new_size - LUKS_METADATA_SIZE))

                luks_dev = device.children[0]
                if luks_dev.resizable:
                    # resize the luks device
                    actions.append(ActionResizeDevice(luks_dev, new_size - LUKS_METADATA_SIZE))

                if luks_dev.format.resizable:
                    # resize the format on the luks device
                    actions.append(ActionResizeFormat(luks_dev, new_size - LUKS_METADATA_SIZE))
            else:
                actions.append(ActionResizeFormat(device, new_size))

        if not actions:
            raise ValueError("device cannot be resized")

        # if this is a shrink, schedule the format resize first
        if new_size < device.size:
            actions.reverse()

        for action in actions:
            self.devicetree.actions.add(action)

    def safe_device_name(self, name, device_type=None):
        """ Convert a device name to something safe and return that.

            LVM limits lv names to 128 characters. I don't know the limits for
            the other various device types, so I'm going to pick a number so
            that we don't have to have an entire library to determine
            device name limits.
        """

        if device_type in (devicefactory.DEVICE_TYPE_LVM, devicefactory.DEVICE_TYPE_LVM_THINP):
            allowed = devicelibs.lvm.safe_name_characters
        elif device_type == devicefactory.DEVICE_TYPE_MD:
            allowed = devicelibs.mdraid.safe_name_characters
        elif device_type == devicefactory.DEVICE_TYPE_BTRFS:
            allowed = devicelibs.btrfs.safe_name_characters
        else:
            allowed = "0-9a-zA-Z._-"

        max_len = 96    # No, you don't need longer names than this. Really.
        tmp = name.strip()

        if "/" not in allowed:
            tmp = tmp.replace("/", "_")

        tmp = re.sub("[^%s]" % allowed, "", tmp)

        # Remove any '-' or '_' prefixes
        tmp = re.sub("^[-_]*", "", tmp)

        # If all that's left is . or .., give up
        if tmp == "." or tmp == "..":
            return ""

        if len(tmp) > max_len:
            tmp = tmp[:max_len]

        return tmp

    def _get_container_name_template(self, prefix=None):
        return prefix or ""

    def suggest_container_name(self, prefix=""):
        """ Return a reasonable, unused device name.

            :keyword prefix: a prefix for the container name
            :returns: the suggested name
            :rtype: str
        """
        if not prefix:
            prefix = self.short_product_name

        template = self._get_container_name_template(prefix=prefix)
        names = self.names
        name = template
        if name in names:
            name = None
            for i in range(100):
                tmpname = "%s%02d" % (template, i,)
                if tmpname not in names:
                    name = tmpname
                    break

            if not name:
                log.error("failed to create device name based on template '%s'", template)
                raise RuntimeError("unable to find suitable device name")

        return name

    def suggest_device_name(self, parent=None, swap=None,
                            mountpoint=None, prefix=""):
        """ Return a suitable, unused name for a new device.

            :keyword parent: the parent device
            :type parent: :class:`~.devices.StorageDevice`
            :keyword swap: will this be a swap device
            :type swap: bool
            :keyword mountpoint: the device's mountpoint
            :type mountpoint: str
            :keyword prefix: device name prefix
            :type prefix: str
            :returns: the suggested name
            :rtype: str
        """
        body = ""
        if mountpoint:
            if mountpoint == "/":
                body = "root"
            else:
                body = mountpoint[1:].replace("/", "_")
        elif swap:
            body = "swap"

        if prefix and body:
            body = "_" + body

        template = self.safe_device_name(prefix + body)
        names = self.names
        name = template

        def full_name(name, parent):
            full = ""
            if parent:
                full = "%s-" % parent.name
            full += name
            return full

        # also include names of any lvs in the parent for the case of the
        # temporary vg in the lvm dialogs, which can contain lvs that are
        # not yet in the devicetree and therefore not in self.names
        if full_name(name, parent) in names or not body:
            for i in range(100):
                name = "%s%02d" % (template, i)
                if full_name(name, parent) not in names:
                    break
                else:
                    name = ""

            if not name:
                log.error("failed to create device name based on parent '%s', "
                          "prefix '%s', mountpoint '%s', swap '%s'",
                          parent.name, prefix, mountpoint, swap)
                raise RuntimeError("unable to find suitable device name")

        return name

    def setup_disk_images(self):
        self.devicetree.set_disk_images(self.disk_images)
        self.devicetree.setup_disk_images()

    def dump_state(self, suffix):
        """ Dump the current device list to the storage shelf. """
        key = "devices.%d.%s" % (time.time(), suffix)
        with contextlib.closing(shelve.open(self._dump_file)) as shelf:
            try:
                shelf[key] = [d.dict for d in self.devices]  # pylint: disable=unsupported-assignment-operation
            except AttributeError:
                log_exception_info()

    @property
    def packages(self):
        pkgs = set()

        # install support packages for all devices in the system
        for device in self.devices:
            # this takes care of device and filesystem packages
            pkgs.update(device.packages)

        return list(pkgs)

    def _check_valid_fstype(self, newtype):
        """ Check the fstype to see if it is valid

            Raise ValueError on invalid input.
        """
        fmt = get_format(newtype)
        if fmt.type is None:
            raise ValueError("unrecognized value %s for new default fs type" % newtype)

        if (not fmt.mountable or not fmt.formattable or not fmt.supported or
                not fmt.linux_native):
            log.debug("invalid default fstype (%s): %r", newtype, fmt)
            raise ValueError("new value %s is not valid as a default fs type" % newtype)

        self._default_fstype = newtype  # pylint: disable=attribute-defined-outside-init

    @property
    def default_fstype(self):
        return self._default_fstype

    def set_default_fstype(self, newtype):
        """ Set the default fstype for this instance.

            Raise ValueError on invalid input.
        """
        log.debug("trying to set new default fstype to '%s'", newtype)
        # This will raise ValueError if it isn't valid
        self._check_valid_fstype(newtype)
        self._default_fstype = newtype  # pylint: disable=attribute-defined-outside-init

    @property
    def mountpoints(self):
        return self.devicetree.mountpoints

    def compare_disks(self, first, second):
        if not isinstance(first, str):
            first = first.name
        if not isinstance(second, str):
            second = second.name

        if first in self.edd_dict and second in self.edd_dict:
            one = self.edd_dict[first]
            two = self.edd_dict[second]
            if (one < two):
                return -1
            elif (one > two):
                return 1

        # if one is in the BIOS and the other not prefer the one in the BIOS
        if first in self.edd_dict:
            return -1
        if second in self.edd_dict:
            return 1

        if first.startswith("hd"):
            type1 = 0
        elif first.startswith("sd"):
            type1 = 1
        elif (first.startswith("vd") or first.startswith("xvd")):
            type1 = -1
        else:
            type1 = 2

        if second.startswith("hd"):
            type2 = 0
        elif second.startswith("sd"):
            type2 = 1
        elif (second.startswith("vd") or second.startswith("xvd")):
            type2 = -1
        else:
            type2 = 2

        if (type1 < type2):
            return -1
        elif (type1 > type2):
            return 1
        else:
            len1 = len(first)
            len2 = len(second)

            if (len1 < len2):
                return -1
            elif (len1 > len2):
                return 1
            else:
                if (first < second):
                    return -1
                elif (first > second):
                    return 1

        return 0

    @property
    def compare_disks_key(self):
        return functools.cmp_to_key(self.compare_disks)

    def get_fstype(self, mountpoint=None):
        """ Return the default filesystem type based on mountpoint. """
        fstype = self.default_fstype
        if not mountpoint:
            # just return the default
            pass
        elif mountpoint.lower() in ("swap", "biosboot", "prepboot"):
            fstype = mountpoint.lower()
        elif mountpoint == "/boot/efi":
            if arch.is_mactel():
                fstype = "macefi"
            else:
                fstype = "efi"

        return fstype

    def factory_device(self, device_type=devicefactory.DEVICE_TYPE_LVM, **kwargs):
        """ Schedule creation of a device based on a top-down specification.

            :param device_type: device type constant
            :type device_type: int (:const:`~.devicefactory.DEVICE_TYPE_*`)
            :returns: the newly configured device
            :rtype: :class:`~.devices.StorageDevice`

            See :class:`~.devicefactory.DeviceFactory` for possible kwargs.

        """
        log_method_call(self, device_type, **kwargs)

        # we can't do anything with existing devices
        # if device and device.exists:
        #    log.info("factory_device refusing to change device %s", device)
        #    return

        if not kwargs.get("fstype"):
            kwargs["fstype"] = self.get_fstype(mountpoint=kwargs.get("mountpoint"))
            if kwargs["fstype"] == "swap":
                kwargs["mountpoint"] = None

        if kwargs["fstype"] == "swap" and \
           device_type == devicefactory.DEVICE_TYPE_BTRFS:
            device_type = devicefactory.DEVICE_TYPE_PARTITION

        factory = devicefactory.get_device_factory(self, device_type=device_type, **kwargs)

        if not factory.disks:
            raise StorageError("no disks specified for new device")

        self.size_sets = []  # clear this since there are no growable reqs now
        factory.configure()
        return factory.device

    def copy(self):
        log.debug("starting Blivet copy")
        new = copy.deepcopy(self)
        # go through and re-get parted_partitions from the disks since they
        # don't get deep-copied
        hidden_partitions = [d for d in new.devicetree._hidden
                             if isinstance(d, PartitionDevice)]
        for partition in new.partitions + hidden_partitions:
            if not partition._parted_partition:
                continue

            # update the refs in req_disks as well
            req_disks = (new.devicetree.get_device_by_id(disk.id) for disk in partition.req_disks)
            partition.req_disks = [disk for disk in req_disks if disk is not None]

            p = partition.disk.format.parted_disk.getPartitionByPath(partition.path)
            partition.parted_partition = p

        for root in new.roots:
            root.swaps = [new.devicetree.get_device_by_id(d.id, hidden=True) for d in root.swaps]
            root.swaps = [s for s in root.swaps if s]

            removed = set()
            for (mountpoint, old_dev) in root.mounts.items():
                if old_dev is None:
                    continue

                new_dev = new.devicetree.get_device_by_id(old_dev.id, hidden=True)
                if new_dev is None:
                    # if the device has been removed don't include this
                    # mountpoint at all
                    removed.add(mountpoint)
                else:
                    root.mounts[mountpoint] = new_dev

            for mnt in removed:
                del root.mounts[mnt]

        log.debug("finished Blivet copy")
        return new
