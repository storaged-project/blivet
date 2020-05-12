# devices/storage.py
# Base class for block device classes.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

import os
import copy
import pyudev

from ..callbacks import callbacks
from .. import errors
from .. import util
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..formats import get_format, DeviceFormat
from ..size import Size

import logging
log = logging.getLogger("blivet")

from .device import Device
from .network import NetworkStorageDevice
from .lib import LINUX_SECTOR_SIZE
from ..devicelibs.crypto import LUKS_METADATA_SIZE


class StorageDevice(Device):

    """ A generic storage device.

        A fully qualified path to the device node can be obtained via the
        path attribute, although it is not guaranteed to be useful, or
        even present, unless the StorageDevice's setup method has been
        run.
    """
    _resizable = False
    """Whether this type of device is inherently resizable."""

    _type = "blivet"
    _dev_dir = "/dev"
    _format_immutable = False
    _partitionable = False
    _is_disk = False
    _encrypted = False

    def __init__(self, name, fmt=None, uuid=None,
                 size=None, major=None, minor=None,
                 sysfs_path='', parents=None, exists=False, serial=None,
                 vendor="", model="", bus=""):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword uuid: universally unique identifier (device -- not fs)
            :type uuid: str
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword major: the device major
            :type major: int
            :keyword minor: the device minor
            :type minor: int
            :keyword serial: the ID_SERIAL_SHORT for this device
            :type serial: str
            :keyword vendor: the manufacturer of this Device
            :type vendor: str
            :keyword model: manufacturer's device model string
            :type model: str
            :keyword bus: the interconnect this device uses
            :type bus: str

        """
        # allow specification of individual parents
        if isinstance(parents, Device):
            parents = [parents]

        self.exists = exists
        self.uuid = uuid

        # Set sysfs path before super call as MDRaidArrayDevice._add_parent()
        # reads it via status().
        self.sysfs_path = sysfs_path

        self._format = get_format(None)

        # For non-existent devices, make sure the initial size is enough for
        # the format's metadata. This is mostly relevant for growable
        # partitions and lvs with thoughtless initial sizes.
        if not self.exists and fmt and fmt.min_size:
            min_size = max(util.numeric_type(size), fmt.min_size)
            if min_size > util.numeric_type(size):
                log.info("%s: using size %s instead of %s to accommodate "
                         "format minimum size", name, min_size, size)
                size = min_size

        # The size will be overridden by a call to update_size at the end of this
        # method for existing and active devices.
        self._size = Size(util.numeric_type(size))
        self._target_size = self._size
        self._current_size = self._size if self.exists else Size(0)
        self.major = util.numeric_type(major)
        self.minor = util.numeric_type(minor)
        self._serial = serial
        self._vendor = vendor or ""
        self._model = model or ""
        self.bus = bus

        self._readonly = False
        self._protected = False
        self._controllable = True

        # Copy only the validity check from Device._set_name() so we don't try
        # to check a bunch of inappropriate state properties during
        # __init__ in subclasses
        # Has to be here because Device does not have exists attribute
        if not self.exists and not self.is_name_valid(name):
            raise ValueError("%s is not a valid name for this device" % name)
        super(StorageDevice, self).__init__(name, parents=parents)

        self.format = fmt
        self.original_format = copy.deepcopy(self.format)
        self.fstab_comment = ""

        self.device_links = []

        if self.exists:
            if self.status:
                self.update_sysfs_path()
                self.update_size()

    def __str__(self):
        exist = "existing"
        if not self.exists:
            exist = "non-existent"
        s = "%s %s %s" % (exist, self.size, super(StorageDevice, self).__str__())
        if self.format.type:
            s += " with %s" % self.format

        return s

    @property
    def packages(self):
        packages = super(StorageDevice, self).packages
        packages.extend(p for p in self.format.packages if p not in packages)
        return packages

    @property
    def disks(self):
        """ A list of all disks this device depends on, including itself. """
        _disks = []
        for parent in self.parents:
            _disks.extend(d for d in parent.disks if d not in _disks)

        if self.is_disk and not self.format.hidden:
            _disks.append(self)

        return _disks

    @property
    def encrypted(self):
        """ True if this device, or any it requires, is encrypted. """
        return self._encrypted or any(p.encrypted for p in self.parents)

    @property
    def raw_device(self):
        """ The device itself, or when encrypted, the backing device. """
        return self

    @property
    def sector_size(self):
        """ Logical sector (block) size of this device """
        if not self.exists:
            if self.parents:
                return self.parents[0].sector_size
            else:
                return LINUX_SECTOR_SIZE

        block_size = util.get_sysfs_attr(self.sysfs_path, "queue/logical_block_size")
        if block_size:
            return int(block_size)
        else:
            return LINUX_SECTOR_SIZE

    @property
    def controllable(self):
        return self._controllable and not flags.testing and not self.unavailable_type_dependencies()

    @controllable.setter
    def controllable(self, value):
        self._controllable = value

    def _set_name(self, value):
        """Set the device's name.

        :param value: the new device name
        :raises errors.DeviceError: if the device exists
        """

        if value == self._name:
            return

        super(StorageDevice, self)._set_name(value)

        # update our format's path
        # First, check that self._format has been defined in case this is
        # running early in the constructor.
        if hasattr(self, "_format") and self.format.device:
            self.format.device = self.path

    def align_target_size(self, newsize):
        """ Return a proposed target size adjusted for device specifics.

            :param :class:`~.Size` newsize: the proposed/unaligned target size
            :returns: newsize modified to yield an aligned device
            :rtype: :class:`~.Size`
        """

        return newsize

    def _get_target_size(self):
        return self._target_size

    def _set_target_size(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if self.max_size and newsize > self.max_size:
            log.error("requested size %s is larger than maximum %s",
                      newsize, self.max_size)
            raise ValueError("size is larger than the maximum for this device")
        elif self.min_size and newsize < self.min_size:
            log.error("requested size %s is smaller than minimum %s",
                      newsize, self.min_size)
            raise ValueError("size is smaller than the minimum for this device")

        if self.align_target_size(newsize) != newsize:
            raise ValueError("new size would violate alignment requirements")

        self._target_size = newsize

    target_size = property(lambda s: s._get_target_size(),
                           lambda s, v: s._set_target_size(v),
                           doc="Target size of this device")

    def __repr__(self):
        s = Device.__repr__(self)
        s += ("  uuid = %(uuid)s  size = %(size)s\n"
              "  format = %(format)s\n"
              "  major = %(major)s  minor = %(minor)s  exists = %(exists)s"
              "  protected = %(protected)s\n"
              "  sysfs path = %(sysfs)s\n"
              "  target size = %(target_size)s  path = %(path)s\n"
              "  format args = %(format_args)s  original_format = %(orig_fmt)s" %
              {"uuid": self.uuid, "format": self.format, "size": self.size,
               "major": self.major, "minor": self.minor, "exists": self.exists,
               "sysfs": self.sysfs_path,
               "target_size": self.target_size, "path": self.path,
               "protected": self.protected,
               "format_args": self.format_args, "orig_fmt": self.original_format.type})
        return s

    @property
    def dict(self):
        d = super(StorageDevice, self).dict
        d.update({"uuid": self.uuid, "size": self.size,
                  "format": self.format.dict, "removable": self.removable,
                  "major": self.major, "minor": self.minor,
                  "exists": self.exists, "sysfs": self.sysfs_path,
                  "target_size": self.target_size, "path": self.path})
        return d

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._dev_dir, self.name)

    def update_sysfs_path(self):
        """ Update this device's sysfs path. """
        # We're using os.path.exists as a stand-in for status. We can't use
        # the status property directly because MDRaidArrayDevice.status calls
        # this method.
        log_method_call(self, self.name, status=os.path.exists(self.path))
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        try:
            udev_device = pyudev.Devices.from_device_file(udev.global_udev,
                                                          self.path)

        # from_device_file() does not process exceptions but just propagates
        # any errors that are raised.
        except (pyudev.DeviceNotFoundError, EnvironmentError, ValueError, OSError) as e:
            log.error("failed to update sysfs path for %s: %s", self.name, e)
            self.sysfs_path = ''
        else:
            self.sysfs_path = udev_device.sys_path
            log.debug("%s sysfs_path set to %s", self.name, self.sysfs_path)

    @property
    def format_args(self):
        """ Device-specific arguments to format creation program. """
        return []

    @property
    def resizable(self):
        """ Can this device be resized? """
        return (self._resizable and self.exists and
                (self.format.resizable or not self.format.exists))

    @property
    def fstab_spec(self):
        spec = self.path
        if self.format and self.format.uuid:
            spec = "UUID=%s" % self.format.uuid
        return spec

    def resize(self):
        """ Resize a device to self.target_size.

            This method should only be invoked via the
            ActionResizeDevice.execute method. All the pre-conditions
            enforced by ActionResizeDevice.__init__ are assumed to hold.

            Returns nothing.
        """
        if self._resizable:
            raise NotImplementedError("method not implemented for device type %s" % self.type)
        else:
            raise errors.DeviceError("device type %s is not resizable" % self.type)

    @property
    def readonly(self):
        # A device is read-only if it or any parent device is read-only
        return self._readonly or any(p.readonly for p in self.parents)

    @readonly.setter
    def readonly(self, value):
        self._readonly = value

    @property
    def protected(self):
        return self.readonly or self._protected

    @protected.setter
    def protected(self, value):
        self._protected = value

    #
    # setup
    #
    def _pre_setup(self, orig=False):
        """ Preparation and pre-condition checking for device setup.

            Return True if setup should proceed or False if not.
        """
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if self.status or not self.controllable:
            return False

        self.setup_parents(orig=orig)
        return True

    def _setup(self, orig=False):
        """ Perform device-specific setup operations. """

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        if not self._pre_setup(orig=orig):
            return

        self._setup(orig=orig)
        self._post_setup()

    def _post_setup(self):
        """ Perform post-setup operations. """
        udev.settle()
        self.update_sysfs_path()
        # the device may not be set up when we want information about it
        if self._size == Size(0):
            self.update_size()

    #
    # teardown
    #
    def _pre_teardown(self, recursive=None):
        """ Preparation and pre-condition checking for device teardown.

            Return True if teardown should proceed or False if not.
        """
        if not self.exists and not recursive:
            raise errors.DeviceError("device has not been created", self.name)

        if not self.status or not self.controllable or self.protected:
            return False

        if self.original_format.exists:
            self.original_format.teardown()
        if self.format.exists:
            self.format.teardown()
        udev.settle()
        return True

    def _teardown(self, recursive=None):
        """ Perform device-specific teardown operations. """

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._pre_teardown(recursive=recursive):
            if recursive:
                self.teardown_parents(recursive=recursive)
            return

        self._teardown(recursive=recursive)
        self._post_teardown(recursive=recursive)

    def _post_teardown(self, recursive=None):
        """ Perform post-teardown operations. """
        if recursive:
            self.teardown_parents(recursive=recursive)

    #
    # create
    #
    def _pre_create(self):
        """ Preparation and pre-condition checking for device creation. """
        if self.exists:
            raise errors.DeviceError("device has already been created", self.name)

        self.setup_parents()

    def _create(self):
        """ Perform device-specific create operations. """

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self._pre_create()
        self._create()
        self._post_create()

    def _post_create(self):
        """ Perform post-create operations. """
        self.exists = True
        self.setup()
        self.update_sysfs_path()
        udev.settle()

        # make sure that target_size is updated to reflect the actual size
        self.update_size()

        self._update_netdev_mount_option()

    #
    # destroy
    #
    def _pre_destroy(self):
        """ Preparation and precondition checking for device destruction. """
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if not self.isleaf:
            raise errors.DeviceError("Cannot destroy non-leaf device", self.name)

        self.teardown()

    def _destroy(self):
        """ Perform device-specific destruction operations. """

    def destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        self._pre_destroy()
        self._destroy()
        self._post_destroy()

    def _post_destroy(self):
        """ Perform post-destruction operations. """
        self.exists = False

    #
    # parents' modifications/notifications
    #
    def setup_parents(self, orig=False):
        """ Run setup method of all parent devices. """
        log_method_call(self, name=self.name, orig=orig)
        for parent in self.parents:
            parent.setup(orig=orig)
            if orig:
                _format = parent.original_format
            else:
                _format = parent.format

            # set up the formatting, if present
            if _format.type and _format.exists:
                _format.setup()

    # pylint: disable=unused-argument
    def remove_hook(self, modparent=True):
        """ Perform actions related to removing a device from the devicetree.

            :keyword bool modparent: whether to account for removal in parents

            Parents' list of child devices is updated regardless of modparent.
            The intended use of modparent is to prevent doing things like
            removing a parted.Partition from the disk that contains it as part
            of msdos extended partition management. In general, you should not
            override the default value of modparent in new code.
        """
        for parent in self.parents:
            parent.remove_child(self)

    def add_hook(self, new=True):
        """ Perform actions related to adding a device to the devicetree.

            :keyword bool new: whether this device is new to the devicetree

            The only intended use case for new=False is when unhiding a device
            from the devicetree. Additional operations are performed when new is
            False that are normally performed as part of the device constructor.
        """
        if not new:
            for p in self.parents:
                p.add_child(self)

    #
    # size manipulations
    #
    def _get_size(self):
        """ Get the device's size, accounting for pending changes. """
        size = self._size
        if self.exists and self.resizable and self.target_size != Size(0):
            size = self.target_size

        return size

    def _set_size(self, newsize):
        """ Set the device's size to a new value.

            This is not adequate to set up a resize as it does not set a new
            target size for the device.
        """
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        # There's no point in checking limits here for existing devices since
        # the only way to change their size is by setting target size. Any call
        # to this setter for an existing device should be to reflect existing
        # state.
        if not self.exists:
            max_size = self.format.max_size
            min_size = self.format.min_size
            if max_size and newsize > max_size:
                raise errors.DeviceError("device cannot be larger than %s" %
                                         max_size, self.name)
            elif min_size and newsize < min_size:
                raise errors.DeviceError("device cannot be smaller than %s" %
                                         min_size, self.name)

        self._size = newsize

    size = property(lambda x: x._get_size(),
                    lambda x, y: x._set_size(y),
                    doc="The device's size, accounting for pending changes")

    def read_current_size(self):
        log_method_call(self, exists=self.exists, path=self.path,
                        sysfs_path=self.sysfs_path)
        size = Size(0)
        if self.exists and os.path.exists(self.path) and \
           os.path.isdir(self.sysfs_path):
            blocks = int(util.get_sysfs_attr(self.sysfs_path, "size") or '0')
            size = Size(blocks * LINUX_SECTOR_SIZE)

        return size

    @property
    def current_size(self):
        """ The device's actual size, generally the size discovered by using
            system tools. May use a cached value if the information is
            currently unavailable.

            If the device does not exist, then the actual size is 0.
        """
        if self._current_size == Size(0):
            self._current_size = self.read_current_size()
        return self._current_size

    def update_size(self, newsize=None):
        """ Update size, current_size, and target_size to actual size.

            :keyword :class:`~.size.Size` newsize: new size for device

            .. note::

                Most callers will not pass a new size. It is for special cases
                like outside resize of inactive LVs, which precludes updating
                the size from /sys.
        """
        if newsize is None:
            self._current_size = Size(0)
        elif isinstance(newsize, Size):
            self._current_size = newsize
        else:
            raise ValueError("new size must be an instance of class Size")

        new_size = self.current_size
        self._size = new_size
        self._target_size = new_size  # bypass setter checks
        log.debug("updated %s size to %s (%s)", self.name, self.size, new_size)

    @property
    def min_size(self):
        """ The minimum size this device can be. """
        if self.format.type == "luks" and self.children:
            if self.resizable:
                min_size = self.children[0].min_size + LUKS_METADATA_SIZE
            else:
                min_size = self.current_size
        else:
            min_size = self.align_target_size(self.format.min_size) if self.resizable else self.current_size

        return min_size

    @property
    def max_size(self):
        """ The maximum size this device can be. """
        return self.align_target_size(self.format.max_size) if self.resizable else self.current_size

    @property
    def growable(self):
        """ True if this device or its component devices are growable. """
        return getattr(self, "req_grow", False) or any(p.growable for p in self.parents)

    def check_size(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.max_size and self.size > self.format.max_size:
            return 1
        elif self.format.min_size and self.size < self.format.min_size:
            return -1
        return 0

    #
    # status
    #
    @property
    def media_present(self):
        """ True if this device contains usable media. """
        return True

    @property
    def status(self):
        """ This device's status.

            For now, this should return a boolean:
                True    the device is open and ready for use
                False   the device is not open
        """
        if not self.exists:
            return False
        return os.access(self.path, os.W_OK)

    #
    # format manipulations
    #
    def _set_format(self, fmt):
        """ Set the Device's format.

            :param fmt: the new format or None
            :type fmt: :class:`~.formats.DeviceFormat` or NoneType

            A value of None will effectively mark the device as unformatted,
            but this is accomplished by setting it to an instance of the base
            :class:`~.formats.DeviceFormat` class.

            .. note::
                :attr:`format` should always be an instance of
                :class:`~.formats.DeviceFormat`. To ensure this continues to be
                the case, all subclasses that define their own :attr:`format`
                setter should call :meth:`StorageDevice._set_format` from their
                setter.

        """
        if not fmt:
            fmt = get_format(None, device=self.path, exists=self.exists)

        if not isinstance(fmt, DeviceFormat):
            raise ValueError("format must be a DeviceFormat instance")

        log_method_call(self, self.name, type=fmt.type,
                        current=getattr(self._format, "type", None))

        # check device size against format limits
        if not fmt.exists:
            if fmt.max_size and fmt.max_size < self.size:
                raise errors.DeviceError("device is too large for new format")
            elif fmt.min_size and fmt.min_size > self.size:
                if self.growable:
                    log.info("%s: using size %s instead of %s to accommodate "
                             "format minimum size", self.name, fmt.min_size, self.size)
                    self.size = fmt.min_size
                else:
                    raise errors.DeviceError("device is too small for new format")

        if self._format != fmt:
            callbacks.format_removed(device=self, fmt=self._format)
            self._format = fmt
            self._format.device = self.path
            self._update_netdev_mount_option()
            callbacks.format_added(device=self, fmt=self._format)

    def _update_netdev_mount_option(self):
        """ Fix mount options to include or exclude _netdev as appropriate. """
        if not hasattr(self._format, "mountpoint"):
            return

        netdev_option = "_netdev"
        option_list = self._format.options.split(",")
        user_options = self._format._user_mountopts.split(",")
        is_netdev = any(isinstance(a, NetworkStorageDevice)
                        for a in self.ancestors)
        has_netdev_option = netdev_option in option_list
        if not is_netdev and has_netdev_option and netdev_option not in user_options:
            option_list.remove(netdev_option)
            self._format.options = ",".join(option_list)
        elif is_netdev and not has_netdev_option:
            option_list.append(netdev_option)
            self._format.options = ",".join(option_list)

    def _get_format(self):
        """ Get the device's format instance.

            :returns: this device's format instance
            :rtype: :class:`~.formats.DeviceFormat`

            .. note::
                :attr:`format` should always be an instance of
                :class:`~.formats.DeviceFormat`. Under no circumstances should
                a programmer directly set :attr:`_format` to any other type.

        """
        return self._format

    format = property(lambda d: d._get_format(),
                      lambda d, f: d._set_format(f),
                      doc="The device's formatting.")

    def pre_commit_fixup(self, current_fmt=False):
        """ Do any necessary pre-commit fixups."""

    @property
    def format_immutable(self):
        """ Is it possible to execute format actions on this device? """
        return self._format_immutable or self.protected

    #
    # misc properties
    #
    @property
    def removable(self):
        devpath = os.path.normpath(self.sysfs_path)
        remfile = os.path.normpath("%s/removable" % devpath)
        return (self.sysfs_path and os.path.exists(devpath) and
                os.access(remfile, os.R_OK) and
                open(remfile).readline().strip() == "1")

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return self.isleaf

    @property
    def is_disk(self):
        return self._is_disk

    @property
    def is_empty(self):
        if not self.partitioned:
            return self.format.type is None and len(self.children) == 0

        return all(p.type == "partition" and p.is_magic for p in self.children)

    @property
    def partitionable(self):
        return self._partitionable

    @property
    def partitioned(self):
        return self.format.type == "disklabel" and self.partitionable

    @property
    def serial(self):
        return self._serial

    @property
    def model(self):
        return self._model

    @property
    def vendor(self):
        return self._vendor

    def populate_ksdata(self, data):
        # the common pieces are basically the formatting
        self.format.populate_ksdata(data)

        # this is a little bit of a hack for container member devices that
        # need aliases, but even more of a hack for btrfs since you cannot tell
        # from inside the BTRFS class whether you're dealing with a member or a
        # volume/subvolume
        if self.format.type == "btrfs" and not self.type.startswith("btrfs"):
            data.mountpoint = "btrfs."  # continued below, also for lvm, raid

        if data.mountpoint.endswith("."):
            data.mountpoint += str(self.id)

    def is_name_valid(self, name):
        # This device corresponds to a file in /dev, so no /'s or nulls,
        # and the name cannot be . or ..

        # ...except some names *do* contain directory components, for this
        # is an imperfect world of joy and sorrow mingled. For cciss, split
        # the path into its components and do the real check on each piece
        if name.startswith("cciss/"):
            return all(self.is_name_valid(n) for n in name.split('/'))

        badchars = any(c in ('\x00', '/') for c in name)
        return not(badchars or name == '.' or name == '..')
