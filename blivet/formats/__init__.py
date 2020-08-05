
# __init__.py
# Entry point for anaconda storage formats subpackage.
#
# Copyright (C) 2009  Red Hat, Inc.
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

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import os
import importlib
from six import add_metaclass

from .. import udev
from ..util import get_sysfs_path_by_name
from ..util import run_program
from ..util import ObjectID
from ..storage_log import log_method_call
from ..errors import DeviceFormatError, FormatCreateError, FormatDestroyError, FormatSetupError
from ..i18n import N_
from ..size import Size, ROUND_DOWN, unit_str
from ..threads import SynchronizedMeta
from ..flags import flags

from ..errors import FSError, FSResizeError, LUKSError, FormatResizeError

from ..tasks import fsinfo
from ..tasks import fsresize
from ..tasks import fssize
from ..tasks import fsck
from ..tasks import fsminsize

import logging
log = logging.getLogger("blivet")

device_formats = {}


def register_device_format(fmt_class):
    if not issubclass(fmt_class, DeviceFormat):
        raise ValueError("arg1 must be a subclass of DeviceFormat")

    device_formats[fmt_class._type] = fmt_class
    log.debug("registered device format class %s as %s", fmt_class.__name__,
              fmt_class._type)


default_fstypes = ("ext4", "xfs", "ext3", "ext2")


def get_default_filesystem_type():
    for fstype in default_fstypes:
        try:
            supported = get_format(fstype).supported
        except AttributeError:
            supported = False

        if supported:
            return fstype

    raise DeviceFormatError("None of %s is supported by your kernel" % ",".join(default_fstypes))


def get_format(fmt_type, *args, **kwargs):
    """ Return an instance of the appropriate DeviceFormat class.

        :param fmt_type: The name of the formatting type
        :type fmt_type: str.
        :return: the format instance
        :rtype: :class:`DeviceFormat`
        :raises: ValueError

        .. note::

            Any additional arguments will be passed on to the constructor for
            the format class. See the various :class:`DeviceFormat` subclasses
            for an exhaustive list of the arguments that can be passed.
    """
    fmt_class = get_device_format_class(fmt_type)
    if not fmt_class:
        fmt_class = DeviceFormat
    fmt = fmt_class(*args, **kwargs)

    # this allows us to store the given type for formats we implement as
    # DeviceFormat.
    if fmt_type and fmt.type is None:
        # unknown type, but we can set the name of the format
        # this should add/set an instance attribute
        fmt._name = fmt_type

    log.debug("get_format('%s') returning %s instance with object id %d",
              fmt_type, fmt.__class__.__name__, fmt.id)
    return fmt


def get_device_format_class(fmt_type):
    """ Return an appropriate format class.

        :param fmt_type: The name of the format type.
        :type fmt_type: str.
        :returns: The chosen DeviceFormat class
        :rtype: class.

        Returns None if no class is found for fmt_type.
    """
    fmt = device_formats.get(fmt_type)
    if not fmt:
        for fmt_class in device_formats.values():
            if fmt_type and fmt_type == fmt_class._name:
                fmt = fmt_class
                break
            elif fmt_type in fmt_class._udev_types:
                fmt = fmt_class
                break

    return fmt


@add_metaclass(SynchronizedMeta)
class DeviceFormat(ObjectID):

    """ Generic device format.

        This represents the absence of recognized formatting. That could mean a
        device is uninitialized, has had zeros written to it, or contains some
        valid formatting that this module does not support.
    """
    _type = None
    _name = N_("Unknown")
    _udev_types = []
    parted_flag = None
    parted_system = None
    _formattable = False                # can be formatted
    _supported = False                  # is supported
    _linux_native = False                # for clearpart
    _packages = []                      # required packages
    _resizable = False                  # can be resized
    _max_size = Size(0)                  # maximum size
    _min_size = Size(0)                  # minimum size
    _dump = False
    _check = False
    _hidden = False                     # hide devices with this formatting?
    _ks_mountpoint = None

    _resize_class = fsresize.UnimplementedFSResize
    _size_info_class = fssize.UnimplementedFSSize
    _info_class = fsinfo.UnimplementedFSInfo
    _minsize_class = fsminsize.UnimplementedFSMinSize

    def __init__(self, **kwargs):
        """
            :keyword device: The path to the device node.
            :type device: str
            :keyword uuid: the formatting's UUID.
            :type uuid: str
            :keyword exists: Whether the formatting exists. (default: False)
            :raises: ValueError

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.
        """
        ObjectID.__init__(self)
        self._label = None
        self._options = None
        self._device = None

        self.device = kwargs.get("device")
        self.uuid = kwargs.get("uuid")
        self.exists = kwargs.get("exists", False)
        self.options = kwargs.get("options")
        self._create_options = kwargs.get("create_options")

        # Create task objects
        self._info = self._info_class(self)
        self._resize = self._resize_class(self)
        # These two may depend on info class, so create them after
        self._minsize = self._minsize_class(self)
        self._size_info = self._size_info_class(self)

        # format size does not necessarily equal device size
        self._size = kwargs.get("size", Size(0))
        self._target_size = self._size
        self._min_instance_size = Size(0)    # min size of this DeviceFormat instance

        # Resize operations are limited to error-free formats whose current
        # size is known.
        self._resizable = False

    def __repr__(self):
        s = ("%(classname)s instance (%(id)s) object id %(object_id)d--\n"
             "  type = %(type)s  name = %(name)s  status = %(status)s\n"
             "  device = %(device)s  uuid = %(uuid)s  exists = %(exists)s\n"
             "  options = %(options)s\n"
             "  create_options = %(create_options)s  supported = %(supported)s"
             "  formattable = %(format)s  resizable = %(resize)s\n" %
             {"classname": self.__class__.__name__, "id": "%#x" % id(self),
              "object_id": self.id,
              "type": self.type, "name": self.name, "status": self.status,
              "device": self.device, "uuid": self.uuid, "exists": self.exists,
              "options": self.options, "supported": self.supported,
              "format": self.formattable, "resize": self.resizable,
              "create_options": self.create_options})
        return s

    @property
    def _existence_str(self):
        return "existing" if self.exists else "non-existent"

    @property
    def desc(self):
        return str(self.type)

    def __str__(self):
        return "%s %s" % (self._existence_str, self.desc)

    @property
    def dict(self):
        d = {"type": self.type, "name": self.name, "device": self.device,
             "uuid": self.uuid, "exists": self.exists,
             "options": self.options, "supported": self.supported,
             "resizable": self.resizable, "create_options": self.create_options}

        return d

    def labeling(self):
        """Returns False by default since most formats are non-labeling."""
        return False

    def relabels(self):
        """Returns False by default since most formats are non-labeling."""
        return False

    def label_format_ok(self, label):
        """Checks whether the format of the label is OK for whatever
           application is used by blivet to write a label for this format.
           If there is no application that blivet uses to write a label,
           then no format is acceptable, so must return False.

           :param str label: The label to be checked

           :rtype: bool
           :return: True if the format of the label is OK, otherwise False
        """
        # pylint: disable=unused-argument
        return self.labeling()

    def _set_label(self, label):
        """Sets the label for this format.

           :param label: the label for this format
           :type label: str or None

           None means no label specified, or in other words, accept the default
           label that the filesystem app may set. Once the device exists the
           label should not be None, as the device must then have some label
           even if just the empty label.

           "" means the empty label, i.e., no label.

           Some filesystems, even though they do not have a
           labeling application may be already labeled, so we allow to set
           the label of a filesystem even if a labeling application does not
           exist. This can happen with the install media, for example, where
           the filesystem on the CD has a label, but there is no labeling
           application for the Iso9660FS format.

           If a labeling application does exist, the label is not
           required to have the correct format for that application.
           The allowable format for the label may be more permissive than
           the format allowed by the labeling application.

           This method is not intended to be overridden.
        """
        self._label = label

    def _get_label(self):
        """The label for this filesystem.

           :return: the label for this device
           :rtype: str

           This method is not intended to be overridden.
        """
        return self._label

    def _set_options(self, options):
        self._options = options

    def _get_options(self):
        return self._options

    options = property(
        lambda s: s._get_options(),
        lambda s, v: s._set_options(v),
        doc="fstab entry option string"
    )

    def _set_create_options(self, options):
        self._create_options = options

    def _get_create_options(self):
        return self._create_options

    create_options = property(
        lambda s: s._get_create_options(),
        lambda s, v: s._set_create_options(v),
        doc="options to be used when running mkfs"
    )

    def _device_check(self, devspec):
        """ Verifies that device spec has a proper format.

            :param devspec: the device spec
            :type devspec: str or NoneType
            :rtype: str or NoneType
            :returns: an explanatory message if devspec fails check, else None
        """
        if devspec and not devspec.startswith("/"):
            return "device must be a fully qualified path"
        return None

    def _set_device(self, devspec):
        error_msg = self._device_check(devspec)
        if error_msg:
            raise ValueError(error_msg)
        self._device = devspec

    def _get_device(self):
        return self._device

    device = property(lambda f: f._get_device(),
                      lambda f, d: f._set_device(d),
                      doc="Full path the device this format occupies")

    @property
    def name(self):
        return self._name or self.type

    @property
    def type(self):
        return self._type

    def _set_target_size(self, newsize):
        """ Set the target size for this filesystem.

            :param :class:`~.size.Size` newsize: the newsize
        """
        if not isinstance(newsize, Size):
            raise ValueError("new size must be of type Size")

        if not self.exists:
            raise DeviceFormatError("format has not been created")

        if not self.resizable:
            raise DeviceFormatError("format is not resizable")

        if newsize < self.min_size:
            raise ValueError("requested size %s must be at least minimum size %s" % (newsize, self.min_size))

        if self.max_size and newsize >= self.max_size:
            raise ValueError("requested size %s must be less than maximum size %s" % (newsize, self.max_size))

        self._target_size = newsize

    def _get_target_size(self):
        """ Get this filesystem's target size. """
        return self._target_size

    target_size = property(_get_target_size, _set_target_size,
                           doc="Target size for this filesystem")

    def _get_size(self):
        """ Get this filesystem's size. """
        return self.target_size if self.resizable else self._size

    size = property(_get_size, doc="This filesystem's size, accounting "
                    "for pending changes")

    @property
    def min_size(self):
        # If self._min_instance_size is not 0, then it should be no less than
        # self._min_size, by definition, and since a non-zero value indicates
        # that it was obtained, it is the preferred value.
        # If self._min_instance_size is less than self._min_size,
        # but not 0, then there must be some mistake, so better to use
        # self._min_size.
        return max(self._min_instance_size, self._min_size)

    def update_size_info(self):
        """ Update this format's current and minimum size (for resize). """

    def do_resize(self):
        """ Resize this filesystem based on this instance's target_size attr.

            :raises: FSResizeError, FormatResizeError
        """
        if not self.exists:
            raise FormatResizeError("format does not exist", self.device)

        if not self.resizable:
            raise FormatResizeError("format not resizable", self.device)

        if self.target_size == self.current_size:
            return

        if not self._resize.available:
            return

        # tmpfs mounts don't need an existing device node
        if not self.device == "tmpfs" and not os.path.exists(self.device):
            raise FormatResizeError("device does not exist", self.device)

        self._pre_resize()

        self.update_size_info()

        # Check again if resizable is True, as update_size_info() can change that
        if not self.resizable:
            raise FormatResizeError("format not resizable", self.device)

        if self.target_size < self.min_size:
            self.target_size = self.min_size
            log.info("Minimum size changed, setting target_size on %s to %s",
                     self.device, self.target_size)

        # Bump target size to nearest whole number of the resize tool's units.
        # We always round down because the fs has to fit on whatever device
        # contains it. To round up would risk quietly setting a target size too
        # large for the device to hold.
        rounded = self.target_size.round_to_nearest(self._resize.unit,
                                                    rounding=ROUND_DOWN)

        # 1. target size was between the min size and max size values prior to
        #    rounding (see _set_target_size)
        # 2. we've just rounded the target size down (or not at all)
        # 3. the minimum size is already either rounded (see _get_min_size) or is
        #    equal to the current size (see update_size_info)
        # 5. the minimum size is less than or equal to the current size (see
        #    _get_min_size)
        #
        # This, I think, is sufficient to guarantee that the rounded target size
        # is greater than or equal to the minimum size.

        # It is possible that rounding down a target size greater than the
        # current size would move it below the current size, thus changing the
        # direction of the resize. That means the target size was less than one
        # unit larger than the current size, and we should do nothing and return
        # early.
        if self.target_size > self.current_size and rounded < self.current_size:
            log.info("rounding target size down to next %s obviated resize of "
                     "filesystem on %s", unit_str(self._resize.unit), self.device)
            return
        else:
            self.target_size = rounded

        try:
            self._resize.do_task()
        except FSError as e:
            raise FSResizeError(e, self.device)
        except LUKSError as e:
            raise FormatResizeError(e, self.device)

        self._post_resize()

    def _pre_resize(self):
        """ Do whatever needs to be done before the format is resized """

    def _post_resize(self):
        # XXX must be a smarter way to do this
        self._size = self.target_size

    @property
    def current_size(self):
        """ The filesystem's current actual size. """
        return self._size if self.exists else Size(0)

    def create(self, **kwargs):
        """ Write the formatting to the specified block device.

            :keyword device: path to device node
            :type device: str.
            :raises: FormatCreateError
            :returns: None.

            .. :note::

                If a device node path is passed to this method it will overwrite
                any previously set value of this instance's "device" attribute.
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        self._pre_create(**kwargs)
        self._create(**kwargs)
        self._post_create(**kwargs)

    def _pre_create(self, **kwargs):
        """ Perform checks and setup prior to creating the format. """
        # allow late specification of device path
        device = kwargs.get("device")
        if device:
            self.device = device

        if not os.path.exists(self.device):
            raise FormatCreateError("invalid device specification", self.device)

        if self.exists:
            raise DeviceFormatError("format already exists")

        if self.status:
            raise DeviceFormatError("device exists and is active")

    # pylint: disable=unused-argument
    def _create(self, **kwargs):
        """ Type-specific create method. """

    # pylint: disable=unused-argument
    def _post_create(self, **kwargs):
        self.exists = True

    def destroy(self, **kwargs):
        """ Remove the formatting from the associated block device.

            :raises: FormatDestroyError
            :returns: None.
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        self._pre_destroy(**kwargs)
        self._destroy(**kwargs)
        self._post_destroy(**kwargs)

    # pylint: disable=unused-argument
    def _pre_destroy(self, **kwargs):
        if not self.exists:
            raise DeviceFormatError("format has not been created")

        if self.status:
            raise DeviceFormatError("device is active")

        if not os.access(self.device, os.W_OK):
            raise DeviceFormatError("device path does not exist or is not writable")

    def _destroy(self, **kwargs):
        rc = 0
        err = ""
        try:
            rc = run_program(["wipefs", "-f", "-a", self.device])
        except OSError as e:
            err = str(e)
        else:
            if rc:
                err = str(rc)

        if err:
            msg = "error wiping old signatures from %s: %s" % (self.device, err)
            raise FormatDestroyError(msg)

    def _post_destroy(self, **kwargs):
        udev.settle()
        self.exists = False

    @property
    def destroyable(self):
        """ Do we have the facilities to destroy a format of this type. """
        # assumes wipefs is always available
        return True

    def setup(self, **kwargs):
        """ Activate the formatting.

            :keyword device: device node path
            :type device: str.
            :raises: FormatSetupError.
            :returns: None.

            .. :note::

                If a device node path is passed to this method it will overwrite
                any previously set value of this instance's "device" attribute.
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self._pre_setup(**kwargs):
            return

        self._setup(**kwargs)
        self._post_setup(**kwargs)

    @property
    def controllable(self):
        """ Are external utilities available to allow this format to be both
            setup and teared down.

            :returns: True if this format can be set up, otherwise False
            :rtype: bool
        """
        return True

    def _pre_setup(self, **kwargs):
        """ Return True if setup should proceed. """
        if not self.exists:
            raise FormatSetupError("format has not been created")

        # allow late specification of device path
        device = kwargs.get("device")
        if device:
            self.device = device

        if not self.device or not os.path.exists(self.device):
            raise FormatSetupError("invalid device specification")

        return not self.status

    # pylint: disable=unused-argument
    def _setup(self, **kwargs):
        pass

    # pylint: disable=unused-argument
    def _post_setup(self, **kwargs):
        pass

    def teardown(self, **kwargs):
        """ Deactivate the formatting. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self._pre_teardown(**kwargs):
            return

        self._teardown(**kwargs)
        self._post_teardown(**kwargs)

    def _pre_teardown(self, **kwargs):
        """ Return True if teardown should proceed. """
        if not self.exists:
            raise DeviceFormatError("format has not been created")

        return self.status

    def _teardown(self, **kwargs):
        pass

    def _post_teardown(self, **kwargs):
        pass

    @property
    def status(self):
        return (self.exists and
                self.__class__ is not DeviceFormat and
                isinstance(self.device, str) and
                self.device and
                os.path.exists(self.device))

    @property
    def formattable(self):
        """ Can we create formats of this type? """
        return self._formattable

    @property
    def supported(self):
        """ Is this format a supported type?

            Are the necessary external applications required by the
            functionality that this format provides actually provided by
            the environment in which blivet is running?
        """
        return self._supported

    @property
    def packages(self):
        """ Packages required to manage formats of this type. """
        return self._packages

    @property
    def resizable(self):
        """ Can formats of this type be resized? """
        return self._resizable and self.exists

    @property
    def linux_native(self):
        """ Is this format type native to linux? """
        return self._linux_native

    @property
    def mountable(self):
        """ Is this something we can mount? """
        return False

    @property
    def dump(self):
        """ Whether or not this format will be dumped by dump(8). """
        return self._dump

    @property
    def check(self):
        """ Whether or not this format is checked on boot. """
        return self._check

    @property
    def max_size(self):
        """ Maximum size for this format type. """
        return self._max_size

    @property
    def hidden(self):
        """ Whether devices with this formatting should be hidden in UIs. """
        return self._hidden

    @property
    def ks_mountpoint(self):
        return (self._ks_mountpoint or self.type or "")

    def populate_ksdata(self, data):
        data.format = not self.exists
        data.fstype = self.type
        data.mountpoint = self.ks_mountpoint


register_device_format(DeviceFormat)

# import the format modules (which register their device formats)
from . import biosboot, disklabel, dmraid, fslib, fs, luks, lvmpv, mdraid, multipath, prepboot, swap
