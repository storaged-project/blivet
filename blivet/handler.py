# handler.py
# Event handling.
#
# Copyright (C) 2015  Red Hat, Inc.
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

import os
import re
import pprint
from six import add_metaclass

from . import udev
from .errors import DeviceError, EventQueueEmptyError
from .formats import getFormat
from .storage_log import log_method_call
from .threads import SynchronizedMeta

import logging
log = logging.getLogger("blivet")

@add_metaclass(SynchronizedMeta)
class EventHandler(object):
    def __init__(self, devicetree, manager):
        self.devicetree = devicetree
        self.manager = manager
        self.manager.handler_cb = self.handleUevent

    def handleUevent(self):
        """ Handle the next uevent in the queue. """
        log_method_call(self)
        try:
            event = self.manager.next_event()
        except EventQueueEmptyError:
            log.debug("uevent queue is empty")
            return

        log.debug("event: %s", event)
        if event.action == "add":
            self.deviceAddedCB(event.info)
        elif event.action == "remove":
            self.deviceRemovedCB(event.info)
        elif event.action == "change":
            self.deviceChangedCB(event.info)
        else:
            log.info("unknown event: %s", event)

    def _notifyDevice(self, action, info):
        """ Notify device condition variables as appropriate.

            :param str action: an action string, eg: 'add', 'remove'
            :param :class:`pyudev.Device` info: udev data for the device
            :returns: True if any condition variable was notified
            :rtype: bool

            Methods :meth:`~.devices.StorageDevice.create`,
            :meth:`~.devices.StorageDevice.destroy`, and
            :meth:`~.devices.StorageDevice.setup` all use a synchronization
            manager (:class:`~.threads.StorageEventSynchronizer`) to
            synchronize the finalization/confirmation of their respective
            operations. Flags within the manager are used to indicate which, if
            any, of these methods is under way.
        """
        ret = False
        name = udev.device_get_name(info)
        sysfs_path = udev.device_get_sysfs_path(info)
        log_method_call(self, name=name, action=action, sysfs_path=sysfs_path)

        actions = self.devicetree.findActions()

        # We can't do this lookup by sysfs path since the StorageDevice
        # might have just been created, in which case it might not have a
        # meaningful sysfs path (for dm and md they aren't predictable).
        device = self.devicetree.getDeviceByName(name)
        if device is None and name.startswith("md"):
            # XXX HACK md devices have no symbolic name by the time they are
            #          removed, so we have to look it up by sysfs path
            # XXX do the same for teardown during action processing?
            for _device in self.devicetree.devices:
                if _device.sysfsPath and \
                   os.path.basename(_device.sysfsPath) == name:
                    device = _device
                    break

        if action in ("add", "change") and device and \
           device.modifySync.creating and not device.delegateModifyEvents and \
           device.modifySync.validate(info):
            log.debug("* create %s", device.name)
            ## device create without event delegation (eg: partition)
            event_sync = device.modifySync
            # Only wait briefly since there is a possibility the device already
            # notified the cv from _postCreate.
            event_sync.wait(1) # wait until the device says it's ready
            event_sync.notify() # notify the device that we received the event
            event_sync.wait() # wait for the device to postprocess the event
            ret = True
        elif action in ("add", "change"):
            # could be any number of operations on a device that may no longer
            # be in the tree
            # device setup could be add or change event
            # all other operations will be change event
            event_sync = None
            name = getattr(device, "name", None)
            if device and device.controlSync.starting and \
               not device.delegateControlEvents:
                ## device setup
                log.debug("* setup %s", device.name)
                # update sysfsPath since the device will not have access to it
                # until later in the change handler
                device.sysfsPath = sysfs_path
                event_sync = device.controlSync
            elif device and device.controlSync.stopping and \
                 device.name.startswith("loop"):
                ## loop device teardown
                # XXX HACK You don't get a remove event when you deactivate a
                #          loop device.
                log.debug("* teardown %s", device.name)
                event_sync = device.controlSync
            elif action == "change" and device and device.modifySync.resizing:
                ## device resize
                log.debug("* resize %s", device.name)
                event_sync = device.modifySync
            elif action == "change" and device and \
                 device.controlSync.changing and \
                 device.controlSync.validate(info):
                ## device change (eg: event on pv for vg or lv creation)
                log.debug("* change %s", device.name)
                event_sync = device.controlSync
                # There's an extra notify/wait pair in device create/destroy
                # that the other branches in this block will not do.
                # Only wait briefly since it's possible the device has already
                # notified the CV from _postCreate/_postDestroy.
                event_sync.wait(1)
            elif action == "change" and device and \
                 device.format.eventSync.active and \
                 device.format.eventSync.validate(info):
                ## any change to a format
                log.debug("* change %s format", device.name)
                event_sync = device.format.eventSync
            elif actions:
                # see if this action is on a device or format that is scheduled
                # for removal
                devices = (a.device for a in actions if a.isDevice and
                                                        a.isDestroy)
                for device in devices:
                    # hopefully all device names are intact after removal
                    if device.name == name:
                        break
                else:
                    device = None

                if action == "change" and not device:
                    # see if this is a format op on a format scheduled for
                    # destruction
                    _actions = (a for a in actions if a.isDestroy and
                                                      a.isFormat)
                    for action in _actions:
                        if action.device.name == name and \
                           action.format.eventSync.active and \
                           action.format.eventSync.validate(info):
                            ## any change to a format scheduled for destruction
                            ## on a device not scheduled for destruction
                            log.debug("*** change %s format", action.device.name)
                            event_sync = action.format.eventSync
                            name = action.device.name
                            break

                # If we haven't come up with an event_sync yet, try the same
                # checks on the device being operated on by the current action,
                # if any.
                # XXX None of the sync manager's flags should be set if an
                #     action is not being executed.
                if device and not event_sync and actions:
                    current_action = actions[0]
                    if current_action.device.controlSync.starting and \
                       not current_action.device.delegateControlEvents:
                        ## setup of device scheduled for destruction
                        log.debug("** setup %s", current_action.device.name)
                        event_sync = current_action.device.controlSync
                    elif action == "change" and \
                         current_action.device.modifySync.destroying and \
                         current_action.device.modifySync.validate(info):
                        # change to pv when removing lv or vg
                        log.debug("** destroy %s", current_action.device.name)
                        event_sync = current_action.device.modifySync
                    elif action == "change" and \
                         current_action.format.eventSync.active and \
                         current_action.format.eventSync.validate(info):
                        ## any change to a format on a device scheduled for
                        ## destruction
                        log.debug("** change %s format", current_action.device.name)
                        event_sync = current_action.format.eventSync

            if event_sync:
                event_sync.notify()
                event_sync.wait()
                ret = True
        elif action == "remove" and device and device.controlSync.stopping and \
             not device.delegateControlEvents:
            ## device teardown
            log.debug("* teardown %s", device.name)
            device.controlSync.notify()
            device.controlSync.wait()
            ret = True
        elif action == "remove":
            ## device destroy
            current_action = None
            if actions:
                current_action = actions[0]

            if current_action and \
               current_action.isDestroy and current_action.isDevice and \
               current_action.device.exists and \
               current_action.device.modifySync.destroying and \
               not current_action.device.delegateModifyEvents:
                device = current_action.device
                log.debug("* destroy %s", device.name)
                event_sync = device.modifySync
                # Only wait briefly since it's possible the device already
                # notified the cv from _postDestroy.
                event_sync.wait(1) # wait until the device says it's ready
                event_sync.notify() # notify device that we received the event
                event_sync.wait() # wait for the device to postprocess the event
                ret = True

        return ret

    def deviceAddedCB(self, info, force=False):
        """ Handle an "add" uevent on a block device.

            The device could be newly created or newly activated.
        """
        sysfs_path = udev.device_get_sysfs_path(info)
        log.debug("device added: %s", sysfs_path)
        if info.subsystem != "block":
            return

        if not info.is_initialized:
            log.debug("new device not initialized -- not processing it")
            return

        # add events are usually not meaningful for dm and md devices, but the
        # change event handler calls this method when a change event for such a
        # device appears to signal an addition
        # sometimes you get add events for md or dm that have no real info like
        # symbolic names -- ignore those, too.
        if not force and (udev.device_is_md(info) or
                          (udev.device_is_dm(info) or
                           re.match(r'/dev/dm-\d+$', info['DEVNAME']) or
                           re.match(r'/dev/md-\d+$', info['DEVNAME']))):
            log.debug("ignoring add event for %s", sysfs_path)
            return

        # If _notifyDevice returns True, this uevent is related to processing
        # of an action. It may or may not be in the tree.
        if self._notifyDevice("add", info):
            # This will update size, uuid, &c for new devices.
            self.deviceChangedCB(info, expected=True)
            return

        device = self.devicetree.getDeviceByName(udev.device_get_name(info))
        if device and device.exists:
            log.info("%s is already in the tree", udev.device_get_name(info))
            return

        # If we get here this should be a device that was added from outside of
        # blivet. Add it to the devicetree.
        device = self.devicetree.discoverer.addUdevDevice(info)
        if device:
            # if this device is on a hidden disk it should also be hidden
            self.devicetree._hideIgnoredDisks()

    def _diskLabelChangeHandler(self, info, device):
        log.info("checking for changes to disklabel on %s", device.name)
        # update the partition list
        self.manager.blacklist_event(device=udev.device_get_name(info),
                                          action="change", count=1)
        device.format.updatePartedDisk()
        udev_devices = [d for d in udev.get_devices()
                if udev.device_get_disklabel_uuid(d) == device.format.uuid and
                    (udev.device_is_partition(d) or udev.device_is_dm_partition(d))]
        def udev_part_start(info):
            start = info.get("ID_PART_ENTRY_OFFSET")
            return int(start) if start is not None else start

        # remove any partitions we have that are no longer on disk
        for old in self.devicetree.getChildren(device):
            if not old.exists:
                log.warning("non-existent partition %s on changed "
                            "disklabel", old.name)
                continue

            if old.isLogical:
                # msdos partitions are of the form
                # "%(disklabel_uuid)s-%(part_num)s". That's because
                # there's not any place to store an actual UUID in
                # the disklabel or partition metadata, I assume.
                # The reason this is so sad is that when you remove
                # logical partition that isn't the highest-numbered
                # one, the others all get their numbers shifted down
                # so the first one is always 5. Seriously. The msdos
                # partition UUIDs are pretty useless for logical
                # partitions.
                start = old.partedPartition.geometry.start
                new = next((p for p in udev_devices
                                if udev_part_start(info) == start),
                           None)
            else:
                new = next((p for p in udev_devices
                    if udev.device_get_partition_uuid(p) == old.uuid),
                            None)

            if new is None:
                log.info("partition %s was removed", old.name)
                self.devicetree.recursiveRemove(old, actions=False,
                                                modparent=False)
            else:
                udev_devices.remove(new)

        # any partitions left in the list have been added
        for new in udev_devices:
            log.info("partition %s was added",
                     udev.device_get_name(new))
            self.devicetree.discoverer.discoverer.addUdevDevice(new)

    def _getMemberUUID(self, info, device, container=False):
        uuid = udev.device_get_uuid(info)
        container_uuid = None
        if device.format.type == "btrfs":
            container_uuid = uuid
            uuid = info["ID_FS_UUID_SUB"]
        elif device.format.type == "mdmember":
            container_uuid = uuid
            uuid = udev.device_get_md_device_uuid(info)
        elif device.format.type == "lvmpv":
            # LVM doesn't put the VG UUID in udev
            if container:
                pv_info = self.devicetree.pvInfo.get(device.path)
                if pv_info is None:
                    log.error("no pv info available for %s", device.name)
                else:
                    container_uuid = udev.device_get_vg_uuid(pv_info)

        return uuid if not container else container_uuid

    def _getContainerUUID(self, info, device):
        return self._getMemberUUID(info, device, container=True)

    def _memberChangeHandler(self, info, device):
        """ Handle a change uevent on a container member device.

            :returns: whether the container changed
            :rtype: bool

        """
        if not hasattr(device.format, "containerUUID"):
            return

        uuid = self._getMemberUUID(info, device)
        container_uuid = self._getContainerUUID(info, device)

        old_container_uuid = device.format.containerUUID
        container_changed = (old_container_uuid != container_uuid)
        try:
            container = self.devicetree.getChildren(device)[0]
        except IndexError:
            container = None

        if container_changed:
            if container:
                if len(container.parents) == 1:
                    self.devicetree.recursiveRemove(container, actions=False)
                else:
                    # FIXME: we need to be able to bypass the checks that
                    #        prevent ill-advised member removals
                    try:
                        container.parents.remove(device)
                    except DeviceError:
                        log.error("failed to remove %s from container %s "
                                  "to reflect uevent", device.name,
                                                       container.name)

            device.format = None
            self.devicetree.handleUdevDeviceFormat(info, device)
        else:
            device.format.containerUUID = container_uuid
            device.format.uuid = uuid

            if device.format.type == "lvmpv":
                pv_info = self.devicetree.pvInfo.get(device.path)
                new_vg_name = udev.device_get_vg_name(pv_info)
                device.format.vgName = new_vg_name
                device.format.peStart = udev.device_get_pv_pe_start(pv_info)
                if container:
                    # vg rename
                    container.name = new_vg_name
                    self.devicetree.updateLVs(container)

        # MD TODO: raid level, spares
        # BTRFS TODO: check for changes to subvol list IFF the volume is mounted

    def deviceChangedCB(self, info, expected=False):
        """ Handle a "changed" uevent on a block device. """
        sysfs_path = udev.device_get_sysfs_path(info)
        log.debug("device changed: %s", sysfs_path)
        if info.subsystem != "block":
            return

        if not info.is_initialized:
            log.debug("new device not initialized -- not processing it")
            return

        # Do this lookup by name -- not by sysfs_path. md and dm devices' sysfs
        # path is unset when inactive and this would be where we're finding out
        # that they've been activated, so there's nowhere in between to set it.
        # It will get set/updated in _notifyDevice or below that call in this
        # method.
        name = udev.device_get_name(info)
        device = self.devicetree.getDeviceByName(name, hidden=True)
        if device and device.exists:
            device.sysfsPath = sysfs_path

        if (not expected and not device and
            ((udev.device_is_md(info) and udev.device_get_md_uuid(info)) or
             (udev.device_is_dm(info) and "DM_NAME" in info))):
            # md and dm devices aren't really added until you get a change
            # event
            return self.deviceAddedCB(info, force=True)

        if not expected:
            # See if this event was triggered a blivet action.
            expected = self._notifyDevice("change", info)

        if not device:
            # We're not concerned with updating devices that have been removed
            # from the tree.
            log.warning("device not found: %s", udev.device_get_name(info))
            return

        if not device.exists:
            #
            # A policy must be decided upon for external events that conflict
            # with scheduled actions.
            #
            log.warning("ignoring change uevent on non-existent device")
            return

        if not os.path.exists(device.path):
            log.info("ignoring change uevent on device with no node (%s)", device.path)
            return

        ##
        ## Check for changes to the device itself.
        ##

        # rename
        name = info.get("DM_LV_NAME", udev.device_get_name(info))
        if getattr(device, "lvname", "name") != name:
            device.name = name

        # resize
        # XXX resize of inactive lvs is handled in updateLVs (via change event
        #     handler for pv(s))
        current_size = device.readCurrentSize()
        if expected or device.currentSize != current_size:
            device.updateSize(newsize=current_size)

        # This is also happening in ContainerDevice._postCreate.
        if udev.device_is_md(info) and expected:
            device.uuid = udev.device_get_md_uuid(info)

        if not device.format.exists:
            #
            # A policy must be decided upon for external events that conflict
            # with scheduled actions.
            #
            log.warning("ignoring change uevent on device with non-existent format")
            return

        log.debug("changed: %s", pprint.pformat(dict(info)))

        ##
        ## Handle changes to the data it contains.
        ##
        uuid = self._getMemberUUID(info, device)
        label = udev.device_get_label(info)

        partitioned = (device.partitionable and
                       info.get("ID_PART_TABLE_TYPE") is not None)
        new_type = getFormat(udev.device_get_format(info)).type
        type_changed = (new_type != device.format.type and
                        not
                        (device.format.type == "disklabel" and partitioned))
        log.info("partitioned: %s\ntype_changed: %s\nold type: %s\nnew type: %s",
                 partitioned, type_changed, device.format.type, new_type)

        if partitioned:
            uuid = udev.device_get_disklabel_uuid(info)

        log.info("old uuid: %s ; new uuid: %s", device.format.uuid, uuid)
        uuid_changed = (device.format.uuid and device.format.uuid != uuid)
        reformatted = uuid_changed or type_changed

        if not type_changed and (expected or not uuid_changed):
            log.info("%s was not reformatted, or was reformatted by blivet",
                     device.name)
            ##
            ## Not reformatted or reformatted as expected by blivet.
            ##

            ## update UUID and label
            device.format.uuid = uuid

            # FIXME: grab the info about uuid attrs from the container instance?
            if expected and hasattr(device.format, "containerUUID"):
                if device.format.type == "lvmpv":
                    self.devicetree.dropLVMCache()
                device.format.containerUUID = self._getContainerUUID(info,
                                                                     device)

            if hasattr(device.format, "label"):
                device.format.label = label
        elif reformatted and not expected:
            log.info("%s was reformatted from outside of blivet", device.name)
            for child in self.devicetree.getChildren(device):
                self.devicetree.recursiveRemove(child, actions=False)

            device.format = None
            self.devicetree.handleUdevDeviceFormat(info, device)

        if expected:
            return

        ##
        ## Now handle devices whose formatting determines other devices'
        ## existence.
        ##
        if partitioned:
            self._diskLabelChangeHandler(info, device)
        elif hasattr(device.format, "containerUUID"):
            if device.format.type == "lvmpv":
                self.devicetree.dropLVMCache()

            self._memberChangeHandler(info, device)

    def deviceRemovedCB(self, info):
        """ Handle a "remove" uevent on a block device.

            This is generally going to be interpreted as a deactivation as
            opposed to a removal since there is no consistent way to determine
            which it is from the information given.

            It seems sensible to interpret remove events as deactivations and
            handle destruction via change events on parent devices.
        """
        log.debug("device removed: %s", udev.device_get_sysfs_path(info))
        if info.subsystem != "block":
            return

        if self._notifyDevice("remove", info):
            return

        # XXX Don't forget about disks actually going offline for some reason.

        device = self.devicetree.getDeviceByName(udev.device_get_name(info))
        if device:
            device.sysfsPath = ""

            # update FS instances since the device is surely no longer mounted
            for fmt in (device.format, device.originalFormat):
                if hasattr(fmt, "_mountpoint"):
                    fmt._mountpoint = None
                    fmt._mounted_read_only = False


