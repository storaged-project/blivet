# events/handler.py
# Event handler mixin class.
#
# Copyright (C) 2015-2016  Red Hat, Inc.
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

from six import add_metaclass

from ..callbacks import callbacks
from ..errors import DeviceError, EventHandlingError
from ..devices import DM_MAJORS, MD_MAJORS
from .. import udev
from ..threads import SynchronizedMeta
from ..static_data import mpath_members

from .changes import data as event_data
from .manager import event_manager

import logging
log = logging.getLogger("blivet")
event_log = logging.getLogger("blivet.event")


@add_metaclass(SynchronizedMeta)
class EventHandlerMixin(object):
    def __init__(self):
        event_manager.handler_cb = self.handle_event

    def handle_event(self, event, notify_cb):
        """ Handle an event on a block device.

            :param :class:`~.event.Event` event: information about the event
            :param callable notify_cb: notification callback

            TODO: Rename all this stuff so it's explicit that it only handles uevents.
        """
        # delegate event to appropriate handler
        handlers = {"add": self._handle_add_event,
                    "change": self._handle_change_event,
                    "remove": self._handle_remove_event}

        handler = handlers.get(event.action)
        if handler is not None:
            handler(event)

        if notify_cb is not None:
            notify_cb(event=event, changes=event_data.changes)

    def _event_device_is_dm(self, event):
        """ Return True if event operand is a dm device.

            Since this may be run on add events it does not require the dm/
            subdirectory be present in the device's sysfs root, unlike
            udev.device_is_dm.

            XXX Should this replace udev.device_is_dm?
        """
        return udev.device_get_major(event.info) in DM_MAJORS

    def _event_device_is_md(self, event):
        """ Return True if event operand is a dm device.

            Since this may be run on add events it does not require the md/
            subdirectory be present in the device's sysfs root, unlike
            udev.device_is_md.

            XXX Should this replace udev.device_is_md?
        """
        return udev.device_get_major(event.info) in MD_MAJORS

    def _should_ignore_add_event(self, event):
        """ Return True if event is an add event that should be ignored.

            add events on md and dm devices should be ignored in general. When the
            operation is complete there will be a change event.
        """
        # udev.device_is_md and udev.device_is_dm are not sufficient for this purpose
        # because there are sometimes events when dm/ or md/ subdir does not exist.
        return (event.action == "add" and
                (self._event_device_is_dm(event) or self._event_device_is_md(event)))

    def _event_device_is_physical_disk(self, event):
        """ Return True if event device is a physical disk. """
        # udev.device_is_md and udev.device_is_dm are not sufficient for this purpose
        # because there are sometimes events when dm/ or md/ subdir does not exist.
        return (udev.device_is_disk(event.info) and
                not self._event_device_is_dm(event) and
                not self._event_device_is_md(event))

    def _handle_add_event(self, event):
        """ Handle an "add" event.

            Add events should correlate to activation rather than creation in
            most cases. When a device is added, there is generally a change
            event on the new device's parent(s). The obvious exception to this
            rule is the addition of a new disk, which has no parents.
        """
        # ignore add on dm and md devices
        if self._should_ignore_add_event(event):
            return

        # Try to look up the device. Do not look it up by sysfs path since in all
        # likelihood blivet thinks the device is not active and therefore has no
        # sysfs path.
        # XXX We need an existing device here, so we should also be checking destroy actions.
        device = self.get_device_by_name(udev.device_get_name(event.info), hidden=True)
        if device is None:
            device = self.get_device_by_uuid(event.info.get("UUID_SUB", udev.device_get_uuid(event.info)),
                                             hidden=True)
            if device is None and udev.device_is_dm_luks(event.info):
                # Special case for first-time decrypted LUKS devices since we do not add a
                # device for the decrypted/mapped device until it has been opened.
                self.handle_device(event.info)
                device = self.get_device_by_name(udev.device_get_name(event.info), hidden=True)

        # XXX Don't change anything (except simple attributes?) if actions are being executed.
        if device is None and self._event_device_is_physical_disk(event):
            log.info("disk %s was added", udev.device_get_name(event.info))
            mpath_members.update_cache(udev.device_get_devname(event.info))
            self.handle_device(event.info)
        elif device is not None and device.exists:
            log.info("device %s was activated", device.name)
            # device was activated from outside, so update the sysfs path
            sysfs_path = udev.device_get_sysfs_path(event.info)
            if device.sysfs_path != sysfs_path:
                old_sysfs_path = device.sysfs_path
                device.sysfs_path = sysfs_path
                callbacks.attribute_changed(device=device, attr="sysfs_path",
                                            old=old_sysfs_path, new=sysfs_path)

    def _handle_format_change(self, event, device):
        helper_class = self._get_format_helper(event.info, device)  # pylint: disable=no-member
        helper = helper_class(self, event.info, device=device)
        new_type = helper.type_spec
        old_type = device.format.type

        new_uuid = helper._get_kwargs().get("uuid")
        old_uuid = device.format.uuid

        # If the type has changed it has been reformatted. Easy.
        # If the type is unchanged and the UUID has changed, it could be a change to
        # the UUID or a reformat. Is it worthwhile to try to differentiate?
        log.debug("old_type=%-8s ; old_uuid=%-16s", old_type, old_uuid)
        log.debug("new_type=%-8s ; new_uuid=%-16s", new_type, new_uuid)
        if new_type == old_type and new_uuid == old_uuid and not self.actions.processing:
            helper.update()
            return

        if self.actions.processing:
            return

        self.cancel_disk_actions(device.disks)

        # The device was reformatted, but we can't blindly remove all children since
        # it could have been a member of a still-intact container.
        if getattr(device.format, "container_uuid", None):
            container = device.children[0]
            if len(container.parents) > 1:
                try:
                    container.parents.remove(device)
                except DeviceError as e:
                    log.error("error removing member %s from container %s: %s",
                              device.name, container.name, str(e))
                    raise EventHandlingError("reformatted container member")

                callbacks.parent_removed(device=container, parent=device)

        self.recursive_remove(device, actions=False, remove_device=False)

        helper.run()

    def _handle_change_event(self, event):
        """ Handle a "change" event.

            This could be any number of things, including activation of md/dm
            devices.
        """
        name = udev.device_get_name(event.info)
        if (name.startswith("dm-") or name.startswith("md")) and name == event.info.sys_name:
            log.debug("ignoring event on virtual device %s with no symbolic name", name)
            return

        if self._event_device_is_md(event) or self._event_device_is_dm(event):
            self._handle_add_event(event)

        # Try to look up the device in the devicetree.
        # We're expecting the device to already be active, so we try the lookup
        # by sysfs path first.
        device = self.get_device_by_sysfs_path(udev.device_get_sysfs_path(event.info))
        if device is None:
            # Lookup by sysfs path failed. Try looking it up by name.
            device = self.get_device_by_name(udev.device_get_name(event.info))

        if device is None:
            log.debug("failed to look up device")
            return

        if not device.exists:
            log.debug("device lookup returned a non-existent device")
            return

        log.info("device %s was changed", device.name)

        helper_class = self._get_device_helper(event.info)  # pylint: disable=no-member
        if helper_class is not None:
            helper = helper_class(self, event.info, device=device)
            helper.update()

        # check for metadata changes, but do not make changes to the devicetree
        # during action processing
        self._handle_format_change(event, device)

    def _handle_remove_event(self, event):
        """ Handle a "remove" event.

            Remove events correlate to deactivation or removal, but we will
            use change events on parent devices to detect removal.
        """
        # XXX We need an existing device here.
        device = self.get_device_by_sysfs_path(udev.device_get_sysfs_path(event.info))
        if device is None:
            device = self.get_device_by_name(udev.device_get_name(event.info))

        if device is None:
            return

        if self._event_device_is_physical_disk(event):
            log.info("disk %s was removed", device.name)
            self._remove_device(device)
        else:
            if device.sysfs_path:
                old_sysfs_path = device.sysfs_path
                log.info("device %s was deactivated", device.name)
                # device was deactivated from outside, so clear the sysfs path
                device.sysfs_path = ''
                callbacks.attribute_changed(device=device, attr="sysfs_path",
                                            old=old_sysfs_path, new='')
