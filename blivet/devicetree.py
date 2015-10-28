# devicetree.py
# Device management for anaconda's storage configuration module.
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
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#

import os
import re

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

from .actionlist import ActionList
from .errors import DeviceError, DeviceTreeError, StorageError
from .deviceaction import ActionDestroyDevice, ActionDestroyFormat
from .devices import BTRFSDevice, DASDDevice, NoDevice, PartitionDevice
from .devices import LVMLogicalVolumeDevice, LVMVolumeGroupDevice
from . import formats, arch
from .devicelibs import lvm
from . import udev
from . import util
from .util import open  # pylint: disable=redefined-builtin
from .flags import flags
from .populator import Populator
from .storage_log import log_method_call, log_method_return

import logging
log = logging.getLogger("blivet")

_LVM_DEVICE_CLASSES = (LVMLogicalVolumeDevice, LVMVolumeGroupDevice)


class DeviceTree(object):

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

    def __init__(self, conf=None, passphrase=None, luks_dict=None,
                 iscsi=None, dasd=None):
        """

            :keyword conf: storage discovery configuration
            :type conf: :class:`~.StorageDiscoveryConfig`
            :keyword passphrase: default LUKS passphrase
            :keyword luks_dict: a dict with UUID keys and passphrase values
            :type luks_dict: dict
            :keyword iscsi: ISCSI control object
            :type iscsi: :class:`~.iscsi.iscsi`
            :keyword dasd: DASD control object
            :type dasd: :class:`~.dasd.DASD`

        """
        self.reset(conf, passphrase, luks_dict, iscsi, dasd)

    def reset(self, conf=None, passphrase=None, luks_dict=None,
              iscsi=None, dasd=None):
        """ Reset the instance to its initial state. """
        # internal data members
        self._devices = []
        self._actions = ActionList()

        # a list of all device names we encounter
        self.names = []

        self._hidden = []

        # initialize attributes that may later hold cached lvm info
        self.drop_lvm_cache()

        lvm.lvm_cc_resetFilter()

        self.edd_dict = {}

        self._populator = Populator(self,
                                    conf=conf,
                                    passphrase=passphrase,
                                    luks_dict=luks_dict,
                                    iscsi=iscsi,
                                    dasd=dasd)

    @property
    def actions(self):
        return self._actions

    def set_disk_images(self, images):
        """ Set the disk images and reflect them in exclusive_disks.

            :param images: dict with image name keys and filename values
            :type images: dict

            .. note::

                Disk images are automatically exclusive. That means that, in the
                presence of disk images, any local storage not associated with
                the disk images is ignored.
        """
        self._populator.set_disk_images(images)

    @property
    def exclusive_disks(self):
        return self._populator.exclusive_disks

    @property
    def ignored_disks(self):
        return self._populator.ignored_disks

    @property
    def dasd(self):
        return self._populator.dasd

    @dasd.setter
    def dasd(self, dasd):
        self._populator.dasd = dasd

    @property
    def protected_dev_names(self):
        return self._populator.protected_dev_names

    @property
    def disk_images(self):
        return self._populator.disk_images

    @property
    def pv_info(self):
        if self._pvs_cache is None:
            pvs = blockdev.lvm.pvs()
            self._pvs_cache = dict((pv.pv_name, pv) for pv in pvs)  # pylint: disable=attribute-defined-outside-init

        return self._pvs_cache

    @property
    def lv_info(self):
        if self._lvs_cache is None:
            lvs = blockdev.lvm.lvs()
            self._lvs_cache = dict(("%s-%s" % (lv.vg_name, lv.lv_name), lv) for lv in lvs)  # pylint: disable=attribute-defined-outside-init

        return self._lvs_cache

    def drop_lvm_cache(self):
        """ Drop cached lvm information. """
        self._pvs_cache = None  # pylint: disable=attribute-defined-outside-init
        self._lvs_cache = None  # pylint: disable=attribute-defined-outside-init

    def _add_device(self, newdev, new=True):
        """ Add a device to the tree.

            :param newdev: the device to add
            :type newdev: a subclass of :class:`~.devices.StorageDevice`

            Raise ValueError if the device's identifier is already
            in the list.
        """
        if newdev.uuid and newdev.uuid in [d.uuid for d in self._devices] and \
           not isinstance(newdev, NoDevice):
            raise ValueError("device is already in tree")

        # make sure this device's parent devices are in the tree already
        for parent in newdev.parents:
            if parent not in self._devices:
                raise DeviceTreeError("parent device not in tree")

        newdev.add_hook(new=new)
        self._devices.append(newdev)

        # don't include "req%d" partition names
        if ((newdev.type != "partition" or
             not newdev.name.startswith("req")) and
                newdev.type != "btrfs volume" and
                newdev.name not in self.names):
            self.names.append(newdev.name)
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
            log.debug("%s has %d kids", dev.name, dev.kids)
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
        if dev.name in self.names and getattr(dev, "complete", True):
            self.names.remove(dev.name)
        log.info("removed %s %s (id %d) from device tree", dev.type,
                 dev.name,
                 dev.id)

    def recursive_remove(self, device, actions=True):
        """ Remove a device after removing its dependent devices.

            :param :class:`~.devices.StorageDevice` device: the device to remove
            :keyword bool actions: whether to schedule actions for the removal

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
                        self.register_action(ActionDestroyFormat(leaf))

                    self.register_action(ActionDestroyDevice(leaf))
                else:
                    if not leaf.format_immutable:
                        leaf.format = None
                    self._remove_device(leaf)

                devices.remove(leaf)

        if not device.format_immutable:
            if actions:
                self.register_action(ActionDestroyFormat(device))
            else:
                device.format = None

        if not device.is_disk:
            if actions:
                self.register_action(ActionDestroyDevice(device))
            else:
                self._remove_device(device)

    def register_action(self, action):
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
            self._add_device(action.device)
        elif action.is_destroy and action.is_device:
            self._remove_device(action.device)
        elif action.is_create and action.is_format:
            if isinstance(action.device.format, formats.fs.FS) and \
               action.device.format.mountpoint in self.filesystems:
                raise DeviceTreeError("mountpoint already in use")

        # apply the action before adding it in case apply raises an exception
        action.apply()
        log.info("registered action: %s", action)
        self._actions.append(action)

    def cancel_action(self, action):
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
        elif action.is_destroy and action.is_device:
            # add the device back into the tree
            self._add_device(action.device, new=False)

        action.cancel()
        self._actions.remove(action)
        log.info("canceled action %s", action)

    def find_actions(self, device=None, action_type=None, object_type=None,
                     path=None, devid=None):
        """ Find all actions that match all specified parameters.

            A value of None for any of the keyword arguments indicates that any
            value is acceptable for that field.

            :keyword device: device to match
            :type device: :class:`~.devices.StorageDevice` or None
            :keyword action_type: action type to match (eg: "create", "destroy")
            :type action_type: str or None
            :keyword object_type: operand type to match (eg: "device" or "format")
            :type object_type: str or None
            :keyword path: device path to match
            :type path: str or None
            :keyword devid: device id to match
            :type devid: int or None
            :returns: a list of matching actions
            :rtype: list of :class:`~.deviceaction.DeviceAction`

        """
        return self._actions.find(device=device,
                                  action_type=action_type,
                                  object_type=object_type,
                                  path=path,
                                  devid=devid)

    def process_actions(self, callbacks=None, dry_run=False):
        self.actions.process(devices=self.devices,
                             dry_run=dry_run,
                             callbacks=callbacks)

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
            disks = [device]
            related_actions = [a for a in self._actions
                               if a.device.depends_on(device)]
            for related_device in (a.device for a in related_actions):
                disks.extend(related_device.disks)

            disks = set(disks)
            cancel = [a for a in self._actions
                      if set(a.device.disks).intersection(disks)]
            for action in reversed(cancel):
                self.cancel_action(action)

        for d in self.get_children(device):
            self.hide(d)

        log.info("hiding device %s", device)

        if not device.exists:
            return

        self._remove_device(device, force=True, modparent=False)

        self._hidden.append(device)
        lvm.lvm_cc_addFilterRejectRegexp(device.name)

        if isinstance(device, DASDDevice):
            self.dasd.remove(device)

        if device.name not in self.names:
            self.names.append(device.name)

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
                if isinstance(device, DASDDevice):
                    self.dasd.append(device)

    def setup_disk_images(self):
        """ Set up devices to represent the disk image files. """
        self._populator.setup_disk_images()

    def update_device_format(self, device):
        return self._populator.update_device_format(device)

    def prune_actions(self):
        return self._actions.prune()

    def sort_actions(self):
        return self._actions.sort()

    def populate(self, cleanup_only=False):
        """ Locate all storage devices.

            Everything should already be active. We just go through and gather
            details as needed and set up the relations between various devices.

            Devices excluded via disk filtering (or because of disk images) are
            scanned just the rest, but then they are hidden at the end of this
            process.
        """
        udev.settle()
        self.drop_lvm_cache()
        try:
            self._populator.populate(cleanup_only=cleanup_only)
        except Exception:
            raise
        finally:
            self._hide_ignored_disks()

        if flags.installer_mode:
            self.teardown_all()

    def _is_ignored_disk(self, disk):
        return ((self.ignored_disks and disk.name in self.ignored_disks) or
                (self.exclusive_disks and
                 disk.name not in self.exclusive_disks))

    def _hide_ignored_disks(self):
        # hide any subtrees that begin with an ignored disk
        for disk in [d for d in self._devices if d.is_disk]:
            if self._is_ignored_disk(disk):
                ignored = True
                # If the filter allows all members of a fwraid or mpath, the
                # fwraid or mpath itself is implicitly allowed as well. I don't
                # like this very much but we have supported this usage in the
                # past, so I guess we will support it forever.
                if disk.parents and all(p.format.hidden for p in disk.parents):
                    ignored = any(self._is_ignored_disk(d) for d in disk.parents)

                if ignored:
                    self.hide(disk)

    def teardown_all(self):
        """ Run teardown methods on all devices. """
        for device in self.leaves:
            if device.protected:
                continue

            try:
                device.teardown(recursive=True)
            except (StorageError, blockdev.BlockDevError) as e:
                log.info("teardown of %s failed: %s", device.name, e)

    def teardown_disk_images(self):
        """ Tear down any disk image stacks. """
        self._populator.teardown_disk_images()

    def setup_all(self):
        """ Run setup methods on all devices. """
        for device in self.leaves:
            try:
                device.setup()
            except DeviceError as e:
                log.error("setup of %s failed: %s", device.name, e)

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

    def make_dasd_list(self, dasds, disks):
        """ Create a list of DASDs recognized by the system

            :param list dasds: a list of DASD devices
            :param list disks: a list of disks on the system
            :returns: a list of DASD devices identified on the system
            :rtype: list of :class:
        """
        if not arch.is_s390():
            return

        log.info("Generating DASD list....")
        for dev in (disk for disk in disks if disk.type == "dasd"):
            if dev not in dasds:
                dasds.append(dev)

        return dasds

    def make_unformatted_dasd_list(self, dasds):
        """ Create a list of DASDs which are detected to require dasdfmt.

            :param list dasds: a list of DASD devices
            :returns: a list of DASDs which need dasdfmt in order to be used
            :rtype: list of :class:
        """
        if not arch.is_s390():
            return

        unformatted = []

        for dasd in dasds:
            if blockdev.s390.dasd_needs_format(dasd.busid):
                unformatted.append(dasd)

        return unformatted

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
            result = next((d for d in devices if d.sysfs_path == path), None)
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
            result = next((d for d in devices if d.uuid == uuid or d.format.uuid == uuid), None)
        log_method_return(self, result)
        return result

    @util.deprecated('1.7', '')
    def get_devices_by_serial(self, serial, incomplete=False, hidden=False):
        """ Return a list of devices with a matching serial.

            :param str serial: the serial to match
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: all matching devices found
            :rtype: list of :class:`~.devices.Device`
        """
        log_method_call(self, serial=serial, incomplete=incomplete, hidden=hidden)
        devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
        retval = []
        for device in devices:
            if not hasattr(device, "serial"):
                log.warning("device %s has no serial attr", device.name)
                continue
            if device.serial == serial:
                retval.append(device)
        log_method_return(self, [r.name for r in retval])
        return retval

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
            result = next((d for d in devices if getattr(d.format, "label", None) == label), None)
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
            result = next((d for d in devices if d.name == name or
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
            result = next((d for d in reversed(list(devices)) if d.path == path or
                           (isinstance(d, _LVM_DEVICE_CLASSES) and d.path == path.replace("--", "-"))),
                          None)

        log_method_return(self, result)
        return result

    @util.deprecated('1.7', '')
    def get_devices_by_type(self, device_type, incomplete=False, hidden=False):
        """ Return a list of devices with a matching device type.

            :param str device_type: the type to match
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: all matching device found
            :rtype: list of :class:`~.devices.Device`
        """
        log_method_call(self, device_type=device_type, incomplete=incomplete, hidden=hidden)
        devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
        result = [d for d in devices if d.type == device_type]
        log_method_return(self, [r.name for r in result])
        return result

    @util.deprecated('1.7', '')
    def get_devices_by_instance(self, device_class, incomplete=False, hidden=False):
        """ Return a list of devices with a matching device class.

            :param class device_class: the device class to match
            :param bool incomplete: include incomplete devices in search
            :param bool hidden: include hidden devices in search
            :returns: all matching device found
            :rtype: list of :class:`~.devices.Device`
        """
        log_method_call(self, device_class=device_class, incomplete=incomplete, hidden=hidden)
        devices = self._filter_devices(incomplete=incomplete, hidden=hidden)
        result = [d for d in devices if isinstance(d, device_class)]
        log_method_return(self, [r.name for r in result])
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
        result = next((d for d in devices if d.id == id_num), None)
        log_method_return(self, result)
        return result

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
    def filesystems(self):
        """ List of filesystems. """
        #""" Dict with mountpoint keys and filesystem values. """
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
    def leaves(self):
        """ List of all devices upon which no other devices exist. """
        leaves = [d for d in self._devices if d.isleaf]
        return leaves

    def get_children(self, device):
        """ Return a list of a device's children. """
        return [c for c in self._devices if device in c.parents]

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
                            device = self.get_children(luks_dev)[0]
                        except IndexError as e:
                            pass
                elif device is None:
                    # dear lvm: can we please have a few more device nodes
                    #           for each logical volume?
                    #           three just doesn't seem like enough.
                    name = devspec[5:]      # strip off leading "/dev/"

                    (vg_name, _slash, lv_name) = name.partition("/")
                    if lv_name and not "/" in lv_name:
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

    def handle_nodev_filesystems(self):
        for line in open("/proc/mounts").readlines():
            try:
                (_devspec, mountpoint, fstype, _options, _rest) = line.split(None, 4)
            except ValueError:
                log.error("failed to parse /proc/mounts line: %s", line)
                continue
            if fstype in formats.fslib.nodev_filesystems:
                if not flags.include_nodev:
                    continue

                log.info("found nodev %s filesystem mounted at %s",
                         fstype, mountpoint)
                # nodev filesystems require some special handling.
                # For now, a lot of this is based on the idea that it's a losing
                # battle to require the presence of an FS class for every type
                # of nodev filesystem. Based on that idea, we just instantiate
                # NoDevFS directly and then hack in the fstype as the device
                # attribute.
                fmt = formats.get_format("nodev")
                fmt.device = fstype

                # NoDevice also needs some special works since they don't have
                # per-instance names in the kernel.
                device = NoDevice(fmt=fmt)
                n = len([d for d in self.devices if d.format.type == fstype])
                device._name += ".%d" % n
                self._add_device(device)

    def save_luks_passphrase(self, device):
        """ Save a device's LUKS passphrase in case of reset. """

        self._populator.save_luks_passphrase(device)

    def __str__(self):
        done = []

        def show_subtree(root, depth):
            abbreviate_subtree = root in done
            s = "%s%s\n" % ("  " * depth, root)
            done.append(root)
            if abbreviate_subtree:
                s += "%s...\n" % ("  " * (depth + 1),)
            else:
                for child in self.get_children(root):
                    s += show_subtree(child, depth + 1)
            return s

        roots = [d for d in self._devices if not d.parents]
        tree = ""
        for root in roots:
            tree += show_subtree(root, 0)
        return tree
