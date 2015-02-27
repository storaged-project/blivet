# filesystems.py
# Filesystem classes for anaconda's storage configuration module.
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
#                    David Cantrell <dcantrell@redhat.com>
#

""" Filesystem classes. """
from decimal import Decimal
import os
import tempfile

from ..tasks import fsck
from ..tasks import fsinfo
from ..tasks import fslabeling
from ..tasks import fsminsize
from ..tasks import fsmkfs
from ..tasks import fsmount
from ..tasks import fsreadlabel
from ..tasks import fsresize
from ..tasks import fssize
from ..tasks import fssync
from ..tasks import fswritelabel
from ..errors import FormatCreateError, FSError, FSReadLabelError
from ..errors import FSWriteLabelError, FSResizeError
from . import DeviceFormat, register_device_format
from .. import util
from .. import platform
from ..flags import flags
from parted import fileSystemType
from ..storage_log import log_exception_info, log_method_call
from .. import arch
from ..size import Size, ROUND_UP, ROUND_DOWN, unitStr
from ..i18n import N_
from .. import udev
from ..mounts import mountsCache

from .fslib import kernel_filesystems, update_kernel_filesystems

import logging
log = logging.getLogger("blivet")

class FS(DeviceFormat):
    """ Filesystem base class. """
    _type = "Abstract Filesystem Class"  # fs type name
    _name = None
    _modules = []                        # kernel modules required for support
    _labelfs = None                      # labeling functionality
    _fsckClass = fsck.UnimplementedFSCK
    _infoClass = fsinfo.UnimplementedFSInfo
    _minsizeClass = fsminsize.UnimplementedFSMinSize
    _mkfsClass = fsmkfs.UnimplementedFSMkfs
    _mountClass = fsmount.FSMount
    _readlabelClass = fsreadlabel.UnimplementedFSReadLabel
    _resizeClass = fsresize.UnimplementedFSResize
    _sizeinfoClass = fssize.UnimplementedFSSize
    _syncClass = fssync.UnimplementedFSSync
    _writelabelClass = fswritelabel.UnimplementedFSWriteLabel

    def __init__(self, **kwargs):
        """
            :keyword device: path to the block device node (required for
                             existing filesystems)
            :keyword mountpoint: the filesystem's planned mountpoint
            :keyword label: the filesystem label
            :keyword uuid: the filesystem UUID
            :keyword mountopts: mount options for the filesystem
            :type mountopts: str
            :keyword size: the filesystem's size in MiB
            :keyword exists: indicates whether this is an existing filesystem
            :type exists: bool

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.
        """

        if self.__class__ is FS:
            raise TypeError("FS is an abstract class.")

        DeviceFormat.__init__(self, **kwargs)

        # Create task objects
        self._info = self._infoClass(self)
        self._fsck = self._fsckClass(self)
        self._mkfs = self._mkfsClass(self)
        self._mount = self._mountClass(self)
        self._readlabel = self._readlabelClass(self)
        self._resize = self._resizeClass(self)
        self._sync = self._syncClass(self)
        self._writelabel = self._writelabelClass(self)

        # These two may depend on info class, so create them after
        self._minsize = self._minsizeClass(self)
        self._sizeinfo = self._sizeinfoClass(self)

        self._current_info = None # info obtained by _info task

        self.mountpoint = kwargs.get("mountpoint")
        self.mountopts = kwargs.get("mountopts")
        self.label = kwargs.get("label")
        self.fsprofile = kwargs.get("fsprofile")

        # filesystem size does not necessarily equal device size
        self._size = kwargs.get("size", Size(0))
        self._minInstanceSize = Size(0)    # min size of this FS instance

        # Resize operations are limited to error-free filesystems whose current
        # size is known.
        self._resizable = False
        if flags.installer_mode and not self._resize.unavailable:
            # if you want current/min size you have to call updateSizeInfo
            try:
                self.updateSizeInfo()
            except FSError:
                log.warning("%s filesystem on %s needs repair", self.type,
                                                                self.device)

        self._targetSize = self._size

        if self.supported:
            self.loadModule()

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  mountpoint = %(mountpoint)s  mountopts = %(mountopts)s\n"
              "  label = %(label)s  size = %(size)s"
              "  targetSize = %(targetSize)s\n" %
              {"mountpoint": self.mountpoint, "mountopts": self.mountopts,
               "label": self.label, "size": self._size,
               "targetSize": self.targetSize})
        return s

    @property
    def desc(self):
        s = "%s filesystem" % self.type
        if self.mountpoint:
            s += " mounted at %s" % self.mountpoint
        return s

    @property
    def dict(self):
        d = super(FS, self).dict
        d.update({"mountpoint": self.mountpoint, "size": self._size,
                  "label": self.label, "targetSize": self.targetSize,
                  "mountable": self.mountable})
        return d

    def labeling(self):
        """Returns True if this filesystem uses labels, otherwise False.

           :rtype: bool
        """
        return (self._mkfs.labels and not self._mkfs.unavailable) or not self._writelabel.unavailable

    def relabels(self):
        """Returns True if it is possible to relabel this filesystem
           after creation, otherwise False.

           :rtype: bool
        """
        return not self._writelabel.unavailable

    def labelFormatOK(self, label):
        """Return True if the label has an acceptable format for this
           filesystem. None, which represents accepting the default for this
           device, is always acceptable.

           :param label: A possible label
           :type label: str or None
        """
        return label is None or (self._labelfs is not None and self._labelfs.labelFormatOK(label))

    label = property(lambda s: s._getLabel(), lambda s,l: s._setLabel(l),
       doc="this filesystem's label")

    def _setTargetSize(self, newsize):
        """ Set a target size for this filesystem. """
        if not isinstance(newsize, Size):
            raise ValueError("new size must be of type Size")

        if not self.exists:
            raise FSError("filesystem has not been created")

        if not self.resizable:
            raise FSError("filesystem is not resizable")

        if newsize is None:
            # unset any outstanding resize request
            self._targetSize = self._size
            return

        if not self.minSize <= newsize < self.maxSize:
            raise ValueError("requested size %s must fall between minimum size %s and maximum size %s" % (newsize, self.minSize, self.maxSize))

        self._targetSize = newsize

    def _getTargetSize(self):
        """ Get this filesystem's target size. """
        return self._targetSize

    targetSize = property(_getTargetSize, _setTargetSize,
                          doc="Target size for this filesystem")

    def _getSize(self):
        """ Get this filesystem's size. """
        return self.targetSize if self.resizable else self._size

    size = property(_getSize, doc="This filesystem's size, accounting "
                                  "for pending changes")

    def updateSizeInfo(self):
        """ Update this filesystem's current and minimum size (for resize). """
        if not self.exists:
            return

        self._size = Size(0)
        self._minSize = self.__class__._minSize
        self._minInstanceSize = Size(0)
        self._resizable = self.__class__._resizable

        # We can't allow resize if the filesystem has errors.
        try:
            self.doCheck()
        except FSError:
            errors = True
            raise
        else:
            errors = False
        finally:
            # try to gather current size info anyway
            self._current_info = self._getFSInfo()
            self._size = self._getExistingSize()
            self._minSize = self._size # default to current size
            # We absolutely need a current size to enable resize. To shrink the
            # filesystem we need a real minimum size provided by the resize
            # tool. Failing that, we can default to the current size,
            # effectively disabling shrink.
            if errors or self._size == Size(0):
                self._resizable = False

        self._minInstanceSize = self._getMinSize()

    def _padSize(self, size):
        """ Return a size padded according to some inflating rules.

            This method was originally designed solely for minimum sizes,
            and may only apply to them.

            :param size: any size
            :type size: :class:`~.size.Size`
            :returns: a padded size
            :rtype: :class:`~.size.Size`
        """
        # add some padding to the min size
        padded = min(size * Decimal('1.1'), size + Size("500 MiB"))

        # make sure the padded and rounded min size is not larger than
        # the current size
        padded = min(padded.roundToNearest(self._resize.unit, rounding=ROUND_UP), self.currentSize)

        return padded

    def _getMinSize(self):
        """ Get the minimum size of the filesystem. This represents a lower
            bound for shrinking the filesystem.

            :returns: a lower bound for shrinking
            :rtype: :class:`~.size.Size`
        """
        if not self._minsizeClass.implemented:
            return self._minInstanceSize

        size = self._minSize
        if self.exists and os.path.exists(self.device) and not self._minsize.unavailable:
            try:
                result = self._minsize.doTask()
            except FSError as e:
                log.warning("failed to get minimum size for %s filesystem "
                            "on %s: %s", self.type, self.device, e)
            else:
                size = self._padSize(result)
                if result < size:
                    log.debug("padding min size from %s up to %s", result, size)
                else:
                    log.debug("using current size %s as min size", size)

        return size

    def _getFSInfo(self):
        """ Get filesystem information by use of external tools.

            :returns: the output of the tool
            :rtype: str

            If for any reason the information is not obtained returns the
            empty string.
        """
        buf = ""

        if not self._info.unavailable:
            try:
                buf = self._info.doTask()
            except FSError as e:
                log.error(e)

        return buf

    def _getExistingSize(self):
        """ Determine the size of this filesystem.

            :returns: size of existing fs
            :rtype: :class:`~.size.Size`
        """
        size = Size(0)

        if not self._sizeinfo.unavailable:
            try:
                size = self._sizeinfo.doTask()
            except FSError as e:
                log.error("failed to obtain size of filesystem on %s: %s", self.device, e)

        return size

    @property
    def currentSize(self):
        """ The filesystem's current actual size. """
        return self._size if self.exists else Size(0)

    @property
    def free(self):
        """ The amount of space that can be gained by resizing this
            filesystem to its minimum size.
        """
        return max(Size(0), self.currentSize - self.minSize)


    def doFormat(self, options=None):
        """ Create the filesystem.

            :param options: options to pass to mkfs
            :type options: list of strings
            :raises: FormatCreateError, FSError
        """
        log_method_call(self, type=self.mountType, device=self.device,
                        mountpoint=self.mountpoint)

        if self._mkfs.unavailable:
            return

        try:
            self._mkfs.doTask(options=options, label=not self.relabels())
        except FSWriteLabelError as e:
            log.warning("Choosing not to apply label (%s) during creation of filesystem %s. Label format is unacceptable for this filesystem.", self.label, self.type)
        except FSError as e:
            raise FormatCreateError(e, self.device)

        self.exists = True
        self.notifyKernel()

        if self.label is not None and self.relabels():
            try:
                self.writeLabel()
            except FSError as e:
                log.warning("Failed to write label (%s) for filesystem %s: %s", self.label, self.type, e)

    def doResize(self):
        """ Resize this filesystem based on this instance's targetSize attr.

            :raises: FSResizeError, FSError
        """
        if not self.resizable:
            raise FSResizeError("filesystem not resizable", self.device)

        if self.targetSize == self.currentSize:
            return

        if self._resize.unavailable:
            return

        # The first minimum size can be incorrect if the fs was not
        # properly unmounted. After doCheck the minimum size will be correct
        # so run the check one last time and bump up the size if it was too
        # small.
        self.updateSizeInfo()

        # Check again if resizable is True, as updateSizeInfo() can change that
        if not self.resizable:
            raise FSResizeError("filesystem not resizable", self.device)

        if self.targetSize < self.minSize:
            self.targetSize = self.minSize
            log.info("Minimum size changed, setting targetSize on %s to %s",
                     self.device, self.targetSize)

        # Bump target size to nearest whole number of the resize tool's units.
        # We always round down because the fs has to fit on whatever device
        # contains it. To round up would risk quietly setting a target size too
        # large for the device to hold.
        rounded = self.targetSize.roundToNearest(self._resize.unit,
                                                 rounding=ROUND_DOWN)

        # 1. target size was between the min size and max size values prior to
        #    rounding (see _setTargetSize)
        # 2. we've just rounded the target size down (or not at all)
        # 3. the minimum size is already either rounded (see _getMinSize) or is
        #    equal to the current size (see updateSizeInfo)
        # 5. the minimum size is less than or equal to the current size (see
        #    _getMinSize)
        #
        # This, I think, is sufficient to guarantee that the rounded target size
        # is greater than or equal to the minimum size.

        # It is possible that rounding down a target size greater than the
        # current size would move it below the current size, thus changing the
        # direction of the resize. That means the target size was less than one
        # unit larger than the current size, and we should do nothing and return
        # early.
        if self.targetSize > self.currentSize and rounded < self.currentSize:
            log.info("rounding target size down to next %s obviated resize of "
                     "filesystem on %s", unitStr(self._resize.unit), self.device)
            return
        else:
            self.targetSize = rounded

        try:
            self._resize.doTask()
        except FSError as e:
            raise FSResizeError(e, self.device)

        self.doCheck()

        # XXX must be a smarter way to do this
        self._size = self.targetSize
        self.notifyKernel()

    def doCheck(self):
        """ Run a filesystem check.

            :raises: FSError
        """
        if not self._fsck.unavailable:
            self._fsck.doTask()
        else:
            return

    def loadModule(self):
        """Load whatever kernel module is required to support this filesystem."""
        if not self._modules or self.mountType in kernel_filesystems:
            return

        for module in self._modules:
            try:
                rc = util.run_program(["modprobe", module])
            except OSError as e:
                log.error("Could not load kernel module %s: %s", module, e)
                self._supported = False
                return

            if rc:
                log.error("Could not load kernel module %s", module)
                self._supported = False
                return

        # If we successfully loaded a kernel module for this filesystem, we
        # also need to update the list of supported filesystems.
        update_kernel_filesystems()

    @property
    def systemMountpoint(self):
        """ Get current mountpoint

            returns: mountpoint
            rtype: str or None

        """

        if not self.exists:
            return None

        return mountsCache.getMountpoint(self.device,
                                         getattr(self, "subvolspec", None))

    def testMount(self):
        """ Try to mount the fs and return True if successful. """
        ret = False

        if self.status:
            return True

        # create a temp dir
        prefix = "%s.%s" % (os.path.basename(self.device), self.type)
        mountpoint = tempfile.mkdtemp(prefix=prefix)

        # try the mount
        try:
            rc = self.mount(mountpoint=mountpoint)
            ret = not rc
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.info, "test mount failed")

        if ret:
            self.unmount()

        os.rmdir(mountpoint)

        return ret

    def mount(self, options="", chroot="/", mountpoint=None):
        """ Mount this filesystem.

            :keyword options: mount options (overrides all other option strings)
            :type options: str.
            :keyword chroot: prefix to apply to mountpoint
            :keyword mountpoint: mountpoint (overrides self.mountpoint)
            :raises: FSError
        """
        if self.status:
            return

        if not mountpoint:
            mountpoint = self.mountpoint

        if not mountpoint:
            raise FSError("no mountpoint given")

        # XXX os.path.join is FUBAR:
        #
        #         os.path.join("/mnt/foo", "/") -> "/"
        #
        #mountpoint = os.path.join(chroot, mountpoint)
        chrootedMountpoint = os.path.normpath("%s/%s" % (chroot, mountpoint))

        options = self._mount.doTask(chrootedMountpoint, options=options)

        if flags.selinux and "ro" not in options.split(",") and flags.installer_mode:
            ret = util.reset_file_context(mountpoint, chroot)
            if not ret:
                log.warning("Failed to reset SElinux context for newly mounted filesystem root directory to default.")
            lost_and_found_context = util.match_path_context("/lost+found")
            lost_and_found_path = os.path.join(mountpoint, "lost+found")
            ret = util.set_file_context(lost_and_found_path, lost_and_found_context, chroot)
            if not ret:
                log.warning("Failed to set SELinux context for newly mounted filesystem lost+found directory at %s to %s", lost_and_found_path, lost_and_found_context)

    def unmount(self):
        """ Unmount this filesystem. """
        if not self.exists:
            raise FSError("filesystem has not been created")

        if not self.systemMountpoint:
            # not mounted
            return

        if not os.path.exists(self.systemMountpoint):
            raise FSError("mountpoint does not exist")

        udev.settle()
        rc = util.umount(self.systemMountpoint)
        if rc:
            # try and catch whatever is causing the umount problem
            util.run_program(["lsof", self.systemMountpoint])
            raise FSError("umount failed")

    def readLabel(self):
        """Read this filesystem's label.

           :return: the filesystem's label
           :rtype: str

           Raises a FSReadLabelError if the label can not be read.
        """
        if not self._readlabel.unavailable:
            return self._readlabel.doTask()
        else:
            raise FSReadLabelError("label reading not implemented for filesystem %s" % self.type)

    def writeLabel(self):
        """ Create a label for this filesystem.

            :raises: FSError

            If self.label is None, this means accept the default, so raise
            an FSError in this case.

            Raises a FSError if the label can not be set.
        """
        if not self._writelabel.unavailable:
            self._writelabel.doTask()
        else:
            raise FSError("label writing not implemented for filesystem %s" % self.type)
        self.notifyKernel()

    @property
    def utilsAvailable(self):
        # we aren't checking for fsck because we shouldn't need it
        tasks = [self._mkfs, self._resize, self._writelabel, self._info]
        return not any(t.implemented and t.unavailable for t in tasks)

    @property
    def supported(self):
        log_method_call(self, supported=self._supported)
        return self._supported and self.utilsAvailable

    @property
    def mountable(self):
        return not self._mount.unavailable

    @property
    def resizable(self):
        """ Can formats of this filesystem type be resized? """
        return super(FS, self).resizable and self.utilsAvailable

    def _getOptions(self):
        return self.mountopts or ",".join(self._mount.options)

    def _setOptions(self, options):
        self.mountopts = options

    @property
    def mountType(self):
        return self._mount.mountType

    # These methods just wrap filesystem-specific methods in more
    # generically named methods so filesystems and formatted devices
    # like swap and LVM physical volumes can have a common API.
    def create(self, **kwargs):
        """ Create the filesystem on the specified block device.

            :keyword device: path to device node
            :type device: str.
            :raises: FormatCreateError, FSError
            :returns: None.

            .. :note::

                If a device node path is passed to this method it will overwrite
                any previously set value of this instance's "device" attribute.
        """
        if self.exists:
            raise FSError("filesystem already exists")

        DeviceFormat.create(self, **kwargs)

        self.doFormat(options=kwargs.get('options'))

    def setup(self, **kwargs):
        """ Mount the filesystem.

            The filesystem will be mounted at the directory indicated by
            self.mountpoint unless overridden via the 'mountpoint' kwarg.

            :keyword device: device node path
            :type device: str.
            :keyword mountpoint: mountpoint (overrides self.mountpoint)
            :type mountpoint: str.
            :raises: FormatSetupError.
            :returns: None.

            .. :note::

                If a device node path is passed to this method it will overwrite
                any previously set value of this instance's "device" attribute.
        """
        return self.mount(**kwargs)

    def teardown(self):
        return self.unmount()

    @property
    def status(self):
        # FIXME check /proc/mounts or similar
        if not self.exists:
            return False
        return self.systemMountpoint is not None

    def sync(self, root='/'):
        """ Ensure that data we've written is at least in the journal.

            This is a little odd because xfs_freeze will only be
            available under the install root.
        """
        if self._sync.unavailable:
            return

        if not self._mountpoint.startswith(root):
            return

        try:
            self._sync.doTask(root)
        except FSError as e:
            log.error(e)

    def populateKSData(self, data):
        super(FS, self).populateKSData(data)
        data.mountpoint = self.mountpoint or "none"
        data.label = self.label or ""
        if self.options != "defaults":
            data.fsopts = self.options
        else:
            data.fsopts = ""

        data.fsprofile = self.fsprofile or ""

class Ext2FS(FS):
    """ ext2 filesystem. """
    _type = "ext2"
    _modules = ["ext2"]
    _labelfs = fslabeling.Ext2FSLabeling()
    _packages = ["e2fsprogs"]
    _formattable = True
    _supported = True
    _resizable = True
    _linuxNative = True
    _maxSize = Size("8 TiB")
    _dump = True
    _check = True
    _fsckClass = fsck.Ext2FSCK
    _infoClass = fsinfo.Ext2FSInfo
    _minsizeClass = fsminsize.Ext2FSMinSize
    _mkfsClass = fsmkfs.Ext2FSMkfs
    _readlabelClass = fsreadlabel.Ext2FSReadLabel
    _resizeClass = fsresize.Ext2FSResize
    _sizeinfoClass = fssize.Ext2FSSize
    _writelabelClass = fswritelabel.Ext2FSWriteLabel
    partedSystem = fileSystemType["ext2"]

    @property
    def minSize(self):
        return self._minInstanceSize

register_device_format(Ext2FS)


class Ext3FS(Ext2FS):
    """ ext3 filesystem. """
    _type = "ext3"
    _modules = ["ext3"]
    partedSystem = fileSystemType["ext3"]
    _mkfsClass = fsmkfs.Ext3FSMkfs

    # It is possible for a user to specify an fsprofile that defines a blocksize
    # smaller than the default of 4096 bytes and therefore to make liars of us
    # with regard to this maximum filesystem size, but if they're doing such
    # things they should know the implications of their chosen block size.
    _maxSize = Size("16 TiB")

register_device_format(Ext3FS)


class Ext4FS(Ext3FS):
    """ ext4 filesystem. """
    _type = "ext4"
    _modules = ["ext4"]
    _mkfsClass = fsmkfs.Ext4FSMkfs
    partedSystem = fileSystemType["ext4"]

register_device_format(Ext4FS)


class FATFS(FS):
    """ FAT filesystem. """
    _type = "vfat"
    _modules = ["vfat"]
    _labelfs = fslabeling.FATFSLabeling()
    _supported = True
    _formattable = True
    _maxSize = Size("1 TiB")
    _packages = [ "dosfstools" ]
    _fsckClass = fsck.DosFSCK
    _mkfsClass = fsmkfs.FATFSMkfs
    _mountClass = fsmount.FATFSMount
    _readlabelClass = fsreadlabel.DosFSReadLabel
    _writelabelClass = fswritelabel.DosFSWriteLabel
    # FIXME this should be fat32 in some cases
    partedSystem = fileSystemType["fat16"]

register_device_format(FATFS)


class EFIFS(FATFS):
    _type = "efi"
    _name = N_("EFI System Partition")
    _minSize = Size("50 MiB")
    _check = True
    _mountClass = fsmount.EFIFSMount

    @property
    def supported(self):
        return super(EFIFS, self).supported and isinstance(platform.platform, platform.EFI)

register_device_format(EFIFS)


class BTRFS(FS):
    """ btrfs filesystem """
    _type = "btrfs"
    _modules = ["btrfs"]
    _formattable = True
    _linuxNative = True
    _supported = True
    _packages = ["btrfs-progs"]
    _minSize = Size("256 MiB")
    _maxSize = Size("16 EiB")
    _mkfsClass = fsmkfs.BTRFSMkfs
    # FIXME parted needs to be taught about btrfs so that we can set the
    # partition table type correctly for btrfs partitions
    # partedSystem = fileSystemType["btrfs"]

    def __init__(self, **kwargs):
        super(BTRFS, self).__init__(**kwargs)
        self.volUUID = kwargs.pop("volUUID", None)
        self.subvolspec = kwargs.pop("subvolspec", None)

    def create(self, **kwargs):
        # filesystem creation is done in blockdev.btrfs_create_volume
        self.exists = True

    def destroy(self, **kwargs):
        # filesystem deletion is done in blockdev.btrfs_delete_volume
        self.exists = False

    def setup(self, **kwargs):
        """ Mount the filesystem.

            The filesystem will be mounted at the directory indicated by
            self.mountpoint unless overridden via the 'mountpoint' kwarg.

            :keyword device: device node path
            :type device: str.
            :keyword mountpoint: mountpoint (overrides self.mountpoint)
            :type mountpoint: str.
            :raises: FormatSetupError.
            :returns: None.

            .. :note::

                If a device node path is passed to this method it will overwrite
                any previously set value of this instance's "device" attribute.
        """
        log_method_call(self, type=self.mountType, device=self.device,
                        mountpoint=self.mountpoint)
        if not self.mountpoint and "mountpoint" not in kwargs:
            # Since btrfs vols have subvols the format setup is automatic.
            # Don't try to mount it if there's no mountpoint.
            return

        return self.mount(**kwargs)

register_device_format(BTRFS)


class GFS2(FS):
    """ gfs2 filesystem. """
    _type = "gfs2"
    _modules = ["dlm", "gfs2"]
    _formattable = True
    _linuxNative = True
    _dump = True
    _check = True
    _packages = ["gfs2-utils"]
    _mkfsClass = fsmkfs.GFS2Mkfs
    # FIXME parted needs to be thaught about btrfs so that we can set the
    # partition table type correctly for btrfs partitions
    # partedSystem = fileSystemType["gfs2"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        return self.utilsAvailable if flags.gfs2 else self._supported

register_device_format(GFS2)


class JFS(FS):
    """ JFS filesystem """
    _type = "jfs"
    _modules = ["jfs"]
    _labelfs = fslabeling.JFSLabeling()
    _maxSize = Size("8 TiB")
    _formattable = True
    _linuxNative = True
    _dump = True
    _check = True
    _infoClass = fsinfo.JFSInfo
    _mkfsClass = fsmkfs.JFSMkfs
    _sizeinfoClass = fssize.JFSSize
    _writelabelClass = fswritelabel.JFSWriteLabel
    partedSystem = fileSystemType["jfs"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        return self.utilsAvailable if flags.jfs else self._supported

register_device_format(JFS)


class ReiserFS(FS):
    """ reiserfs filesystem """
    _type = "reiserfs"
    _labelfs = fslabeling.ReiserFSLabeling()
    _modules = ["reiserfs"]
    _maxSize = Size("16 TiB")
    _formattable = True
    _linuxNative = True
    _dump = True
    _check = True
    _packages = ["reiserfs-utils"]
    _infoClass = fsinfo.ReiserFSInfo
    _mkfsClass = fsmkfs.ReiserFSMkfs
    _sizeinfoClass = fssize.ReiserFSSize
    _writelabelClass = fswritelabel.ReiserFSWriteLabel
    partedSystem = fileSystemType["reiserfs"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        return self.utilsAvailable if flags.reiserfs else self._supported

register_device_format(ReiserFS)


class XFS(FS):
    """ XFS filesystem """
    _type = "xfs"
    _modules = ["xfs"]
    _labelfs = fslabeling.XFSLabeling()
    _maxSize = Size("16 EiB")
    _formattable = True
    _linuxNative = True
    _supported = True
    _packages = ["xfsprogs"]
    _infoClass = fsinfo.XFSInfo
    _mkfsClass = fsmkfs.XFSMkfs
    _readlabelClass = fsreadlabel.XFSReadLabel
    _sizeinfoClass = fssize.XFSSize
    _syncClass = fssync.XFSSync
    _writelabelClass = fswritelabel.XFSWriteLabel
    partedSystem = fileSystemType["xfs"]

register_device_format(XFS)

class HFS(FS):
    _type = "hfs"
    _modules = ["hfs"]
    _labelfs = fslabeling.HFSLabeling()
    _formattable = True
    _mkfsClass = fsmkfs.HFSMkfs
    partedSystem = fileSystemType["hfs"]

register_device_format(HFS)


class AppleBootstrapFS(HFS):
    _type = "appleboot"
    _name = N_("Apple Bootstrap")
    _minSize = Size("768 KiB")
    _maxSize = Size("1 MiB")
    _supported = True
    _mountClass = fsmount.AppleBootstrapFSMount

    @property
    def supported(self):
        return super(AppleBootstrapFS, self).supported and isinstance(platform.platform, platform.NewWorldPPC)

register_device_format(AppleBootstrapFS)


class HFSPlus(FS):
    _type = "hfs+"
    _modules = ["hfsplus"]
    _udevTypes = ["hfsplus"]
    _packages = ["hfsplus-tools"]
    _labelfs = fslabeling.HFSPlusLabeling()
    _formattable = True
    _minSize = Size("1 MiB")
    _maxSize = Size("2 TiB")
    _check = True
    partedSystem = fileSystemType["hfs+"]
    _fsckClass = fsck.HFSPlusFSCK
    _mkfsClass = fsmkfs.HFSPlusMkfs
    _mountClass = fsmount.HFSPlusMount

register_device_format(HFSPlus)


class MacEFIFS(HFSPlus):
    _type = "macefi"
    _name = N_("Linux HFS+ ESP")
    _udevTypes = []
    _minSize = Size("50 MiB")
    _supported = True

    @property
    def supported(self):
        return super(MacEFIFS, self).supported and isinstance(platform.platform, platform.MacEFI)

    def __init__(self, **kwargs):
        if "label" not in kwargs:
            kwargs["label"] = self._name
        super(MacEFIFS, self).__init__(**kwargs)

register_device_format(MacEFIFS)


class NTFS(FS):
    """ ntfs filesystem. """
    _type = "ntfs"
    _labelfs = fslabeling.NTFSLabeling()
    _resizable = True
    _minSize = Size("1 MiB")
    _maxSize = Size("16 TiB")
    _packages = ["ntfsprogs"]
    _fsckClass = fsck.NTFSFSCK
    _infoClass = fsinfo.NTFSInfo
    _minsizeClass = fsminsize.NTFSMinSize
    _mkfsClass = fsmkfs.NTFSMkfs
    _mountClass = fsmount.NTFSMount
    _readlabelClass = fsreadlabel.NTFSReadLabel
    _resizeClass = fsresize.NTFSResize
    _sizeinfoClass = fssize.NTFSSize
    _writelabelClass = fswritelabel.NTFSWriteLabel
    partedSystem = fileSystemType["ntfs"]

    @property
    def minSize(self):
        return self._minInstanceSize

register_device_format(NTFS)


# if this isn't going to be mountable it might as well not be here
class NFS(FS):
    """ NFS filesystem. """
    _type = "nfs"
    _modules = ["nfs"]
    _mountClass = fsmount.NFSMount

    def _deviceCheck(self, devspec):
        if devspec is not None and ":" not in devspec:
            return "device must be of the form <host>:<path>"
        return None

register_device_format(NFS)


class NFSv4(NFS):
    """ NFSv4 filesystem. """
    _type = "nfs4"
    _modules = ["nfs4"]

register_device_format(NFSv4)


class Iso9660FS(FS):
    """ ISO9660 filesystem. """
    _type = "iso9660"
    _supported = True
    _mountClass = fsmount.Iso9660FSMount

register_device_format(Iso9660FS)


class NoDevFS(FS):
    """ nodev filesystem base class """
    _type = "nodev"
    _mountClass = fsmount.NoDevFSMount

    def __init__(self, **kwargs):
        FS.__init__(self, **kwargs)
        self.exists = True
        self.device = self._type

    def _deviceCheck(self, devspec):
        return None

    @property
    def type(self):
        return self.device

    def notifyKernel(self):
        # NoDevFS should not need to tell the kernel anything.
        pass

register_device_format(NoDevFS)


class DevPtsFS(NoDevFS):
    """ devpts filesystem. """
    _type = "devpts"
    _mountClass = fsmount.DevPtsFSMount

register_device_format(DevPtsFS)


# these don't really need to be here
class ProcFS(NoDevFS):
    _type = "proc"

register_device_format(ProcFS)


class SysFS(NoDevFS):
    _type = "sysfs"

register_device_format(SysFS)


class TmpFS(NoDevFS):
    _type = "tmpfs"
    _supported = True
    # remounting can be used to change
    # the size of a live tmpfs mount
    # as tmpfs is part of the Linux kernel,
    # it is Linux-native
    _linuxNative = True
    # in a sense, I guess tmpfs is formattable
    # in the regard that the format is automatically created
    # once mounted
    _formattable = True
    _sizeinfoClass = fssize.TmpFSSize
    _mountClass = fsmount.TmpFSMount
    _resizeClass = fsresize.TmpFSResize

    def __init__(self, **kwargs):
        NoDevFS.__init__(self, **kwargs)
        self._device = "tmpfs"

        # according to the following Kernel ML thread:
        # http://www.gossamer-threads.com/lists/linux/kernel/875278
        # maximum tmpfs mount size is 16TB on 32 bit systems
        # and 16EB on 64 bit systems
        bits = arch.numBits()
        if bits == 32:
            self._maxSize = Size("16TiB")
        elif bits == 64:
            self._maxSize = Size("16EiB")
        # if the architecture is other than 32 or 64 bit or unknown
        # just use the default maxsize, which is 0, this disables
        # resizing but other operations such as mounting should work fine

        # if the size is 0, which is probably not set, accept the default
        # size when mounting.
        self._accept_default_size = not(self._size)

    def create(self, **kwargs):
        """ A filesystem is created automatically once tmpfs is mounted. """
        pass

    def destroy(self, *args, **kwargs):
        """ The device and its filesystem are automatically destroyed once the
        mountpoint is unmounted.
        """
        pass

    def _sizeOption(self, size):
        """ Returns a size option string appropriate for mounting tmpfs.

            :param Size size: any size
            :returns: size option
            :rtype: str

            This option should be appended to other mount options, in
            case the regular mountopts also contain a size option.
            This is not impossible, since a special option for mounting
            is size=<percentage>%.
        """
        return "size=%s" % (self._resize.size_fmt % size.convertTo(self._resize.unit))

    def _getOptions(self):
        # Returns the regular mount options with the special size option,
        # if any, appended.
        # The size option should be last, as the regular mount options may
        # also contain a size option, but the later size option supercedes
        # the earlier one.
        opts = super(TmpFS, self)._getOptions()
        if self._accept_default_size:
            size_opt = None
        else:
            size_opt = self._sizeOption(self._size)
        return ",".join(o for o in (opts, size_opt) if o)

    @property
    def free(self):
        if self.systemMountpoint:
            # If self.systemMountpoint is defined, it means this tmpfs mount
            # has been mounted and there is a path we can use as a handle to
            # look-up the free space on the filesystem.
            # When running with changeroot, such as during installation,
            # self.systemMountpoint is set to the full changeroot path once
            # mounted so even with changeroot, statvfs should still work fine.
            st = os.statvfs(self.systemMountpoint)
            free_space = Size(st.f_bavail*st.f_frsize)
        else:
            # Free might be called even if the tmpfs mount has not been
            # mounted yet, in this case just return the size set for the mount.
            # Once mounted, the tmpfs mount will be empty
            # and therefore free space will correspond to its size.
            free_space = self._size
        return free_space

    def _getDevice(self):
        """ All the tmpfs mounts use the same "tmpfs" device. """
        return self._type

    def _setDevice(self, value):
        # the DeviceFormat parent class does a
        # self.device = kwargs["device"]
        # assignment, so we need a setter for the
        # device property, but as the device is always the
        # same, nothing actually needs to be set
        pass

    def doResize(self):
        # Override superclass method to record whether mount options
        # should include an explicit size specification.
        original_size = self._size
        FS.doResize(self)
        self._accept_default_size = self._accept_default_size and original_size == self._size

register_device_format(TmpFS)


class BindFS(FS):
    _type = "bind"
    _mountClass = fsmount.BindFSMount

register_device_format(BindFS)


class SELinuxFS(NoDevFS):
    _type = "selinuxfs"
    _mountClass = fsmount.SELinuxFSMount

register_device_format(SELinuxFS)


class USBFS(NoDevFS):
    _type = "usbfs"

register_device_format(USBFS)
