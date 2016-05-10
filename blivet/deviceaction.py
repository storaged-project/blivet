# deviceaction.py
# Device modification action classes.
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


from . import util

from . import udev
from .util import get_current_entropy
from .devices import StorageDevice
from .devices import PartitionDevice, LVMLogicalVolumeDevice
from .formats import getFormat, luks
from parted import partitionFlag, PARTITION_LBA
from .i18n import _, N_
from .callbacks import CreateFormatPreData, CreateFormatPostData
from .callbacks import ResizeFormatPreData, ResizeFormatPostData
from .callbacks import WaitForEntropyData

import logging
log = logging.getLogger("blivet")

# The values are just hints as to the ordering.
# Eg: fsmod and devmod ordering depends on the mod (shrink -v- grow)
ACTION_TYPE_NONE = 0
ACTION_TYPE_DESTROY = 1000
ACTION_TYPE_RESIZE = 500
ACTION_TYPE_CREATE = 100
ACTION_TYPE_ADD = 50
ACTION_TYPE_REMOVE = 10

action_strings = {ACTION_TYPE_NONE: "None",
                  ACTION_TYPE_DESTROY: "Destroy",
                  ACTION_TYPE_RESIZE: "Resize",
                  ACTION_TYPE_CREATE: "Create",
                  ACTION_TYPE_ADD: "Add",
                  ACTION_TYPE_REMOVE: "Remove"}

ACTION_OBJECT_NONE = 0
ACTION_OBJECT_FORMAT = 1
ACTION_OBJECT_DEVICE = 2
ACTION_OBJECT_CONTAINER = 3

object_strings = {ACTION_OBJECT_NONE: "None",
                  ACTION_OBJECT_FORMAT: "Format",
                  ACTION_OBJECT_DEVICE: "Device",
                  ACTION_OBJECT_CONTAINER: "Container"}

RESIZE_SHRINK = 88
RESIZE_GROW = 89

resize_strings = {RESIZE_SHRINK: "Shrink",
                  RESIZE_GROW: "Grow"}

def action_type_from_string(type_string):
    if type_string is None:
        return None

    for (k,v) in action_strings.items():
        if v.lower() == type_string.lower():
            return k

    return resize_type_from_string(type_string)

def action_object_from_string(type_string):
    if type_string is None:
        return None

    for (k,v) in object_strings.items():
        if v.lower() == type_string.lower():
            return k

def resize_type_from_string(type_string):
    if type_string is None:
        return None

    for (k,v) in resize_strings.items():
        if v.lower() == type_string.lower():
            return k

class DeviceAction(util.ObjectID):
    """ An action that will be carried out in the future on a Device.

        These classes represent actions to be performed on devices or
        filesystems.

        The operand Device instance will be modified according to the
        action, but no changes will be made to the underlying device or
        filesystem until the DeviceAction instance's execute method is
        called. The DeviceAction instance's cancel method should reverse
        any modifications made to the Device instance's attributes.

        If the Device instance represents a pre-existing device, the
        constructor should call any methods or set any attributes that the
        action will eventually change. Device/DeviceFormat classes should verify
        that the requested modifications are reasonable and raise an
        exception if not.

        Only one action of any given type/object pair can exist for any
        given device at any given time. This is enforced by the
        DeviceTree.

        Basic usage:

            a = DeviceAction(dev)
            a.execute()

            OR

            a = DeviceAction(dev)
            a.cancel()


        XXX should we back up the device with a deep copy for forcibly
            cancelling actions?

            The downside is that we lose any checking or verification that
            would get done when resetting the Device instance's attributes to
            their original values.

            The upside is that we would be guaranteed to achieve a total
            reversal. No chance of, eg: resizes ending up altering Device
            size due to rounding or other miscalculation.
"""
    type = ACTION_TYPE_NONE
    obj = ACTION_OBJECT_NONE
    typeDescStr = ""

    def __init__(self, device):
        util.ObjectID.__init__(self)
        if not isinstance(device, StorageDevice):
            raise ValueError("arg 1 must be a StorageDevice instance")
        self.device = device
        self.container = getattr(self.device, "container", None)
        self._applied = False

    def apply(self):
        """ apply changes related to the action to the device(s) """
        self._applied = True

    def execute(self, callbacks=None):
        """
        Perform the action.

        :param callbacks: callbacks to be run when matching actions are
                          executed (see :meth:`~.blivet.Blivet.doIt`)

        """
        # pylint: disable=unused-argument
        if not self._applied:
            raise RuntimeError("cannot execute unapplied action")

    def cancel(self):
        """ cancel the action """
        self._applied = False

    @property
    def isDestroy(self):
        return self.type == ACTION_TYPE_DESTROY

    @property
    def isCreate(self):
        return self.type == ACTION_TYPE_CREATE

    @property
    def isResize(self):
        return self.type == ACTION_TYPE_RESIZE

    @property
    def isShrink(self):
        return (self.isResize and self.dir == RESIZE_SHRINK) # pylint: disable=no-member

    @property
    def isGrow(self):
        return (self.isResize and self.dir == RESIZE_GROW) # pylint: disable=no-member

    @property
    def isAdd(self):
        return self.type == ACTION_TYPE_ADD

    @property
    def isRemove(self):
        return self.type == ACTION_TYPE_REMOVE

    @property
    def isDevice(self):
        return self.obj == ACTION_OBJECT_DEVICE

    @property
    def isContainer(self):
        return self.obj == ACTION_OBJECT_CONTAINER

    @property
    def isFormat(self):
        return self.obj == ACTION_OBJECT_FORMAT

    @property
    def format(self):
        return self.device.format

    @property
    def typeString(self):
        """ String indicating if this action is a create, destroy or resize. """
        return action_strings[self.type]

    @property
    def objectString(self):
        """ String indicating if this action's operand is device or format. """
        return object_strings[self.obj]

    @property
    def resizeString(self):
        """ String representing the direction of a resize action. """
        s = ""
        if self.isResize:
            s = resize_strings[self.dir] # pylint: disable=no-member

        return s

    @property
    def objectTypeString(self):
        """ String representing the type of the operand device or format. """
        if self.isFormat:
            s = self.format.name
        else:
            s = self.device.type

        return s

    @property
    def typeDesc(self):
        return _(self.typeDescStr)

    def __str__(self):
        s = "[%d] %s" % (self.id, self.typeDescStr)
        if self.isResize:
            s += " (%s)" % self.resizeString
        if self.isFormat:
            s += " %s on" % self.format.desc
        s += " %s %s (id %d)" % (self.device.type, self.device.name,
                                 self.device.id)
        return s

    def requires(self, action):
        """ Return True if self requires action. """
        return (not (self.isContainer or action.isContainer) and
                self.type < action.type)

    def obsoletes(self, action):
        """ Return True is self obsoletes action.

            DeviceAction instances obsolete other DeviceAction instances with
            lower id and same device.
        """
        return (self.device.id == action.device.id and
                self.type == action.type and
                self.obj == action.obj and
                self.id > action.id)


class ActionCreateDevice(DeviceAction):
    """ Action representing the creation of a new device. """
    type = ACTION_TYPE_CREATE
    obj = ACTION_OBJECT_DEVICE
    typeDescStr = N_("create device")

    def __init__(self, device):
        if device.exists:
            raise ValueError("device already exists")

        # FIXME: assert device.fs is None
        DeviceAction.__init__(self, device)

    def execute(self, callbacks=None):
        super(ActionCreateDevice, self).execute(callbacks=None)
        self.device.create()

    def requires(self, action):
        """ Return True if self requires action.

            Device create actions require other actions when either of the
            following is true:

                - this action's device depends on the other action's device
                - both actions are partition create actions on the same disk
                  and this partition has a higher number
                - the other action adds a member to this device's container
        """
        rc = super(ActionCreateDevice, self).requires(action)
        if self.device.dependsOn(action.device):
            rc = True
        elif (action.isCreate and action.isDevice and
              isinstance(self.device, PartitionDevice) and
              isinstance(action.device, PartitionDevice) and
              self.device.disk == action.device.disk):
            # create partitions in ascending numerical order
            selfNum = self.device.partedPartition.number
            otherNum = action.device.partedPartition.number
            if selfNum > otherNum:
                rc = True
        elif (action.isCreate and action.isDevice and
              isinstance(self.device, LVMLogicalVolumeDevice) and
              isinstance(action.device, LVMLogicalVolumeDevice) and
              self.device.vg == action.device.vg):
            # create cached LVs before non-cached LVs so that fast cache space
            # is not taken by non-cached LVs
            if not self.device.cached and action.device.cached:
                rc = True
        elif (action.isAdd and action.container == self.container):
            rc = True

        return rc


class ActionDestroyDevice(DeviceAction):
    """ An action representing the deletion of an existing device. """
    type = ACTION_TYPE_DESTROY
    obj = ACTION_OBJECT_DEVICE
    typeDescStr = N_("destroy device")

    def __init__(self, device):
        # XXX should we insist that device.fs be None?
        DeviceAction.__init__(self, device)

    def execute(self, callbacks=None):
        super(ActionDestroyDevice, self).execute(callbacks=None)
        self.device.destroy()

    def requires(self, action):
        """ Return True if self requires action.

            Device destroy actions require other actions when either of the
            following is true:

                - the other action's device depends on this action's device
                - both actions are partition create actions on the same disk
                  and this partition has a lower number
                - the other action removes this action's device from a container
        """
        rc = super(ActionDestroyDevice, self).requires(action)
        if action.device.dependsOn(self.device) and action.isDestroy:
            rc = True
        elif (action.isDestroy and action.isDevice and
              (isinstance(self.device, PartitionDevice) and self.device.disklabelSupported) and
              (isinstance(action.device, PartitionDevice) and action.device.disklabelSupported) and
              self.device.disk == action.device.disk):
            # remove partitions in descending numerical order
            selfNum = self.device.partedPartition.number
            otherNum = action.device.partedPartition.number
            if selfNum < otherNum:
                rc = True
        elif (action.isDestroy and action.isFormat and
              action.device.id == self.device.id):
            # device destruction comes after destruction of device's format
            rc = True
        elif (action.isRemove and action.device == self.device):
            rc = True
        return rc

    def obsoletes(self, action):
        """ Return True if self obsoletes action.

            - obsoletes all actions w/ lower id that act on the same device,
              including self, if device does not exist

            - obsoletes all but ActionDestroyFormat actions w/ lower id on the
              same device if device exists

            - obsoletes all actions that add a member to this action's
              (container) device

        """
        rc = False
        if action.device.id == self.device.id:
            if self.id >= action.id and not self.device.exists:
                rc = True
            elif self.id > action.id and \
                 self.device.exists and \
                 not (action.isDestroy and action.isFormat):
                rc = True
            elif action.isAdd and (action.device == self.device):
                rc = True
        elif action.isAdd and (action.container == self.device):
            rc = True

        return rc


class ActionResizeDevice(DeviceAction):
    """ An action representing the resizing of an existing device. """
    type = ACTION_TYPE_RESIZE
    obj = ACTION_OBJECT_DEVICE
    typeDescStr = N_("resize device")

    def __init__(self, device, newsize):
        if not device.resizable:
            raise ValueError("device is not resizable")

        if device.currentSize == newsize:
            raise ValueError("new size same as old size")

        if newsize < device.minSize:
            raise ValueError("new size is too small")

        if device.maxSize and newsize > device.maxSize:
            raise ValueError("new size is too large")

        DeviceAction.__init__(self, device)
        if newsize > device.currentSize:
            self.dir = RESIZE_GROW
        else:
            self.dir = RESIZE_SHRINK
        if device.targetSize > 0:
            self.origsize = device.targetSize
        else:
            self.origsize = device.size

        self._targetSize = newsize

    def apply(self):
        """ apply changes related to the action to the device(s) """
        if self._applied:
            return

        self.device.targetSize = self._targetSize
        super(ActionResizeDevice, self).apply()

    def execute(self, callbacks=None):
        super(ActionResizeDevice, self).execute(callbacks=None)
        self.device.resize()

    def cancel(self):
        if not self._applied:
            return

        self.device.targetSize = self.origsize
        super(ActionResizeDevice, self).cancel()

    def requires(self, action):
        """ Return True if self requires action.

            A device resize action requires another action if:

                - the other action is a format resize on the same device and
                  both are shrink operations
                - the other action grows a device (or format it contains) that
                  this action's device depends on
                - the other action shrinks a device (or format it contains)
                  that depends on this action's device
                - the other action removes this action's device from a container
                - the other action adds a member to this device's container
        """
        retval = super(ActionResizeDevice, self).requires(action)
        if action.isResize:
            if self.device.id == action.device.id and \
               self.dir == action.dir and \
               action.isFormat and self.isShrink:
                retval = True
            elif action.isGrow and self.device.dependsOn(action.device):
                retval = True
            elif action.isShrink and action.device.dependsOn(self.device):
                retval = True
        elif (action.isRemove and action.device == self.device):
            retval = True
        elif (action.isAdd and action.container == self.container):
            retval = True

        return retval


class ActionCreateFormat(DeviceAction):
    """ An action representing creation of a new filesystem. """
    type = ACTION_TYPE_CREATE
    obj = ACTION_OBJECT_FORMAT
    typeDescStr = N_("create format")

    def __init__(self, device, fmt=None):
        """
            :param device: the device on which the format will be created
            :type device: :class:`~.devices.StorageDevice`
            :keyword fmt: the format to put on the device
            :type fmt: :class:~.formats.DeviceFormat`

            If no format is specified, it is assumed that the format is already
            associated with the device.
        """
        if device.formatImmutable:
            raise ValueError("this device's formatting cannot be modified")

        DeviceAction.__init__(self, device)
        if fmt:
            self.origFormat = device.format
        else:
            self.origFormat = getFormat(None)

        self._format = fmt or device.format

        if self._format.exists:
            raise ValueError("specified format already exists")

    def apply(self):
        """ apply changes related to the action to the device(s) """
        if self._applied:
            return

        self.device.format = self._format
        super(ActionCreateFormat, self).apply()

    def execute(self, callbacks=None):
        super(ActionCreateFormat, self).execute(callbacks=None)
        if callbacks and callbacks.create_format_pre:
            msg = _("Creating %(type)s on %(device)s") % {"type": self.device.format.type, "device": self.device.path}
            callbacks.create_format_pre(CreateFormatPreData(msg))
            self.device.setup()

        if isinstance(self.device, PartitionDevice) and self.device.disklabelSupported:
            for flag in partitionFlag.keys():
                # Keep the LBA flag on pre-existing partitions
                if flag in [ PARTITION_LBA, self.format.partedFlag ]:
                    continue
                self.device.unsetFlag(flag)

            if self.format.partedFlag is not None:
                self.device.setFlag(self.format.partedFlag)

            if self.format.partedSystem is not None:
                self.device.partedPartition.system = self.format.partedSystem

            self.device.disk.format.commitToDisk()
            udev.settle()

        if isinstance(self.device.format, luks.LUKS):
            # LUKS needs to wait for random data entropy if it is too low
            min_required_entropy = self.device.format.min_luks_entropy
            current_entropy = get_current_entropy()
            if current_entropy < min_required_entropy:
                force_cont = False
                if callbacks and callbacks.wait_for_entropy:
                    msg = _("Not enough entropy to create LUKS format. "
                            "%d bits are needed.") % min_required_entropy
                    force_cont = callbacks.wait_for_entropy(WaitForEntropyData(msg, min_required_entropy))

                if force_cont:
                    # log warning and set format's required entropy to 0
                    log.warning("Forcing LUKS creation regardless of enough "
                                "random data entropy (%d/%d)",
                                get_current_entropy(), min_required_entropy)
                    self.device.format.min_luks_entropy = 0

        self.device.format.create(device=self.device.path,
                                  options=self.device.formatArgs)
        udev.settle()
        # Get the UUID now that the format is created
        info = udev.get_device(self.device.sysfsPath)
        # only do this if the format has a device known to udev
        # (the format might not have a normal device at all)
        if info:
            if self.device.format.type != "btrfs":
                self.device.format.uuid = udev.device_get_uuid(info)

            self.device.deviceLinks = udev.device_get_symlinks(info)
        elif self.device.format.type != "tmpfs":
            # udev lookup failing is a serious issue for anything other than tmpfs
            log.error("udev lookup failed for device: %s", self.device)

        if callbacks and callbacks.create_format_post:
            msg = _("Created %(type)s on %(device)s") % {"type": self.device.format.type, "device": self.device.path}
            callbacks.create_format_post(CreateFormatPostData(msg))

    def cancel(self):
        if not self._applied:
            return

        self.device.format = self.origFormat
        super(ActionCreateFormat, self).cancel()

    def requires(self, action):
        """ Return True if self requires action.

            Format create action can require another action if:

                - this action's device depends on the other action's device
                  and the other action is not a device destroy action or a
                  container action
                - the other action is a create or resize of this action's
                  device
        """
        return (super(ActionCreateFormat, self).requires(action) or
                (self.device.dependsOn(action.device) and
                 not ((action.isDestroy and action.isDevice) or
                      action.isContainer)) or
                (action.isDevice and (action.isCreate or action.isResize) and
                 self.device.id == action.device.id))

    def obsoletes(self, action):
        """ Return True if this action obsoletes action.

            Format create actions obsolete the following actions:

                - format actions w/ lower id on this action's device, other
                  than those that destroy existing formats
        """
        return (self.device.id == action.device.id and
                self.obj == action.obj and
                not (action.isDestroy and action.format.exists) and
                self.id > action.id)


class ActionDestroyFormat(DeviceAction):
    """ An action representing the removal of an existing filesystem. """
    type = ACTION_TYPE_DESTROY
    obj = ACTION_OBJECT_FORMAT
    typeDescStr = N_("destroy format")

    def __init__(self, device):
        if device.formatImmutable:
            raise ValueError("this device's formatting cannot be modified")

        DeviceAction.__init__(self, device)
        self.origFormat = self.device.format

    def apply(self):
        if self._applied:
            return

        self.device.format = None
        super(ActionDestroyFormat, self).apply()

    def execute(self, callbacks=None):
        """ wipe the filesystem signature from the device """
        super(ActionDestroyFormat, self).execute(callbacks=None)
        status = self.device.status
        self.device.setup(orig=True)
        self.format.destroy()
        udev.settle()
        if not status:
            self.device.teardown()

    def cancel(self):
        if not self._applied:
            return

        self.device.format = self.origFormat
        super(ActionDestroyFormat, self).cancel()

    @property
    def format(self):
        return self.origFormat

    def requires(self, action):
        """ Return True if self requires action.

            Format destroy actions require other actions when:

                - the other action's device depends on this action's device
                  and the other action is a destroy action
                - the other action removes this action's device from a container
        """
        retval = super(ActionDestroyFormat, self).requires(action)
        if action.device.dependsOn(self.device) and action.isDestroy:
            retval = True
        elif (action.isRemove and action.device == self.device):
            retval = True

        return retval

    def obsoletes(self, action):
        """ Return True if this action obsoletes action.

            Format destroy actions obsolete the following actions:

            - non-destroy format actions w/ lower id on same device, including
              self if format does not exist

            - destroy format action w/ higher id on same device

            - format destroy action on a non-existent format shouldn't
              obsolete a format destroy action on an existing one
        """
        retval = False
        same_device = self.device.id == action.device.id
        format_action = self.obj == action.obj
        if same_device and format_action:
            if action.isDestroy:
                if self.format.exists and not action.format.exists:
                    retval = True
                elif not self.format.exists and action.format.exists:
                    retval = False
                elif self.id == action.id and not self.format.exists:
                    retval = True
                else:
                    retval = self.id < action.id
            else:
                retval = self.id > action.id

        return retval

class ActionResizeFormat(DeviceAction):
    """ An action representing the resizing of an existing filesystem.

        XXX Do we even want to support resizing of a filesystem without
            also resizing the device it resides on?
    """
    type = ACTION_TYPE_RESIZE
    obj = ACTION_OBJECT_FORMAT
    typeDescStr = N_("resize format")

    def __init__(self, device, newsize):
        if device.formatImmutable:
            raise ValueError("this device's formatting cannot be modified")

        if not device.format.resizable:
            raise ValueError("format is not resizable")

        if device.format.currentSize == newsize:
            raise ValueError("new size same as old size")

        DeviceAction.__init__(self, device)
        if newsize > device.format.currentSize:
            self.dir = RESIZE_GROW
        else:
            self.dir = RESIZE_SHRINK
        self.origSize = self.device.format.targetSize
        self._targetSize = newsize

    def apply(self):
        if self._applied:
            return

        self.device.format.targetSize = self._targetSize
        super(ActionResizeFormat, self).apply()

    def execute(self, callbacks=None):
        super(ActionResizeFormat, self).execute(callbacks=None)
        if callbacks and callbacks.resize_format_pre:
            msg = _("Resizing filesystem on %(device)s") % {"device": self.device.path}
            callbacks.resize_format_pre(ResizeFormatPreData(msg))

        self.device.setup(orig=True)
        self.device.format.doResize()

        if callbacks and callbacks.resize_format_post:
            msg = _("Resized filesystem on %(device)s") % {"device": self.device.path}
            callbacks.resize_format_post(ResizeFormatPostData(msg))

    def cancel(self):
        if not self._applied:
            return

        self.device.format.targetSize = self.origSize
        super(ActionResizeFormat, self).cancel()

    def requires(self, action):
        """ Return True if self requires action.

            A format resize action requires another action if:

                - the other action is a device resize on the same device and
                  both are grow operations
                - the other action shrinks a device (or format it contains)
                  that depends on this action's device
                - the other action grows a device (or format) that this
                  action's device depends on
                - the other action removes this action's device from a container
        """
        retval = super(ActionResizeFormat, self).requires(action)
        if action.isResize:
            if self.device.id == action.device.id and \
               self.dir == action.dir and \
               action.isDevice and self.isGrow:
                retval = True
            elif action.isShrink and action.device.dependsOn(self.device):
                retval = True
            elif action.isGrow and self.device.dependsOn(action.device):
                retval = True
        elif (action.isRemove and action.device == self.device):
            retval = True

        return retval


class ActionAddMember(DeviceAction):
    """ An action representing addition of a member device to a container. """
    type = ACTION_TYPE_ADD
    obj = ACTION_OBJECT_CONTAINER
    typeDescStr = N_("add container member")

    def __init__(self, container, device):
        super(ActionAddMember, self).__init__(device)
        self.container = container

    def apply(self):
        if self._applied:
            return

        self.container.parents.append(self.device)
        super(ActionAddMember, self).apply()

    def cancel(self):
        if not self._applied:
            return

        self.container.parents.remove(self.device)
        super(ActionAddMember, self).cancel()

    def execute(self, callbacks=None):
        super(ActionAddMember, self).execute(callbacks=None)
        self.container.add(self.device)

    def requires(self, action):
        """
            requires
                - create/resize the same device

            required by
                - any create/grow action on a device in the same container
        """
        return ((action.isCreate or action.isResize) and
                action.device == self.device)

    def obsoletes(self, action):
        """
            obsoletes
                - remove same member from same container
                - add same member to same container w/ higher id

            obsoleted by
                - destroy the container
                - destroy the device
                - remove same member from same container
        """
        retval = False
        if (action.isRemove and
            action.device == self.device and
            action.container == self.container):
            retval = True
        elif (action.isAdd and
              action.device == self.device and
              action.container == self.container and
              action.id > self.id):
            retval = True

        return retval


class ActionRemoveMember(DeviceAction):
    """ An action representing removal of a member device from a container. """
    type = ACTION_TYPE_REMOVE
    obj = ACTION_OBJECT_CONTAINER
    typeDescStr = N_("remove container member")

    def __init__(self, container, device):
        super(ActionRemoveMember, self).__init__(device)
        self.container = container

    def apply(self):
        if self._applied:
            return

        self.container.parents.remove(self.device)
        super(ActionRemoveMember, self).apply()

    def cancel(self):
        if not self._applied:
            return

        self.container.parents.append(self.device)
        super(ActionRemoveMember, self).cancel()

    def execute(self, callbacks=None):
        super(ActionRemoveMember, self).execute(callbacks=None)
        self.container.remove(self.device)

    def requires(self, action):
        """
            requires
                - any destroy/shrink action on a device in the same container
                - any add action on this container

            required by
                - any destroy/resize action on the device
        """
        retval = False
        if ((action.isShrink or action.isDestroy) and
            action.device.container == self.container):
            retval = True
        elif action.isAdd and action.container == self.container:
            retval = True

        return retval

    def obsoletes(self, action):
        """
            obsoletes
                - add same member to same container
                - remove same member from same container w/ higher id

            obsoleted by
                - add same member to same container
        """
        retval = False
        if (action.isAdd and
            action.device == self.device and
            action.container == self.container):
            retval = True
        elif (action.isRemove and
              action.device == self.device and
              action.container == self.container and
              action.id > self.id):
            retval = True

        return retval
