# devicetree.py
# Device management for anaconda's storage configuration module.
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

import os
import pprint
import re
import six

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from .actionlist import ActionList
from .callbacks import callbacks
from .errors import DeviceError, DeviceTreeError, StorageError, DuplicateUUIDError
from .deviceaction import ActionDestroyDevice, ActionDestroyFormat
from .devices import BTRFSDevice, NoDevice, PartitionDevice
from .devices import LVMLogicalVolumeDevice, LVMVolumeGroupDevice
from .devices.lib import Tags
from . import formats
from .devicelibs import lvm
from .events.handler import EventHandlerMixin
from . import util
from .populator import PopulatorMixin
from .storage_log import log_method_call, log_method_return
from .threads import SynchronizedMeta
from .static_data import lvs_info

import logging
log = logging.getLogger("blivet")

_LVM_DEVICE_CLASSES = (LVMLogicalVolumeDevice, LVMVolumeGroupDevice)


@six.add_metaclass(SynchronizedMeta)
class DeviceTreeBase(object):
    """ A quasi-tree that represents the devices in the system.

        The tree contains a list of :class:`~.devices.StorageDevice` instances,
        which does not necessarily reflect the actual state of the system's
        devices. :class:`~.deviceaction.DeviceAction` is used to perform
        modifications to the tree, except when initially populating the tree.

        :class:`~.deviceaction.DeviceAction` instances are registered, possibly
        causing the addition or removal of :class:`~.devices.StorageDevice`
        instances to/from the tree. A :class:`~.deviceaction.DeviceAction`
        is reversible up to the time its 'execute' method is called.

        Only one action of any given type/object pair should exist for
        any given device at any given time.

        :class:`~.deviceaction.DeviceAction` instances can only be registered
        for leaf devices, except for resize actions.
    """
    def __init__(self, ignored_disks=None, exclusive_disks=None):
        """
            :keyword ignored_disks: ignored disks
            :type ignored_disks: list
            :keyword exclusive_disks: exclusive didks
            :type exclusive_disks: list
        """
        self.reset(ignored_disks, exclusive_disks)

    def reset(self, ignored_disks=None, exclusive_disks=None):
        """ Reset the instance to its initial state.

            :keyword ignored_disks: ignored disks
            :type ignored_disks: list
            :keyword exclusive_disks: exclusive didks
            :type exclusive_disks: list
        """
        # internal data members
        self._devices = []
        self._actions = ActionList(addfunc=self._register_action,
                                   removefunc=self._cancel_action)

        self._hidden = []

        lvm.lvm_cc_resetFilter()

        self.exclusive_disks = exclusive_disks or []
        self.ignored_disks = ignored_disks or []

        self.edd_dict = {}

    def __str__(self):
        done = []

        def show_subtree(root, depth):
            abbreviate_subtree = root in done
            s = "%s%s\n" % ("  " * depth, root)
            done.append(root)
            if abbreviate_subtree:
                s += "%s...\n" % ("  " * (depth + 1),)
            else:
                for child in root.children:
                    s += show_subtree(child, depth + 1)
            return s

        roots = [d for d in self._devices if not d.parents]
        tree = ""
        for root in roots:
            tree += show_subtree(root, 0)
        return tree

    #
    # Device list
    #
    @property
    def devices(self):
        """ List of devices currently in the tree """
        devices = []
        for device in self._devices:
            if not getattr(device, "complete", True):
                continue

            if device.uuid and device.uuid in [d.uuid for d in devices] and \
               not isinstance(device, NoDevice):
                raise DeviceTreeError("duplicate uuids in device tree")

            devices.append(device)

        return devices

    @property
    def names(self):
        """ List of devices names """
        lv_info = list(lvs_info.cache.keys())

        names = []
        for dev in self._devices + self._hidden:
            # don't include "req%d" partition names
            if (dev.type != "partition" or not dev.name.startswith("req")) and \
               dev.type != "btrfs volume" and \
               dev.name not in names:
                names.append(dev.name)

        # include LVs that are not in the devicetree and not scheduled for removal
        removed_names = [ac.device.name for ac in self.actions.find(action_type="destroy",
                                                                    object_type="device")]
        names.extend(n for n in lv_info if n not in names and n not in removed_names)

        return names

    def _add_device(self, newdev, new=True):
        """ Add a device to the tree.

            :param newdev: the device to add
            :type newdev: a subclass of :class:`~.devices.StorageDevice`

            Raise DeviceTreeError if the device's identifier is already
            in the list.
        """
        if newdev.uuid and newdev.uuid in [d.uuid for d in self._devices] and \
           not isinstance(newdev, NoDevice):
            # Just found a device with already existing UUID. Is it the same device?
            dev = self.get_device_by_uuid(newdev.uuid, incomplete=True, hidden=True)
            if dev.name == newdev.name:
                raise DeviceTreeError("Trying to add already existing device.")
            else:
                raise DuplicateUUIDError("Duplicate UUID '%s' found for devices: "
                                         "'%s' and '%s'." % (newdev.uuid, newdev.name, dev.name))

        # make sure this device's parent devices are in the tree already
        for parent in newdev.parents:
            if parent not in self._devices:
                raise DeviceTreeError("parent device not in tree")

        newdev.add_hook(new=new)
        self._devices.append(newdev)

        callbacks.device_added(device=newdev)
        log.info("added %s %s (id %d) to device tree", newdev.type,
                 newdev.name,
                 newdev.id)

    def _remove_device(self, dev, force=None, modparent=True):
        """ Remove a device from the tree.

            :param dev: the device to remove
            :type dev: a subclass of :class:`~.devices.StorageDevice`
            :keyword force: whether to force removal of a non-leaf device
            :type force: bool
            :keyword modparent: update parent device to account for removal
            :type modparent: bool

            .. note::

                Only leaves may be removed.
        """
        if dev not in self._devices:
            raise ValueError("Device '%s' not in tree" % dev.name)

        if not dev.isleaf and not force:
            log.debug("%s has children %s", dev.name, pprint.pformat(c.name for c in dev.children))
            raise ValueError("Cannot remove non-leaf device '%s'" % dev.name)

        dev.remove_hook(modparent=modparent)
        if modparent:
            # if this is a partition we need to remove it from the parted.Disk
            if isinstance(dev, PartitionDevice) and dev.disk is not None:
                # adjust all other PartitionDevice instances belonging to the
                # same disk so the device name matches the potentially altered
                # name of the parted.Partition
                for device in self._devices:
                    if isinstance(device, PartitionDevice) and \
                       device.disk == dev.disk:
                        device.update_name()

        self._devices.remove(dev)
        callbacks.device_removed(device=dev)
        log.info("removed %s %s (id %d) from device tree", dev.type,
                 dev.name,
                 dev.id)

    def recursive_remove(self, device, actions=True, remove_device=True, modparent=True):
        """ Remove a device after removing its dependent devices.

            :param :class:`~.devices.StorageDevice` device: the device to remove
            :keyword bool actions: whether to schedule actions for the removal
            :keyword bool modparent: whether to update parent device upon removal
            :keyword bool remove_device: whether to remove the root device

            If the device is not a leaf, all of its dependents are removed
            recursively until it is a leaf device. At that point the device is
            removed, unless it is a disk. If the device is a disk, its
            formatting is removed but no attempt is made to actually remove the
            disk device.
        """
        log.debug("removing %s", device.name)
        devices = self.get_dependent_devices(device)

        # this isn't strictly necessary, but it makes the action list easier to
        # read when removing logical partitions because of the automatic
        # renumbering that happens if you remove them in ascending numerical
        # order
        devices.reverse()

        while devices:
            log.debug("devices to remove: %s", [d.name for d in devices])
            leaves = [d for d in devices if d.isleaf]
            log.debug("leaves to remove: %s", [d.name for d in leaves])
            for leaf in leaves:
                if actions:
                    if leaf.format.exists and not leaf.protected and \
                       not leaf.format_immutable:
                        self.actions.add(ActionDestroyFormat(leaf))

                    self.actions.add(ActionDestroyDevice(leaf))
                else:
                    if not leaf.format_immutable:
                        leaf.format = None
                    self._remove_device(leaf, modparent=modparent)

                devices.remove(leaf)

        if not device.format_immutable:
            if actions:
                self.actions.add(ActionDestroyFormat(device))
            else:
                device.format = None

        if remove_device and not device.is_disk:
            if actions:
                self.actions.add(ActionDestroyDevice(device))
            else:
                self._remove_device(device, modparent=modparent)

    #
    # Actions
    #
    @property
    def actions(self):
        return self._actions

    def _register_action(self, action):
        """ Register an action to be performed at a later time.

            :param action: the action
            :type action: :class:`~.deviceaction.DeviceAction`

            Modifications to the Device instance are handled before we
            get here.
        """
        if not (action.is_create and action.is_device) and \
           action.device not in self._devices:
            raise DeviceTreeError("device is not in the tree")
        elif (action.is_create and action.is_device):
            if action.device in self._devices:
                raise DeviceTreeError("device is already in the tree")

        if action.is_create and action.is_device:
            # if adding an LV constructed from other LVs, we need to remove the
            # LVs it's supposed to be constructed from the device tree
            if isinstance(action.device, LVMLogicalVolumeDevice) and action.device.from_lvs:
                for lv in action.device.from_lvs:
                    if lv in self._devices:
                        self._remove_device(lv)
            self._add_device(action.device)
        elif action.is_destroy and action.is_device:
            self._remove_device(action.device)
            # if removing an LV constructed from other LVs, we need to put the
            # LVs it's supposed to be constructed from back into the device tree
            if isinstance(action.device, LVMLogicalVolumeDevice) and action.device.from_lvs:
                for lv in action.device.from_lvs:
                    self._add_device(lv, new=False)
        elif action.is_create and action.is_format:
            if isinstance(action.device.format, formats.fs.FS) and \
               action.device.format.mountpoint in self.filesystems:
                raise DeviceTreeError("mountpoint already in use")

    def _cancel_action(self, action):
        """ Cancel a registered action.

            :param action: the action
            :type action: :class:`~.deviceaction.DeviceAction`

            This will unregister the action and do any required
            modifications to the device list.

            Actions all operate on a Device, so we can use the devices
            to determine dependencies.
        """
        if action.is_create and action.is_device:
            # remove the device from the tree
            self._remove_device(action.device)
            if isinstance(action.device, LVMLogicalVolumeDevice) and action.device.from_lvs:
                # if removing an LV constructed from other LVs, we need to put the
                # LVs it's supposed to be constructed from back into the device tree
                for lv in action.device.from_lvs:
                    self._add_device(lv, new=False)
        elif action.is_destroy and action.is_device:
            # if adding an LV constructed from other LVs, we need to remove the
            # LVs it's supposed to be constructed from the device tree
            if isinstance(action.device, LVMLogicalVolumeDevice) and action.device.from_lvs:
                for lv in action.device.from_lvs:
                    if lv in self._devices:
                        self._remove_device(lv)
            # add the device back into the tree
            self._add_device(action.device, new=False)

    #
    # Device control
    #
    def teardown_all(self):
        """ Run teardown methods on all devices. """
        for device in self.leaves:
            if device.protected:
                continue

            try:
                device.teardown(recursive=True)
            except (StorageError, blockdev.BlockDevError) as e:
                log.info("teardown of %s failed: %s", device.name, e)

    def setup_all(self):
        """ Run setup methods on all devices. """
        for device in self.leaves:
            try:
                device.setup()
            except DeviceError as e:
                log.error("setup of %s failed: %s", device.name, e)

    #
    # Device search by relation
    #
    def get_dependent_devices(self, dep, hidden=False):
        """ Return a list of devices that depend on dep.

            The list includes both direct and indirect dependents.

            :param dep: the device whose dependents we are looking for
            :type dep: :class:`~.devices.StorageDevice`
            :keyword bool hidden: include hidden devices in search
        """
        dependents = []
        log_method_call(self, dep=dep, hidden=hidden)

        # don't bother looping looking for dependents if this is a leaf device
        # XXX all hidden devices are leaves
        if dep.isleaf and not hidden:
            log.debug("dep is a leaf")
            return dependents

        devices = self._devices[:]
        if hidden:
            devices.extend(self._hidden)

        for device in devices:
            log.debug("checking if %s depends on %s", device.name, dep.name)
            if device.depends_on(dep):
                dependents.append(device)

        return dependents

    def get_related_disks(self, disk):
        """ Return disks related to disk by container membership.

            :param :class:`~.devices.StorageDevice` disk: the disk
            :returns: related disks
            :rtype: set of :class:`~.devices.StorageDevice`

            .. note::

                The disk may be hidden.

        """
        return set(d for dep in self.get_dependent_devices(disk, hidden=True)
                   for d in dep.disks)

    def get_disk_actions(self, disks):
        """ Return a list of actions related to the specified disk.

            :param disks: list of disks
            :type disk: list of :class:`~.devices.StorageDevices`
            :returns: list of related actions
            :rtype: list of :class:`~.deviceaction.DeviceAction`

            This includes all actions on the specified disks, plus all actions
            on disks that are in any way connected to the specified disk via
            container devices.
        """
        # This is different from get_related_disks in that we are finding disks
        # related by any action -- not just the current state of the devicetree.
        related_disks = set()
        for action in self.actions:
            if any(action.device.depends_on(d) for d in disks):
                related_disks.update(action.device.disks)

        # now related_disks could be a superset of disks, so go through and
        # build a list of actions related to any disk in related_disks
        # Note that this list preserves the ordering of the action list.
        related_actions = [a for a in self.actions
                           if set(a.device.disks).intersection(related_disks)]
        return related_actions

    def cancel_disk_actions(self, disks):
        """ Cancel all actions related to the specified disk.

            :param disks: list of disks
            :type disk: list of :class:`~.devices.StorageDevices`

            This includes actions related directly and indirectly (via container
            membership, for example).
        """
        actions = self.get_disk_actions(disks)
        for action in reversed(actions):
            self.actions.remove(action)

    #
    # Device search by property
    #
    def _filter_devices(self, incomplete=False, hidden=False):
        """ Return list of devices modified according to parameters.

            :param bool incomplete: include incomplete devices in result
            :param bool hidden: include hidden devices in result

            :returns: a generator of devices
            :rtype: generator of :class:`~.devices.Device`
        """
        if hidden:
            devices = (d for d in self._devices[:] + self._hidden[:])
        else:
            devices = (d for d in self._devices[:])

        if not incomplete:
            devices = (d for d in devices if getattr(d, "complete", True))
        return devices

    def get_device_by_sysfs_path(self, path, incomplete=False, hidden=False):
        """ Return a list of devices with a matching sysfs path.

            :param str path: the sysfs path to match
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: the first matching device found
            :rtype: :class:`~.devices.Device`
        """
        log_method_call(self, path=path, incomplete=incomplete, hidden=hidden)
        result = None
        if path:
            devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
            result = six.next((d for d in devices if d.sysfs_path == path), None)
        log_method_return(self, result)
        return result

    def get_device_by_uuid(self, uuid, incomplete=False, hidden=False):
        """ Return a list of devices with a matching UUID.

            :param str uuid: the UUID to match
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: the first matching device found
            :rtype: :class:`~.devices.Device`
        """
        log_method_call(self, uuid=uuid, incomplete=incomplete, hidden=hidden)
        result = None
        if uuid:
            devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
            result = six.next((d for d in devices if d.uuid == uuid or d.format.uuid == uuid), None)
        log_method_return(self, result)
        return result

    def get_device_by_label(self, label, incomplete=False, hidden=False):
        """ Return a device with a matching filesystem label.

            :param str label: the filesystem label to match
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: the first matching device found
            :rtype: :class:`~.devices.Device`
        """
        log_method_call(self, label=label, incomplete=incomplete, hidden=hidden)
        result = None
        if label:
            devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
            result = six.next((d for d in devices if getattr(d.format, "label", None) == label), None)
        log_method_return(self, result)
        return result

    def get_device_by_name(self, name, incomplete=False, hidden=False):
        """ Return a device with a matching name.

            :param str name: the name to look for
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: the first matching device found
            :rtype: :class:`~.devices.Device`
        """
        log_method_call(self, name=name, incomplete=incomplete, hidden=hidden)
        result = None
        if name:
            devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
            result = six.next((d for d in devices if d.name == name or
                               (isinstance(d, _LVM_DEVICE_CLASSES) and d.name == name.replace("--", "-"))),
                              None)
        log_method_return(self, result)
        return result

    def get_device_by_path(self, path, incomplete=False, hidden=False):
        """ Return a device with a matching path.

            If there is more than one device with a matching path,
            prefer a leaf device to a non-leaf device.

            :param str path: the path to match
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: the first matching device found
            :rtype: :class:`~.devices.Device`
        """
        log_method_call(self, path=path, incomplete=incomplete, hidden=hidden)
        result = None
        if path:
            devices = self._filter_devices(incomplete=incomplete, hidden=hidden)

            # The usual order of the devices list is one where leaves are at
            # the end. So that the search can prefer leaves to interior nodes
            # the list that is searched is the reverse of the devices list.
            result = six.next((d for d in reversed(list(devices)) if d.path == path or
                               (isinstance(d, _LVM_DEVICE_CLASSES) and d.path == path.replace("--", "-"))),
                              None)

        log_method_return(self, result)
        return result

    def get_device_by_id(self, id_num, incomplete=False, hidden=False):
        """ Return a device with specified device id.

            :param int id_num: the id to look for
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: the first matching device found
            :rtype: :class:`~.devices.Device`
        """
        log_method_call(self, id_num=id_num, incomplete=incomplete, hidden=hidden)
        devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
        result = six.next((d for d in devices if d.id == id_num), None)
        log_method_return(self, result)
        return result

    def resolve_device(self, devspec, blkid_tab=None, crypt_tab=None, options=None):
        """ Return the device matching the provided device specification.

            The spec can be anything from a device name (eg: 'sda3') to a device
            node path (eg: '/dev/mapper/fedora-root' or '/dev/dm-2') to
            something like 'UUID=xyz-tuv-qrs' or 'LABEL=rootfs'.

            :param devspec: a string describing a block device
            :type devspec: str
            :keyword blkid_tab: blkid info
            :type blkid_tab: :class:`~.BlkidTab`
            :keyword crypt_tab: crypto info
            :type crypt_tab: :class:`~.CryptTab`
            :keyword options: mount options
            :type options: str
            :returns: the device
            :rtype: :class:`~.devices.StorageDevice` or None
        """
        # find device in the tree
        device = None
        if devspec.startswith("UUID="):
            # device-by-uuid
            uuid = devspec.partition("=")[2]
            if ((uuid.startswith('"') and uuid.endswith('"')) or
                    (uuid.startswith("'") and uuid.endswith("'"))):
                uuid = uuid[1:-1]
            device = self.uuids.get(uuid)
        elif devspec.startswith("LABEL="):
            # device-by-label
            label = devspec.partition("=")[2]
            if ((label.startswith('"') and label.endswith('"')) or
                    (label.startswith("'") and label.endswith("'"))):
                label = label[1:-1]
            device = self.labels.get(label)
        elif re.match(r'(0x)?[A-Fa-f0-9]{2}(p\d+)?$', devspec):
            # BIOS drive number
            (drive, _p, partnum) = devspec.partition("p")
            spec = int(drive, 16)
            for (edd_name, edd_number) in self.edd_dict.items():
                if edd_number == spec:
                    device = self.get_device_by_name(edd_name + partnum)
                    break
        elif options and "nodev" in options.split(","):
            device = self.get_device_by_name(devspec)
            if not device:
                device = self.get_device_by_path(devspec)
        else:
            if not devspec.startswith("/dev/"):
                device = self.get_device_by_name(devspec)
                if not device:
                    devspec = "/dev/" + devspec

            if not device:
                if devspec.startswith("/dev/disk/"):
                    devspec = os.path.realpath(devspec)

                if devspec.startswith("/dev/dm-"):
                    try:
                        dm_name = blockdev.dm.name_from_node(devspec[5:])
                    except blockdev.DMError as e:
                        log.info("failed to resolve %s: %s", devspec, e)
                        dm_name = None

                    if dm_name:
                        devspec = "/dev/mapper/" + dm_name

                if re.match(r'/dev/md\d+(p\d+)?$', devspec):
                    try:
                        md_name = blockdev.md.name_from_node(devspec[5:])
                    except blockdev.MDRaidError as e:
                        log.info("failed to resolve %s: %s", devspec, e)
                        md_name = None

                    if md_name:
                        devspec = "/dev/md/" + md_name

                # device path
                device = self.get_device_by_path(devspec)

            if device is None:
                if blkid_tab:
                    # try to use the blkid.tab to correlate the device
                    # path with a UUID
                    blkid_tab_ent = blkid_tab.get(devspec)
                    if blkid_tab_ent:
                        log.debug("found blkid.tab entry for '%s'", devspec)
                        uuid = blkid_tab_ent.get("UUID")
                        if uuid:
                            device = self.get_device_by_uuid(uuid)
                            if device:
                                devstr = device.name
                            else:
                                devstr = "None"
                            log.debug("found device '%s' in tree", devstr)
                        if device and device.format and \
                           device.format.type == "luks":
                            map_name = device.format.map_name
                            log.debug("luks device; map name is '%s'", map_name)
                            mapped_dev = self.get_device_by_name(map_name)
                            if mapped_dev:
                                device = mapped_dev

                if device is None and crypt_tab and \
                   devspec.startswith("/dev/mapper/"):
                    # try to use a dm-crypt mapping name to
                    # obtain the underlying device, possibly
                    # using blkid.tab
                    crypt_tab_ent = crypt_tab.get(devspec.split("/")[-1])
                    if crypt_tab_ent:
                        luks_dev = crypt_tab_ent['device']
                        try:
                            device = luks_dev.children[0]
                        except IndexError as e:
                            pass
                elif device is None:
                    # dear lvm: can we please have a few more device nodes
                    #           for each logical volume?
                    #           three just doesn't seem like enough.
                    name = devspec[5:]      # strip off leading "/dev/"

                    (vg_name, _slash, lv_name) = name.partition("/")
                    if lv_name and "/" not in lv_name:
                        # looks like we may have one
                        lv = "%s-%s" % (vg_name, lv_name)
                        device = self.get_device_by_name(lv)

        # check mount options for btrfs volumes in case it's a subvol
        if device and device.type.startswith("btrfs") and options:
            # start with the volume -- not a subvolume
            device = getattr(device, "volume", device)

            attr = None
            if "subvol=" in options:
                attr = "name"
                val = util.get_option_value("subvol", options)
            elif "subvolid=" in options:
                attr = "vol_id"
                val = util.get_option_value("subvolid", options)
            elif device.default_subvolume:
                # default subvolume
                device = device.default_subvolume

            if attr and val:
                for subvol in device.subvolumes:
                    if getattr(subvol, attr, None) == val:
                        device = subvol
                        break

        if device:
            log.debug("resolved '%s' to '%s' (%s)", devspec, device.name, device.type)
        else:
            log.debug("failed to resolve '%s'", devspec)
        return device

    #
    # Conveniences
    #
    @property
    def leaves(self):
        """ List of all devices upon which no other devices exist. """
        leaves = [d for d in self._devices if d.isleaf]
        return leaves

    @property
    def filesystems(self):
        """ List of filesystems. """
        filesystems = []
        for dev in self.leaves:
            if dev.format and getattr(dev.format, 'mountpoint', None):
                filesystems.append(dev.format)

        return filesystems

    @property
    def uuids(self):
        """ Dict with uuid keys and :class:`~.devices.Device` values. """
        uuids = {}
        for dev in self._devices:
            try:
                uuid = dev.uuid
            except AttributeError:
                uuid = None

            if uuid:
                uuids[uuid] = dev

            try:
                uuid = dev.format.uuid
            except AttributeError:
                uuid = None

            if uuid:
                uuids[uuid] = dev

        return uuids

    @property
    def labels(self):
        """ Dict with label keys and Device values.

            FIXME: duplicate labels are a possibility
        """
        labels = {}
        for dev in self._devices:
            # don't include btrfs member devices
            if getattr(dev.format, "label", None) and \
               (dev.format.type != "btrfs" or isinstance(dev, BTRFSDevice)):
                labels[dev.format.label] = dev

        return labels

    @property
    def mountpoints(self):
        """ Dict with mountpoint keys and Device values. """
        filesystems = {}
        for device in self.devices:
            if device.format.mountable and device.format.mountpoint:
                filesystems[device.format.mountpoint] = device
        return filesystems

    #
    # Disk filter
    #
    def hide(self, device):
        """ Hide the specified device.

            :param device: the device to hide
            :type device: :class:`~.devices.StorageDevice`

            Hiding a device will cancel all actions that involve the device and
            will remove the device from the device list.

            If the device is not a leaf device, all devices that depend on it
            will be hidden leaves-first until the device is a leaf device.

            If a device exists, performs some special actions and places
            it on a list of hidden devices.

            Mixes recursion and side effects, most significantly in the code
            that removes all the actions. However, this code is a null op
            in every case except the first base case that is reached,
            where all actions are removed. This means that when a device
            is removed explicitly in this function by means of a direct call to
            _remove_devices it is guaranteed that all actions have already
            been canceled.

            If a device does not exist then it must have been removed by the
            cancelation of all the actions, so it does not need to be removed
            explicitly.

            Most devices are considered leaf devices if they have no children,
            however, some devices must satisfy more stringent requirements.
            _remove_device() will raise an exception if the device it is
            removing is not a leaf device. hide() guarantees that any
            device that it removes will have no children, but it does not
            guarantee that the more stringent requirements will be enforced.
            Therefore, _remove_device() is invoked with the force parameter
            set to True, to skip the isleaf check.
        """
        if device in self._hidden:
            return

        # cancel actions first thing so that we hide the correct set of devices
        if device.is_disk:
            # Cancel all actions on this disk and any disk related by way of an
            # aggregate/container device (eg: lvm volume group).
            self.cancel_disk_actions([device])

        for d in device.children:
            self.hide(d)

        log.info("hiding device %s", device)

        if not device.exists:
            return

        self._remove_device(device, force=True, modparent=False)

        self._hidden.append(device)
        lvm.lvm_cc_addFilterRejectRegexp(device.name)

    def unhide(self, device):
        """ Restore a device's visibility.

            :param device: the device to restore/unhide
            :type device: :class:`~.devices.StorageDevice`

            .. note::

                Actions canceled while hiding the device are not rescheduled
                automatically.

        """

        # the hidden list should be in leaves-first order
        for hidden in reversed(self._hidden):
            if hidden == device or hidden.depends_on(device) and \
               not any(parent in self._hidden for parent in hidden.parents):

                log.info("unhiding device %s %s (id %d)", hidden.type,
                         hidden.name,
                         hidden.id)
                self._hidden.remove(hidden)
                self._devices.append(hidden)
                hidden.add_hook(new=False)
                lvm.lvm_cc_removeFilterRejectRegexp(hidden.name)

    def expand_taglist(self, taglist):
        """ Expands tags in input list into devices.

            :param taglist: list of strings
            :returns: set of devices
            :rtype: set of strings

            Raise ValueError if unknown tag encountered in taglist

            .. note::

                Returns empty set if taglist is empty
        """
        result = set()
        devices = self._devices[:]
        for item in taglist:
            if item.startswith('@'):
                tag = item[1:]
                if tag not in Tags.__members__:
                    raise ValueError("unknown tag '@%s' encountered" % tag)
                for device in devices:
                    if tag in device.tags:
                        result.add(device.name)
            else:
                result.add(item)
        return result

    def _disk_in_taglist(self, disk, taglist):
        # Taglist is a list containing mix of disk names and tags into which disk may belong.
        # Check if it does. Raise ValueError if unknown tag is encountered.
        if disk.name in taglist:
            return True
        tags = [t[1:] for t in taglist if t.startswith("@")]
        for tag in tags:
            if tag not in Tags.__members__:
                raise ValueError("unknown ignoredisk tag '@%s' encountered" % tag)
            if Tags(tag) in disk.tags:
                return True
        return False

    def _is_ignored_disk(self, disk):
        """ Checks config for lists of exclusive and ignored disks
            and returns if the given one should be ignored
        """
        return ((self.ignored_disks and self._disk_in_taglist(disk, self.ignored_disks)) or
                (self.exclusive_disks and not self._disk_in_taglist(disk, self.exclusive_disks)))

    def _hide_ignored_disks(self):
        # hide any subtrees that begin with an ignored disk
        for disk in [d for d in self._devices if d.is_disk]:
            is_ignored = self.ignored_disks and self._disk_in_taglist(disk, self.ignored_disks)
            is_exclusive = self.exclusive_disks and self._disk_in_taglist(disk, self.exclusive_disks)

            if is_ignored:
                if len(disk.children) == 1:
                    if not all(self._is_ignored_disk(d) for d in disk.children[0].parents):
                        raise DeviceTreeError("Including only a subset of raid/multipath member disks is not allowed.")

                    # and also children like fwraid or mpath
                    self.hide(disk.children[0])

                # this disk is ignored: ignore it and all it's potential parents
                for p in disk.parents:
                    self.hide(p)

                # and finally hide the disk itself
                self.hide(disk)

            if self.exclusive_disks and not is_exclusive:
                ignored = True
                # If the filter allows all members of a fwraid or mpath, the
                # fwraid or mpath itself is implicitly allowed as well. I don't
                # like this very much but we have supported this usage in the
                # past, so I guess we will support it forever.
                if disk.parents and all(p.format.hidden for p in disk.parents):
                    ignored = any(self._is_ignored_disk(d) for d in disk.parents)
                elif disk.format.hidden and len(disk.children) == 1:
                    # Similarly, if the filter allows an mpath or fwraid, we cannot
                    # ignore the member devices.
                    ignored = self._is_ignored_disk(disk.children[0])

                if ignored:
                    self.hide(disk)


class DeviceTree(DeviceTreeBase, PopulatorMixin, EventHandlerMixin):
    def __init__(self, ignored_disks=None, exclusive_disks=None, disk_images=None):
        DeviceTreeBase.__init__(self, ignored_disks=ignored_disks, exclusive_disks=exclusive_disks)
        PopulatorMixin.__init__(self, disk_images=disk_images)
        EventHandlerMixin.__init__(self)

    # pylint: disable=arguments-differ
    def reset(self, ignored_disks=None, exclusive_disks=None, disk_images=None):
        DeviceTreeBase.reset(self, ignored_disks=ignored_disks, exclusive_disks=exclusive_disks)
        PopulatorMixin.reset(self, disk_images=disk_images)
