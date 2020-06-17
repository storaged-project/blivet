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

import copy

from six import add_metaclass

from . import util
from . import udev
from .errors import DependencyError
from .util import get_current_entropy
from .devices import StorageDevice
from .devices import PartitionDevice, LVMLogicalVolumeDevice
from .formats import get_format, luks
from parted import partitionFlag, PARTITION_LBA
from .i18n import _, N_
from .callbacks import CreateFormatPreData, CreateFormatPostData
from .callbacks import ResizeFormatPreData, ResizeFormatPostData
from .callbacks import WaitForEntropyData, ReportProgressData
from .size import Size
from .threads import SynchronizedMeta
from .static_data import luks_data

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
ACTION_TYPE_CONFIGURE = 5

action_strings = {ACTION_TYPE_NONE: "None",
                  ACTION_TYPE_DESTROY: "Destroy",
                  ACTION_TYPE_RESIZE: "Resize",
                  ACTION_TYPE_CREATE: "Create",
                  ACTION_TYPE_ADD: "Add",
                  ACTION_TYPE_REMOVE: "Remove",
                  ACTION_TYPE_CONFIGURE: "Configure"}

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

    for (k, v) in action_strings.items():
        if v.lower() == type_string.lower():
            return k

    return resize_type_from_string(type_string)


def action_object_from_string(type_string):
    if type_string is None:
        return None

    for (k, v) in object_strings.items():
        if v.lower() == type_string.lower():
            return k


def resize_type_from_string(type_string):
    if type_string is None:
        return None

    for (k, v) in resize_strings.items():
        if v.lower() == type_string.lower():
            return k


@add_metaclass(SynchronizedMeta)
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
    type_desc_str = ""

    def __init__(self, device):
        util.ObjectID.__init__(self)
        if not isinstance(device, StorageDevice):
            raise ValueError("arg 1 must be a StorageDevice instance")

        self.device = device

        if self.is_device:
            self._check_device_dependencies()

        self.container = getattr(self.device, "container", None)
        self._applied = False

    def _check_device_dependencies(self):
        unavailable_dependencies = self.device.unavailable_dependencies
        if unavailable_dependencies:
            dependencies_str = ", ".join(str(d) for d in unavailable_dependencies)
            raise DependencyError("device type %s requires unavailable_dependencies: %s" % (self.device.type, dependencies_str))

    def apply(self):
        """ apply changes related to the action to the device(s) """
        self._applied = True

    def execute(self, callbacks=None):
        """
        Perform the action.

        :param callbacks: callbacks to be run when matching actions are
                          executed (see :meth:`~.blivet.Blivet.do_it`)

        """
        # pylint: disable=unused-argument
        if not self._applied:
            raise RuntimeError("cannot execute unapplied action")

        if callbacks and callbacks.report_progress:
            msg = _("Executing %(action)s") % {"action": str(self)}
            callbacks.report_progress(ReportProgressData(msg))

    def cancel(self):
        """ cancel the action """
        self._applied = False

    @property
    def is_destroy(self):
        return self.type == ACTION_TYPE_DESTROY

    @property
    def is_create(self):
        return self.type == ACTION_TYPE_CREATE

    @property
    def is_resize(self):
        return self.type == ACTION_TYPE_RESIZE

    @property
    def is_shrink(self):
        return (self.is_resize and self.dir == RESIZE_SHRINK)  # pylint: disable=no-member

    @property
    def is_grow(self):
        return (self.is_resize and self.dir == RESIZE_GROW)  # pylint: disable=no-member

    @property
    def is_add(self):
        return self.type == ACTION_TYPE_ADD

    @property
    def is_remove(self):
        return self.type == ACTION_TYPE_REMOVE

    @property
    def is_configure(self):
        return self.type == ACTION_TYPE_CONFIGURE

    @property
    def is_device(self):
        return self.obj == ACTION_OBJECT_DEVICE

    @property
    def is_container(self):
        return self.obj == ACTION_OBJECT_CONTAINER

    @property
    def is_format(self):
        return self.obj == ACTION_OBJECT_FORMAT

    @property
    def format(self):
        return self.device.format

    @property
    def type_string(self):
        """ String indicating if this action is a create, destroy or resize. """
        return action_strings[self.type]

    @property
    def object_string(self):
        """ String indicating if this action's operand is device or format. """
        return object_strings[self.obj]

    @property
    def resize_string(self):
        """ String representing the direction of a resize action. """
        s = ""
        if self.is_resize:
            s = resize_strings[self.dir]  # pylint: disable=no-member

        return s

    @property
    def object_type_string(self):
        """ String representing the type of the operand device or format. """
        if self.is_format:
            s = self.format.name
        else:
            s = self.device.type

        return s

    @property
    def type_desc(self):
        return _(self.type_desc_str)

    # Force str and unicode types since there's a good chance that the self.device.*
    # strings are unicode.
    def _to_string(self):
        s = "[%d] %s" % (self.id, self.type_desc_str)
        if self.is_resize:
            s += " (%s)" % self.resize_string
        if self.is_format:
            s += " %s on" % self.format.desc
        s += " %s %s (id %d)" % (self.device.type, self.device.name,
                                 self.device.id)
        return s

    def __str__(self):
        return util.stringize(self._to_string())

    def __unicode__(self):
        return util.unicodeize(self._to_string())

    def requires(self, action):
        """ Return True if self requires action. """
        return (not (self.is_container or action.is_container) and
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
    type_desc_str = N_("create device")

    def __init__(self, device):
        if device.exists:
            raise ValueError("device already exists")

        # FIXME: assert device.fs is None
        DeviceAction.__init__(self, device)

    def execute(self, callbacks=None):
        super(ActionCreateDevice, self).execute(callbacks=callbacks)
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
        if self.device.depends_on(action.device):
            rc = True
        elif (action.is_create and action.is_device and
              isinstance(self.device, PartitionDevice) and
              isinstance(action.device, PartitionDevice) and
              self.device.disk == action.device.disk):
            # create partitions in ascending numerical order
            self_num = self.device.parted_partition.number
            other_num = action.device.parted_partition.number
            if self_num > other_num:
                rc = True
        elif (action.is_create and action.is_device and
              isinstance(self.device, LVMLogicalVolumeDevice) and
              isinstance(action.device, LVMLogicalVolumeDevice) and
              self.device.vg == action.device.vg):
            # create cached LVs before non-cached LVs so that fast cache space
            # is not taken by non-cached LVs
            if not self.device.cached and action.device.cached:
                rc = True
            # create non-linear LVs before linear LVs because the latter ones
            # can be allocated anywhere
            elif self.device.seg_type == "linear" and action.device.seg_type != "linear":
                rc = True
        elif (action.is_add and action.container == self.container):
            rc = True

        return rc


class ActionDestroyDevice(DeviceAction):

    """ An action representing the deletion of an existing device. """
    type = ACTION_TYPE_DESTROY
    obj = ACTION_OBJECT_DEVICE
    type_desc_str = N_("destroy device")

    def __init__(self, device):
        # XXX should we insist that device.fs be None?
        DeviceAction.__init__(self, device)

    def _check_device_dependencies(self):
        if self.device.type == "btrfs volume":
            # XXX destroying a btrfs volume is a special case -- we don't destroy
            # the device, but use wipefs to destroy format on its parents so we
            # don't need btrfs plugin or btrfs-progs for this
            return

        super(ActionDestroyDevice, self)._check_device_dependencies()

    def apply(self):
        """ apply changes related to the action to the device(s) """
        if self._applied:
            return

        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation += 1

        super(ActionDestroyDevice, self).apply()

    def execute(self, callbacks=None):
        super(ActionDestroyDevice, self).execute(callbacks=callbacks)
        self.device.destroy()

    def cancel(self):
        if not self._applied:
            return

        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation -= 1

        super(ActionDestroyDevice, self).cancel()

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
        if action.device.depends_on(self.device) and action.is_destroy:
            rc = True
        elif (action.is_destroy and action.is_device and
              isinstance(self.device, PartitionDevice) and self.device.disklabel_supported and
              isinstance(action.device, PartitionDevice) and action.device.disklabel_supported and
              self.device.disk == action.device.disk):
            # remove partitions in descending numerical order
            self_num = self.device.parted_partition.number
            other_num = action.device.parted_partition.number
            if self_num < other_num:
                rc = True
        elif (action.is_destroy and action.is_format and
              action.device.id == self.device.id):
            # device destruction comes after destruction of device's format
            rc = True
        elif (action.is_remove and action.device == self.device):
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
                    not (action.is_destroy and action.is_format):
                rc = True
            elif action.is_add and (action.device == self.device):
                rc = True
        elif action.is_add and (action.container == self.device):
            rc = True

        return rc


class ActionResizeDevice(DeviceAction):

    """ An action representing the resizing of an existing device. """
    type = ACTION_TYPE_RESIZE
    obj = ACTION_OBJECT_DEVICE
    type_desc_str = N_("resize device")

    def __init__(self, device, newsize):
        if not device.resizable:
            raise ValueError("device is not resizable")

        if device.current_size == newsize:
            raise ValueError("new size same as old size")

        if newsize < device.min_size:
            raise ValueError("new size is too small")

        if device.max_size and newsize > device.max_size:
            raise ValueError("new size is too large")

        DeviceAction.__init__(self, device)
        if newsize > device.current_size:
            self.dir = RESIZE_GROW
        else:
            self.dir = RESIZE_SHRINK
        if device.target_size > Size(0):
            self.origsize = device.target_size
        else:
            self.origsize = device.size

        self._target_size = newsize

    def apply(self):
        """ apply changes related to the action to the device(s) """
        if self._applied:
            return

        self.device.target_size = self._target_size
        super(ActionResizeDevice, self).apply()

    def execute(self, callbacks=None):
        super(ActionResizeDevice, self).execute(callbacks=callbacks)
        self.device.resize()

    def cancel(self):
        if not self._applied:
            return

        self.device.target_size = self.origsize
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
                - this action is a grow action and the other action is a shrink
                  action and the two actions' respective devices share one or more
                  ancestors
                - the other action removes this action's device from a container
                - the other action adds a member to this device's container
        """
        retval = super(ActionResizeDevice, self).requires(action)
        if action.is_resize:
            if self.device.id == action.device.id and \
               self.dir == action.dir and \
               action.is_format and self.is_shrink:
                retval = True
            elif action.is_grow and self.device.depends_on(action.device):
                retval = True
            elif action.is_shrink and action.device.depends_on(self.device):
                retval = True
            elif self.is_grow and action.is_shrink and \
                    set(self.device.ancestors).intersection(set(action.device.ancestors)):
                return True
        elif (action.is_remove and action.device == self.device):
            retval = True
        elif (action.is_add and action.container == self.container):
            retval = True

        return retval


class ActionCreateFormat(DeviceAction):

    """ An action representing creation of a new filesystem. """
    type = ACTION_TYPE_CREATE
    obj = ACTION_OBJECT_FORMAT
    type_desc_str = N_("create format")

    def __init__(self, device, fmt=None):
        """
            :param device: the device on which the format will be created
            :type device: :class:`~.devices.StorageDevice`
            :keyword fmt: the format to put on the device
            :type fmt: :class:~.formats.DeviceFormat`

            If no format is specified, it is assumed that the format is already
            associated with the device.
        """
        if device.format_immutable:
            raise ValueError("this device's formatting cannot be modified")

        DeviceAction.__init__(self, device)
        if fmt:
            self.orig_format = device.format
        else:
            self.orig_format = get_format(None)

        self._format = fmt or device.format

        if self._format.exists:
            raise ValueError("specified format already exists")

        if not self._format.formattable:
            raise ValueError("resource to create this format %s is unavailable" % self._format.type)

    def apply(self):
        """ apply changes related to the action to the device(s) """
        if self._applied:
            return

        self.device.format = self._format
        super(ActionCreateFormat, self).apply()

    def execute(self, callbacks=None):
        super(ActionCreateFormat, self).execute(callbacks=callbacks)
        if callbacks and callbacks.create_format_pre:
            msg = _("Creating %(type)s on %(device)s") % {"type": self.device.format.type, "device": self.device.path}
            callbacks.create_format_pre(CreateFormatPreData(msg))

        if isinstance(self.device, PartitionDevice) and self.device.disklabel_supported:
            for flag in partitionFlag.keys():
                # Keep the LBA flag on pre-existing partitions
                if flag in [PARTITION_LBA, self.format.parted_flag]:
                    continue
                self.device.unset_flag(flag)

            if self.format.parted_flag is not None:
                self.device.set_flag(self.format.parted_flag)

            if self.format.parted_system is not None:
                self.device.parted_partition.system = self.format.parted_system

            self.device.disk.format.commit_to_disk()
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
                    luks_data.min_entropy = 0

        self.device.setup()
        self.device.format.create(device=self.device.path,
                                  options=self.device.format_args)

        # Get the UUID now that the format is created
        udev.settle()
        self.device.update_sysfs_path()
        info = udev.get_device(self.device.sysfs_path)
        # only do this if the format has a device known to udev
        # (the format might not have a normal device at all)
        if info:
            if self.device.format.type != "btrfs":
                self.device.format.uuid = udev.device_get_uuid(info)
            self.device.device_links = udev.device_get_symlinks(info)
        elif self.device.format.type != "tmpfs":
            # udev lookup failing is a serious issue for anything other than tmpfs
            log.error("udev lookup failed for device: %s", self.device)

        if callbacks and callbacks.create_format_post:
            msg = _("Created %(type)s on %(device)s") % {"type": self.device.format.type, "device": self.device.path}
            callbacks.create_format_post(CreateFormatPostData(msg))

        self.device.original_format = copy.deepcopy(self.device.format)

    def cancel(self):
        if not self._applied:
            return

        self.device.format = self.orig_format
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
                (self.device.depends_on(action.device) and
                 not ((action.is_destroy and action.is_device) or
                      action.is_container)) or
                (action.is_device and (action.is_create or action.is_resize) and
                 self.device.id == action.device.id))

    def obsoletes(self, action):
        """ Return True if this action obsoletes action.

            Format create actions obsolete the following actions:

                - format actions w/ lower id on this action's device, other
                  than those that destroy existing formats
        """
        return (self.device.id == action.device.id and
                self.obj == action.obj and
                not (action.is_destroy and action.format.exists) and
                self.id > action.id)


class ActionDestroyFormat(DeviceAction):

    """ An action representing the removal of an existing filesystem. """
    type = ACTION_TYPE_DESTROY
    obj = ACTION_OBJECT_FORMAT
    type_desc_str = N_("destroy format")

    def __init__(self, device):
        if device.format_immutable:
            raise ValueError("this device's formatting cannot be modified")

        DeviceAction.__init__(self, device)
        self.orig_format = self.device.format

        if not device.format.destroyable:
            raise ValueError("resource to destroy this format type %s is unavailable" % device.format.type)

    def apply(self):
        if self._applied:
            return

        self.device.format = None
        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation += 1

        super(ActionDestroyFormat, self).apply()

    def execute(self, callbacks=None):
        """ wipe the filesystem signature from the device """
        # remove any flag if set
        super(ActionDestroyFormat, self).execute(callbacks=callbacks)
        status = self.device.status
        self.device.setup(orig=True)
        if hasattr(self.device, 'set_rw'):
            self.device.set_rw()

        self.format.destroy()
        udev.settle()
        if isinstance(self.device, PartitionDevice) and self.device.disklabel_supported:
            if self.format.parted_flag:
                self.device.unset_flag(self.format.parted_flag)
            self.device.disk.original_format.commit_to_disk()
            udev.settle()

        if not status:
            self.device.teardown()

    def cancel(self):
        if not self._applied:
            return

        self.device.format = self.orig_format
        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation -= 1
        super(ActionDestroyFormat, self).cancel()

    @property
    def format(self):
        return self.orig_format

    def requires(self, action):
        """ Return True if self requires action.

            Format destroy actions require other actions when:

                - the other action's device depends on this action's device
                  and the other action is a destroy action
                - the other action removes this action's device from a container
        """
        retval = super(ActionDestroyFormat, self).requires(action)
        if action.device.depends_on(self.device) and action.is_destroy:
            retval = True
        elif (action.is_remove and action.device == self.device):
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
            if action.is_destroy:
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
    type_desc_str = N_("resize format")

    def __init__(self, device, newsize):
        if device.format_immutable:
            raise ValueError("this device's formatting cannot be modified")

        if not device.format.resizable:
            raise ValueError("format is not resizable")

        if device.format.current_size == newsize:
            raise ValueError("new size same as old size")

        DeviceAction.__init__(self, device)
        if newsize > device.format.current_size:
            self.dir = RESIZE_GROW
        else:
            self.dir = RESIZE_SHRINK

        if device.format.target_size > Size(0):
            self.orig_size = device.format.target_size
        # no target_size -- original size for device was its current_size
        else:
            self.orig_size = device.format.current_size

        self._target_size = newsize

    def apply(self):
        if self._applied:
            return

        self.device.format.target_size = self._target_size
        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation += 1

        super(ActionResizeFormat, self).apply()

    def execute(self, callbacks=None):
        super(ActionResizeFormat, self).execute(callbacks=callbacks)
        if callbacks and callbacks.resize_format_pre:
            msg = _("Resizing filesystem on %(device)s") % {"device": self.device.path}
            callbacks.resize_format_pre(ResizeFormatPreData(msg))

        self.device.setup(orig=True)
        self.device.format.do_resize()

        if callbacks and callbacks.resize_format_post:
            msg = _("Resized filesystem on %(device)s") % {"device": self.device.path}
            callbacks.resize_format_post(ResizeFormatPostData(msg))

    def cancel(self):
        if not self._applied:
            return

        self.device.format.target_size = self.orig_size
        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation -= 1

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
        if action.is_resize:
            if self.device.id == action.device.id and \
               self.dir == action.dir and \
               action.is_device and self.is_grow:
                retval = True
            elif action.is_shrink and action.device.depends_on(self.device):
                retval = True
            elif action.is_grow and self.device.depends_on(action.device):
                retval = True
        elif (action.is_remove and action.device == self.device):
            retval = True

        return retval


class ActionAddMember(DeviceAction):

    """ An action representing addition of a member device to a container. """
    type = ACTION_TYPE_ADD
    obj = ACTION_OBJECT_CONTAINER
    type_desc_str = N_("add container member")

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
        super(ActionAddMember, self).execute(callbacks=callbacks)
        self.container.add(self.device)

    def requires(self, action):
        """
            requires
                - create/resize the same device

            required by
                - any create/grow action on a device in the same container
        """
        return ((action.is_create or action.is_resize) and
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
        if (action.is_remove and
                action.device == self.device and
                action.container == self.container):
            retval = True
        elif (action.is_add and
              action.device == self.device and
              action.container == self.container and
              action.id > self.id):
            retval = True

        return retval


class ActionRemoveMember(DeviceAction):

    """ An action representing removal of a member device from a container. """
    type = ACTION_TYPE_REMOVE
    obj = ACTION_OBJECT_CONTAINER
    type_desc_str = N_("remove container member")

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
        super(ActionRemoveMember, self).execute(callbacks=callbacks)
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
        if ((action.is_shrink or action.is_destroy) and
                action.device.container == self.container):
            retval = True
        elif action.is_add and action.container == self.container:
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
        if (action.is_add and
                action.device == self.device and
                action.container == self.container):
            retval = True
        elif (action.is_remove and
              action.device == self.device and
              action.container == self.container and
              action.id > self.id):
            retval = True

        return retval


class ActionConfigureFormat(DeviceAction):

    """ An action change of an attribute of device format """
    type = ACTION_TYPE_CONFIGURE
    obj = ACTION_OBJECT_FORMAT
    type_desc_str = N_("configure format")

    def __init__(self, device, attr, new_value):
        super(ActionConfigureFormat, self).__init__(device)

        self.device = device
        self.attr = attr
        self.new_value = new_value

        config_actions_map = getattr(self.device.format, "config_actions_map", None)
        if config_actions_map is None or self.attr not in config_actions_map.keys():
            raise ValueError("Format %s doesn't support changing '%s' attribute "
                             "using configuration actions" % (self.device.format.type, self.attr))

        if config_actions_map[self.attr] is None:
            self._execute = None
        else:
            self._execute = getattr(self.device.format, config_actions_map[self.attr], None)
            if not callable(self._execute):
                raise RuntimeError("Invalid method for changing format attribute '%s'" % self.attr)

        self.old_value = getattr(self.device.format, self.attr)

        if self._execute:
            self._execute(dry_run=True)

    def apply(self):
        if self._applied:
            return

        setattr(self.device.format, self.attr, self.new_value)
        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation += 1

        super(ActionConfigureFormat, self).apply()

    def cancel(self):
        if not self._applied:
            return

        setattr(self.device.format, self.attr, self.old_value)
        if hasattr(self.device, 'ignore_skip_activation'):
            self.device.ignore_skip_activation -= 1

    def execute(self, callbacks=None):
        super(ActionConfigureFormat, self).execute(callbacks=callbacks)

        if self._execute is not None:
            self._execute(dry_run=False)


class ActionConfigureDevice(DeviceAction):

    """ An action change of an attribute of a device """
    type = ACTION_TYPE_CONFIGURE
    obj = ACTION_OBJECT_FORMAT
    type_desc_str = N_("configure device")

    def __init__(self, device, attr, new_value):
        super(ActionConfigureDevice, self).__init__(device)

        self.device = device
        self.attr = attr
        self.new_value = new_value

        config_actions_map = getattr(self.device, "config_actions_map", None)
        if config_actions_map is None or self.attr not in config_actions_map.keys():
            raise ValueError("Device %s doesn't support changing '%s' attribute "
                             "using configuration actions" % (self.device.type, self.attr))

        if config_actions_map[self.attr] is None:
            self._execute = None
        else:
            self._execute = getattr(self.device, config_actions_map[self.attr], None)
            if not callable(self._execute):
                raise RuntimeError("Invalid method for changing attribute '%s'" % self.attr)

        self.old_value = getattr(self.device, self.attr)

        if self._execute:
            self._execute(dry_run=True)

    def apply(self):
        if self._applied:
            return

        setattr(self.device, self.attr, self.new_value)
        super(ActionConfigureDevice, self).apply()

    def cancel(self):
        if not self._applied:
            return

        setattr(self.device, self.attr, self.old_value)

    def execute(self, callbacks=None):
        super(ActionConfigureDevice, self).execute(callbacks=callbacks)

        if self._execute is not None:
            self._execute(dry_run=False)
