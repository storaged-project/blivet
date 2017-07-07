# actionlist.py
# Action management.
#
# Copyright (C) 2009-2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

import copy
from functools import wraps
from six import add_metaclass

from .callbacks import callbacks as _callbacks
from .deviceaction import ActionCreateDevice
from .deviceaction import action_type_from_string, action_object_from_string
from .devicelibs import lvm
from .devices import PartitionDevice
from .errors import DiskLabelCommitError, StorageError
from .flags import flags
from . import tsort
from .threads import blivet_lock, SynchronizedMeta

import logging
log = logging.getLogger("blivet")


def with_flag(flag_attr):
    """ Decorator to set a flag attribute while running a method. """
    def run_func_with_flag_attr_set(func):
        @wraps(func)
        def wrapped_func(obj, *args, **kwargs):
            setattr(obj, flag_attr, True)
            try:
                return func(obj, *args, **kwargs)
            finally:
                setattr(obj, flag_attr, False)

        return wrapped_func

    return run_func_with_flag_attr_set


@add_metaclass(SynchronizedMeta)
class ActionList(object):
    _unsynchronized_methods = ['process']

    def __init__(self, addfunc=None, removefunc=None):
        self._add_func = addfunc
        self._remove_func = removefunc
        self._actions = []
        self._completed_actions = []
        self.processing = False

    def __iter__(self):
        return iter(self._actions)

    def add(self, action):
        if self._add_func is not None:
            self._add_func(action)

        # apply the action before adding it in case apply raises an exception
        action.apply()
        self._actions.append(action)
        _callbacks.action_added(action=action)
        log.info("registered action: %s", action)

    def remove(self, action):
        if self._remove_func:
            self._remove_func(action)

        action.cancel()
        self._actions.remove(action)
        _callbacks.action_removed(action=action)
        log.info("canceled action %s", action)

    def find(self, device=None, action_type=None, object_type=None,
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
        if device is None and action_type is None and object_type is None and \
           path is None and devid is None:
            return self._actions[:]

        # convert the string arguments to the types used in actions
        _type = action_type_from_string(action_type)
        _object = action_object_from_string(object_type)

        actions = []
        for action in self._actions:
            if device is not None and action.device != device:
                continue

            if _type is not None and action.type != _type:
                continue

            if _object is not None and action.obj != _object:
                continue

            if path is not None and action.device.path != path:
                continue

            if devid is not None and action.device.id != devid:
                continue

            actions.append(action)

        return actions

    def prune(self):
        """ Remove redundant/obsolete actions from the action list. """
        for action in reversed(self._actions[:]):
            if action not in self._actions:
                log.debug("action %d already pruned", action.id)
                continue

            for obsolete in self._actions[:]:
                if action.obsoletes(obsolete):
                    log.info("removing obsolete action %d (%d)",
                             obsolete.id, action.id)
                    self._actions.remove(obsolete)

                    if obsolete.obsoletes(action) and action in self._actions:
                        log.info("removing mutually-obsolete action %d (%d)",
                                 action.id, obsolete.id)
                        self._actions.remove(action)

    def sort(self):
        """ Sort actions based on dependencies. """
        if not self._actions:
            return

        edges = []

        # collect all ordering requirements for the actions
        for action in self._actions:
            action_idx = self._actions.index(action)
            children = []
            for _action in self._actions:
                if _action == action:
                    continue

                # create edges based on both action type and dependencies.
                if _action.requires(action):
                    children.append(_action)

            for child in children:
                child_idx = self._actions.index(child)
                edges.append((action_idx, child_idx))

        # create a graph reflecting the ordering information we have
        graph = tsort.create_graph(list(range(len(self._actions))), edges)

        # perform a topological sort based on the graph's contents
        order = tsort.tsort(graph)

        # now replace self._actions with a sorted version of the same list
        actions = []
        for idx in order:
            actions.append(self._actions[idx])
        self._actions = actions

    def _pre_process(self, devices=None):
        """ Prepare the action queue for execution. """
        devices = devices or []
        for action in self._actions:
            log.debug("action: %s", action)

        log.info("pruning action queue...")
        self.prune()

        problematic = self._find_active_devices_on_action_disks(devices=devices)
        if problematic:
            if flags.auto_dev_updates:
                for device in devices:
                    if device.protected:
                        continue

                    try:
                        device.teardown(recursive=True)
                    except StorageError as e:
                        log.info("teardown of %s failed: %s", device.name, e)
            else:
                raise RuntimeError("partitions in use on disks with changes "
                                   "pending: %s" %
                                   ",".join(problematic))

        log.info("resetting parted disks...")
        for device in devices:
            if device.partitioned and device.format.supported:
                device.format.reset_parted_disk()

            if device.original_format.type == "disklabel" and \
               device.original_format != device.format:
                device.original_format.reset_parted_disk()

        # Call pre_commit_fixup on all devices, including those we're going to
        # destroy (these are already removed from the tree)
        fixup_devices = devices + [a.device for a in self._actions
                                   if a.is_destroy and a.is_device]
        for device in fixup_devices:
            if isinstance(device, PartitionDevice) and not self.find(device=device, object_type="device"):
                device.pre_commit_fixup(current_fmt=True)
            else:
                device.pre_commit_fixup()

        # setup actions to create any extended partitions we added
        #
        # If the extended partition was explicitly requested it will already
        # have an action registered.
        #
        # XXX At this point there can be duplicate partition paths in the
        #     tree (eg: non-existent sda6 and previous sda6 that will become
        #     sda5 in the course of partitioning), so we access the list
        #     directly here.
        for device in devices:
            if isinstance(device, PartitionDevice) and \
               device.is_extended and not device.exists and \
               not self.find(device=device, action_type="create"):
                # don't properly register the action since the device is
                # already in the tree
                action = ActionCreateDevice(device)
                # apply the action first in case the apply method fails
                action.apply()
                self._actions.append(action)

        log.info("sorting actions...")
        self.sort()
        for action in self._actions:
            log.debug("action: %s", action)

            # Remove lvm filters for devices we are operating on
            for device in (d for d in devices if d.depends_on(action.device)):
                lvm.lvm_cc_removeFilterRejectRegexp(device.name)

    def _post_process(self, devices=None):
        """ Clean up relics from action queue execution. """
        devices = devices or []
        # removal of partitions makes use of original_format, so it has to stay
        # up to date in case of multiple passes through this method
        for disk in (d for d in devices if d.partitioned and d.format.supported):
            disk.format.update_orig_parted_disk()
            disk.original_format = copy.deepcopy(disk.format)

        # now we have to update the parted partitions of all devices so they
        # match the parted disks we just updated
        for partition in (d for d in devices if isinstance(d, PartitionDevice)):
            pdisk = partition.disk.format.parted_disk
            partition.parted_partition = pdisk.getPartitionByPath(partition.path)

    def _find_active_devices_on_action_disks(self, devices=None):
        """ Return a list of devices using the disks we plan to change. """
        # Find out now if there are active devices using partitions on disks
        # whose disklabels we are going to change. If there are, do not proceed.
        devices = devices or []
        disks = []
        for action in self._actions:
            disk = None
            if action.is_format and action.format.type == "disklabel":
                disk = action.device

            if disk is not None and disk not in disks:
                disks.append(disk)

        active = []
        for dev in devices:
            if dev.status and not dev.is_disk and \
               not isinstance(dev, PartitionDevice):
                active.append(dev)

            elif dev.format.status and not dev.is_disk:
                active.append(dev)

        devices = [a.name for a in active if any(d in disks for d in a.disks)]
        return devices

    @with_flag("processing")
    def process(self, callbacks=None, devices=None, dry_run=None):
        """
        Execute all registered actions.

        :param callbacks: callbacks to be invoked when actions are executed
        :param devices: a list of all devices current in the devicetree
        :type callbacks: :class:`~.callbacks.DoItCallbacks`

        """
        devices = devices or []
        self._pre_process(devices=devices)

        for action in self._actions[:]:
            log.info("executing action: %s", action)
            if dry_run:
                continue

            with blivet_lock:
                try:
                    action.execute(callbacks)
                except DiskLabelCommitError:
                    # it's likely that a previous action
                    # triggered setup of an lvm or md device.
                    # include deps no longer in the tree due to pending removal
                    devs = devices + [a.device for a in self._actions]
                    for dep in set(devs):
                        if dep.exists and \
                           any(dep.depends_on(disk) for disk in action.device.disks):
                            dep.teardown(recursive=True)

                    action.execute(callbacks)

                for device in devices:
                    # make sure we catch any renumbering parted does
                    if device.exists and isinstance(device, PartitionDevice):
                        # also update existence for partitions on unsupported disklabels
                        if not device.disklabel_supported and \
                           action.is_destroy and action.is_format and action.device == device.disk:
                            device.exists = False
                            continue

                        device.update_name()
                        device.format.device = device.path

                self._completed_actions.append(self._actions.pop(0))
                _callbacks.action_executed(action=action)

        self._post_process(devices=devices)
