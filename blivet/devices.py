# devices.py
# Classes to represent various types of block devices.
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
import copy
import pprint
import tempfile
import abc
from decimal import Decimal
import re

from six import with_metaclass

# device backend modules
from .devicelibs import mdraid
from .devicelibs import lvm
from .devicelibs import dm
from .devicelibs import loop
from .devicelibs import btrfs
from .devicelibs import crypto
from .devicelibs import raid
import parted
import _ped
import block

from . import errors
from . import util
from . import arch
from .flags import flags
from .storage_log import log_method_call
from . import udev
from .formats import get_device_format_class, getFormat, DeviceFormat
from .size import Size
from .i18n import P_

import logging
log = logging.getLogger("blivet")

def get_device_majors():
    majors = {}
    for line in open("/proc/devices").readlines():
        try:
            (major, device) = line.split()
        except ValueError:
            continue
        try:
            majors[int(major)] = device
        except ValueError:
            continue
    return majors
device_majors = get_device_majors()


def devicePathToName(devicePath):
    """ Return a name based on the given path to a device node.

        :param devicePath: the path to a device node
        :type devicePath: str
        :returns: the name
        :rtype: str
    """
    if not devicePath:
        return None

    if devicePath.startswith("/dev/"):
        name = devicePath[5:]
    else:
        name = devicePath

    if name.startswith("mapper/"):
        name = name[7:]

    if name.startswith("md/"):
        name = name[3:]

    return name


def deviceNameToDiskByPath(deviceName=None):
    """ Return a /dev/disk/by-path/ symlink path for the given device name.

        :param deviceName: the device name
        :type deviceName: str
        :returns: the full path to a /dev/disk/by-path/ symlink, or None
        :rtype: str or NoneType
    """
    if not deviceName:
        return ""

    ret = None
    for dev in udev.udev_get_block_devices():
        if udev.udev_device_get_name(dev) == deviceName:
            ret = udev.udev_device_get_by_path(dev)
            break

    if ret:
        return ret
    raise errors.DeviceNotFoundError(deviceName)

class ParentList(object):
    """ A list with auditing and side-effects for additions and removals.

        The class provides an ordered list with guaranteed unique members and
        optional functions to run before adding or removing a member. It
        provides a subset of the functionality provided by :class:`list`,
        making it easy to ensure that changes pass through the check functions.

        The following operations are implemented:

        .. code::

            ml.append(x)
            ml.remove(x)
            iter(ml)
            len(ml)
            x in ml
            x = ml[i]   # not ml[i] = x
    """
    def __init__(self, items=None, appendfunc=None, removefunc=None):
        """
            :keyword items: initial contents
            :type items: any iterable
            :keyword appendfunc: a function to call before adding an item
            :type appendfunc: callable
            :keyword removefunc: a function to call before removing an item
            :type removefunc: callable

            appendfunc and removefunc should take the item to be added or
            removed and perform any checks or other processing. The appropriate
            function will be called immediately before adding or removing the
            item. The function should raise an exception if the addition/removal
            should not take place. :class:`~.ParentList` instance is not passed
            to the function. While this is not optimal for general-purpose use,
            it is ideal for the intended use as part of :class:`~.Device`. The
            functions themselves should not modify the :class:`~.ParentList`.
        """
        self.items = list()
        if items:
            self.items.extend(items)

        self.appendfunc = appendfunc or (lambda i: True)
        """ a function to call before adding an item """

        self.removefunc = removefunc or (lambda i: True)
        """ a function to call before removing an item """

    def __iter__(self):
        return iter(self.items)

    def __contains__(self, y):
        return y in self.items

    def __getitem__(self, i):
        return self.items[i]

    def __len__(self):
        return len(self.items)

    def append(self, y):
        """ Add an item to the list after running a callback. """
        if y in self.items:
            raise ValueError("item is already in the list")

        self.appendfunc(y)
        self.items.append(y)

    def remove(self, y):
        """ Remove an item from the list after running a callback. """
        if y not in self.items:
            raise ValueError("item is not in the list")

        self.removefunc(y)
        self.items.remove(y)

class Device(util.ObjectID):
    """ A generic device.

        Device instances know which devices they depend upon (parents
        attribute). They do not know which devices depend upon them, but
        they do know whether or not they have any dependent devices
        (isleaf attribute).

        A Device's setup method should set up all parent devices as well
        as the device itself. It should not run the resident format's
        setup method.

            Which Device types rely on their parents' formats being active?
                DMCryptDevice

        A Device's teardown method should accept the keyword argument
        recursive, which takes a boolean value and indicates whether or
        not to recursively close parent devices.

        A Device's create method should create all parent devices as well
        as the device itself. It should also run the Device's setup method
        after creating the device. The create method should not create a
        device's resident format.

            Which device type rely on their parents' formats to be created
            before they can be created/assembled?
                VolumeGroup
                DMCryptDevice

        A Device's destroy method should destroy any resident format
        before destroying the device itself.

    """

    _type = "device"
    _packages = []
    _services = []

    def __init__(self, name, parents=None):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword parents: a list of parent devices
            :type parents: list of :class:`Device` instances
        """
        util.ObjectID.__init__(self)
        self.kids = 0

        # Copy only the validity check from _setName so we don't try to check a
        # bunch of inappropriate state properties during __init__ in subclasses
        if not self.isNameValid(name):
            raise ValueError("%s is not a valid name for this device" % name)
        self._name = name

        self.parents = []
        if parents and not isinstance(parents, list):
            raise ValueError("parents must be a list of Device instances")

        if parents:
            self.parents = parents

    def __deepcopy__(self, memo):
        """ Create a deep copy of a Device instance.

            We can't do copy.deepcopy on parted objects, which is okay.
            For these parted objects, we just do a shallow copy.
        """
        return util.variable_copy(self, memo,
           omit=('_raidSet', 'node'),
           shallow=('_partedDevice', '_partedPartition'))

    def __repr__(self):
        s = ("%(type)s instance (%(id)s) --\n"
             "  name = %(name)s  status = %(status)s"
             "  kids = %(kids)s id = %(dev_id)s\n"
             "  parents = %(parents)s\n" %
             {"type": self.__class__.__name__, "id": "%#x" % id(self),
              "name": self.name, "kids": self.kids, "status": self.status,
              "dev_id": self.id,
              "parents": pprint.pformat([str(p) for p in self.parents])})
        return s

    def __str__(self):
        s = "%s %s (%d)" % (self.type, self.name, self.id)
        return s

    def _addParent(self, parent):
        """ Called before adding a parent to this device.

            See :attr:`~.ParentList.appendfunc`.
        """
        parent.addChild()

    def _removeParent(self, parent):
        """ Called before removing a parent from this device.

            See :attr:`~.ParentList.removefunc`.
        """
        parent.removeChild()

    def _initParentList(self):
        """ Initialize this instance's parent list. """
        if not hasattr(self, "_parents"):
            # pylint: disable=attribute-defined-outside-init
            self._parents = ParentList(appendfunc=self._addParent,
                                       removefunc=self._removeParent)

        # iterate over a copy of the parent list because we are altering it in
        # the for-cycle
        for parent in list(self._parents):
            self._parents.remove(parent)

    def _setParentList(self, parents):
        """ Set this instance's parent list. """
        self._initParentList()
        for parent in parents:
            self._parents.append(parent)

    def _getParentList(self):
        return self._parents

    parents = property(_getParentList, _setParentList,
                       doc="devices upon which this device is built")

    @property
    def dict(self):
        d =  {"type": self.type, "name": self.name,
              "parents": [p.name for p in self.parents]}
        return d

    def removeChild(self):
        """ Decrement the child counter for this device. """
        log_method_call(self, name=self.name, kids=self.kids)
        self.kids -= 1

    def addChild(self):
        """ Increment the child counter for this device. """
        log_method_call(self, name=self.name, kids=self.kids)
        self.kids += 1

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        raise NotImplementedError("setup method not defined for Device")

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        raise NotImplementedError("teardown method not defined for Device")

    def create(self):
        """ Create the device. """
        raise NotImplementedError("create method not defined for Device")

    def destroy(self):
        """ Destroy the device. """
        raise NotImplementedError("destroy method not defined for Device")

    def setupParents(self, orig=False):
        """ Run setup method of all parent devices.

            :keyword orig: set up original format instead of current format
            :type orig: bool
        """
        log_method_call(self, name=self.name, orig=orig, kids=self.kids)
        for parent in self.parents:
            parent.setup(orig=orig)

    def teardownParents(self, recursive=None):
        """ Run teardown method of all parent devices.

            :keyword recursive: tear down all ancestor devices recursively
            :type recursive: bool
        """
        for parent in self.parents:
            parent.teardown(recursive=recursive)

    def dependsOn(self, dep):
        """ Return True if this device depends on dep.

            This device depends on another device if the other device is an
            ancestor of this device. For example, a PartitionDevice depends on
            the DiskDevice on which it resides.

            :param dep: the other device
            :type dep: :class:`Device`
            :returns: whether this device depends on 'dep'
            :rtype: bool
        """
        # XXX does a device depend on itself?
        if dep in self.parents:
            return True

        for parent in self.parents:
            if parent.dependsOn(dep):
                return True

        return False

    def dracutSetupArgs(self):
        return set()

    @property
    def status(self):
        """ Is this device currently active and ready for use? """
        return False

    def _getName(self):
        return self._name

    def _setName(self, value):
        if not self.isNameValid(value):
            raise ValueError("%s is not a valid name for this device" % value)
        self._name = value

    name = property(lambda s: s._getName(),
                    lambda s, v: s._setName(v),
                    doc="This device's name")

    @property
    def isleaf(self):
        """ True if no other device depends on this one. """
        return self.kids == 0

    @property
    def typeDescription(self):
        """ String describing the device type. """
        return self._type

    @property
    def type(self):
        """ Device type. """
        return self._type

    @property
    def ancestors(self):
        """ A list of all of this device's ancestors, including itself. """
        l = set([self])
        for p in [d for d in self.parents if d not in l]:
            l.update(set(p.ancestors))
        return list(l)

    @property
    def packages(self):
        """ List of packages required to manage devices of this type.

            This list includes the packages required by its parent devices.
        """
        packages = self._packages
        for parent in self.parents:
            for package in parent.packages:
                if package not in packages:
                    packages.append(package)

        return packages

    @property
    def services(self):
        """ List of services required to manage devices of this type.

            This list includes the services required by its parent devices."
        """
        services = self._services
        for parent in self.parents:
            for service in parent.services:
                if service not in services:
                    services.append(service)

        return services

    @property
    def mediaPresent(self):
        """ True if this device contains usable media. """
        return True

    @classmethod
    def isNameValid(cls, name): # pylint: disable=unused-argument
        """Is the device name valid for the device type?"""

        # By default anything goes
        return True


class NetworkStorageDevice(object):
    """ Virtual base class for network backed storage devices """

    def __init__(self, host_address=None, nic=None):
        """ Note this class is only to be used as a baseclass and then only with
            multiple inheritance. The only correct use is:
            class MyStorageDevice(StorageDevice, NetworkStorageDevice):

            The sole purpose of this class is to:
            1) Be able to check if a StorageDevice is network backed
               (using isinstance).
            2) To be able to get the host address of the host (server) backing
               the storage *or* the NIC through which the storage is connected

            :keyword host_address: host address of the backing server
            :type host_address: str
            :keyword nic: NIC to which the block device is bound
            :type nic: str
        """
        self.host_address = host_address
        self.nic = nic


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
    _devDir = "/dev"
    sysfsBlockDir = "class/block"
    _formatImmutable = False
    _partitionable = False
    _isDisk = False

    def __init__(self, name, fmt=None, uuid=None,
                 size=None, major=None, minor=None,
                 sysfsPath='', parents=None, exists=False, serial=None,
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
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
        Device.__init__(self, name, parents=parents)

        self._format = None
        self._size = Size(util.numeric_type(size))
        self.major = util.numeric_type(major)
        self.minor = util.numeric_type(minor)
        self.sysfsPath = sysfsPath
        self._serial = serial
        self._vendor = vendor
        self._model = model
        self.bus = bus

        self.protected = False
        self.controllable = not flags.testing

        self.format = fmt
        self.originalFormat = copy.copy(self.format)
        self.fstabComment = ""
        self._targetSize = self._size

        self._partedDevice = None

        self.deviceLinks = []

        if self.exists and flags.testing and not self._size:
            def read_int_from_sys(path):
                return int(open(path).readline().strip())

            device_root = "/sys/class/block/%s" % self.name
            if os.path.exists("%s/queue" % device_root):
                sector_size = read_int_from_sys("%s/queue/logical_block_size"
                                                % device_root)
                size = read_int_from_sys("%s/size" % device_root)
                self._size = Size(size * sector_size)

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
        """ List of packages required to manage devices of this type.

            This list includes the packages required by this device's
            format type as well those required by all of its parent
            devices.
        """
        packages = super(StorageDevice, self).packages
        packages.extend(self.format.packages)
        for parent in self.parents:
            for package in parent.format.packages:
                if package not in packages:
                    packages.append(package)

        return packages

    @property
    def services(self):
        """ List of services required to manage devices of this type.

            This list includes the services required by this device's
            format type as well those required by all of its parent
            devices.
        """
        services = super(StorageDevice, self).services
        services.extend(self.format.services)
        for parent in self.parents:
            for service in parent.format.services:
                if service not in services:
                    services.append(service)

        return services

    @property
    def disks(self):
        """ A list of all disks this device depends on, including itself. """
        _disks = []
        for parent in self.parents:
            for disk in parent.disks:
                if disk not in _disks:
                    _disks.append(disk)

        if self.isDisk and not self.format.hidden:
            _disks.append(self)

        return _disks

    @property
    def encrypted(self):
        """ True if this device, or any it requires, is encrypted. """
        crypted = False
        for parent in self.parents:
            if parent.encrypted:
                crypted = True
                break

        if not crypted and isinstance(self, DMCryptDevice):
            crypted = True

        return crypted

    def _getPartedDevicePath(self):
        return self.path

    @property
    def partedDevice(self):
        devicePath = self._getPartedDevicePath()
        if self.exists and self.status and not self._partedDevice:
            log.debug("looking up parted Device: %s", devicePath)

            # We aren't guaranteed to be able to get a device.  In
            # particular, built-in USB flash readers show up as devices but
            # do not always have any media present, so parted won't be able
            # to find a device.
            try:
                self._partedDevice = parted.Device(path=devicePath)
            except (_ped.IOException, _ped.DeviceException):
                pass

        return self._partedDevice

    @property
    def raw_device(self):
        """ The device itself, or when encrypted, the backing device. """
        return self

    def _setName(self, value):
        """Set the device's name.

        :param value: the new device name
        :raises errors.DeviceError: if the device exists
        """

        if value == self._name:
            return

        if self.exists:
            raise errors.DeviceError("Cannot rename existing device.")

        super(StorageDevice, self)._setName(value)

    def _getTargetSize(self):
        return self._targetSize

    def _setTargetSize(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if self.maxSize and newsize > self.maxSize:
            log.error("requested size %s is larger than maximum %s",
                      newsize, self.maxSize)
            raise ValueError("size is larger than the maximum for this device")

        self._targetSize = newsize

    targetSize = property(lambda s: s._getTargetSize(),
                          lambda s, v: s._setTargetSize(v),
                          doc="Target size of this device")

    def __repr__(self):
        s = Device.__repr__(self)
        s += ("  uuid = %(uuid)s  size = %(size)s\n"
              "  format = %(format)s\n"
              "  major = %(major)s  minor = %(minor)s  exists = %(exists)s"
              "  protected = %(protected)s\n"
              "  sysfs path = %(sysfs)s  partedDevice = %(partedDevice)s\n"
              "  target size = %(targetSize)s  path = %(path)s\n"
              "  format args = %(formatArgs)s  originalFormat = %(origFmt)s" %
              {"uuid": self.uuid, "format": self.format, "size": self.size,
               "major": self.major, "minor": self.minor, "exists": self.exists,
               "sysfs": self.sysfsPath, "partedDevice": self.partedDevice,
               "targetSize": self.targetSize, "path": self.path,
               "protected": self.protected,
               "formatArgs": self.formatArgs, "origFmt": self.originalFormat.type})
        return s

    @property
    def dict(self):
        d =  super(StorageDevice, self).dict
        d.update({"uuid": self.uuid, "size": self.size,
                  "format": self.format.dict, "removable": self.removable,
                  "major": self.major, "minor": self.minor,
                  "exists": self.exists, "sysfs": self.sysfsPath,
                  "targetSize": self.targetSize, "path": self.path})
        return d

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._devDir, self.name)

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        sysfsName = self.name.replace("/", "!")
        path = os.path.join("/sys", self.sysfsBlockDir, sysfsName)
        self.sysfsPath = os.path.realpath(path)[4:]
        log.debug("%s sysfsPath set to %s", self.name, self.sysfsPath)

    @property
    def formatArgs(self):
        """ Device-specific arguments to format creation program. """
        return []

    @property
    def resizable(self):
        """ Can this device be resized? """
        return (self._resizable and self.exists and
                (self.format.type is None or self.format.resizable or
                 not self.format.exists))

    def notifyKernel(self):
        """ Send a 'change' uevent to the kernel for this device. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            log.debug("not sending change uevent for non-existent device")
            return

        if not self.status:
            log.debug("not sending change uevent for inactive device")
            return

        path = os.path.normpath("/sys/%s" % self.sysfsPath)
        try:
            util.notify_kernel(path, action="change")
        except (ValueError, IOError) as e:
            log.warning("failed to notify kernel of change: %s", e)

    @property
    def fstabSpec(self):
        spec = self.path
        if self.format and self.format.uuid:
            spec = "UUID=%s" % self.format.uuid
        return spec

    def resize(self):
        """ Resize a device to self.targetSize.

            This method should only be invoked via the
            ActionResizeDevice.execute method. All the pre-conditions
            enforced by ActionResizeDevice.__init__ are assumed to hold.

            Returns nothing.
        """
        if self._resizable:
            raise NotImplementedError("method not implemented for device type %s" % self.type)
        else:
            raise errors.DeviceError("device type %s is not resizable" % self.type)

    #
    # setup
    #
    def _preSetup(self, orig=False):
        """ Preparation and pre-condition checking for device setup.

            Return True if setup should proceed or False if not.
        """
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if self.status or not self.controllable:
            return False

        self.setupParents(orig=orig)
        return True

    def _setup(self, orig=False):
        """ Perform device-specific setup operations. """
        pass

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        if not self._preSetup(orig=orig):
            return

        self._setup(orig=orig)
        self._postSetup()

    def _postSetup(self):
        """ Perform post-setup operations. """
        udev.udev_settle()
        # we always probe since the device may not be set up when we want
        # information about it
        self._size = self.currentSize

    #
    # teardown
    #
    def _preTeardown(self, recursive=None):
        """ Preparation and pre-condition checking for device teardown.

            Return True if teardown should proceed or False if not.
        """
        if not self.exists and not recursive:
            raise errors.DeviceError("device has not been created", self.name)

        if not self.status or not self.controllable:
            return False

        if self.originalFormat.exists:
            self.originalFormat.teardown()
        self.format.cacheMajorminor()
        if self.format.exists:
            self.format.teardown()
        udev.udev_settle()
        return True

    def _teardown(self, recursive=None):
        """ Perform device-specific teardown operations. """
        pass

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._preTeardown(recursive=recursive):
            return

        self._teardown(recursive=recursive)
        self._postTeardown(recursive=recursive)

    def _postTeardown(self, recursive=None):
        """ Perform post-teardown operations. """
        if recursive:
            self.teardownParents(recursive=recursive)

    #
    # create
    #
    def _preCreate(self):
        """ Preparation and pre-condition checking for device creation. """
        if self.exists:
            raise errors.DeviceError("device has already been created", self.name)

        self.setupParents()

    def _create(self):
        """ Perform device-specific create operations. """
        pass

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self._preCreate()
        try:
            self._create()
        except Exception as e:
            raise errors.DeviceCreateError(str(e), self.name)
        else:
            self._postCreate()

    def _postCreate(self):
        """ Perform post-create operations. """
        self.exists = True
        self.setup()
        self.updateSysfsPath()
        udev.udev_settle()

        # make sure that targetSize is updated to reflect the actual size
        if self.resizable:
            self._partedDevice = None
            self._targetSize = self.currentSize

    #
    # destroy
    #
    def _preDestroy(self):
        """ Preparation and precondition checking for device destruction. """
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if not self.isleaf:
            raise errors.DeviceError("Cannot destroy non-leaf device", self.name)

        self.teardown()

    def _destroy(self):
        """ Perform device-specific destruction operations. """
        pass

    def destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        self._preDestroy()
        self._destroy()
        self._postDestroy()

    def _postDestroy(self):
        """ Perform post-destruction operations. """
        self.exists = False

    def setupParents(self, orig=False):
        """ Run setup method of all parent devices. """
        log_method_call(self, name=self.name, orig=orig, kids=self.kids)
        for parent in self.parents:
            parent.setup(orig=orig)
            if orig:
                _format = parent.originalFormat
            else:
                _format = parent.format

            # set up the formatting, if present
            if _format.type and _format.exists:
                _format.setup()

    def _getSize(self):
        """ Get the device's size, accounting for pending changes. """
        if self.exists and not self.mediaPresent:
            return 0

        if self.exists and self.partedDevice:
            self._size = self.currentSize

        size = self._size
        if self.exists and self.resizable:
            size = self.targetSize

        return size

    def _setSize(self, newsize):
        """ Set the device's size to a new value. """
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if self.maxSize and newsize > self.maxSize:
            raise errors.DeviceError("device cannot be larger than %s" %
                              (self.maxSize,), self.name)
        self._size = newsize

    size = property(lambda x: x._getSize(),
                    lambda x, y: x._setSize(y),
                    doc="The device's size, accounting for pending changes")

    @property
    def currentSize(self):
        """ The device's actual size, generally the size discovered by using
            system tools. May use a cached value if the information is
            currently unavailable.

            If the device does not exist, then the actual size is 0.
        """
        size = 0
        if self.exists and self.partedDevice:
            size = Size(self.partedDevice.getLength(unit="B"))
        elif self.exists:
            size = self._size
        return size

    @property
    def minSize(self):
        """ The minimum size this device can be. """
        return self.format.minSize if self.resizable else self.currentSize

    @property
    def maxSize(self):
        """ The maximum size this device can be. """
        return self.format.maxSize if self.resizable else self.currentSize

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

    def _setFormat(self, fmt):
        """ Set the Device's format. """
        if not fmt:
            fmt = getFormat(None, device=self.path, exists=self.exists)
        log_method_call(self, self.name, type=fmt.type,
                        current=getattr(self._format, "type", None))
        if self._format and self._format.status:
            # FIXME: self.format.status doesn't mean much
            raise errors.DeviceError("cannot replace active format", self.name)

        self._format = fmt
        self._format.device = self.path

    def _getFormat(self):
        return self._format

    format = property(lambda d: d._getFormat(),
                      lambda d,f: d._setFormat(f),
                      doc="The device's formatting.")

    def preCommitFixup(self, *args, **kwargs):
        """ Do any necessary pre-commit fixups."""
        pass

    @property
    def removable(self):
        devpath = os.path.normpath("/sys/%s" % self.sysfsPath)
        remfile = os.path.normpath("%s/removable" % devpath)
        return (self.sysfsPath and os.path.exists(devpath) and
                os.access(remfile, os.R_OK) and
                open(remfile).readline().strip() == "1")

    @property
    def formatImmutable(self):
        """ Is it possible to execute format actions on this device? """
        return self._formatImmutable or self.protected

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return self.isleaf

    @property
    def isDisk(self):
        return self._isDisk

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
        if not self._model:
            self._model = getattr(self.partedDevice, "model", "")
        return self._model

    @property
    def vendor(self):
        return self._vendor

    @property
    def growable(self):
        """ True if this device or it's component devices are growable. """
        grow = getattr(self, "req_grow", False)
        if not grow:
            for parent in self.parents:
                grow = parent.growable
                if grow:
                    break
        return grow

    def checkSize(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.maxSize and self.size > self.format.maxSize:
            return 1
        elif self.format.minSize and self.size < self.format.minSize:
            return -1
        return 0

    def populateKSData(self, data):
        # the common pieces are basically the formatting
        self.format.populateKSData(data)

        # this is a little bit of a hack for container member devices that
        # need aliases, but even more of a hack for btrfs since you cannot tell
        # from inside the BTRFS class whether you're dealing with a member or a
        # volume/subvolume
        if self.format.type == "btrfs" and not isinstance(self, BTRFSDevice):
            data.mountpoint = "btrfs."  # continued below, also for lvm, raid

        if data.mountpoint.endswith("."):
            data.mountpoint += str(self.id)

    @classmethod
    def isNameValid(cls, name):
        # This device corresponds to a file in /dev, so no /'s or nulls,
        # and the name cannot be . or ..

        # ...except some names *do* contain directory components, for this
        # is an imperfect world of joy and sorrow mingled. For cciss, split
        # the path into its components and do the real check on each piece
        if name.startswith("cciss/"):
            return all(cls.isNameValid(n) for n in name.split('/'))

        badchars = any(c in ('\x00', '/') for c in name)
        return not(badchars or name == '.' or name == '..')

class DiskDevice(StorageDevice):
    """ A local/generic disk.

        This is not the only kind of device that is treated as a disk. More
        useful than checking isinstance(device, DiskDevice) is checking
        device.isDisk.
    """
    _type = "disk"
    _partitionable = True
    _isDisk = True

    def __init__(self, name, fmt=None,
                 size=None, major=None, minor=None, sysfsPath='',
                 parents=None, serial=None, vendor="", model="", bus="",
                 exists=True):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword uuid: universally unique identifier (device -- not fs)
            :type uuid: str
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword removable: whether or not this is a removable device
            :type removable: bool
            :keyword serial: the ID_SERIAL_SHORT for this device
            :type serial: str
            :keyword vendor: the manufacturer of this Device
            :type vendor: str
            :keyword model: manufacturer's device model string
            :type model: str
            :keyword bus: the interconnect this device uses
            :type bus: str

            DiskDevices always exist.
        """
        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               major=major, minor=minor, exists=exists,
                               sysfsPath=sysfsPath, parents=parents,
                               serial=serial, model=model,
                               vendor=vendor, bus=bus)

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  removable = %(removable)s  partedDevice = %(partedDevice)r" %
              {"removable": self.removable, "partedDevice": self.partedDevice})
        return s

    @property
    def mediaPresent(self):
        if flags.testing:
            return True

        if not self.partedDevice:
            return False

        # Some drivers (cpqarray <blegh>) make block device nodes for
        # controllers with no disks attached and then report a 0 size,
        # treat this as no media present
        return self.partedDevice.getLength(unit="B") != 0

    @property
    def description(self):
        return self.model

    @property
    def size(self):
        """ The disk's size """
        return super(DiskDevice, self).size

    def _preDestroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        if not self.mediaPresent:
            raise errors.DeviceError("cannot destroy disk with no media", self.name)

        StorageDevice._preDestroy(self)


class PartitionDevice(StorageDevice):
    """ A disk partition.

        On types and flags...

        We don't need to deal with numerical partition types at all. The
        only type we are concerned with is primary/logical/extended. Usage
        specification is accomplished through the use of flags, which we
        will set according to the partition's format.
    """
    _type = "partition"
    _resizable = True
    defaultSize = Size("500MiB")

    def __init__(self, name, fmt=None,
                 size=None, grow=False, maxsize=None, start=None, end=None,
                 major=None, minor=None, bootable=None,
                 sysfsPath='', parents=None, exists=False,
                 partType=None, primary=False, weight=0):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class::class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it

            For existing partitions only:

            :keyword major: the device major
            :type major: long
            :keyword minor: the device minor
            :type minor: long
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str

            For non-existent partitions only:

            :keyword partType: parted type constant, eg:
                                :const:`parted.PARTITION_NORMAL`
            :type partType: parted partition type constant
            :keyword grow: whether or not to grow the partition
            :type grow: bool
            :keyword maxsize: max size for growable partitions
            :type maxsize: :class:`~.size.Size`
            :keyword start: start sector (see note, below)
            :type start: long
            :keyword end: end sector (see note, below)
            :type end: long
            :keyword bootable: whether the partition is bootable
            :type bootable: bool
            :keyword weight: an initial sorting weight to assign
            :type weight: int

            .. note::

                If a start sector is specified the partition will not be
                adjusted for optimal alignment. That is up to the caller.
        """
        self.req_disks = []
        self.req_partType = None
        self.req_primary = None
        self.req_grow = None
        self.req_bootable = None
        self.req_size = Size(0)
        self.req_base_size = Size(0)
        self.req_max_size = Size(0)
        self.req_base_weight = 0
        self.req_start_sector = None
        self.req_end_sector = None
        self.req_name = None

        self._bootable = False

        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               major=major, minor=minor, exists=exists,
                               sysfsPath=sysfsPath, parents=parents)

        if not exists:
            # this is a request, not a partition -- it has no parents
            self.req_disks = list(self.parents)
            self.parents = []

        # FIXME: Validate partType, but only if this is a new partition
        #        Otherwise, overwrite it with the partition's type.
        self._partType = None
        self.partedFlags = {}
        self._partedPartition = None
        self._origPath = None
        self._currentSize = 0

        # FIXME: Validate size, but only if this is a new partition.
        #        For existing partitions we will get the size from
        #        parted.

        if self.exists and not flags.testing:
            log.debug("looking up parted Partition: %s", self.path)
            self._partedPartition = self.disk.format.partedDisk.getPartitionByPath(self.path)
            if not self._partedPartition:
                raise errors.DeviceError("cannot find parted partition instance", self.name)

            self._origPath = self.path
            # collect information about the partition from parted
            self.probe()
            if self.getFlag(parted.PARTITION_PREP):
                # the only way to identify a PPC PReP Boot partition is to
                # check the partition type/flags, so do it here.
                self.format = getFormat("prepboot", device=self.path, exists=True)
            elif self.getFlag(parted.PARTITION_BIOS_GRUB):
                # the only way to identify a BIOS Boot partition is to
                # check the partition type/flags, so do it here.
                self.format = getFormat("biosboot", device=self.path, exists=True)
        else:
            # XXX It might be worthwhile to create a shit-simple
            #     PartitionRequest class and pass one to this constructor
            #     for new partitions.
            if not self._size:
                if start is not None and end is not None:
                    self._size = 0
                else:
                    # default size for new partition requests
                    self._size = self.defaultSize

            self.req_name = name
            self.req_partType = partType
            self.req_primary = primary
            self.req_max_size = Size(util.numeric_type(maxsize))
            self.req_grow = grow
            self.req_bootable = bootable

            # req_size may be manipulated in the course of partitioning
            self.req_size = self._size

            # req_base_size will always remain constant
            self.req_base_size = self._size

            self.req_base_weight = weight

            self.req_start_sector = start
            self.req_end_sector = end

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  grow = %(grow)s  max size = %(maxsize)s  bootable = %(bootable)s\n"
              "  part type = %(partType)s  primary = %(primary)s"
              "  start sector = %(start)s  end sector = %(end)s\n"
              "  partedPartition = %(partedPart)s\n"
              "  disk = %(disk)s\n" %
              {"grow": self.req_grow, "maxsize": self.req_max_size,
               "bootable": self.bootable, "partType": self.partType,
               "primary": self.req_primary,
               "start": self.req_start_sector, "end": self.req_end_sector,
               "partedPart": self.partedPartition, "disk": self.disk})

        if self.partedPartition:
            s += ("  start = %(start)s  end = %(end)s  length = %(length)s\n"
                  "  flags = %(flags)s" %
                  {"length": self.partedPartition.geometry.length,
                   "start": self.partedPartition.geometry.start,
                   "end": self.partedPartition.geometry.end,
                   "flags": self.partedPartition.getFlagsAsString()})

        return s

    @property
    def dict(self):
        d = super(PartitionDevice, self).dict
        d.update({"type": self.partType})
        if not self.exists:
            d.update({"grow": self.req_grow, "maxsize": self.req_max_size,
                      "bootable": self.bootable,
                      "primary": self.req_primary})

        if self.partedPartition:
            d.update({"length": self.partedPartition.geometry.length,
                      "start": self.partedPartition.geometry.start,
                      "end": self.partedPartition.geometry.end,
                      "flags": self.partedPartition.getFlagsAsString()})
        return d

    def _setTargetSize(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if newsize != self.size:
            # change this partition's geometry in-memory so that other
            # partitioning operations can complete (e.g., autopart)
            super(PartitionDevice, self)._setTargetSize(newsize)
            disk = self.disk.format.partedDisk

            # resize the partition's geometry in memory
            (constraint, geometry) = self._computeResize(self.partedPartition)
            disk.setPartitionGeometry(partition=self.partedPartition,
                                      constraint=constraint,
                                      start=geometry.start, end=geometry.end)

    @property
    def path(self):
        if not self.parents:
            devDir = StorageDevice._devDir
        else:
            devDir = self.parents[0]._devDir

        return "%s/%s" % (devDir, self.name)

    @property
    def partType(self):
        """ Get the partition's type (as parted constant). """
        try:
            ptype = self.partedPartition.type
        except AttributeError:
            ptype = self._partType

        if not self.exists and ptype is None:
            ptype = self.req_partType

        return ptype

    @property
    def isExtended(self):
        return (self.partType is not None and
                self.partType & parted.PARTITION_EXTENDED)

    @property
    def isLogical(self):
        return (self.partType is not None and
                self.partType & parted.PARTITION_LOGICAL)

    @property
    def isPrimary(self):
        return (self.partType is not None and
                self.partType == parted.PARTITION_NORMAL)

    @property
    def isProtected(self):
        return (self.partType is not None and
                self.partType & parted.PARTITION_PROTECTED)

    @property
    def fstabSpec(self):
        spec = self.path
        if self.disk and self.disk.type == 'dasd':
            spec = deviceNameToDiskByPath(self.name)
        elif self.format and self.format.uuid:
            spec = "UUID=%s" % self.format.uuid
        return spec

    def _getPartedPartition(self):
        return self._partedPartition

    def _setPartedPartition(self, partition):
        """ Set this PartitionDevice's parted Partition instance. """
        log_method_call(self, self.name)

        if partition is not None and not isinstance(partition, parted.Partition):
            raise ValueError("partition must be None or a parted.Partition instance")

        log.debug("device %s new partedPartition %s", self.name, partition)
        self._partedPartition = partition
        self.updateName()

    partedPartition = property(lambda d: d._getPartedPartition(),
                               lambda d,p: d._setPartedPartition(p))

    def preCommitFixup(self, *args, **kwargs):
        """ Re-get self.partedPartition from the original disklabel. """
        log_method_call(self, self.name)
        if not self.exists:
            return

        # find the correct partition on the original parted.Disk since the
        # name/number we're now using may no longer match
        _disklabel = self.disk.originalFormat

        if self.isExtended:
            # getPartitionBySector doesn't work on extended partitions
            _partition = _disklabel.extendedPartition
            log.debug("extended lookup found partition %s",
                        devicePathToName(getattr(_partition, "path", None) or "(none)"))
        else:
            # lookup the partition by sector to avoid the renumbering
            # nonsense entirely
            _sector = self.partedPartition.geometry.start
            _partition = _disklabel.partedDisk.getPartitionBySector(_sector)
            log.debug("sector-based lookup found partition %s",
                        devicePathToName(getattr(_partition, "path", None) or "(none)"))

        self.partedPartition = _partition

    def _getWeight(self):
        return self.req_base_weight

    def _setWeight(self, weight):
        self.req_base_weight = weight

    weight = property(lambda d: d._getWeight(),
                      lambda d,w: d._setWeight(w))

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        if not self.parents:
            self.sysfsPath = ''

        elif isinstance(self.parents[0], DMDevice):
            dm_node = dm.dm_node_from_name(self.name)
            path = os.path.join("/sys", self.sysfsBlockDir, dm_node)
            self.sysfsPath = os.path.realpath(path)[4:]
        elif isinstance(self.parents[0], MDRaidArrayDevice):
            md_node = mdraid.md_node_from_name(self.name)
            path = os.path.join("/sys", self.sysfsBlockDir, md_node)
            self.sysfsPath = os.path.realpath(path)[4:]
        else:
            StorageDevice.updateSysfsPath(self)

    def _setName(self, value):
        self._name = value  # actual name setting is done by parted

    def updateName(self):
        if self.partedPartition is None:
            self.name = self.req_name
        else:
            self.name = \
                devicePathToName(self.partedPartition.getDeviceNodeName())

    def dependsOn(self, dep):
        """ Return True if this device depends on dep. """
        if isinstance(dep, PartitionDevice) and dep.isExtended and \
           self.isLogical and self.disk == dep.disk:
            return True

        return Device.dependsOn(self, dep)

    @property
    def isleaf(self):
        """ True if no other device depends on this one. """
        no_kids = super(PartitionDevice, self).isleaf
        # it is possible that the disk that originally contained this partition
        # no longer contains a disklabel, in which case we can assume that this
        # device is a leaf
        if self.disk and self.partedPartition and \
           self.disk.format.type == "disklabel" and \
           self.partedPartition in self.disk.format.partitions:
            disklabel = self.disk.format
        else:
            disklabel = None

        extended_has_logical = (self.isExtended and
                                (disklabel and disklabel.logicalPartitions))
        return (no_kids and not extended_has_logical)

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return self.isleaf and not self.isExtended

    def _setFormat(self, fmt):
        """ Set the Device's format. """
        log_method_call(self, self.name)
        StorageDevice._setFormat(self, fmt)

    def _setBootable(self, bootable):
        """ Set the bootable flag for this partition. """
        if self.partedPartition:
            if arch.isS390():
                return
            if self.flagAvailable(parted.PARTITION_BOOT):
                if bootable:
                    self.setFlag(parted.PARTITION_BOOT)
                else:
                    self.unsetFlag(parted.PARTITION_BOOT)
            else:
                raise errors.DeviceError("boot flag not available for this partition", self.name)

            self._bootable = bootable
        else:
            self.req_bootable = bootable

    def _getBootable(self):
        return self._bootable or self.req_bootable

    bootable = property(_getBootable, _setBootable)

    def flagAvailable(self, flag):
        if not self.partedPartition:
            return

        return self.partedPartition.isFlagAvailable(flag)

    def getFlag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.partedPartition or not self.flagAvailable(flag):
            return

        return self.partedPartition.getFlag(flag)

    def setFlag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.partedPartition or not self.flagAvailable(flag):
            return

        self.partedPartition.setFlag(flag)

    def unsetFlag(self, flag):
        log_method_call(self, path=self.path, flag=flag)
        if not self.partedPartition or not self.flagAvailable(flag):
            return

        self.partedPartition.unsetFlag(flag)

    @property
    def isMagic(self):
        if not self.disk:
            return False

        number = getattr(self.partedPartition, "number", -1)
        magic = self.disk.format.magicPartitionNumber
        return (number == magic)

    def probe(self):
        """ Probe for any missing information about this device.

            size, partition type, flags
        """
        log_method_call(self, self.name, exists=self.exists)
        if not self.exists:
            return

        self._size = Size(self.partedPartition.getLength(unit="B"))
        self._currentSize = self._size
        self.targetSize = self._size

        self._partType = self.partedPartition.type

        self._bootable = self.getFlag(parted.PARTITION_BOOT)

    def _wipe(self):
        """ Wipe the partition metadata. """
        log_method_call(self, self.name, status=self.status)

        start = self.partedPartition.geometry.start
        part_len = self.partedPartition.geometry.end - start
        bs = self.partedPartition.geometry.device.sectorSize
        device = self.partedPartition.geometry.device.path

        # Erase 1MiB or to end of partition
        count = int(Size("1 MiB") / bs)
        count = min(count, part_len)

        cmd = ["dd", "if=/dev/zero", "of=%s" % device, "bs=%s" % bs,
               "seek=%s" % start, "count=%s" % count]
        try:
            util.run_program(cmd)
        except OSError as e:
            log.error(str(e))
        finally:
            # If a udev device is created with the watch option, then
            # a change uevent is synthesized and we need to wait for
            # things to settle.
            udev.udev_settle()

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self.disk.format.addPartition(self.partedPartition)

        self._wipe()
        try:
            self.disk.format.commit()
        except errors.DiskLabelCommitError:
            part = self.disk.format.partedDisk.getPartitionByPath(self.path)
            self.disk.format.removePartition(part)
            raise

    def _postCreate(self):
        if self.isExtended:
            partition = self.disk.format.extendedPartition
        else:
            start = self.partedPartition.geometry.start
            partition = self.disk.format.partedDisk.getPartitionBySector(start)

        log.debug("post-commit partition path is %s", getattr(partition,
                                                             "path", None))
        self.partedPartition = partition
        if not self.isExtended:
            # Ensure old metadata which lived in freespace so did not get
            # explictly destroyed by a destroyformat action gets wiped
            DeviceFormat(device=self.path, exists=True).destroy()

        StorageDevice._postCreate(self)
        self._currentSize = Size(self.partedPartition.getLength(unit="B"))

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self._preCreate()
        try:
            self._create()
        except errors.DiskLabelCommitError as e:
            raise
        except Exception as e:
            raise errors.DeviceCreateError(str(e), self.name)
        else:
            self._postCreate()

    def _computeResize(self, partition):
        log_method_call(self, self.name, status=self.status)

        # compute new size for partition
        currentGeom = partition.geometry
        currentDev = currentGeom.device
        newLen = int(self.targetSize) / currentDev.sectorSize
        newGeometry = parted.Geometry(device=currentDev,
                                      start=currentGeom.start,
                                      length=newLen)
        # and align the end sector
        newGeometry.end = self.disk.format.endAlignment.alignDown(newGeometry,
                                                               newGeometry.end)
        constraint = parted.Constraint(exactGeom=newGeometry)

        return (constraint, newGeometry)

    def resize(self):
        log_method_call(self, self.name, status=self.status)
        self._preDestroy()

        # partedDisk has been restored to _origPartedDisk, so
        # recalculate resize geometry because we may have new
        # partitions on the disk, which could change constraints
        partedDisk = self.disk.format.partedDisk
        partition = partedDisk.getPartitionByPath(self.path)
        (constraint, geometry) = self._computeResize(partition)

        partedDisk.setPartitionGeometry(partition=partition,
                                        constraint=constraint,
                                        start=geometry.start,
                                        end=geometry.end)

        self.disk.format.commit()
        self._currentSize = Size(partition.getLength(unit="B"))

    def _preDestroy(self):
        StorageDevice._preDestroy(self)
        if not self.sysfsPath:
            return

        self.setupParents(orig=True)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        # we should have already set self.partedPartition to point to the
        # partition on the original disklabel
        self.disk.originalFormat.removePartition(self.partedPartition)
        try:
            self.disk.originalFormat.commit()
        except errors.DiskLabelCommitError:
            self.disk.originalFormat.addPartition(self.partedPartition)
            self.partedPartition = self.disk.originalFormat.partedDisk.getPartitionByPath(self.path)
            raise

        if self.disk.format.exists and \
           self.disk.format.type == "disklabel" and \
           self.disk.format.partedDisk != self.disk.originalFormat.partedDisk:
            # If the new/current disklabel is the same as the original one, we
            # have to duplicate the removal on the other copy of the DiskLabel.
            part = self.disk.format.partedDisk.getPartitionByPath(self.path)
            self.disk.format.removePartition(part)
            self.disk.format.commit()

    def _postDestroy(self):
        super(PartitionDevice, self)._postDestroy()
        if isinstance(self.disk, DMDevice):
            udev.udev_settle()
            if self.status:
                try:
                    dm.dm_remove(self.name)
                except (errors.DMError, OSError):
                    pass

    def deactivate(self):
        """
        This is never called. For instructional purposes only.

        We do not want multipath partitions disappearing upon their teardown().
        """
        if self.parents[0].type == 'dm-multipath':
            devmap = block.getMap(major=self.major, minor=self.minor)
            if devmap:
                try:
                    block.removeDeviceMap(devmap)
                except Exception as e:
                    raise errors.DeviceTeardownError("failed to tear down device-mapper partition %s: %s" % (self.name, e))
            udev.udev_settle()

    def _getSize(self):
        """ Get the device's size. """
        size = self._size
        if self.partedPartition:
            size = Size(self.partedPartition.getLength(unit="B"))
        return size

    def _setSize(self, newsize):
        """ Set the device's size (for resize, not creation).

            Arguments:

                newsize -- the new size

        """
        log_method_call(self, self.name,
                        status=self.status, size=self._size, newsize=newsize)
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if not self.exists:
            raise errors.DeviceError("device does not exist", self.name)

        if newsize > self.disk.size:
            raise ValueError("partition size would exceed disk size")

        maxAvailableSize = Size(self.partedPartition.getMaxAvailableSize(unit="B"))

        if newsize > maxAvailableSize:
            raise ValueError("new size is greater than available space")

         # now convert the size to sectors and update the geometry
        geometry = self.partedPartition.geometry
        physicalSectorSize = geometry.device.physicalSectorSize

        new_length = int(newsize) / physicalSectorSize
        geometry.length = new_length

    def _getDisk(self):
        """ The disk that contains this partition."""
        try:
            disk = self.parents[0]
        except IndexError:
            disk = None
        return disk

    def _setDisk(self, disk):
        """Change the parent.

        Setting up a disk is not trivial.  It has the potential to change
        the underlying object.  If necessary we must also change this object.
        """
        log_method_call(self, self.name, old=getattr(self.disk, "name", None),
                        new=getattr(disk, "name", None))
        self.parents = []
        if disk:
            self.parents.append(disk)

    disk = property(lambda p: p._getDisk(), lambda p,d: p._setDisk(d))

    @property
    def maxSize(self):
        """ The maximum size this partition can be. """
        # XXX Only allow growth up to the amount of free space following this
        #     partition on disk. We don't care about leading free space --
        #     a filesystem cannot be relocated, so if you want to use space
        #     before and after your partition, remove it and create a new one.
        sector = self.partedPartition.geometry.end + 1
        maxPartSize = self.size
        try:
            partition = self.partedPartition.disk.getPartitionBySector(sector)
        except _ped.PartitionException:
            pass
        else:
            if partition.type == parted.PARTITION_FREESPACE:
                maxPartSize = self.size + Size(partition.getLength(unit="B"))

        maxFormatSize = self.format.maxSize
        return min(maxFormatSize, maxPartSize) if maxFormatSize else maxPartSize

    @property
    def currentSize(self):
        if self.exists:
            return self._currentSize
        else:
            return 0

    @property
    def resizable(self):
        return super(PartitionDevice, self).resizable and \
               self.disk.type != 'dasd'

    def checkSize(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.maxSize and self.size > self.format.maxSize:
            return 1
        elif (self.format.minSize and
              (not self.req_grow and
               self.size < self.format.minSize) or
              (self.req_grow and self.req_max_size and
               self.req_max_size < self.format.minSize)):
            return -1
        return 0

    def populateKSData(self, data):
        super(PartitionDevice, self).populateKSData(data)
        data.resize = (self.exists and self.targetSize and
                       self.targetSize != self.currentSize)
        if not self.exists:
            data.size = self.req_base_size.convertTo(spec="MiB")
            data.grow = self.req_grow
            if self.req_grow:
                data.maxSizeMB = self.req_max_size.convertTo(spec="MiB")

            ##data.disk = self.disk.name                      # by-id
            if self.req_disks and len(self.req_disks) == 1:
                data.disk = self.disk.name
            data.primOnly = self.req_primary
        else:
            data.onPart = self.name                     # by-id

            if data.resize:
                data.size = self.size.convertTo(spec="MiB")

class DMDevice(StorageDevice):
    """ A device-mapper device """
    _type = "dm"
    _devDir = "/dev/mapper"

    def __init__(self, name, fmt=None, size=None, dmUuid=None, uuid=None,
                 target=None, exists=False, parents=None, sysfsPath=''):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword dmUuid: device-mapper UUID (see note below)
            :type dmUuid: str
            :type str uuid: device UUID (see note below)
            :keyword target: device mapper table/target name (eg: "linear")
            :type target: str

            .. note::

                The dmUuid is not necessarily persistent, as it is based on
                map name in many cases. The uuid, however, is a persistent UUID
                stored in device metadata on disk.
        """
        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               exists=exists, uuid=uuid,
                               parents=parents, sysfsPath=sysfsPath)
        self.target = target
        self.dmUuid = dmUuid

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  target = %(target)s  dmUuid = %(dmUuid)s" %
              {"target": self.target, "dmUuid": self.dmUuid})
        return s

    @property
    def dict(self):
        d = super(DMDevice, self).dict
        d.update({"target": self.target, "dmUuid": self.dmUuid})
        return d

    @property
    def fstabSpec(self):
        """ Return the device specifier for use in /etc/fstab. """
        return self.path

    @property
    def mapName(self):
        """ This device's device-mapper map name """
        return self.name

    @property
    def status(self):
        match = next((m for m in block.dm.maps() if m.name == self.mapName),
           None)
        return (match.live_table and not match.suspended) if match else False

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if self.status:
            dm_node = self.getDMNode()
            path = os.path.join("/sys", self.sysfsBlockDir, dm_node)
            self.sysfsPath = os.path.realpath(path)[4:]
        else:
            self.sysfsPath = ''

    #def getTargetType(self):
    #    return dm.getDmTarget(name=self.name)

    def getDMNode(self):
        """ Return the dm-X (eg: dm-0) device node for this device. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        return dm.dm_node_from_name(self.name)

    def setupPartitions(self):
        log_method_call(self, name=self.name, kids=self.kids)
        rc = util.run_program(["kpartx", "-a", "-s", self.path])
        if rc:
            raise errors.DMError("partition activation failed for '%s'" % self.name)
        udev.udev_settle()

    def teardownPartitions(self):
        log_method_call(self, name=self.name, kids=self.kids)
        rc = util.run_program(["kpartx", "-d", "-s", self.path])
        if rc:
            raise errors.DMError("partition deactivation failed for '%s'" % self.name)
        udev.udev_settle()
        for dev in os.listdir("/dev/mapper/"):
            prefix = self.name + "p"
            if dev.startswith(prefix) and dev[len(prefix):].isdigit():
                dm.dm_remove(dev)

    def _setName(self, value):
        """ Set the device's map name. """
        if value == self._name:
            return

        log_method_call(self, self.name, status=self.status)
        if self.status:
            raise errors.DeviceError("cannot rename active device", self.name)

        super(DMDevice, self)._setName(value)
        #self.sysfsPath = "/dev/disk/by-id/dm-name-%s" % self.name

    @property
    def slave(self):
        """ This device's backing device. """
        return self.parents[0]


class DMLinearDevice(DMDevice):
    _type = "dm-linear"
    _partitionable = True
    _isDisk = True

    def __init__(self, name, fmt=None, size=None, dmUuid=None,
                 exists=False, parents=None, sysfsPath=''):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword dmUuid: device-mapper UUID
            :type dmUuid: str
        """
        if not parents:
            raise ValueError("DMLinearDevice requires a backing block device")

        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfsPath=sysfsPath,
                          exists=exists, target="linear", dmUuid=dmUuid)

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        slave_length = self.slave.partedDevice.length
        dm.dm_create_linear(self.name, self.slave.path, slave_length,
                            self.dmUuid)

    def _postSetup(self):
        StorageDevice._postSetup(self)
        self.setupPartitions()
        udev.udev_settle()

    def _teardown(self, recursive=False):
        self.teardownPartitions()
        udev.udev_settle()
        dm.dm_remove(self.name)
        udev.udev_settle()

    def deactivate(self, recursive=False):
        StorageDevice.teardown(self, recursive=recursive)

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._preTeardown(recursive=recursive):
            return

        log.debug("not tearing down dm-linear device %s", self.name)

    @property
    def description(self):
        return self.model


class DMCryptDevice(DMDevice):
    """ A dm-crypt device """
    _type = "dm-crypt"

    def __init__(self, name, fmt=None, size=None, uuid=None,
                 exists=False, sysfsPath='', parents=None):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
        """
        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfsPath=sysfsPath,
                          exists=exists, target="crypt")

class LUKSDevice(DMCryptDevice):
    """ A mapped LUKS device. """
    _type = "luks/dm-crypt"
    _packages = ["cryptsetup"]

    def __init__(self, name, fmt=None, size=None, uuid=None,
                 exists=False, sysfsPath='', parents=None):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword uuid: the device UUID
            :type uuid: str
        """
        DMCryptDevice.__init__(self, name, fmt=fmt, size=size,
                               parents=parents, sysfsPath=sysfsPath,
                               uuid=None, exists=exists)

    @property
    def raw_device(self):
        return self.slave

    @property
    def size(self):
        if not self.exists or not self.partedDevice:
            size = self.slave.size - crypto.LUKS_METADATA_SIZE
        else:
            size = Size(self.partedDevice.getLength(unit="B"))
        return size

    def _postCreate(self):
        self.name = self.slave.format.mapName
        StorageDevice._postCreate(self)

    def _postTeardown(self, recursive=False):
        if not recursive:
            # this is handled by StorageDevice._postTeardown if recursive
            # is True
            self.teardownParents(recursive=recursive)

        StorageDevice._postTeardown(self, recursive=recursive)

    def dracutSetupArgs(self):
        return set(["rd.luks.uuid=luks-%s" % self.slave.format.uuid])

    def populateKSData(self, data):
        self.slave.populateKSData(data)
        data.encrypted = True
        super(LUKSDevice, self).populateKSData(data)

class ContainerDevice(with_metaclass(abc.ABCMeta, StorageDevice)):
    """ A device that aggregates a set of member devices.

        The only interfaces provided by this class are for addition and removal
        of member devices -- one set for modifying the member set of the
        python objects, and one for writing the changes to disk.

        The member set of the instance can be manipulated using the methods
        :meth:`~.ParentList.append` and :meth:`~.ParentList.remove` of the
        instance's :attr:`~.Device.parents` attribute.

        :meth:`add` and :meth:`remove` remove a member from the container's on-
        disk representation. These methods should normally only be called from
        within :meth:`.deviceaction.ActionAddMember.execute` and
        :meth:`.deviceaction.ActionRemoveMember.execute`.
    """

    _formatClassName = abc.abstractproperty(lambda s: None,
        doc="The type of member devices' required format")
    _formatUUIDAttr = abc.abstractproperty(lambda s: None,
        doc="The container UUID attribute in the member format class")

    def __init__(self, *args, **kwargs):
        self.formatClass = get_device_format_class(self._formatClassName)
        if not self.formatClass:
            raise errors.StorageError("cannot find '%s' class" % self._formatClassName)

        super(ContainerDevice, self).__init__(*args, **kwargs)

    def _addParent(self, member):
        """ Add a member device to the container.

            :param member: the member device to add
            :type member: :class:`.StorageDevice`

            This operates on the in-memory model and does not alter disk
            contents at all.
        """
        log_method_call(self, self.name, member=member.name)
        if not isinstance(member.format, self.formatClass):
            raise ValueError("member has wrong format")

        if member.format.exists and self.uuid and self._formatUUIDAttr and \
           getattr(member.format, self._formatUUIDAttr) != self.uuid:
            raise ValueError("cannot add member with mismatched UUID")

        super(ContainerDevice, self)._addParent(member)

    @abc.abstractmethod
    def _add(self, member):
        """ Device-type specific code to add a member to the container.

            :param member: the member device to add
            :type member: :class:`.StorageDevice`

            This method writes the member addition to disk.
        """
        raise NotImplementedError()

    def add(self, member):
        """ Add a member to the container.

            :param member: the member device to add
            :type member: :class:`.StorageDevice`

            This method writes the member addition to disk.
        """
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if member.format.exists and self.uuid and self._formatUUIDAttr and \
           getattr(member.format, self._formatUUIDAttr) == self.uuid:
            log.error("cannot re-add member: %s", member)
            raise ValueError("cannot add members that are already part of the container")

        self._add(member)

        if member not in self.parents:
            self.parents.append(member)

    @abc.abstractmethod
    def _remove(self, member):
        """ Device-type specific code to remove a member from the container.

            :param member: the member device to remove
            :type member: :class:`.StorageDevice`

            This method writes the member removal to disk.
        """
        raise NotImplementedError()

    def remove(self, member):
        """ Remove a member from the container.

            :param member: the member device to remove
            :type member: :class:`.StorageDevice`

            This method writes the member removal to disk.
        """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if self._formatUUIDAttr and self.uuid and \
           getattr(member.format, self._formatUUIDAttr) != self.uuid:
            log.error("cannot remove non-member: %s (%s/%s)", member, getattr(member.format, self._formatUUIDAttr), self.uuid)
            raise ValueError("cannot remove members that are not part of the container")

        self._remove(member)

        if member in self.parents:
            self.parents.remove(member)


class LVMVolumeGroupDevice(ContainerDevice):
    """ An LVM Volume Group """
    _type = "lvmvg"
    _packages = ["lvm2"]
    _formatClassName = property(lambda s: "lvmpv")
    _formatUUIDAttr = property(lambda s: "vgUuid")

    def __init__(self, name, parents=None, size=None, free=None,
                 peSize=None, peCount=None, peFree=None, pvCount=None,
                 uuid=None, exists=False, sysfsPath=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword peSize: physical extent size
            :type peSize: :class:`~.size.Size`

            For existing VG's only:

            :keyword size: the VG's size
            :type size: :class:`~.size.Size`
            :keyword free -- amount of free space in the VG
            :type free: :class:`~.size.Size`
            :keyword peFree: number of free extents
            :type peFree: int
            :keyword peCount -- total number of extents
            :type peCount: int
            :keyword pvCount: number of PVs in this VG
            :type pvCount: int
            :keyword uuid: the VG UUID
            :type uuid: str
        """
        # These attributes are used by _addParent, so they must be initialized
        # prior to instantiating the superclass.
        self._lvs = []
        self.hasDuplicate = False
        self._complete = False  # have we found all of this VG's PVs?
        self.pvCount = util.numeric_type(pvCount)
        if exists and not pvCount:
            self._complete = True

        super(LVMVolumeGroupDevice, self).__init__(name, parents=parents,
                                            uuid=uuid, size=size,
                                            exists=exists, sysfsPath=sysfsPath)

        self.free = util.numeric_type(free)
        self.peSize = util.numeric_type(peSize)
        self.peCount = util.numeric_type(peCount)
        self.peFree = util.numeric_type(peFree)
        self.reserved_percent = 0
        self.reserved_space = Size(0)

        # this will have to be covered by the 20% pad for non-existent pools
        self.poolMetaData = 0

        # TODO: validate peSize if given
        if not self.peSize:
            self.peSize = lvm.LVM_PE_SIZE

        if not self.exists:
            self.pvCount = len(self.parents)

        # >0 is fixed
        self.size_policy = self.size

    def __repr__(self):
        s = super(LVMVolumeGroupDevice, self).__repr__()
        s += ("  free = %(free)s  PE Size = %(peSize)s  PE Count = %(peCount)s\n"
              "  PE Free = %(peFree)s  PV Count = %(pvCount)s\n"
              "  modified = %(modified)s"
              "  extents = %(extents)s  free space = %(freeSpace)s\n"
              "  free extents = %(freeExtents)s"
              "  reserved percent = %(rpct)s  reserved space = %(res)s\n"
              "  PVs = %(pvs)s\n"
              "  LVs = %(lvs)s" %
              {"free": self.free, "peSize": self.peSize, "peCount": self.peCount,
               "peFree": self.peFree, "pvCount": self.pvCount,
               "modified": self.isModified,
               "extents": self.extents, "freeSpace": self.freeSpace,
               "freeExtents": self.freeExtents,
               "rpct": self.reserved_percent, "res": self.reserved_space,
               "pvs": pprint.pformat([str(p) for p in self.pvs]),
               "lvs": pprint.pformat([str(l) for l in self.lvs])})
        return s

    @property
    def dict(self):
        d = super(LVMVolumeGroupDevice, self).dict
        d.update({"free": self.free, "peSize": self.peSize,
                  "peCount": self.peCount, "peFree": self.peFree,
                  "pvCount": self.pvCount, "extents": self.extents,
                  "freeSpace": self.freeSpace,
                  "freeExtents": self.freeExtents,
                  "reserved_percent": self.reserved_percent,
                  "reserved_space": self.reserved_space,
                  "lvNames": [lv.name for lv in self.lvs]})
        return d

    @property
    def mapName(self):
        """ This device's device-mapper map name """
        # Thank you lvm for this lovely hack.
        return self.name.replace("-","--")

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._devDir, self.mapName)

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        self.sysfsPath = ''

    @property
    def status(self):
        """ The device's status (True means active). """
        if not self.exists:
            return False

        # certainly if any of this VG's LVs are active then so are we
        for lv in self.lvs:
            if lv.status:
                return True

        # if any of our PVs are not active then we cannot be
        for pv in self.pvs:
            if not pv.status:
                return False

        # if we are missing some of our PVs we cannot be active
        if not self.complete:
            return False

        return True

    def _preSetup(self, orig=False):
        if self.exists and not self.complete:
            raise errors.DeviceError("cannot activate VG with missing PV(s)", self.name)
        return StorageDevice._preSetup(self, orig=orig)

    def _teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        lvm.vgdeactivate(self.name)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        pv_list = [pv.path for pv in self.parents]
        lvm.vgcreate(self.name, pv_list, self.peSize)

    def _postCreate(self):
        self._complete = True
        super(LVMVolumeGroupDevice, self)._postCreate()

    def _preDestroy(self):
        StorageDevice._preDestroy(self)
        # set up the pvs since lvm needs access to them to do the vgremove
        self.setupParents(orig=True)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        if not self.complete:
            for pv in self.pvs:
                # Remove the PVs from the ignore filter so we can wipe them.
                lvm.lvm_cc_removeFilterRejectRegexp(pv.name)

            # Don't run vgremove or vgreduce since there may be another VG with
            # the same name that we want to keep/use.
            return

        lvm.vgreduce(self.name, None, missing=True)
        lvm.vgdeactivate(self.name)
        lvm.vgremove(self.name)

    def _remove(self, member):
        status = []
        for lv in self.lvs:
            status.append(lv.status)
            if lv.exists:
                lv.setup()

        lvm.pvmove(member.path)
        lvm.vgreduce(self.name, member.path)

        for (lv, status) in zip(self.lvs, status):
            if lv.status and not status:
                lv.teardown()

    def _add(self, member):
        lvm.vgextend(self.name, member.path)

    def _addLogVol(self, lv):
        """ Add an LV to this VG. """
        if lv in self._lvs:
            raise ValueError("lv is already part of this vg")

        # verify we have the space, then add it
        # do not verify for growing vg (because of ks)
        # FIXME: add a "isthin" property and/or "ispool"?
        if not lv.exists and not self.growable and \
           not isinstance(lv, LVMThinLogicalVolumeDevice) and \
           lv.size > self.freeSpace:
            raise errors.DeviceError("new lv is too large to fit in free space", self.name)

        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.append(lv)

    def _removeLogVol(self, lv):
        """ Remove an LV from this VG. """
        if lv not in self.lvs:
            raise ValueError("specified lv is not part of this vg")

        self._lvs.remove(lv)

        if self.poolMetaData and not self.thinpools:
            self.poolMetaData = 0

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.remove(lv)

    def _addParent(self, member):
        super(LVMVolumeGroupDevice, self)._addParent(member)

        # now see if the VG can be activated
        ## XXX TODO: remove this activation code
        if self.exists and member.format.exists and self.complete and \
           flags.installer_mode:
            self.setup()

        if (self.exists and member.format.exists and
            len(self.parents) + 1 == self.pvCount):
            self._complete = True

    def _removeParent(self, member):
        # XXX It would be nice to raise an exception if removing this member
        #     would not leave enough space, but the devicefactory relies on it
        #     being possible to _temporarily_ overcommit the VG.
        #
        #     Maybe removeMember could be a wrapper with the checks and the
        #     devicefactory could call the _ versions to bypass the checks.
        super(LVMVolumeGroupDevice, self)._removeParent(member)

    # We can't rely on lvm to tell us about our size, free space, &c
    # since we could have modifications queued, unless the VG and all of
    # its PVs already exist.
    #
    #        -- liblvm may contain support for in-memory devices

    @property
    def isModified(self):
        """ Return True if the VG has changes queued that LVM is unaware of. """
        modified = True
        if self.exists and not [d for d in self.pvs if not d.exists]:
            modified = False

        return modified

    @property
    def reservedSpace(self):
        """ Reserved space in this VG """
        reserved = Size(0)
        if self.reserved_percent > 0:
            reserved = self.reserved_percent * Decimal('0.01') * self.size
        elif self.reserved_space > 0:
            reserved = self.reserved_space

        return self.align(reserved, roundup=True)

    @property
    def size(self):
        """ The size of this VG """
        # TODO: just ask lvm if isModified returns False

        # sum up the sizes of the PVs and align to pesize
        size = 0
        for pv in self.pvs:
            size += max(0, self.align(pv.size - pv.format.peStart))

        return size

    @property
    def extents(self):
        """ Number of extents in this VG """
        # TODO: just ask lvm if isModified returns False

        return int(self.size / self.peSize)

    @property
    def freeSpace(self):
        """ The amount of free space in this VG. """
        # TODO: just ask lvm if isModified returns False

        # get the number of disks used by PVs on RAID (if any)
        raid_disks = 0
        for pv in self.pvs:
            if isinstance(pv, MDRaidArrayDevice):
                raid_disks = max([raid_disks, len(pv.disks)])

        # total the sizes of any LVs
        log.debug("%s size is %s", self.name, self.size)
        used = sum(lv.vgSpaceUsed for lv in self.lvs)
        if not self.exists and raid_disks:
            # (only) we allocate (5 * num_disks) extra extents for LV metadata
            # on RAID (see the devicefactory.LVMFactory._get_total_space method)
            new_lvs = [lv for lv in self.lvs if not lv.exists]
            used += len(new_lvs) * 5 * raid_disks * self.peSize
        used += self.reservedSpace
        used += self.poolMetaData
        free = self.size - used
        log.debug("vg %s has %s free", self.name, free)
        return free

    @property
    def freeExtents(self):
        """ The number of free extents in this VG. """
        # TODO: just ask lvm if isModified returns False
        return int(self.freeSpace / self.peSize)

    def align(self, size, roundup=None):
        """ Align a size to a multiple of physical extent size. """
        size = util.numeric_type(size)

        return lvm.clampSize(size, self.peSize, roundup=roundup)

    @property
    def pvs(self):
        """ A list of this VG's PVs """
        return self.parents[:]

    @property
    def lvs(self):
        """ A list of this VG's LVs """
        return self._lvs[:]

    @property
    def thinpools(self):
        return [l for l in self._lvs if isinstance(l, LVMThinPoolDevice)]

    @property
    def thinlvs(self):
        return [l for l in self._lvs if isinstance(l, LVMThinLogicalVolumeDevice)]

    @property
    def complete(self):
        """Check if the vg has all its pvs in the system
        Return True if complete.
        """
        # vgs with duplicate names are overcomplete, which is not what we want
        if self.hasDuplicate:
            return False

        return self._complete or not self.exists

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return False

    def populateKSData(self, data):
        super(LVMVolumeGroupDevice, self).populateKSData(data)
        data.vgname = self.name
        data.physvols = ["pv.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        if not self.exists:
            data.pesize = self.peSize.convertTo(spec="KiB")

        # reserved percent/space

    @classmethod
    def isNameValid(cls, name):
        # No . or ..
        if name == '.' or name == '..':
            return False

        # Check that all characters are in the allowed set and that the name
        # does not start with a -
        if not re.match('^[a-zA-Z0-9+_.][a-zA-Z0-9+_.-]*$', name):
            return False

        # According to the LVM developers, vgname + lvname is limited to 126 characters
        # minus the number of hyphens, and possibly minus up to another 8 characters
        # in some unspecified set of situations. Instead of figuring all of that out,
        # no one gets a vg or lv name longer than, let's say, 55.
        if len(name) > 55:
            return False

        return True

class LVMLogicalVolumeDevice(DMDevice):
    """ An LVM Logical Volume """
    _type = "lvmlv"
    _resizable = True
    _packages = ["lvm2"]

    def __init__(self, name, parents=None, size=None, uuid=None,
                 copies=1, logSize=0, segType=None,
                 fmt=None, exists=False, sysfsPath='',
                 grow=None, maxsize=None, percent=None,
                 singlePV=False):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword uuid: the device UUID
            :type uuid: str

            For existing LVs only:

            :keyword copies: number of copies in the vg (>1 for mirrored lvs)
            :type copies: int
            :keyword logSize: size of log volume (for mirrored lvs)
            :type logSize: :class:`~.size.Size`
            :keyword singlePV: if true, maps this lv to a single pv
            :type singlePV: bool
            :keyword segType: segment type (eg: "linear", "raid1")
            :type segType: str

            For non-existent LVs only:

            :keyword grow: whether to grow this LV
            :type grow: bool
            :keyword maxsize: maximum size for growable LV
            :type maxsize: :class:`~.size.Size`
            :keyword percent -- percent of VG space to take
            :type percent: int

        """
        if self.__class__.__name__ == "LVMLogicalVolumeDevice":
            if isinstance(parents, list):
                if len(parents) != 1:
                    raise ValueError("constructor requires a single LVMVolumeGroupDevice instance")
                elif not isinstance(parents[0], LVMVolumeGroupDevice):
                    raise ValueError("constructor requires a LVMVolumeGroupDevice instance")
            elif not isinstance(parents, LVMVolumeGroupDevice):
                raise ValueError("constructor requires a LVMVolumeGroupDevice instance")
        DMDevice.__init__(self, name, size=size, fmt=fmt,
                          sysfsPath=sysfsPath, parents=parents,
                          exists=exists)

        self.singlePVerr = ("%(mountpoint)s is restricted to a single "
                            "physical volume on this platform.  No physical "
                            "volumes available in volume group %(vgname)s "
                            "with %(size)s of available space." %
                           {'mountpoint': getattr(self.format, "mountpoint",
                                                  "A proposed logical volume"),
                            'vgname': self.vg.name,
                            'size': self.size})

        self.uuid = uuid
        self.copies = copies
        self.logSize = logSize
        self.metaDataSize = 0
        self.singlePV = singlePV
        self.segType = segType or "linear"
        self.snapshots = []

        self.req_grow = None
        self.req_max_size = Size(0)
        self.req_size = Size(0)
        self.req_percent = 0

        if not self.exists:
            self.req_grow = grow
            self.req_max_size = Size(util.numeric_type(maxsize))
            # XXX should we enforce that req_size be pe-aligned?
            self.req_size = self._size
            self.req_percent = util.numeric_type(percent)

        if self.singlePV:
            # make sure there is at least one PV that can hold this LV
            validpvs = [x for x in self.vg.pvs if float(x.size) >= self.req_size]
            if not validpvs:
                for dev in self.parents:
                    dev.removeChild()
                raise errors.SinglePhysicalVolumeError(self.singlePVerr)

        # here we go with the circular references
        self.parents[0]._addLogVol(self)

    def __repr__(self):
        s = DMDevice.__repr__(self)
        s += ("  VG device = %(vgdev)r\n"
              "  segment type = %(type)s percent = %(percent)s\n"
              "  mirror copies = %(copies)d"
              "  VG space used = %(vgspace)s" %
              {"vgdev": self.vg, "percent": self.req_percent,
               "copies": self.copies, "type": self.segType,
               "vgspace": self.vgSpaceUsed })
        return s

    @property
    def dict(self):
        d = super(LVMLogicalVolumeDevice, self).dict
        if self.exists:
            d.update({"copies": self.copies,
                      "vgspace": self.vgSpaceUsed})
        else:
            d.update({"percent": self.req_percent})

        return d

    @property
    def mirrored(self):
        return self.copies > 1

    def _setSize(self, size):
        if not isinstance(size, Size):
            raise ValueError("new size must of type Size")

        size = self.vg.align(size)
        log.debug("trying to set lv %s size to %s", self.name, size)
        if size <= self.vg.freeSpace + self.vgSpaceUsed:
            self._size = size
            self.targetSize = size
        else:
            log.debug("failed to set size: %s short", size - (self.vg.freeSpace + self.vgSpaceUsed))
            raise ValueError("not enough free space in volume group")

    size = property(StorageDevice._getSize, _setSize)

    @property
    def maxSize(self):
        """ The maximum size this lv can be. """
        max_lv = self.size + self.vg.freeSpace
        max_format = self.format.maxSize
        return min(max_lv, max_format) if max_format else max_lv

    @property
    def vgSpaceUsed(self):
        """ Space occupied by this LV, not including snapshots. """
        return (self.vg.align(self.size, roundup=True) * self.copies
                + self.logSize + self.metaDataSize)

    @property
    def vg(self):
        """ This Logical Volume's Volume Group. """
        return self.parents[0]

    @property
    def container(self):
        return self.vg

    @property
    def mapName(self):
        """ This device's device-mapper map name """
        # Thank you lvm for this lovely hack.
        return "%s-%s" % (self.vg.mapName, self._name.replace("-","--"))

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._devDir, self.mapName)

    def getDMNode(self):
        """ Return the dm-X (eg: dm-0) device node for this device. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        return dm.dm_node_from_name(self.mapName)

    def _getName(self):
        """ This device's name. """
        return "%s-%s" % (self.vg.name, self._name)

    @property
    def lvname(self):
        """ The LV's name (not including VG name). """
        return self._name

    @property
    def complete(self):
        """ Test if vg exits and if it has all pvs. """
        return self.vg.complete

    def setupParents(self, orig=False):
        # parent is a vg, which has no formatting (or device for that matter)
        Device.setupParents(self, orig=orig)

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        lvm.lvactivate(self.vg.name, self._name)

    def _teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        lvm.lvdeactivate(self.vg.name, self._name)

    def _postTeardown(self, recursive=False):
        try:
            # It's likely that teardown of a VG will fail due to other
            # LVs being active (filesystems mounted, &c), so don't let
            # it bring everything down.
            StorageDevice._postTeardown(self, recursive=recursive)
        except errors.StorageError:
            if recursive:
                log.debug("vg %s teardown failed; continuing", self.vg.name)
            else:
                raise

    def _preCreate(self):
        super(LVMLogicalVolumeDevice, self)._preCreate()

        try:
            vg_info = lvm.vginfo(self.vg.name)
        except errors.LVMError as lvmerr:
            log.error("Failed to get free space for the %s VG: %s", self.vg.name, lvmerr)
            # nothing more can be done, we don't know the VG's free space
            return

        extent_size = Size(vg_info["LVM2_VG_EXTENT_SIZE"] + "MiB")
        extents_free = int(vg_info["LVM2_VG_FREE_COUNT"])
        can_use = extent_size * extents_free

        if self.size > can_use:
            msg = ("%s LV's size (%s) exceeds the VG's usable free space (%s),"
                  "shrinking the LV") % (self.name, self.size, can_use)
            log.warning(msg)
            self.size = can_use

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        # should we use --zero for safety's sake?
        if self.singlePV:
            lvm.lvcreate(self.vg.name, self._name, self.size,
                         pvs=self._getSinglePV())
        else:
            lvm.lvcreate(self.vg.name, self._name, self.size)

    def _preDestroy(self):
        StorageDevice._preDestroy(self)
        # set up the vg's pvs so lvm can remove the lv
        self.vg.setupParents(orig=True)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        lvm.lvremove(self.vg.name, self._name)

    def _getSinglePV(self):
        validpvs = [x for x in self.vg.pvs if float(x.size) >= self.size]

        if not validpvs:
            raise errors.SinglePhysicalVolumeError(self.singlePVerr)

        return [validpvs[0].path]

    def resize(self):
        log_method_call(self, self.name, status=self.status)

        # Setup VG parents (in case they are dmraid partitions for example)
        self.vg.setupParents(orig=True)

        if self.originalFormat.exists:
            self.originalFormat.teardown()
        if self.format.exists:
            self.format.teardown()

        udev.udev_settle()
        lvm.lvresize(self.vg.name, self._name, self.size)

    @property
    def isleaf(self):
        # Thin snapshots do not need to be removed prior to removal of the
        # origin, but the old snapshots do.
        non_thin_snapshots = any(s for s in self.snapshots
                                    if not isinstance(s, LVMThinSnapShotDevice))
        return (super(LVMLogicalVolumeDevice, self).isleaf and
                not non_thin_snapshots)

    @property
    def direct(self):
        """ Is this device directly accessible? """
        # an LV can contain a direct filesystem if it is a leaf device or if
        # its only dependent devices are snapshots
        return super(LVMLogicalVolumeDevice, self).isleaf

    def dracutSetupArgs(self):
        # Note no mapName usage here, this is a lvm cmdline name, which
        # is different (ofcourse)
        return set(["rd.lvm.lv=%s/%s" % (self.vg.name, self._name)])

    def checkSize(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.maxSize and self.size > self.format.maxSize:
            return 1
        elif (self.format.minSize and
              (not self.req_grow and
               self.size < self.format.minSize) or
              (self.req_grow and self.req_max_size and
               self.req_max_size < self.format.minSize)):
            return -1
        return 0

    def populateKSData(self, data):
        super(LVMLogicalVolumeDevice, self).populateKSData(data)
        data.vgname = self.vg.name
        data.name = self.lvname
        data.preexist = self.exists
        data.resize = (self.exists and self.targetSize and
                       self.targetSize != self.currentSize)
        if not self.exists:
            data.grow = self.req_grow
            if self.req_grow:
                data.size = self.req_size.convertTo(spec="MiB")
                data.maxSizeMB = self.req_max_size.convertTo(spec="MiB")
            else:
                data.size = self.size.convertTo(spec="MiB")

            data.percent = self.req_percent
        elif data.resize:
            data.size = self.targetSize.convertTo(spec="MiB")

    @classmethod
    def isNameValid(cls, name):
        # Check that the LV name is valid

        # Start with the checks shared with volume groups
        if not LVMVolumeGroupDevice.isNameValid(name):
            return False

        # And now the ridiculous ones
        # These strings are taken from apply_lvname_restrictions in lib/misc/lvm-string.c
        reserved_prefixes = set(['pvmove', 'snapshot'])
        reserved_substrings = set(['_cdata', '_cmeta', '_mimage', '_mlog', '_pmspare', '_rimage',
                                   '_rmeta', '_tdata', '_tmeta', '_vorigin'])

        for prefix in reserved_prefixes:
            if name.startswith(prefix):
                return False

        for substring in reserved_substrings:
            if substring in name:
                return False

        return True

class LVMSnapShotBase(with_metaclass(abc.ABCMeta, object)):
    """ Abstract base class for lvm snapshots

        This class is intended to be used with multiple inheritance in addition
        to some subclass of :class:`~.StorageDevice`.

        Snapshots do not have their origin/source volume as parent. They are
        like other LVs except that they have an origin attribute and are in that
        instance's snapshots list.

        Normal/old snapshots must be removed with their origin, while thin
        snapshots can remain after their origin is removed.

        It is also impossible to set the format for a snapshot explicitly as it
        always has the same format as its origin.
    """
    _type = "lvmsnapshotbase"

    def __init__(self, origin=None, vorigin=False, exists=False):
        """
            :keyword :class:`~.LVMLogicalVolumeDevice` origin: source volume
            :keyword bool vorigin: is this a vorigin snapshot?
            :keyword bool exists: is this an existing snapshot?

            vorigin is a special type of device that makes use of snapshots to
            create a sparse device. These snapshots have no origin lv, instead
            using space in the vg directly. Only preexisting vorigin snapshots
            are supported here.
        """
        self._originSpecifiedCheck(origin, vorigin, exists)
        self._originTypeCheck(origin)
        self._originExistenceCheck(origin)
        self._voriginExistenceCheck(vorigin, exists)

        self.origin = origin
        """ the snapshot's source volume """

        self.vorigin = vorigin
        """ a boolean flag indicating a vorigin snapshot """

    def _originSpecifiedCheck(self, origin, vorigin, exists):
        # pylint: disable=unused-argument
        if not origin and not vorigin:
            raise ValueError("lvm snapshot devices require an origin lv")

    def _originTypeCheck(self, origin):
        if origin and not isinstance(origin, LVMLogicalVolumeDevice):
            raise ValueError("lvm snapshot origin must be a logical volume")

    def _originExistenceCheck(self, origin):
        if origin and not origin.exists:
            raise ValueError("lvm snapshot origin volume must already exist")

    def _voriginExistenceCheck(self, vorigin, exists):
        if vorigin and not exists:
            raise ValueError("only existing vorigin snapshots are supported")

    def _setFormat(self, fmt):
        pass

    def _getFormat(self):
        if self.origin is None:
            fmt = getFormat(None)
        else:
            fmt = self.origin.format
        return fmt

    @abc.abstractmethod
    def _create(self):
        """ Create the device. """
        raise NotImplementedError()

    def merge(self):
        """ Merge the snapshot back into its origin volume. """
        log_method_call(self, self.name, status=self.status) # pylint: disable=no-member
        self.vg.setup()    # pylint: disable=no-member
        try:
            self.origin.teardown()
        except errors.FSError:
            # the merge will begin based on conditions described in the --merge
            # section of lvconvert(8)
            pass

        try:
            self.teardown() # pylint: disable=no-member
        except errors.FSError:
            pass

        udev.udev_settle()
        lvm.lvsnapshotmerge(self.vg.name, self.lvname) # pylint: disable=no-member


class LVMSnapShotDevice(LVMSnapShotBase, LVMLogicalVolumeDevice):
    """ An LVM snapshot """
    _type = "lvmsnapshot"
    _formatImmutable = True

    def __init__(self, name, parents=None, size=None, uuid=None,
                 copies=1, logSize=0, segType=None,
                 fmt=None, exists=False, sysfsPath='',
                 grow=None, maxsize=None, percent=None,
                 origin=None, vorigin=False):
        """ Create an LVMSnapShotDevice instance.

            This class is for the old-style (not thin) lvm snapshots. The origin
            volume cannot be removed without also removing all snapshots (not so
            for thin snapshots). Also, the snapshot is automatically activated
            or deactivated with its origin.

            :param str name: the device name (generally a device node basename)
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str sysfsPath: sysfs device path
            :keyword str uuid: the device UUID
            :keyword str segType: segment type

            :keyword :class:`~.StorageDevice` origin: the origin/source volume
            :keyword bool vorigin: is this a vorigin snapshot?

            For non-existent devices only:

            :keyword bool grow: whether to grow this LV
            :keyword :class:`~.size.Size` maxsize: maximum size for growable LV
            :keyword int percent: percent of VG space to take
        """
        # pylint: disable=unused-argument

        if isinstance(origin, LVMLogicalVolumeDevice) and \
           isinstance(parents[0], LVMVolumeGroupDevice) and \
           origin.vg != parents[0]:
            raise ValueError("lvm snapshot and origin must be in the same vg")

        LVMSnapShotBase.__init__(self, origin=origin, vorigin=vorigin,
                                 exists=exists)

        LVMLogicalVolumeDevice.__init__(self, name, parents=parents, size=size,
                                        uuid=uuid, fmt=None, exists=exists,
                                        copies=copies, logSize=logSize,
                                        segType=segType,
                                        sysfsPath=sysfsPath, grow=grow,
                                        maxsize=maxsize, percent=percent)

    def setup(self, orig=False):
        pass

    def teardown(self, recursive=False):
        pass

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        lvm.lvsnapshotcreate(self.vg.name, self._name, self.size,
                             self.origin.lvname)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        # old-style snapshots' status is tied to the origin's so we never
        # explicitly activate or deactivate them and we have to tell lvremove
        # that it is okay to remove the active snapshot
        lvm.lvremove(self.vg.name, self._name, force=True)

    def _getPartedDevicePath(self):
        return "%s-cow" % self.path

    def dependsOn(self, dep):
        # pylint: disable=bad-super-call
        return (self.origin == dep or
                super(LVMSnapShotBase, self).dependsOn(dep))

class LVMThinPoolDevice(LVMLogicalVolumeDevice):
    """ An LVM Thin Pool """
    _type = "lvmthinpool"
    _resizable = False

    def __init__(self, name, parents=None, size=None, uuid=None,
                 fmt=None, exists=False, sysfsPath='',
                 grow=None, maxsize=None, percent=None,
                 metadatasize=None, chunksize=None, segType=None):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword uuid: the device UUID
            :type uuid: str
            :keyword segType: segment type
            :type segType: str

            For non-existent pools only:

            :keyword grow: whether to grow this LV
            :type grow: bool
            :keyword maxsize: maximum size for growable LV
            :type maxsize: :class:`~.size.Size`
            :keyword percent: percent of VG space to take
            :type percent: int
            :keyword metadatasize: the size of the metadata LV
            :type metadatasize: :class:`~.size.Size`
            :keyword chunksize: chunk size for the pool
            :type chunksize: :class:`~.size.Size`
        """
        if metadatasize is not None and \
           not lvm.is_valid_thin_pool_metadata_size(metadatasize):
            raise ValueError("invalid metadatasize value")

        if chunksize is not None and \
           not lvm.is_valid_thin_pool_chunk_size(chunksize):
            raise ValueError("invalid chunksize value")

        super(LVMThinPoolDevice, self).__init__(name, parents=parents,
                                                size=size, uuid=uuid,
                                                fmt=fmt, exists=exists,
                                                sysfsPath=sysfsPath, grow=grow,
                                                maxsize=maxsize,
                                                percent=percent,
                                                segType=segType)

        self.metaDataSize = metadatasize or 0
        self.chunkSize = chunksize or 0
        self._lvs = []

    def _addLogVol(self, lv):
        """ Add an LV to this pool. """
        if lv in self._lvs:
            raise ValueError("lv is already part of this vg")

        # TODO: add some checking to prevent overcommit for preexisting
        self.vg._addLogVol(lv)
        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

    def _removeLogVol(self, lv):
        """ Remove an LV from this pool. """
        if lv not in self._lvs:
            raise ValueError("specified lv is not part of this vg")

        self._lvs.remove(lv)
        self.vg._removeLogVol(lv)

    @property
    def lvs(self):
        """ A list of this pool's LVs """
        return self._lvs[:]     # we don't want folks changing our list

    @property
    def vgSpaceUsed(self):
        space = super(LVMThinPoolDevice, self).vgSpaceUsed
        space += lvm.get_pool_padding(space, pesize=self.vg.peSize)
        return space

    @property
    def usedSpace(self):
        return sum(l.poolSpaceUsed for l in self.lvs)

    @property
    def freeSpace(self):
        return self.size - self.usedSpace

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        # TODO: chunk size, data/metadata split --> profile
        lvm.thinpoolcreate(self.vg.name, self.lvname, self.size,
                           metadatasize=self.metaDataSize,
                           chunksize=self.chunkSize)

    def dracutSetupArgs(self):
        return set()

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return False

    def populateKSData(self, data):
        super(LVMThinPoolDevice, self).populateKSData(data)
        data.thin_pool = True
        data.metadata_size = self.metaDataSize
        data.chunk_size = self.chunkSize

class LVMThinLogicalVolumeDevice(LVMLogicalVolumeDevice):
    """ An LVM Thin Logical Volume """
    _type = "lvmthinlv"

    @property
    def pool(self):
        return self.parents[0]

    @property
    def vg(self):
        return self.pool.vg

    @property
    def poolSpaceUsed(self):
        """ The total space used within the thin pool by this volume.

            This should probably align to the greater of vg extent size and
            pool chunk size. If it ends up causing overcommit in the amount of
            less than one chunk per thin lv, so be it.
        """
        return self.vg.align(self.size, roundup=True)

    @property
    def vgSpaceUsed(self):
        return 0    # the pool's size is already accounted for in the vg

    def _setSize(self, size):
        if not isinstance(size, Size):
            raise ValueError("new size must of type Size")

        size = self.vg.align(size)
        size = self.vg.align(util.numeric_type(size))
        self._size = size
        self.targetSize = size

    size = property(StorageDevice._getSize, _setSize)

    def _preCreate(self):
        # skip LVMLogicalVolumeDevice's _preCreate() method as it checks for a
        # free space in a VG which doesn't make sense for a ThinLV and causes a
        # bug by limitting the ThinLV's size to VG free space which is nonsense
        super(LVMLogicalVolumeDevice, self)._preCreate() # pylint: disable=bad-super-call

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        lvm.thinlvcreate(self.vg.name, self.pool.lvname, self.lvname,
                         self.size)

    def populateKSData(self, data):
        super(LVMThinLogicalVolumeDevice, self).populateKSData(data)
        data.thin_volume = True
        data.pool_name = self.pool.lvname

class LVMThinSnapShotDevice(LVMSnapShotBase, LVMThinLogicalVolumeDevice):
    """ An LVM Thin Snapshot """
    _type = "lvmthinsnapshot"
    _resizable = False
    _formatImmutable = True

    def __init__(self, name, parents=None, sysfsPath='', origin=None,
                 fmt=None, uuid=None, size=None, exists=False, segType=None):
        """
            :param str name: the name of the device
            :param :class:`~.ParentList` parents: parent devices
            :param str sysfsPath: path to this device's /sys directory
            :keyword origin: the origin(source) volume for the snapshot
            :type origin: :class:`~.LVMLogicalVolumeDevice` or None
            :keyword str segType: segment type
            :keyword :class:`~.formats.DeviceFormat` fmt: this device's format
            :keyword str uuid: the device UUID
            :keyword :class:`~.size.Size` size: the device's size
            :keyword bool exists: is this an existing device?

            LVM thin snapshots can remain after their origin volume is removed,
            unlike the older-style snapshots.
        """
        # pylint: disable=unused-argument

        if isinstance(origin, LVMLogicalVolumeDevice) and \
           isinstance(parents[0], LVMThinPoolDevice) and \
           origin.vg != parents[0].vg:
            raise ValueError("lvm snapshot and origin must be in the same vg")

        if size and not exists:
            raise ValueError("thin snapshot size is determined automatically")

        LVMSnapShotBase.__init__(self, origin=origin, exists=exists)
        LVMThinLogicalVolumeDevice.__init__(self, name, parents=parents,
                                            sysfsPath=sysfsPath,fmt=None,
                                            segType=segType,
                                            uuid=uuid, size=size, exists=exists)

    def _originSpecifiedCheck(self, origin, vorigin, exists):
        if not exists and not origin:
            raise ValueError("non-existent lvm thin snapshots require an origin")

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        lvm.lvactivate(self.vg.name, self._name, ignore_skip=True)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        pool_name = None
        if not isinstance(self.origin, LVMThinLogicalVolumeDevice):
            # if the origin is not a thin volume we need to tell lvm which pool
            # to use
            pool_name = self.pool.lvname

        lvm.thinsnapshotcreate(self.vg.name, self._name, self.origin.lvname,
                               pool_name=pool_name)

    def dependsOn(self, dep):
        # once a thin snapshot exists it no longer depends on its origin
        return ((self.origin == dep and not self.exists) or
                super(LVMThinSnapShotDevice, self).dependsOn(dep))

class MDRaidArrayDevice(ContainerDevice):
    """ An mdraid (Linux RAID) device. """
    _type = "mdarray"
    _packages = ["mdadm"]
    _devDir = "/dev/md"
    _formatClassName = property(lambda s: "mdmember")
    _formatUUIDAttr = property(lambda s: "mdUuid")

    def __init__(self, name, level=None, major=None, minor=None, size=None,
                 memberDevices=None, totalDevices=None,
                 uuid=None, fmt=None, exists=False, metadataVersion=None,
                 parents=None, sysfsPath=''):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword uuid: the device UUID
            :type uuid: str

            :keyword level: the device's RAID level
            :type level: any valid RAID level descriptor
            :keyword int memberDevices: the number of active member devices
            :keyword int totalDevices: the total number of member devices
            :keyword metadataVersion: the version of the device's md metadata
            :type metadataVersion: str (eg: "0.90")
            :keyword minor: the device minor (obsolete?)
            :type minor: int
        """
        # pylint: disable=unused-argument

        # These attributes are used by _addParent, so they must be initialized
        # prior to instantiating the superclass.
        self._memberDevices = 0     # the number of active (non-spare) members
        self._totalDevices = 0      # the total number of members

        super(MDRaidArrayDevice, self).__init__(name, fmt=fmt, uuid=uuid,
                                                exists=exists, size=size,
                                                parents=parents,
                                                sysfsPath=sysfsPath)

        if level == "container":
            self._type = "mdcontainer"
        self.level = level

        # For new arrays check if we have enough members
        if (not exists and parents and len(parents) < self.level.min_members):
            for dev in self.parents:
                dev.removeChild()
            raise errors.DeviceError(P_("A %(raidLevel)s set requires at least %(minMembers)d member",
                                 "A %(raidLevel)s set requires at least %(minMembers)d members",
                                 self.level.min_members) % \
                                 {"raidLevel": self.level, "minMembers": self.level.min_members})

        self.uuid = uuid
        self._totalDevices = util.numeric_type(totalDevices)
        self.memberDevices = util.numeric_type(memberDevices)

        self.chunkSize = mdraid.MD_CHUNK_SIZE

        if not self.exists and not isinstance(metadataVersion, str):
            self.metadataVersion = "default"
        else:
            self.metadataVersion = metadataVersion

        # For container members probe size now, as we cannot determine it
        # when teared down.
        if self.parents and self.parents[0].type == "mdcontainer":
            self._size = self.currentSize
            self._type = "mdbiosraidarray"

        if self.exists and self.uuid and not flags.testing:
            # this is a hack to work around mdadm's insistence on giving
            # really high minors to arrays it has no config entry for
            open("/etc/mdadm.conf", "a").write("ARRAY %s UUID=%s\n"
                                                % (self.path, self.uuid))

    @property
    def level(self):
        """ Return the raid level

            :returns: raid level value
            :rtype:   an object that represents a RAID level
        """
        return self._level

    @level.setter
    def level(self, value):
        """ Set the RAID level and enforce restrictions based on it.

            :param value: new raid level
            :param type:  a valid raid level descriptor
            :returns:     None
        """
        self._level = mdraid.RAID_levels.raidLevel(value) # pylint: disable=attribute-defined-outside-init

    @property
    def createBitmap(self):
        """ Whether or not a bitmap should be created on the array.

            If the the array is sufficiently small, a bitmap yields no benefit.

            If the array has no redundancy, a bitmap is just pointless.
        """
        return self.level.has_redundancy and self.size >= 1000 and  self.format.type != "swap"

    def getSuperBlockSize(self, raw_array_size):
        """Estimate the superblock size for a member of an array,
           given the total available memory for this array and raid level.

           :param raw_array_size: total available for this array and level
           :type raw_array_size: :class:`~.size.Size`
           :returns: estimated superblock size
           :rtype: :class:`~.size.Size`
        """
        return mdraid.get_raid_superblock_size(raw_array_size,
                                               version=self.metadataVersion)

    @property
    def size(self):
        """Returns the actual or estimated size depending on whether or
           not the array exists.
        """
        # For container members return probed size, as we cannot determine it
        # when teared down.
        if self.type == "mdbiosraidarray":
            return self._size

        if not self.exists or not self.partedDevice:
            try:
                size = self.level.get_size([d.size for d in self.devices],
                    self.memberDevices,
                    self.chunkSize,
                    self.getSuperBlockSize)
            except (errors.MDRaidError, errors.RaidError) as e:
                log.info("could not calculate size of device %s for raid level %s: %s", self.name, self.level, e)
                size = 0
            log.debug("non-existent RAID %s size == %s", self.level, size)
        else:
            size = Size(self.partedDevice.getLength(unit="B"))
            log.debug("existing RAID %s size == %s", self.level, size)

        return size

    @property
    def description(self):
        if self.type == "mdcontainer":
            return "BIOS RAID container"
        else:
            levelstr = self.level.nick if self.level.nick else self.level.name
            if self.type == "mdbiosraidarray":
                return "BIOS RAID set (%s)" % levelstr
            else:
                return "MDRAID set (%s)" % levelstr

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  level = %(level)s  spares = %(spares)s\n"
              "  members = %(memberDevices)s\n"
              "  total devices = %(totalDevices)s"
              "  metadata version = %(metadataVersion)s" %
              {"level": self.level, "spares": self.spares,
               "memberDevices": self.memberDevices,
               "totalDevices": self.totalDevices,
               "metadataVersion": self.metadataVersion})
        return s

    @property
    def dict(self):
        d = super(MDRaidArrayDevice, self).dict
        d.update({"level": str(self.level),
                  "spares": self.spares, "memberDevices": self.memberDevices,
                  "totalDevices": self.totalDevices,
                  "metadataVersion": self.metadataVersion})
        return d

    @property
    def mdadmConfEntry(self):
        """ This array's mdadm.conf entry. """
        if self.memberDevices is None or not self.uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        # containers and the sets within must only have a UUID= parameter
        if self.type == "mdcontainer" or self.type == "mdbiosraidarray":
            fmt = "ARRAY %s UUID=%s\n"
            return fmt % (self.path, self.uuid)

        fmt = "ARRAY %s level=%s num-devices=%d UUID=%s\n"
        return fmt % (self.path, self.level, self.memberDevices, self.uuid)

    @property
    def totalDevices(self):
        """ Total number of devices in the array, including spares. """
        if not self.exists:
            return self._totalDevices
        else:
            return len(self.parents)

    def _getMemberDevices(self):
        return self._memberDevices

    def _setMemberDevices(self, number):
        if not isinstance(number, int):
            raise ValueError("memberDevices is an integer")

        if not self.exists and number > self.totalDevices:
            raise ValueError("memberDevices cannot be greater than totalDevices")
        self._memberDevices = number

    memberDevices = property(_getMemberDevices, _setMemberDevices,
                             doc="number of member devices")

    def _getSpares(self):
        spares = 0
        if self.memberDevices is not None:
            if self.totalDevices is not None and \
               self.totalDevices > self.memberDevices:
                spares = self.totalDevices - self.memberDevices
            elif self.totalDevices is None:
                spares = self.memberDevices
                self._totalDevices = self.memberDevices
        return spares

    def _setSpares(self, spares):
        max_spares = self.level.get_max_spares(len(self.parents))
        if spares > max_spares:
            log.debug("failed to set new spares value %d (max is %d)",
                      spares, max_spares)
            raise errors.DeviceError("new spares value is too large")

        if self.totalDevices > spares:
            self.memberDevices = self.totalDevices - spares

    spares = property(_getSpares, _setSpares)

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        # don't include self.status here since this method is called by
        # MDRaidArrayDevice.status
        log_method_call(self, self.name)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        # We don't use self.status here because self.status requires a valid
        # sysfs path to function correctly.
        if os.path.exists(self.path):
            md_node = mdraid.md_node_from_name(self.name)
            self.sysfsPath = "/devices/virtual/block/%s" % md_node
        else:
            self.sysfsPath = ''

    def _addParent(self, member):
        super(MDRaidArrayDevice, self)._addParent(member)

        ## XXX TODO: remove this whole block of activation code
        if self.exists and member.format.exists and flags.installer_mode:
            member.setup()
            udev.udev_settle()

            if self.spares <= 0:
                try:
                    mdraid.mdadd(None, member.path, incremental=True)
                    # mdadd causes udev events
                    udev.udev_settle()
                except errors.MDRaidError as e:
                    log.warning("failed to add member %s to md array %s: %s",
                                member.path, self.path, e)

        if self.status and member.format.exists:
            # we always probe since the device may not be set up when we want
            # information about it
            self._size = self.currentSize

        # These should be incremented when adding new member devices except
        # during devicetree.populate. When detecting existing arrays we will
        # have gotten these values from udev and will use them to determine
        # whether we found all of the members, so we shouldn't change them in
        # that case.
        if not member.format.exists:
            self._totalDevices += 1
            self.memberDevices += 1

    def _removeParent(self, member):
        """ If this is a raid array that is not actually redundant and it
            appears to have formatting and therefore probably data on it,
            removing one of its devices is a bad idea.
        """
        if not self.level.has_redundancy and self.exists and member.format.exists:
            raise errors.DeviceError("cannot remove members from existing raid0")

        super(MDRaidArrayDevice, self)._removeParent(member)
        self.memberDevices -= 1

    @property
    def status(self):
        """ This device's status.

            For now, this should return a boolean:
                True    the device is open and ready for use
                False   the device is not open
        """
        # check the status in sysfs
        status = False
        if not self.exists:
            return status

        if os.path.exists(self.path) and not self.sysfsPath:
            # the array has been activated from outside of blivet
            self.updateSysfsPath()

            # make sure the active array is the one we expect
            info = udev.udev_get_block_device(self.sysfsPath)
            uuid = udev.udev_device_get_md_uuid(info)
            if uuid and uuid != self.uuid:
                log.warning("md array %s is active, but has UUID %s -- not %s",
                            self.path, uuid, self.uuid)
                self.sysfsPath = ""
                return status

        state_file = "/sys/%s/md/array_state" % self.sysfsPath
        try:
            state = open(state_file).read().strip()
            if state in ("clean", "active", "active-idle", "readonly", "read-auto"):
                status = True
            # mdcontainers have state inactive when started (clear if stopped)
            if self.type == "mdcontainer" and state == "inactive":
                status = True
        except IOError:
            status = False

        return status

    def memberStatus(self, member):
        if not (self.status and member.status):
            return

        member_name = os.path.basename(member.sysfsPath)
        path = "/sys/%s/md/dev-%s/state" % (self.sysfsPath, member_name)
        try:
            state = open(path).read().strip()
        except IOError:
            state = None

        return state

    @property
    def degraded(self):
        """ Return True if the array is running in degraded mode. """
        rc = False
        degraded_file = "/sys/%s/md/degraded" % self.sysfsPath
        if os.access(degraded_file, os.R_OK):
            val = open(degraded_file).read().strip()
            if val == "1":
                rc = True

        return rc

    @property
    def members(self):
        """ Returns this array's members.

            If the array is a BIOS RAID array then its unique parent
            is a container and its actual member devices are the
            container's parents.

            :rtype: list of :class:`StorageDevice`
        """
        if self.type == "mdbiosraidarray":
            members = self.parents[0].parents
        else:
            members = self.parents
        return list(members)

    @property
    def complete(self):
        """ An MDRaidArrayDevice is complete if it has at least as many
            component devices as its count of active devices.
        """
        return (self.memberDevices <= len(self.members)) or not self.exists

    @property
    def devices(self):
        """ Return a list of this array's member device instances. """
        return self.parents

    def _postSetup(self):
        super(MDRaidArrayDevice, self)._postSetup()
        self.updateSysfsPath()

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        disks = []
        for member in self.devices:
            member.setup(orig=orig)
            disks.append(member.path)

        mdraid.mdactivate(self.path,
                          members=disks,
                          uuid=self.uuid)

    def _postTeardown(self, recursive=False):
        super(MDRaidArrayDevice, self)._postTeardown(recursive=recursive)
        # mdadm reuses minors indiscriminantly when there is no mdadm.conf, so
        # we need to clear the sysfs path now so our status method continues to
        # give valid results
        self.updateSysfsPath()

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # we don't really care about the return value of _preTeardown here.
        # see comment just above mddeactivate call
        self._preTeardown(recursive=recursive)

        # Since BIOS RAID sets (containers in mdraid terminology) never change
        # there is no need to stop them and later restart them. Not stopping
        # (and thus also not starting) them also works around bug 523334
        if self.type == "mdcontainer" or self.type == "mdbiosraidarray":
            return

        # We don't really care what the array's state is. If the device
        # file exists, we want to deactivate it. mdraid has too many
        # states.
        if self.exists and os.path.exists(self.path):
            mdraid.mddeactivate(self.path)

        self._postTeardown(recursive=recursive)

    def preCommitFixup(self, *args, **kwargs):
        """ Determine create parameters for this set """
        mountpoints = kwargs.pop("mountpoints")
        log_method_call(self, self.name, mountpoints)

        if "/boot" in mountpoints:
            bootmountpoint = "/boot"
        else:
            bootmountpoint = "/"

        # If we are used to boot from we cannot use 1.1 metadata
        if getattr(self.format, "mountpoint", None) == bootmountpoint or \
           getattr(self.format, "mountpoint", None) == "/boot/efi" or \
           self.format.type == "prepboot":
            self.metadataVersion = "1.0"

    def _postCreate(self):
        # this is critical since our status method requires a valid sysfs path
        md_node = mdraid.md_node_from_name(self.name)
        self.sysfsPath = "/devices/virtual/block/%s" % md_node
        self.exists = True  # I think we can remove this.

        StorageDevice._postCreate(self)

        # update our uuid attribute with the new array's UUID
        info = udev.udev_get_block_device(self.sysfsPath)
        self.uuid = udev.udev_device_get_md_uuid(info)
        for member in self.devices:
            member.format.mdUuid = self.uuid

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        disks = [disk.path for disk in self.devices]
        spares = len(self.devices) - self.memberDevices
        mdraid.mdcreate(self.path,
                        self.level,
                        disks,
                        spares,
                        metadataVer=self.metadataVersion,
                        bitmap=self.createBitmap)
        udev.udev_settle()

    def _remove(self, member):
        self.setup()
        # see if the device must be marked as failed before it can be removed
        fail = (self.memberStatus(member) == "in_sync")
        mdraid.mdremove(self.path, member.path, fail=fail)

    def _add(self, member):
        self.setup()
        if self.level.has_redundancy:
            raid_devices = None
        else:
            raid_devices = self.memberDevices

        mdraid.mdadd(self.path, member.path, raid_devices=raid_devices)

    @property
    def formatArgs(self):
        formatArgs = []
        if self.format.type == "ext2":
            recommended_stride = self.level.get_recommended_stride(self.memberDevices)
            if recommended_stride:
                formatArgs = ['-R', 'stride=%d' % recommended_stride ]
        return formatArgs

    @property
    def mediaPresent(self):
        # Containers should not get any format handling done
        # (the device node does not allow read / write calls)
        if self.type == "mdcontainer":
            return False
        # BIOS RAID sets should show as present even when teared down
        elif self.type == "mdbiosraidarray":
            return True
        elif flags.testing:
            return True
        else:
            return self.partedDevice is not None

    @property
    def model(self):
        return self.description

    @property
    def partitionable(self):
        return self.type == "mdbiosraidarray"

    @property
    def isDisk(self):
        return self.type == "mdbiosraidarray"

    def dracutSetupArgs(self):
        return set(["rd.md.uuid=%s" % self.uuid])

    def populateKSData(self, data):
        if self.isDisk:
            return

        super(MDRaidArrayDevice, self).populateKSData(data)
        data.level = self.level.name
        data.spares = self.spares
        data.members = ["raid.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        data.device = self.name

class DMRaidArrayDevice(DMDevice, ContainerDevice):
    """ A dmraid (device-mapper RAID) device """
    _type = "dm-raid array"
    _packages = ["dmraid"]
    _partitionable = True
    _isDisk = True
    _formatClassName = property(lambda s: "dmraidmember")
    _formatUUIDAttr = property(lambda s: None)

    def __init__(self, name, raidSet=None, fmt=None,
                 size=None, parents=None, sysfsPath=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword raidSet: the RaidSet object from block
            :type raidSet: :class:`block.RaidSet`

            DMRaidArrayDevices always exist. Blivet cannot create or destroy
            them.
        """
        super(DMRaidArrayDevice, self).__init__(name, fmt=fmt, size=size,
                                                parents=parents, exists=True,
                                                sysfsPath=sysfsPath)

        self._raidSet = raidSet

    @property
    def raidSet(self):
        return self._raidSet

    @property
    def devices(self):
        """ Return a list of this array's member device instances. """
        return self.parents

    def deactivate(self):
        """ Deactivate the raid set. """
        log_method_call(self, self.name, status=self.status)
        # This call already checks if the set is not active.
        self._raidSet.deactivate()

    def activate(self):
        """ Activate the raid set. """
        log_method_call(self, self.name, status=self.status)
        # This call already checks if the set is active.
        self._raidSet.activate(mknod=True)
        udev.udev_settle()

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        self.activate()

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._preTeardown(recursive=recursive):
            return

        log.debug("not tearing down dmraid device %s", self.name)

    def _add(self, member):
        raise NotImplementedError()

    def _remove(self, member):
        raise NotImplementedError()

    @property
    def description(self):
        return "BIOS RAID set (%s)" % self._raidSet.rs.set_type

    @property
    def model(self):
        return self.description

    def dracutSetupArgs(self):
        return set(["rd.dm.uuid=%s" % self.name])

class MultipathDevice(DMDevice):
    """ A multipath device """
    _type = "dm-multipath"
    _packages = ["device-mapper-multipath"]
    _services = ["multipathd"]
    _partitionable = True
    _isDisk = True

    def __init__(self, name, fmt=None, size=None, serial=None,
                 parents=None, sysfsPath=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword serial: the device's serial number
            :type serial: str

            MultipathDevices always exist. Blivet cannot create or destroy
            them.
        """

        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfsPath=sysfsPath,
                          exists=True)

        self.identity = serial
        self.config = {
            'wwid' : self.identity,
            'mode' : '0600',
            'uid' : '0',
            'gid' : '0',
        }

    @property
    def wwid(self):
        identity = self.identity
        ret = []
        while identity:
            ret.append(identity[:2])
            identity = identity[2:]
        return ":".join(ret)

    @property
    def model(self):
        if not self.parents:
            return ""
        return self.parents[0].model

    @property
    def vendor(self):
        if not self.parents:
            return ""
        return self.parents[0].vendor

    @property
    def description(self):
        return "WWID %s" % (self.wwid,)

    def addParent(self, parent):
        """ Add a parent device to the mpath. """
        log_method_call(self, self.name, status=self.status)
        if self.status:
            self.teardown()
            self.parents.append(parent)
            self.setup()
        else:
            self.parents.append(parent)

    def deactivate(self):
        """
        This is never called, included just for documentation.

        If we called this during teardown(), we wouldn't be able to get parted
        object because /dev/mapper/mpathX wouldn't exist.
        """
        if self.exists and os.path.exists(self.path):
            #self.teardownPartitions()
            #rc = util.run_program(["multipath", '-f', self.name])
            #if rc:
            #    raise MPathError("multipath deactivation failed for '%s'" %
            #                    self.name)
            bdev = block.getDevice(self.name)
            devmap = block.getMap(major=bdev[0], minor=bdev[1])
            if devmap.open_count:
                return
            try:
                block.removeDeviceMap(devmap)
            except Exception as e:
                raise errors.MPathError("failed to tear down multipath device %s: %s"
                                % (self.name, e))

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        udev.udev_settle()
        rc = util.run_program(["multipath", self.name])
        if rc:
            raise errors.MPathError("multipath activation failed for '%s'" %
                            self.name, hardware_fault=True)

    def _postSetup(self):
        StorageDevice._postSetup(self)
        self.setupPartitions()
        udev.udev_settle()

class NoDevice(StorageDevice):
    """ A nodev device for nodev filesystems like tmpfs. """
    _type = "nodev"

    def __init__(self, fmt=None):
        """
            :keyword fmt: the device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
        """
        if fmt:
            name = fmt.device
        else:
            name = "none"

        StorageDevice.__init__(self, name, fmt=fmt, exists=True)

    @property
    def path(self):
        """ Device node representing this device. """
        # the name may have a '.%d' suffix to make it unique
        return self.name.split(".")[0]

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)

    def teardown(self, recursive=False):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # just make sure the format is unmounted
        self._preTeardown(recursive=recursive)

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)

    def destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        self._preDestroy()


class TmpFSDevice(NoDevice):
    """ A nodev device for a tmpfs filesystem. """
    _type = "tmpfs"

    def __init__(self, *args, **kwargs):
        """Create a tmpfs device"""
        # pylint: disable=unused-argument
        fmt = kwargs.get('fmt')
        NoDevice.__init__(self, fmt)
        # the tmpfs device does not exist until mounted
        self.exists = False
        self._size = kwargs["size"]
        self._targetSize = self._size

    @property
    def size(self):
        if self._size is not None:
            return self._size
        elif self.format:
            return self.format.size
        else:
            return 0

    @property
    def fstabSpec(self):
        return self._type

    def populateKSData(self, data):
        super(TmpFSDevice, self).populateKSData(data)
        # we need to supply a format to ksdata, otherwise the kickstart line
        # would include --noformat, resulting in an invalid command combination
        data.format = self.format


class FileDevice(StorageDevice):
    """ A file on a filesystem.

        This exists because of swap files.
    """
    _type = "file"
    _devDir = ""

    def __init__(self, path, fmt=None, size=None,
                 exists=False, parents=None):
        """
            :param path: full path to the file
            :type path: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
        """
        if not os.path.isabs(path):
            raise ValueError("FileDevice requires an absolute path")

        StorageDevice.__init__(self, path, fmt=fmt, size=size,
                               exists=exists, parents=parents)

    @property
    def fstabSpec(self):
        return self.name

    @property
    def path(self):
        try:
            root = self.parents[0].format._mountpoint
            mountpoint = self.parents[0].format.mountpoint
        except (AttributeError, IndexError):
            root = ""
        else:
            # trim the mountpoint down to the chroot since we already have
            # the otherwise fully-qualified path
            while mountpoint.endswith("/"):
                mountpoint = mountpoint[:-1]
            if mountpoint:
                root = root[:-len(mountpoint)]

        return os.path.normpath("%s%s" % (root, self.name))

    def _preSetup(self, orig=False):
        if self.format and self.format.exists and not self.format.status:
            self.format.device = self.path

        return StorageDevice._preSetup(self, orig=orig)

    def _preTeardown(self, recursive=None):
        if self.format and self.format.exists and not self.format.status:
            self.format.device = self.path

        return StorageDevice._preTeardown(self, recursive=recursive)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        fd = os.open(self.path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC)
        # all this fuss is so we write the zeros 1MiB at a time
        zero = "\0"
        MiB = Size("1 MiB")
        count = int(self.size.convertTo(spec="MiB"))
        rem = self.size % MiB

        for _n in range(count):
            os.write(fd, zero * MiB)

        if rem:
            # write out however many more zeros it takes to hit our size target
            os.write(fd, zero * rem)

        os.close(fd)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        os.unlink(self.path)

    @classmethod
    def isNameValid(cls, name):
        # Override StorageDevice.isNameValid to allow /
        return not('\x00' in name or name == '.' or name == '..')

class SparseFileDevice(FileDevice):
    """A sparse file on a filesystem.
    This exists for sparse disk images."""
    _type = "sparse file"
    def _create(self):
        """Create a sparse file."""
        log_method_call(self, self.name, status=self.status)
        util.create_sparse_file(self.path, self.size)

class DirectoryDevice(FileDevice):
    """ A directory on a filesystem.

        This exists because of bind mounts.
    """
    _type = "directory"

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        util.makedirs(self.path)


class LoopDevice(StorageDevice):
    """ A loop device. """
    _type = "loop"

    def __init__(self, name=None, fmt=None, size=None, sysfsPath=None,
                 exists=False, parents=None):
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

            Loop devices always exist.
        """
        if not parents:
            raise ValueError("LoopDevice requires a backing device")

        if not name:
            # set up a temporary name until we've activated the loop device
            name = "tmploop%d" % self.id

        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               exists=True, parents=parents)

    def _setName(self, value):
        self._name = value  # actual name is set by losetup

    def updateName(self):
        """ Update this device's name. """
        if not self.slave.status:
            # if the backing device is inactive, so are we
            return self.name

        if self.name.startswith("loop"):
            # if our name is loopN we must already be active
            return self.name

        name = loop.get_loop_name(self.slave.path)
        if name.startswith("loop"):
            self.name = name

        return self.name

    @property
    def status(self):
        return (self.slave.status and
                self.name.startswith("loop") and
                loop.get_loop_name(self.slave.path) == self.name)

    @property
    def size(self):
        return self.slave.size

    def _preSetup(self, orig=False):
        if not os.path.exists(self.slave.path):
            raise errors.DeviceError("specified file (%s) does not exist" % self.slave.path)
        return StorageDevice._preSetup(self, orig=orig)

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        loop.loop_setup(self.slave.path)

    def _postSetup(self):
        StorageDevice._postSetup(self)
        self.updateName()
        self.updateSysfsPath()

    def _teardown(self, recursive=False):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        loop.loop_teardown(self.path)

    def _postTeardown(self, recursive=False):
        StorageDevice._postTeardown(self, recursive=recursive)
        self.name = "tmploop%d" % self.id
        self.sysfsPath = ''

    @property
    def slave(self):
        return self.parents[0]


class iScsiDiskDevice(DiskDevice, NetworkStorageDevice):
    """ An iSCSI disk. """
    _type = "iscsi"
    _packages = ["iscsi-initiator-utils", "dracut-network"]

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword node: ???
            :type node: str
            :keyword ibft: use iBFT
            :type ibft: bool
            :keyword nic: name of NIC to use
            :type nic: str
            :keyword initiator: initiator name
            :type initiator: str
            :keyword fw_name: qla4xxx partial offload
            :keyword fw_address: qla4xxx partial offload
            :keyword fw_port: qla4xxx partial offload
        """
        self.node = kwargs.pop("node")
        self.ibft = kwargs.pop("ibft")
        self.nic = kwargs.pop("nic")
        self.initiator = kwargs.pop("initiator")

        if self.node is None:
            # qla4xxx partial offload
            name = kwargs.pop("fw_name")
            address = kwargs.pop("fw_address")
            port = kwargs.pop("fw_port")
            DiskDevice.__init__(self, device, **kwargs)
            NetworkStorageDevice.__init__(self,
                                          host_address=address,
                                          nic=self.nic)
            log.debug("created new iscsi disk %s %s:%s using fw initiator %s",
                      name, address, port, self.initiator)
        else:
            DiskDevice.__init__(self, device, **kwargs)
            NetworkStorageDevice.__init__(self, host_address=self.node.address,
                                          nic=self.nic)
            log.debug("created new iscsi disk %s %s:%d via %s:%s", self.node.name,
                                                                   self.node.address,
                                                                   self.node.port,
                                                                   self.node.iface,
                                                                   self.nic)

    def dracutSetupArgs(self):
        if self.ibft:
            return set(["iscsi_firmware"])

        # qla4xxx partial offload
        if self.node is None:
            return set()

        address = self.node.address
        # surround ipv6 addresses with []
        if ":" in address:
            address = "[%s]" % address

        netroot="netroot=iscsi:"
        auth = self.node.getAuth()
        if auth:
            netroot += "%s:%s" % (auth.username, auth.password)
            if len(auth.reverse_username) or len(auth.reverse_password):
                netroot += ":%s:%s" % (auth.reverse_username,
                                       auth.reverse_password)

        iface_spec = ""
        if self.nic != "default":
            iface_spec = ":%s:%s" % (self.node.iface, self.nic)
        netroot += "@%s::%d%s::%s" % (address,
                                      self.node.port,
                                      iface_spec,
                                      self.node.name)

        initiator = "iscsi_initiator=%s" % self.initiator

        return set([netroot, initiator])

class FcoeDiskDevice(DiskDevice, NetworkStorageDevice):
    """ An FCoE disk. """
    _type = "fcoe"
    _packages = ["fcoe-utils", "dracut-network"]

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword nic: name of NIC to use
            :keyword identifier: ???
        """
        self.nic = kwargs.pop("nic")
        self.identifier = kwargs.pop("identifier")
        DiskDevice.__init__(self, device, **kwargs)
        NetworkStorageDevice.__init__(self, nic=self.nic)
        log.debug("created new fcoe disk %s (%s) @ %s",
                  device, self.identifier, self.nic)

    def dracutSetupArgs(self):
        dcb = True

        from .fcoe import fcoe

        for nic, dcb, _auto_vlan in fcoe().nics:
            if nic == self.nic:
                break
        else:
            return set()

        if dcb:
            dcbOpt = "dcb"
        else:
            dcbOpt = "nodcb"

        if self.nic in fcoe().added_nics:
            return set(["fcoe=%s:%s" % (self.nic, dcbOpt)])
        else:
            return set(["fcoe=edd:%s" % dcbOpt])

class OpticalDevice(StorageDevice):
    """ An optical drive, eg: cdrom, dvd+r, &c.

        XXX Is this useful?
    """
    _type = "cdrom"

    def __init__(self, name, major=None, minor=None, exists=False,
                 fmt=None, parents=None, sysfsPath='', vendor="",
                 model=""):
        StorageDevice.__init__(self, name, fmt=fmt,
                               major=major, minor=minor, exists=True,
                               parents=parents, sysfsPath=sysfsPath,
                               vendor=vendor, model=model)

    @property
    def mediaPresent(self):
        """ Return a boolean indicating whether or not the device contains
            media.
        """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        try:
            fd = os.open(self.path, os.O_RDONLY)
        except OSError as e:
            # errno 123 = No medium found
            if e.errno == 123:
                return False
            else:
                return True
        else:
            os.close(fd)
            return True

    def eject(self):
        """ Eject the drawer. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        #try to umount and close device before ejecting
        self.teardown()

        try:
            util.run_program(["eject", self.name])
        except OSError as e:
            log.warning("error ejecting cdrom %s: %s", self.name, e)


class ZFCPDiskDevice(DiskDevice):
    """ A mainframe ZFCP disk. """
    _type = "zfcp"

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword hba_id: ???
            :keyword wwpn: ???
            :keyword fcp_lun: ???
        """
        self.hba_id = kwargs.pop("hba_id")
        self.wwpn = kwargs.pop("wwpn")
        self.fcp_lun = kwargs.pop("fcp_lun")
        DiskDevice.__init__(self, device, **kwargs)

    def __repr__(self):
        s = DiskDevice.__repr__(self)
        s += ("  hba_id = %(hba_id)s  wwpn = %(wwpn)s  fcp_lun = %(fcp_lun)s" %
              {"hba_id": self.hba_id,
               "wwpn": self.wwpn,
               "fcp_lun": self.fcp_lun})
        return s

    @property
    def description(self):
        return "FCP device %(device)s with WWPN %(wwpn)s and LUN %(lun)s" \
               % {'device': self.hba_id,
                  'wwpn': self.wwpn,
                  'lun': self.fcp_lun}

    def dracutSetupArgs(self):
        return set(["rd.zfcp=%s,%s,%s" % (self.hba_id, self.wwpn, self.fcp_lun,)])

class DASDDevice(DiskDevice):
    """ A mainframe DASD. """
    _type = "dasd"

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword busid: bus ID
            :keyword opts: options
            :type opts: dict with option name keys and option value values
        """
        self.busid = kwargs.pop('busid')
        self.opts = kwargs.pop('opts')
        DiskDevice.__init__(self, device, **kwargs)

    @property
    def description(self):
        return "DASD device %s" % self.busid

    def getOpts(self):
        return ["%s=%s" % (k, v) for k, v in self.opts.items() if v == '1']

    def dracutSetupArgs(self):
        conf = "/etc/dasd.conf"
        line = None
        if os.path.isfile(conf):
            f = open(conf)
            # grab the first line that starts with our busID
            for l in f.readlines():
                if l.startswith(self.busid):
                    line = l.rstrip()
                    break

            f.close()

        # See if we got a line.  If not, grab our getOpts
        if not line:
            line = self.busid
            for devopt in self.getOpts():
                line += " %s" % devopt

        # Create a translation mapping from dasd.conf format to module format
        translate = {'use_diag': 'diag',
                     'readonly': 'ro',
                     'erplog': 'erplog',
                     'failfast': 'failfast'}

        # this is a really awkward way of determining if the
        # feature found is actually desired (1, not 0), plus
        # translating that feature into the actual kernel module
        # value
        opts = []
        parts = line.split()
        for chunk in parts[1:]:
            try:
                feat, val = chunk.split('=')
                if int(val):
                    opts.append(translate[feat])
            except (ValueError, KeyError):
                # If we don't know what the feature is (feat not in translate
                # or if we get a val that doesn't cleanly convert to an int
                # we can't do anything with it.
                log.warning("failed to parse dasd feature %s", chunk)

        if opts:
            return set(["rd.dasd=%s(%s)" % (self.busid,
                                            ":".join(opts))])
        else:
            return set(["rd.dasd=%s" % self.busid])

class NFSDevice(StorageDevice, NetworkStorageDevice):
    """ An NFS device """
    _type = "nfs"
    _packages = ["dracut-network"]

    def __init__(self, device, fmt=None, parents=None):
        """
            :param device: the device name (generally a device node's basename)
            :type device: str
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
        """
        # we could make host/ip, path, &c but will anything use it?
        StorageDevice.__init__(self, device, fmt=fmt, parents=parents)
        NetworkStorageDevice.__init__(self, device.split(":")[0])

    @property
    def path(self):
        """ Device node representing this device. """
        return self.name

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self._preCreate()

    def destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)

    @classmethod
    def isNameValid(cls, name):
        # Override StorageDevice.isNameValid to allow /
        return not('\x00' in name or name == '.' or name == '..')

class BTRFSDevice(StorageDevice):
    """ Base class for BTRFS volume and sub-volume devices. """
    _type = "btrfs"
    _packages = ["btrfs-progs"]

    def __init__(self, *args, **kwargs):
        """ Passing None or no name means auto-generate one like btrfs.%d """
        if not args or not args[0]:
            args = ("btrfs.%d" % self.id,)

        if kwargs.get("parents") is None:
            raise ValueError("BTRFSDevice must have at least one parent")

        self.req_size = kwargs.pop("size", None)
        super(BTRFSDevice, self).__init__(*args, **kwargs)

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        self.parents[0].updateSysfsPath()
        self.sysfsPath = self.parents[0].sysfsPath
        log.debug("%s sysfsPath set to %s", self.name, self.sysfsPath)

    def _postCreate(self):
        super(BTRFSDevice, self)._postCreate()
        self.format.exists = True
        self.format.device = self.path

    def _preDestroy(self):
        """ Preparation and precondition checking for device destruction. """
        super(BTRFSDevice, self)._preDestroy()
        self.setupParents(orig=True)

    def _getSize(self):
        size = sum([d.size for d in self.parents])
        return size

    def _setSize(self, newsize):
        raise RuntimeError("cannot directly set size of btrfs volume")

    @property
    def currentSize(self):
        return self.size

    @property
    def status(self):
        return not any([not d.status for d in self.parents])

    @property
    def _temp_dir_prefix(self):
        return "btrfs-tmp.%s" % self.id

    def _do_temp_mount(self, orig=False):
        if self.format.status or not self.exists:
            return

        tmpdir = tempfile.mkdtemp(prefix=self._temp_dir_prefix)
        if orig:
            fmt = self.originalFormat
        else:
            fmt = self.format

        fmt.mount(mountpoint=tmpdir)

    def _undo_temp_mount(self):
        if getattr(self.format, "_mountpoint", None):
            fmt = self.format
        elif getattr(self.originalFormat, "_mountpoint", None):
            fmt = self.originalFormat
        else:
            return

        mountpoint = fmt._mountpoint

        if os.path.basename(mountpoint).startswith(self._temp_dir_prefix):
            fmt.unmount()
            os.rmdir(mountpoint)

    @property
    def path(self):
        return self.parents[0].path if self.parents else None

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return True

    @property
    def fstabSpec(self):
        if self.format.volUUID:
            spec = "UUID=%s" % self.format.volUUID
        else:
            spec = super(BTRFSDevice, self).fstabSpec
        return spec

class BTRFSVolumeDevice(BTRFSDevice, ContainerDevice):
    _type = "btrfs volume"
    vol_id = btrfs.MAIN_VOLUME_ID
    _formatClassName = property(lambda s: "btrfs")
    _formatUUIDAttr = property(lambda s: "volUUID")

    def __init__(self, *args, **kwargs):
        """
            :param str name: the volume name
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: a list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str uuid: UUID of top-level filesystem/volume
            :keyword str sysfsPath: sysfs device path
            :keyword dataLevel: RAID level for data
            :type dataLevel: any valid raid level descriptor
            :keyword metaDataLevel: RAID level for metadata
            :type metaDataLevel: any valid raid level descriptor
        """
        # pop these arguments before the constructor call to avoid
        # unrecognized keyword error in superclass constructor
        dataLevel = kwargs.pop("dataLevel", None)
        metaDataLevel = kwargs.pop("metaDataLevel", None)

        super(BTRFSVolumeDevice, self).__init__(*args, **kwargs)

        # assign after constructor to avoid AttributeErrors in setter functions
        self.dataLevel = dataLevel
        self.metaDataLevel = metaDataLevel

        self.subvolumes = []
        self.size_policy = self.size

        if self.parents and not self.format.type:
            label = getattr(self.parents[0].format, "label", None)
            self.format = getFormat("btrfs",
                                    exists=self.exists,
                                    label=label,
                                    volUUID=self.uuid,
                                    device=self.path,
                                    mountopts="subvolid=%d" % self.vol_id)
            self.originalFormat = copy.copy(self.format)

        self._defaultSubVolumeID = None

    @property
    def dataLevel(self):
        """ Return the RAID level for data.

            :returns: raid level
            :rtype: an object that represents a raid level
        """
        return self._dataLevel

    @dataLevel.setter
    def dataLevel(self, value):
        """ Set the RAID level for data.

            :param value: new raid level
            :param type:  a valid raid level descriptor
            :returns:     None
        """
        # pylint: disable=attribute-defined-outside-init
        self._dataLevel = btrfs.RAID_levels.raidLevel(value) if value else None

    @property
    def metaDataLevel(self):
        """ Return the RAID level for metadata.

            :returns: raid level
            :rtype: an object that represents a raid level
        """
        return self._metaDataLevel

    @metaDataLevel.setter
    def metaDataLevel(self, value):
        """ Set the RAID level for metadata.

            :param value: new raid level
            :param type:  a valid raid level descriptor
            :returns:     None
        """
        # pylint: disable=attribute-defined-outside-init
        self._metaDataLevel = btrfs.metadata_levels.raidLevel(value) if value else None

    @property
    def formatImmutable(self):
        return self.exists

    def _setName(self, value):
        self._name = value  # name is not used outside of blivet

    def _setFormat(self, fmt):
        """ Set the Device's format. """
        super(BTRFSVolumeDevice, self)._setFormat(fmt)
        self.name = "btrfs.%d" % self.id
        label = getattr(self.format, "label", None)
        if label:
            self.name = label

    def _getSize(self):
        size = sum([d.size for d in self.parents])
        if self.dataLevel in (raid.RAID1, raid.RAID10):
            size /= len(self.parents)

        return size

    def _removeParent(self, member):
        """ Raises a DeviceError if the device has a raid level and the
            resulting number of parents would be fewer than the minimum
            number required by the raid level.

            Note: btrfs does not permit degrading an array.
        """
        levels = [l for l in [self.dataLevel, self.metaDataLevel] if l]
        if levels:
            min_level = min(levels, key=lambda l: l.min_members)
            min_members = min_level.min_members
            if len(self.parents) - 1 < min_members:
                raise errors.DeviceError("device %s requires at least %d membersfor raid level %s" % (self.name, min_members, min_level))
        super(BTRFSVolumeDevice, self)._removeParent(member)

    def _addSubVolume(self, vol):
        if vol.name in [v.name for v in self.subvolumes]:
            raise ValueError("subvolume %s already exists" % vol.name)

        self.subvolumes.append(vol)

    def _removeSubVolume(self, name):
        if name not in [v.name for v in self.subvolumes]:
            raise ValueError("cannot remove non-existent subvolume %s" % name)

        names = [v.name for v in self.subvolumes]
        self.subvolumes.pop(names.index(name))

    def listSubVolumes(self, snapshotsOnly=False):
        subvols = []
        if flags.installer_mode:
            self.setup(orig=True)

        try:
            self._do_temp_mount(orig=True)
        except errors.FSError as e:
            log.debug("btrfs temp mount failed: %s", e)
            return subvols

        try:
            subvols = btrfs.list_subvolumes(self.originalFormat._mountpoint,
                                            snapshots_only=snapshotsOnly)
        except errors.BTRFSError as e:
            log.debug("failed to list subvolumes: %s", e)
        else:
            self._getDefaultSubVolumeID()
        finally:
            self._undo_temp_mount()

        return subvols

    def createSubVolumes(self):
        self._do_temp_mount()

        for _name, subvol in self.subvolumes:
            if subvol.exists:
                continue
            subvol.create(mountpoint=self._temp_dir_prefix)
        self._undo_temp_mount()

    def removeSubVolume(self, name):
        raise NotImplementedError()

    def _getDefaultSubVolumeID(self):
        subvolid = None
        try:
            subvolid = btrfs.get_default_subvolume(self.originalFormat._mountpoint)
        except errors.BTRFSError as e:
            log.debug("failed to get default subvolume id: %s", e)

        self._defaultSubVolumeID = subvolid

    @property
    def defaultSubVolume(self):
        default = None
        if self._defaultSubVolumeID is None:
            return None

        if self._defaultSubVolumeID == self.vol_id:
            return self

        for sv in self.subvolumes:
            if sv.vol_id == self._defaultSubVolumeID:
                default = sv
                break

        return default

    def _create(self):
        log_method_call(self, self.name, status=self.status)
        btrfs.create_volume(devices=[d.path for d in self.parents],
                            label=self.format.label,
                            data=self.dataLevel,
                            metadata=self.metaDataLevel)

    def _postCreate(self):
        super(BTRFSVolumeDevice, self)._postCreate()
        info = udev.udev_get_block_device(self.sysfsPath)
        if not info:
            log.error("failed to get updated udev info for new btrfs volume")
        else:
            self.format.volUUID = udev.udev_device_get_uuid(info)

        self.format.exists = True
        self.originalFormat.exists = True

    def _destroy(self):
        log_method_call(self, self.name, status=self.status)
        for device in self.parents:
            device.setup(orig=True)
            DeviceFormat(device=device.path, exists=True).destroy()

    def _remove(self, member):
        log_method_call(self, self.name, status=self.status)
        try:
            self._do_temp_mount(orig=True)
        except errors.FSError as e:
            log.debug("btrfs temp mount failed: %s", e)
            raise

        try:
            btrfs.remove(self.originalFormat._mountpoint, member.path)
        finally:
            self._undo_temp_mount()

    def _add(self, member):
        try:
            self._do_temp_mount(orig=True)
        except errors.FSError as e:
            log.debug("btrfs temp mount failed: %s", e)
            raise

        try:
            btrfs.add(self.originalFormat._mountpoint, member.path)
        finally:
            self._undo_temp_mount()

    def populateKSData(self, data):
        super(BTRFSVolumeDevice, self).populateKSData(data)
        data.dataLevel = self.dataLevel.name if self.dataLevel else None
        data.metaDataLevel = self.metaDataLevel.name if self.metaDataLevel else None
        data.devices = ["btrfs.%d" % p.id for p in self.parents]
        data.preexist = self.exists

class BTRFSSubVolumeDevice(BTRFSDevice):
    """ A btrfs subvolume pseudo-device. """
    _type = "btrfs subvolume"
    _formatImmutable = True

    def __init__(self, *args, **kwargs):
        """
            :param str name: the subvolume name
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: a list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str sysfsPath: sysfs device path
        """
        self.vol_id = kwargs.pop("vol_id", None)

        super(BTRFSSubVolumeDevice, self).__init__(*args, **kwargs)

        if len(self.parents) != 1:
            raise errors.DeviceError("%s %s must have exactly one parent." % (self.type, self.name))

        if not isinstance(self.parents[0], BTRFSDevice):
            raise errors.DeviceError("%s %s's unique parent must be a BTRFSDevice." % (self.type, self.name))

        self.volume._addSubVolume(self)

    @property
    def volume(self):
        """Return the first ancestor that is not a BTRFSSubVolumeDevice.

           Note: Assumes that each ancestor in traversal has only one parent.

           Raises a DeviceError if the ancestor found is not a
           BTRFSVolumeDevice.
        """
        parent = self.parents[0]
        vol = None
        while True:
            if not isinstance(parent, BTRFSSubVolumeDevice):
                vol = parent
                break

            parent = parent.parents[0]

        if not isinstance(vol, BTRFSVolumeDevice):
            raise errors.DeviceError("%s %s's first non subvolume ancestor must be a btrfs volume" % (self.type, self.name))
        return vol

    @property
    def container(self):
        return self.volume

    def setupParents(self, orig=False):
        """ Run setup method of all parent devices. """
        log_method_call(self, name=self.name, orig=orig, kids=self.kids)
        self.volume.setup(orig=orig)

    def _create(self):
        log_method_call(self, self.name, status=self.status)
        self.volume._do_temp_mount()
        mountpoint = self.volume.format._mountpoint
        if not mountpoint:
            raise RuntimeError("btrfs subvol create requires mounted volume")

        try:
            btrfs.create_subvolume(mountpoint, self.name)
        finally:
            self.volume._undo_temp_mount()

    def _postCreate(self):
        super(BTRFSSubVolumeDevice, self)._postCreate()
        self.format.volUUID = self.volume.format.volUUID

    def _destroy(self):
        log_method_call(self, self.name, status=self.status)
        self.volume._do_temp_mount(orig=True)
        mountpoint = self.volume.originalFormat._mountpoint
        if not mountpoint:
            raise RuntimeError("btrfs subvol destroy requires mounted volume")
        btrfs.delete_subvolume(mountpoint, self.name)
        self.volume._undo_temp_mount()

    def populateKSData(self, data):
        super(BTRFSSubVolumeDevice, self).populateKSData(data)
        data.subvol = True
        data.name = self.name
        data.preexist = self.exists

    @classmethod
    def isNameValid(cls, name):
        # Override StorageDevice.isNameValid to allow /
        return not('\x00' in name or name == '.' or name == '..')

class BTRFSSnapShotDevice(BTRFSSubVolumeDevice):
    """ A btrfs snapshot pseudo-device.

        BTRFS snapshots are a specialized type of subvolume that contains a
        source attribute which identifies which subvolume the snapshot was taken
        from. They do not have to be removed when removing the source subvolume.
    """
    _type = "btrfs snapshot"

    def __init__(self, *args, **kwargs):
        """
            :param str name: the subvolume name
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: a list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str sysfsPath: sysfs device path
            :keyword :class:`~.BTRFSDevice` source: the snapshot source
            :keyword bool readOnly: create a read-only snapshot

            Snapshot source can be either a subvolume or a top-level volume.

        """
        source = kwargs.pop("source", None)
        if not kwargs.get("exists") and not source:
            # it is possible to remove a source subvol and keep snapshots of it
            raise ValueError("non-existent btrfs snapshots must have a source")

        if source and not isinstance(source, BTRFSDevice):
            raise ValueError("btrfs snapshot source must be a btrfs subvolume")

        if source and not source.exists:
            raise ValueError("btrfs snapshot source must already exist")

        self.source = source
        """ the snapshot's source subvolume """

        self.readOnly = kwargs.pop("readOnly", False)

        super(BTRFSSnapShotDevice, self).__init__(*args, **kwargs)

        if source and getattr(source, "volume", source) != self.volume:
            self.volume._removeSubVolume(self.name)
            self.parents = []
            raise ValueError("btrfs snapshot and source must be in the same volume")

    def _create(self):
        log_method_call(self, self.name, status=self.status)
        self.volume._do_temp_mount()
        mountpoint = self.volume.format._mountpoint
        if not mountpoint:
            raise RuntimeError("btrfs subvol create requires mounted volume")

        if isinstance(self.source, BTRFSVolumeDevice):
            source_path = mountpoint
        else:
            source_path = "%s/%s" % (mountpoint, self.source.name)

        dest_path = "%s/%s" % (mountpoint, self.name)
        try:
            btrfs.create_snapshot(source_path, dest_path, ro=self.readOnly)
        finally:
            self.volume._undo_temp_mount()

    def dependsOn(self, dep):
        return (dep == self.source or
                super(BTRFSSnapShotDevice, self).dependsOn(dep))
