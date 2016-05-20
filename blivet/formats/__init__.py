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

import os

from ..util import notify_kernel
from ..util import get_sysfs_path_by_name
from ..util import run_program
from ..util import ObjectID
from ..storage_log import log_method_call
from ..errors import DeviceFormatError, DMError, FormatCreateError, FormatDestroyError, FormatSetupError, MDRaidError, StorageError
from ..devicelibs.dm import dm_node_from_name
from ..devicelibs.mdraid import md_node_from_name
from ..i18n import _, N_
from ..size import Size

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
            supported = getFormat(fstype).supported
        except AttributeError:
            supported = False

        if supported:
            return fstype

    raise DeviceFormatError("None of %s is supported by your kernel" % ",".join(default_fstypes))

def getFormat(fmt_type, *args, **kwargs):
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

    log.debug("getFormat('%s') returning %s instance with object id %d",
       fmt_type, fmt.__class__.__name__, fmt.id)
    return fmt

def collect_device_format_classes():
    """ Pick up all device format classes from this directory.

        .. note::

            Modules must call :func:`register_device_format` to make format
            classes available to :func:`getFormat`.
    """
    mydir = os.path.dirname(__file__)
    myfile = os.path.basename(__file__)
    (myfile_name, _ext) = os.path.splitext(myfile)
    for module_file in os.listdir(mydir):
        (mod_name, ext) = os.path.splitext(module_file)
        if ext == ".py" and mod_name != myfile_name:
            try:
                globals()[mod_name] = __import__(mod_name, globals(), locals(), [], -1)
            except ImportError:
                log.error("import of device format module '%s' failed", mod_name)
                from traceback import format_exc
                log.debug("%s", format_exc())

def get_device_format_class(fmt_type):
    """ Return an appropriate format class.

        :param fmt_type: The name of the format type.
        :type fmt_type: str.
        :returns: The chosen DeviceFormat class
        :rtype: class.

        Returns None if no class is found for fmt_type.
    """
    if not device_formats:
        collect_device_format_classes()

    fmt = device_formats.get(fmt_type)
    if not fmt:
        for fmt_class in device_formats.values():
            if fmt_type and fmt_type == fmt_class._name:
                fmt = fmt_class
                break
            elif fmt_type in fmt_class._udevTypes:
                fmt = fmt_class
                break

    return fmt

class DeviceFormat(ObjectID):
    """ Generic device format.

        This represents the absence of recognized formatting. That could mean a
        device is uninitialized, has had zeros written to it, or contains some
        valid formatting that this module does not support.
    """
    _type = None
    _name = N_("Unknown")
    _udevTypes = []
    partedFlag = None
    partedSystem = None
    _formattable = False                # can be formatted
    _supported = False                  # is supported
    _linuxNative = False                # for clearpart
    _packages = []                      # required packages
    _services = []                      # required services
    _resizable = False                  # can be resized
    _maxSize = Size(0)                  # maximum size
    _minSize = Size(0)                  # minimum size
    _dump = False
    _check = False
    _hidden = False                     # hide devices with this formatting?
    _ksMountpoint = None

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
        self._device = None

        self.device = kwargs.get("device")
        self.uuid = kwargs.get("uuid")
        self.exists = kwargs.get("exists")
        self.options = kwargs.get("options")
        self._createOptions = kwargs.get("createOptions")

        # don't worry about existence if this is a DeviceFormat instance
        #if self.__class__ is DeviceFormat:
        #    self.exists = True

    def __repr__(self):
        s = ("%(classname)s instance (%(id)s) object id %(object_id)d--\n"
             "  type = %(type)s  name = %(name)s  status = %(status)s\n"
             "  device = %(device)s  uuid = %(uuid)s  exists = %(exists)s\n"
             "  options = %(options)s\n"
             "  createOptions = %(createOptions)s  supported = %(supported)s"
             "  formattable = %(format)s  resizable = %(resize)s\n" %
             {"classname": self.__class__.__name__, "id": "%#x" % id(self),
              "object_id": self.id,
              "type": self.type, "name": self.name, "status": self.status,
              "device": self.device, "uuid": self.uuid, "exists": self.exists,
              "options": self.options, "supported": self.supported,
              "format": self.formattable, "resize": self.resizable,
              "createOptions": self.createOptions})
        return s

    @property
    def _existence_str(self):
        exist = "existing"
        if not self.exists:
            exist = "non-existent"
        return exist

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
             "resizable": self.resizable, "createOptions": self.createOptions}
        return d

    @classmethod
    def labeling(cls):
        """Returns False by default since most formats are non-labeling."""
        return False

    @classmethod
    def labelFormatOK(cls, label):
        """Checks whether the format of the label is OK for whatever
           application is used by blivet to write a label for this format.
           If there is no application that blivet uses to write a label,
           then no format is acceptable, so must return False.

           :param str label: The label to be checked

           :rtype: bool
           :return: True if the format of the label is OK, otherwise False
        """
        # pylint: disable=unused-argument
        return cls.labeling()

    def _setLabel(self, label):
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
        self._label = label # pylint: disable=attribute-defined-outside-init

    def _getLabel(self):
        """The label for this filesystem.

           :return: the label for this device
           :rtype: str

           This method is not intended to be overridden.
        """
        return self._label

    def _setOptions(self, options):
        self._options = options # pylint: disable=attribute-defined-outside-init

    def _getOptions(self):
        return self._options

    options = property(_getOptions, _setOptions)

    def _setCreateOptions(self, options):
        self._createOptions = options

    def _getCreateOptions(self):
        return self._createOptions

    createOptions = property(_getCreateOptions, _setCreateOptions)

    def _setDevice(self, devspec):
        if devspec and not devspec.startswith("/"):
            raise ValueError("device must be a fully qualified path")
        self._device = devspec

    def _getDevice(self):
        return self._device

    device = property(lambda f: f._getDevice(),
                      lambda f,d: f._setDevice(d),
                      doc="Full path the device this format occupies")

    @property
    def name(self):
        if self._name:
            name = self._name
        else:
            name = self.type
        return name

    @property
    def type(self):
        return self._type

    def probe(self):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)

    def notifyKernel(self):
        log_method_call(self, device=self.device,
                        type=self.type)
        if not self.device:
            return

        if self.device.startswith("/dev/mapper/"):
            try:
                name = dm_node_from_name(os.path.basename(self.device))
            except DMError:
                log.warning("failed to get dm node for %s", self.device)
                return
        elif self.device.startswith("/dev/md/"):
            try:
                name = md_node_from_name(os.path.basename(self.device))
            except MDRaidError:
                log.warning("failed to get md node for %s", self.device)
                return
        else:
            name = self.device

        path = get_sysfs_path_by_name(name)
        try:
            notify_kernel(path, action="change")
        except (ValueError, IOError) as e:
            log.warning("failed to notify kernel of change: %s", e)

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
        # allow late specification of device path
        device = kwargs.get("device")
        if device:
            self.device = device

        if not os.path.exists(self.device):
            raise FormatCreateError("invalid device specification", self.device)

    def destroy(self, **kwargs):
        """ Remove the formatting from the associated block device.

            :raises: FormatDestroyError
            :returns: None.
        """
        # pylint: disable=unused-argument
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        try:
            rc = run_program(["wipefs", "-f", "-a", self.device])
        except OSError as e:
            err = str(e)
        else:
            err = ""
            if rc:
                err = str(rc)

        if err:
            msg = "error wiping old signatures from %s: %s" % (self.device, err)
            raise FormatDestroyError(msg)

        self.exists = False

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

        if not self.exists:
            raise FormatSetupError("format has not been created")

        if self.status:
            return

        # allow late specification of device path
        device = kwargs.get("device")
        if device:
            self.device = device

        if not self.device or not os.path.exists(self.device):
            raise FormatSetupError("invalid device specification")

    def teardown(self):
        """ Deactivate the formatting. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)

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
        """ Is this format a supported type? """
        return self._supported

    @property
    def packages(self):
        """ Packages required to manage formats of this type. """
        return self._packages

    @property
    def services(self):
        """ Services required to manage formats of this type. """
        return self._services

    @property
    def resizable(self):
        """ Can formats of this type be resized? """
        return self._resizable and self.exists

    @property
    def linuxNative(self):
        """ Is this format type native to linux? """
        return self._linuxNative

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
    def maxSize(self):
        """ Maximum size for this format type. """
        return self._maxSize

    @property
    def minSize(self):
        """ Minimum size for this format type. """
        return self._minSize

    @property
    def hidden(self):
        """ Whether devices with this formatting should be hidden in UIs. """
        return self._hidden

    @property
    def ksMountpoint(self):
        return (self._ksMountpoint or self.type or "")

    def populateKSData(self, data):
        data.format = not self.exists
        data.fstype = self.type
        data.mountpoint = self.ksMountpoint

register_device_format(DeviceFormat)

collect_device_format_classes()
