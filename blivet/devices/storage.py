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

from .. import arch
from .. import errors
from .. import util
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..formats import getFormat
from ..size import Size

import logging
log = logging.getLogger("blivet")

from .device import Device
from .lib import LINUX_SECTOR_SIZE
from .network import NetworkStorageDevice

# openlmi-storage was using StorageDevice.partedDevice, which I invited by
# naming it as a public attribute. We have removed it, and aren't bringing it
# back, so this allows us to put back just the bits that openlmi-storage expects
# to find.
from collections import namedtuple
PartedAlignment = namedtuple('PartedAlignment', ['grainSize'])
PartedDevice = namedtuple('PartedDevice',
                          ['length', 'sectorSize', 'optimumAlignment'])

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
    _formatImmutable = False
    _partitionable = False
    _isDisk = False
    _encrypted = False

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

        # Set these fields before super call as MDRaidArrayDevice._addParent()
        # reads them, through calls to status() and partedDevice().
        self.sysfsPath = sysfsPath

        self._format = None

        # The size will be overridden by a call to updateSize at the end of this
        # method for existing and active devices.
        self._size = Size(util.numeric_type(size))
        self._currentSize = self._size if self.exists else Size(0)
        self.major = util.numeric_type(major)
        self.minor = util.numeric_type(minor)
        self._serial = serial
        self._vendor = vendor or ""
        self._model = model or ""
        self.bus = bus

        self._readonly = False
        self._protected = False
        self.controllable = not flags.testing

        Device.__init__(self, name, parents=parents)

        self.format = fmt
        self.originalFormat = copy.copy(self.format)
        self.fstabComment = ""
        self._targetSize = self._size

        self.deviceLinks = []

        self.partedDevice = None
        if self.exists and self.status:
            self.updateSize()

        self._orig_size = self._size

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
        return self._encrypted or any(p.encrypted for p in self.parents)

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

    def alignTargetSize(self, newsize):
        """ Return a proposed target size adjusted for device specifics.

            :param :class:`~.Size` newsize: the proposed/unaligned target size
            :returns: newsize modified to yield an aligned device
            :rtype: :class:`~.Size`
        """

        return newsize

    def _getTargetSize(self):
        return self._targetSize

    def _setTargetSize(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        if self.maxSize and newsize > self.maxSize:
            log.error("requested size %s is larger than maximum %s",
                      newsize, self.maxSize)
            raise ValueError("size is larger than the maximum for this device")
        elif self.minSize and newsize < self.minSize:
            log.error("requested size %s is smaller than minimum %s",
                      newsize, self.minSize)
            raise ValueError("size is smaller than the minimum for this device")

        # reverting to unaligned original size is not an issue
        if self.alignTargetSize(newsize) != newsize and newsize != self._orig_size:
            raise ValueError("new size would violate alignment requirements")

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
              "  sysfs path = %(sysfs)s\n"
              "  target size = %(targetSize)s  path = %(path)s\n"
              "  format args = %(formatArgs)s  originalFormat = %(origFmt)s" %
              {"uuid": self.uuid, "format": self.format, "size": self.size,
               "major": self.major, "minor": self.minor, "exists": self.exists,
               "sysfs": self.sysfsPath,
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
        # We're using os.path.exists as a stand-in for status. We can't use
        # the status property directly because MDRaidArrayDevice.status calls
        # this method.
        log_method_call(self, self.name, status=os.path.exists(self.path))
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        try:
            udev_device = pyudev.Device.from_device_file(udev.global_udev,
                                                         self.path)

        # from_device_file() does not process exceptions but just propagates
        # any errors that are raised.
        except (pyudev.DeviceNotFoundError, EnvironmentError, ValueError, OSError) as e:
            log.error("failed to update sysfs path for %s: %s", self.name, e)
            self.sysfsPath = ''
        else:
            self.sysfsPath = udev_device.sys_path
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

        path = os.path.normpath(self.sysfsPath)
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
        udev.settle()
        self.updateSysfsPath()
        # the device may not be set up when we want information about it
        if self._size == Size(0):
            self.updateSize()

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
        if self.format.exists:
            self.format.teardown()
        udev.settle()
        return True

    def _teardown(self, recursive=None):
        """ Perform device-specific teardown operations. """
        pass

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._preTeardown(recursive=recursive):
            if recursive:
                self.teardownParents(recursive=recursive)
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
        udev.settle()

        # make sure that targetSize is updated to reflect the actual size
        self.updateSize()

        self._updateNetDevMountOption()

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
        size = self._size
        if self.exists and self.resizable:
            size = self.targetSize

        return size

    def _setSize(self, newsize):
        """ Set the device's size to a new value.

            This is not adequate to set up a resize as it does not set a new
            target size for the device.
        """
        if not isinstance(newsize, Size):
            raise ValueError("new size must of type Size")

        # only calculate these once
        max_size = self.maxSize
        min_size = self.minSize
        if max_size and newsize > max_size:
            raise errors.DeviceError("device cannot be larger than %s" %
                                     max_size, self.name)
        elif min_size and newsize < min_size:
            raise errors.DeviceError("device cannot be smaller than %s" %
                                     min_size, self.name)

        self._size = newsize

    size = property(lambda x: x._getSize(),
                    lambda x, y: x._setSize(y),
                    doc="The device's size, accounting for pending changes")

    def _mockPartedDevice(self, size):
        # mock up a partedDevice for openlmi-storage
        sector_size_str = util.get_sysfs_attr(self.sysfsPath,
                                              "queue/logical_block_size")
        if sector_size_str is not None:
            sector_size = int(sector_size_str)
        else:
            sector_size = int(LINUX_SECTOR_SIZE)

        length = size // sector_size

        # XXX Here, we duplicate linux_get_optimum_alignment from libparted in
        #     its entirety.
        default_io_size = int(Size("1MiB"))
        optimum_io_size = int(util.get_sysfs_attr(self.sysfsPath,
                                                  "queue/optimal_io_size")
                              or '0')
        minimum_io_size = int(util.get_sysfs_attr(self.sysfsPath,
                                                  "queue/minimum_io_size")
                              or '0')
        optimum_divides_default = (optimum_io_size and
                                   default_io_size % optimum_io_size == 0)
        minimum_divides_default = (minimum_io_size and
                                   default_io_size % minimum_io_size == 0)
        io_size = optimum_io_size
        if ((not optimum_io_size and not minimum_io_size) or
            (optimum_divides_default and minimum_divides_default) or
            (not minimum_io_size and optimum_divides_default) or
            (not optimum_io_size and minimum_divides_default)):
            if arch.isS390():
                io_size = minimum_io_size
            else:
                io_size = default_io_size
        elif io_size == 0:
            io_size = minimum_io_size

        alignment = PartedAlignment(io_size // sector_size)
        self.partedDevice = PartedDevice(length=length,
                                         sectorSize=sector_size,
                                         optimumAlignment=alignment)

    def readCurrentSize(self):
        log_method_call(self, exists=self.exists, path=self.path,
                        sysfsPath=self.sysfsPath)
        size = Size(0)
        if self.exists and os.path.exists(self.path) and \
           os.path.isdir(self.sysfsPath):
            blocks = int(util.get_sysfs_attr(self.sysfsPath, "size") or '0')
            size = Size(blocks * LINUX_SECTOR_SIZE)

            self._mockPartedDevice(size)

        return size

    @property
    def currentSize(self):
        """ The device's actual size, generally the size discovered by using
            system tools. May use a cached value if the information is
            currently unavailable.

            If the device does not exist, then the actual size is 0.
        """
        if self._currentSize == Size(0):
            self._currentSize = self.readCurrentSize()
        return self._currentSize

    def updateSize(self):
        """ Update size, currentSize, and targetSize to actual size. """
        self._currentSize = Size(0)
        new_size = self.currentSize
        self._size = new_size
        self._targetSize = new_size # bypass setter checks
        log.debug("updated %s size to %s (%s)", self.name, self.size, new_size)

    @property
    def minSize(self):
        """ The minimum size this device can be. """
        return self.alignTargetSize(self.format.minSize) if self.resizable else self.currentSize

    @property
    def maxSize(self):
        """ The maximum size this device can be. """
        return self.alignTargetSize(self.format.maxSize) if self.resizable else self.currentSize

    @property
    def mediaPresent(self):
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
        self._updateNetDevMountOption()

    def _updateNetDevMountOption(self):
        """ Fix mount options to include or exclude _netdev as appropriate. """
        if not hasattr(self._format, "mountpoint"):
            return

        netdev_option = "_netdev"
        option_list = self._format.options.split(",")
        is_netdev = any(isinstance(a, NetworkStorageDevice)
                        for a in self.ancestors)
        has_netdev_option = netdev_option in option_list
        if not is_netdev and has_netdev_option:
            option_list.remove(netdev_option)
            self._format.options = ",".join(option_list)
        elif is_netdev and not has_netdev_option:
            option_list.append(netdev_option)
            self._format.options = ",".join(option_list)

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
        devpath = os.path.normpath(self.sysfsPath)
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

    # pylint: disable=unused-argument
    def removeHook(self, modparent=True):
        """ Perform actions related to removing a device from the devicetree.

            :keyword bool modparent: whether to account for removal in parents

            Parent child counts are adjusted regardless of modparent's value.
            The intended use of modparent is to prevent doing things like
            removing a parted.Partition from the disk that contains it as part
            of msdos extended partition management. In general, you should not
            override the default value of modparent in new code.
        """
        for parent in self.parents:
            parent.removeChild()

    def addHook(self, new=True):
        """ Perform actions related to adding a device to the devicetree.

            :keyword bool new: whether this device is new to the devicetree

            The only intended use case for new=False is when unhiding a device
            from the devicetree. Additional operations are performed when new is
            False that are normally performed as part of the device constructor.
        """
        if not new:
            map(lambda p: p.addChild(), self.parents)

    def populateKSData(self, data):
        # the common pieces are basically the formatting
        self.format.populateKSData(data)

        # this is a little bit of a hack for container member devices that
        # need aliases, but even more of a hack for btrfs since you cannot tell
        # from inside the BTRFS class whether you're dealing with a member or a
        # volume/subvolume
        if self.format.type == "btrfs" and not self.type.startswith("btrfs"):
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
