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

from . import fslabeling
from ..errors import FormatCreateError, FSError, FSResizeError
from . import DeviceFormat, register_device_format
from .. import util
from .. import platform
from ..flags import flags
from parted import fileSystemType
from ..storage_log import log_exception_info, log_method_call
from .. import arch
from ..size import Size, ROUND_UP, ROUND_DOWN, unitStr
from ..size import B, KiB, MiB, GiB, KB, MB, GB
from ..i18n import _, N_
from .. import udev

import logging
log = logging.getLogger("blivet")

fs_configs = {}

kernel_filesystems = []
nodev_filesystems = []

def update_kernel_filesystems():
    for line in open("/proc/filesystems").readlines():
        fields = line.split()
        kernel_filesystems.append(fields[-1])
        if fields[0] == "nodev":
            nodev_filesystems.append(fields[-1])

update_kernel_filesystems()

class FS(DeviceFormat):
    """ Filesystem base class. """
    _type = "Abstract Filesystem Class"  # fs type name
    _mountType = None                    # like _type but for passing to mount
    _name = None
    _mkfs = ""                           # mkfs utility
    _modules = []                        # kernel modules required for support
    _resizefs = ""                       # resize utility
    _labelfs = None                      # labeling functionality
    _fsck = ""                           # fs check utility
    _fsckErrors = {}                     # fs check command error codes & msgs
    _infofs = ""                         # fs info utility
    _defaultFormatOptions = []           # default options passed to mkfs
    _defaultMountOptions = ["defaults"]  # default options passed to mount
    _defaultCheckOptions = []
    _defaultInfoOptions = []
    _existingSizeFields = []
    _resizefsUnit = None
    _fsProfileSpecifier = None           # mkfs option specifying fsprofile

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
        self.mountpoint = kwargs.get("mountpoint")
        self.mountopts = kwargs.get("mountopts")
        self.label = kwargs.get("label")
        self.fsprofile = kwargs.get("fsprofile")

        # filesystem size does not necessarily equal device size
        self._size = kwargs.get("size", Size(0))
        self._minInstanceSize = Size(0)    # min size of this FS instance
        self._mountpoint = None     # the current mountpoint when mounted

        # Resize operations are limited to error-free filesystems whose current
        # size is known.
        self._resizable = False
        if flags.installer_mode and self.resizefsProg:
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

    @classmethod
    def labeling(cls):
        """Returns True if this filesystem uses labels, otherwise False.

           :rtype: bool
        """
        return cls._labelfs is not None

    @classmethod
    def relabels(cls):
        """Returns True if it is possible to relabel this filesystem
           after creation, otherwise False.

           :rtype: bool
        """
        return cls._labelfs is not None and cls._labelfs.label_app is not None

    @classmethod
    def labelFormatOK(cls, label):
        """Return True if the label has an acceptable format for this
           filesystem. None, which represents accepting the default for this
           device, is always acceptable.

           :param label: A possible label
           :type label: str or None
        """
        return label is None or (cls._labelfs is not None and cls._labelfs.labelFormatOK(label))

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
            info = self._getFSInfo()
            self._size = self._getExistingSize(info=info)
            self._minSize = self._size # default to current size
            # We absolutely need a current size to enable resize. To shrink the
            # filesystem we need a real minimum size provided by the resize
            # tool. Failing that, we can default to the current size,
            # effectively disabling shrink.
            if errors or self._size == Size(0):
                self._resizable = False

        self._getMinSize(info=info)   # force calculation of minimum size

    def _getMinSize(self, info=None):
        pass

    def _getFSInfo(self):
        buf = ""
        if self.infofsProg and self.exists and \
           util.find_program_in_path(self.infofsProg):
            argv = self._defaultInfoOptions + [ self.device ]
            try:
                buf = util.capture_output([self.infofsProg] + argv)
            except OSError as e:
                log.error("failed to gather fs info: %s", e)

        return buf

    def _getExistingSize(self, info=None):
        """ Determine the size of this filesystem.

            Filesystem must exist.  Each filesystem varies, but the general
            procedure is to run the filesystem dump or info utility and read
            the block size and number of blocks for the filesystem
            and compute megabytes from that.

            The loop that reads the output from the infofsProg is meant
            to be simple, but take in to account variations in output.
            The general procedure:
                1) Capture output from infofsProg.
                2) Iterate over each line of the output:
                       a) Trim leading and trailing whitespace.
                       b) Break line into fields split on ' '
                       c) If line begins with any of the strings in
                          _existingSizeFields, start at the end of
                          fields and take the first one that converts
                          to an int.  Store this in the values list.
                       d) Repeat until the values list length equals
                          the _existingSizeFields length.
                3) If the length of the values list equals the length
                   of _existingSizeFields, compute the size of this
                   filesystem by multiplying all of the values together
                   to get bytes, then convert to megabytes.  Return
                   this value.
                4) If we were unable to capture all fields, return 0.

            The caller should catch exceptions from this method.  Any
            exception raised indicates a need to change the fields we
            are looking for, the command to run and arguments, or
            something else.  If you catch an exception from this method,
            assume the filesystem cannot be resized.

            :keyword info: filesystem info buffer
            :type info: str (output of :attr:`infofsProg`)
            :returns: size of existing fs in MiB.
            :rtype: float.
        """
        if not self._existingSizeFields:
            return Size(0)

        size = Size(0)
        if self.exists:
            if info is None:
                info = self._getFSInfo()

            try:
                values = []
                for line in info.splitlines():
                    found = False

                    line = line.strip()
                    tmp = line.split()
                    tmp.reverse()

                    for field in self._existingSizeFields:
                        if line.startswith(field):
                            for subfield in tmp:
                                try:
                                    values.append(int(subfield))
                                    found = True
                                    break
                                except ValueError:
                                    continue

                        if found:
                            break

                    if len(values) == len(self._existingSizeFields):
                        break

                if len(values) != len(self._existingSizeFields):
                    return Size(0)

                size = 1
                for value in values:
                    size *= value

                size = Size(size)
            except Exception: # pylint: disable=broad-except
                log_exception_info(log.error, "failed to obtain size of filesystem on %s", [self.device])

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

    def _getFormatOptions(self, options=None, do_labeling=False):
        """Get a list of format options to be used when creating the
           filesystem.

           :param options: any special options
           :type options: list of str or None
           :param bool do_labeling: True if labeling during filesystem creation,
             otherwise False
        """
        argv = []
        if options and isinstance(options, list):
            argv.extend(options)
        argv.extend(self.defaultFormatOptions)
        if self._fsProfileSpecifier and self.fsprofile:
            argv.extend([self._fsProfileSpecifier, self.fsprofile])

        if do_labeling and self.label is not None:
            if self.labelFormatOK(self.label):
                argv.extend(self._labelfs.labelingArgs(self.label))
            else:
                log.warning("Choosing not to apply label (%s) during creation of filesystem %s. Label format is unacceptable for this filesystem.", self.label, self.type)

        argv.append(self.device)
        return argv

    def doFormat(self, options=None):
        """ Create the filesystem.

            :param options: options to pass to mkfs
            :type options: list of strings
            :raises: FormatCreateError, FSError
        """
        log_method_call(self, type=self.mountType, device=self.device,
                        mountpoint=self.mountpoint)

        if self.exists:
            raise FormatCreateError("filesystem already exists", self.device)

        if not self.formattable:
            return

        if not self.mkfsProg:
            return

        if not os.path.exists(self.device):
            raise FormatCreateError("device does not exist", self.device)

        argv = self._getFormatOptions(options=options,
           do_labeling=not self.relabels())

        try:
            ret = util.run_program([self.mkfsProg] + argv)
        except OSError as e:
            raise FormatCreateError(e, self.device)

        if ret:
            raise FormatCreateError("format failed: %s" % ret, self.device)

        self.exists = True
        self.notifyKernel()

        if self.label is not None and self.relabels():
            try:
                self.writeLabel()
            except FSError as e:
                log.warning("Failed to write label (%s) for filesystem %s: %s", self.label, self.type, e)

    @property
    def resizeArgs(self):
        """ Returns the arguments for resizing the filesystem.

            Must be overridden by every class that has non-None _resizefs.

            :returns: arguments for resizing a filesystem.
            :rtype: list of str
        """
        return []

    def doResize(self):
        """ Resize this filesystem based on this instance's targetSize attr.

            :raises: FSResizeError, FSError
        """
        if not self.exists:
            raise FSResizeError("filesystem does not exist", self.device)

        if not self.resizable:
            raise FSResizeError("filesystem not resizable", self.device)

        if self.targetSize == self.currentSize:
            return

        if not self.resizefsProg:
            return

        # tmpfs mounts don't need an existing device node
        if not self.device == "tmpfs" and not os.path.exists(self.device):
            raise FSResizeError("device does not exist", self.device)

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
        rounded = self.targetSize.roundToNearest(self._resizefsUnit,
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
                     "filesystem on %s", unitStr(self._resizefsUnit), self.device)
            return
        else:
            self.targetSize = rounded

        try:
            ret = util.run_program([self.resizefsProg] + self.resizeArgs)
        except OSError as e:
            raise FSResizeError(e, self.device)

        if ret:
            raise FSResizeError("resize failed: %s" % ret, self.device)

        self.doCheck()

        # XXX must be a smarter way to do this
        self._size = self.targetSize
        self.notifyKernel()

    def _getCheckArgs(self):
        argv = []
        argv.extend(self.defaultCheckOptions)
        argv.append(self.device)
        return argv

    def _fsckFailed(self, rc):
        # pylint: disable=unused-argument
        return False

    def _fsckErrorMessage(self, rc):
        return _("Unknown return code: %d.") % (rc,)

    def doCheck(self):
        """ Run a filesystem check.

            :raises: FSError
        """
        if not self.exists:
            raise FSError("filesystem has not been created")

        if not self.fsckProg:
            return

        if not os.path.exists(self.device):
            raise FSError("device does not exist")

        try:
            ret = util.run_program([self.fsckProg] + self._getCheckArgs())
        except OSError as e:
            raise FSError("filesystem check failed: %s" % e)

        if self._fsckFailed(ret):
            hdr = _("%(type)s filesystem check failure on %(device)s: ") % \
                    {"type": self.type, "device": self.device}

            msg = self._fsckErrorMessage(ret)
            raise FSError(hdr + msg)

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
            self.mount(mountpoint=mountpoint)
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.info, "test mount failed")
        else:
            self.unmount()
            ret = True
        finally:
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
        if not self.exists:
            raise FSError("filesystem has not been created")

        if not mountpoint:
            mountpoint = self.mountpoint

        if not mountpoint:
            raise FSError("no mountpoint given")

        if self.status:
            return

        if not isinstance(self, NoDevFS) and not os.path.exists(self.device):
            raise FSError("device %s does not exist" % self.device)

        # XXX os.path.join is FUBAR:
        #
        #         os.path.join("/mnt/foo", "/") -> "/"
        #
        #mountpoint = os.path.join(chroot, mountpoint)
        chrootedMountpoint = os.path.normpath("%s/%s" % (chroot, mountpoint))
        util.makedirs(chrootedMountpoint)

        # passed in options override default options
        if not options or not isinstance(options, str):
            options = self.options

        if isinstance(self, BindFS):
            options = "bind," + options

        try:
            rc = util.mount(self.device, chrootedMountpoint,
                            fstype=self.mountType,
                            options=options)
        except Exception as e:
            raise FSError("mount failed: %s" % e)

        if rc:
            raise FSError("mount failed: %s" % rc)

        if flags.selinux and "ro" not in options.split(",") and flags.installer_mode:
            ret = util.reset_file_context(mountpoint, chroot)
            if not ret:
                log.warning("Failed to reset SElinux context for newly mounted filesystem root directory to default.")
            lost_and_found_context = util.match_path_context("/lost+found")
            lost_and_found_path = os.path.join(mountpoint, "lost+found")
            ret = util.set_file_context(lost_and_found_path, lost_and_found_context, chroot)
            if not ret:
                log.warning("Failed to set SELinux context for newly mounted filesystem lost+found directory at %s to %s", lost_and_found_path, lost_and_found_context)

        self._mountpoint = chrootedMountpoint

    def unmount(self):
        """ Unmount this filesystem. """
        if not self.exists:
            raise FSError("filesystem has not been created")

        if not self._mountpoint:
            # not mounted
            return

        if not os.path.exists(self._mountpoint):
            raise FSError("mountpoint does not exist")

        udev.settle()
        rc = util.umount(self._mountpoint)
        if rc:
            # try and catch whatever is causing the umount problem
            util.run_program(["lsof", self._mountpoint])
            raise FSError("umount failed")

        self._mountpoint = None

    def readLabel(self):
        """Read this filesystem's label.

           :return: the filesystem's label
           :rtype: str

           Raises a FSError if the label can not be read.
        """
        if not self.exists:
            raise FSError("filesystem has not been created")

        if not os.path.exists(self.device):
            raise FSError("device does not exist")

        if not self.relabels() or not self._labelfs.label_app.reads:
            raise FSError("no application to read label for filesystem %s" % self.type)

        (rc, out) = util.run_program_and_capture_output(self._labelfs.label_app.readLabelCommand(self))
        if rc:
            raise FSError("read label failed")

        label = out.strip()

        if label == "":
            return ""
        else:
            return self._labelfs.label_app.extractLabel(label)

    def writeLabel(self):
        """ Create a label for this filesystem.

            :raises: FSError

            If self.label is None, this means accept the default, so raise
            an FSError in this case.

            Raises a FSError if the label can not be set.
        """
        if self.label is None:
            raise FSError("makes no sense to write a label when accepting default label")

        if not self.exists:
            raise FSError("filesystem has not been created")

        if not self.relabels():
            raise FSError("no application to set label for filesystem %s" % self.type)

        if not self.labelFormatOK(self.label):
            raise FSError("bad label format for labelling application %s" % self._labelfs.label_app.name)

        if not os.path.exists(self.device):
            raise FSError("device does not exist")

        rc = util.run_program(self._labelfs.label_app.setLabelCommand(self))
        if rc:
            raise FSError("label failed")

        self.notifyKernel()

    @property
    def mkfsProg(self):
        """ Program used to create filesystems of this type. """
        return self._mkfs

    @property
    def fsckProg(self):
        """ Program used to check filesystems of this type. """
        return self._fsck

    @property
    def resizefsProg(self):
        """ Program used to resize filesystems of this type. """
        return self._resizefs

    @property
    def labelfsProg(self):
        """ Program used to manage labels for this filesystem type.

            May be None if no such program exists.
        """
        if self._labelfs and self._labelfs.label_app:
            return self._labelfs.label_app.name
        else:
            return None

    @property
    def infofsProg(self):
        """ Program used to get information for this filesystem type. """
        return self._infofs

    @property
    def utilsAvailable(self):
        # we aren't checking for fsck because we shouldn't need it
        for prog in [self.mkfsProg, self.resizefsProg, self.labelfsProg,
                     self.infofsProg]:
            if not prog:
                continue

            if not util.find_program_in_path(prog):
                return False

        return True

    @property
    def supported(self):
        log_method_call(self, supported=self._supported)
        return self._supported and self.utilsAvailable

    @property
    def mountable(self):
        canmount = (self.mountType in kernel_filesystems) or \
                   (os.access("/sbin/mount.%s" % (self.mountType,), os.X_OK))

        # Still consider the filesystem type mountable if there exists
        # an appropriate filesystem driver in the kernel modules directory.
        if not canmount:
            modpath = os.path.realpath(os.path.join("/lib/modules", os.uname()[2]))
            if os.path.isdir(modpath):
                modname = "%s.ko" % self.mountType
                for _root, _dirs, files in os.walk(modpath):
                    if any(x.startswith(modname) for x in files):
                        return True

        return canmount

    @property
    def resizable(self):
        """ Can formats of this filesystem type be resized? """
        return super(FS, self).resizable and self.utilsAvailable

    @property
    def defaultFormatOptions(self):
        """ Default options passed to mkfs for this filesystem type. """
        # return a copy to prevent modification
        return self._defaultFormatOptions[:]

    @property
    def defaultMountOptions(self):
        """ Default options passed to mount for this filesystem type. """
        # return a copy to prevent modification
        return self._defaultMountOptions[:]

    @property
    def defaultCheckOptions(self):
        """ Default options passed to checker for this filesystem type. """
        # return a copy to prevent modification
        return self._defaultCheckOptions[:]

    def _getOptions(self):
        return self.mountopts or ",".join(self.defaultMountOptions)

    def _setOptions(self, options):
        self.mountopts = options

    @property
    def mountType(self):
        if not self._mountType:
            self._mountType = self._type

        return self._mountType

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

        return self.doFormat(options=kwargs.get('options'))

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
        return self._mountpoint is not None

    def sync(self, root="/"):
        pass

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
    _mkfs = "mke2fs"
    _modules = ["ext2"]
    _resizefs = "resize2fs"
    _labelfs = fslabeling.Ext2FSLabeling()
    _fsck = "e2fsck"
    _fsckErrors = {4: N_("File system errors left uncorrected."),
                   8: N_("Operational error."),
                   16: N_("Usage or syntax error."),
                   32: N_("e2fsck cancelled by user request."),
                   128: N_("Shared library error.")}
    _packages = ["e2fsprogs"]
    _formattable = True
    _supported = True
    _resizable = True
    _linuxNative = True
    _maxSize = Size("8 TiB")
    _defaultCheckOptions = ["-f", "-p", "-C", "0"]
    _dump = True
    _check = True
    _infofs = "dumpe2fs"
    _defaultInfoOptions = ["-h"]
    _existingSizeFields = ["Block count:", "Block size:"]
    _resizefsUnit = MiB
    _fsProfileSpecifier = "-T"
    partedSystem = fileSystemType["ext2"]

    def _fsckFailed(self, rc):
        for errorCode in self._fsckErrors.keys():
            if rc & errorCode:
                return True
        return False

    def _fsckErrorMessage(self, rc):
        msg = ''

        for errorCode in self._fsckErrors.keys():
            if rc & errorCode:
                msg += "\n" + _(self._fsckErrors[errorCode])

        return msg.strip()

    def _getMinSize(self, info=None):
        """ Set the minimum size for this filesystem in MiB.

            :keyword info: filesystem info buffer
            :type info: str (output of :attr:`infofsProg`)
            :rtype: None.
        """
        size = self._minSize
        blockSize = None

        if self.exists and os.path.exists(self.device):
            if info is None:
                # get block size
                info = self._getFSInfo()

            for line in info.splitlines():
                if line.startswith("Block size:"):
                    blockSize = int(line.split(" ")[-1])

            if blockSize is None:
                raise FSError("failed to get block size for %s filesystem "
                              "on %s" % (self.mountType, self.device))

            # get minimum size according to resize2fs
            buf = util.capture_output([self.resizefsProg,
                                       "-P", self.device])
            _size = None
            for line in buf.splitlines():
                # line will look like:
                # Estimated minimum size of the filesystem: 1148649
                (text, _sep, minSize) = line.partition(":")
                if "minimum size of the filesystem" not in text:
                    continue
                minSize = minSize.strip()
                if not minSize:
                    break
                _size = Size(int(minSize) * blockSize)
                break

            if not _size:
                log.warning("failed to get minimum size for %s filesystem "
                            "on %s", self.mountType, self.device)
            else:
                size = _size
                orig_size = size
                log.debug("size=%s, current=%s", size, self.currentSize)
                # add some padding
                size = min(size * Decimal('1.1'),
                           size + Size("500 MiB"))
                # make sure that the padded and rounded min size is not larger
                # than the current size
                size = min(size.roundToNearest(self._resizefsUnit,
                                               rounding=ROUND_UP),
                           self.currentSize)
                if orig_size < size:
                    log.debug("padding min size from %s up to %s", orig_size, size)
                else:
                    log.debug("using current size %s as min size", size)

        self._minInstanceSize = size

    @property
    def minSize(self):
        return self._minInstanceSize

    @property
    def resizeArgs(self):
        # No unit specifier is interpreted not as bytes, but block size.
        FMT = {KiB: "%dK", MiB: "%dM", GiB: "%dG"}[self._resizefsUnit]
        size_spec = FMT % self.targetSize.convertTo(self._resizefsUnit)
        return ["-p", self.device, size_spec]

register_device_format(Ext2FS)


class Ext3FS(Ext2FS):
    """ ext3 filesystem. """
    _type = "ext3"
    _defaultFormatOptions = ["-t", "ext3"]
    _modules = ["ext3"]
    partedSystem = fileSystemType["ext3"]

    # It is possible for a user to specify an fsprofile that defines a blocksize
    # smaller than the default of 4096 bytes and therefore to make liars of us
    # with regard to this maximum filesystem size, but if they're doing such
    # things they should know the implications of their chosen block size.
    _maxSize = Size("16 TiB")

register_device_format(Ext3FS)


class Ext4FS(Ext3FS):
    """ ext4 filesystem. """
    _type = "ext4"
    _defaultFormatOptions = ["-t", "ext4"]
    _modules = ["ext4"]
    partedSystem = fileSystemType["ext4"]

register_device_format(Ext4FS)


class FATFS(FS):
    """ FAT filesystem. """
    _type = "vfat"
    _mkfs = "mkdosfs"
    _modules = ["vfat"]
    _labelfs = fslabeling.FATFSLabeling()
    _fsck = "dosfsck"
    _fsckErrors = {1: N_("Recoverable errors have been detected or dosfsck has "
                        "discovered an internal inconsistency."),
                   2: N_("Usage error.")}
    _supported = True
    _formattable = True
    _maxSize = Size("1 TiB")
    _packages = [ "dosfstools" ]
    _defaultMountOptions = ["umask=0077", "shortname=winnt"]
    _defaultCheckOptions = ["-n"]
    # FIXME this should be fat32 in some cases
    partedSystem = fileSystemType["fat16"]

    def _fsckFailed(self, rc):
        if rc >= 1:
            return True
        return False

    def _fsckErrorMessage(self, rc):
        return _(self._fsckErrors[rc])

register_device_format(FATFS)


class EFIFS(FATFS):
    _type = "efi"
    _mountType = "vfat"
    _name = N_("EFI System Partition")
    _minSize = Size("50 MiB")

    @property
    def supported(self):
        return (isinstance(platform.platform, platform.EFI) and
                self.utilsAvailable)

register_device_format(EFIFS)


class BTRFS(FS):
    """ btrfs filesystem """
    _type = "btrfs"
    _mkfs = "mkfs.btrfs"
    _modules = ["btrfs"]
    _formattable = True
    _linuxNative = True
    _supported = True
    _packages = ["btrfs-progs"]
    _minSize = Size("256 MiB")
    _maxSize = Size("16 EiB")
    # FIXME parted needs to be taught about btrfs so that we can set the
    # partition table type correctly for btrfs partitions
    # partedSystem = fileSystemType["btrfs"]

    def __init__(self, **kwargs):
        super(BTRFS, self).__init__(**kwargs)
        self.volUUID = kwargs.pop("volUUID", None)

    def create(self, **kwargs):
        # filesystem creation is done in blockdev.btrfs.create_volume
        self.exists = True

    def destroy(self, **kwargs):
        # filesystem deletion is done in blockdev.btrfs.delete_volume
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
    _mkfs = "mkfs.gfs2"
    _modules = ["dlm", "gfs2"]
    _formattable = True
    _defaultFormatOptions = ["-j", "1", "-p", "lock_nolock", "-O"]
    _linuxNative = True
    _dump = True
    _check = True
    _packages = ["gfs2-utils"]
    # FIXME parted needs to be thaught about btrfs so that we can set the
    # partition table type correctly for btrfs partitions
    # partedSystem = fileSystemType["gfs2"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        supported = self._supported
        if flags.gfs2:
            supported = self.utilsAvailable

        return supported

register_device_format(GFS2)


class JFS(FS):
    """ JFS filesystem """
    _type = "jfs"
    _mkfs = "mkfs.jfs"
    _modules = ["jfs"]
    _labelfs = fslabeling.JFSLabeling()
    _defaultFormatOptions = ["-q"]
    _maxSize = Size("8 TiB")
    _formattable = True
    _linuxNative = True
    _dump = True
    _check = True
    _infofs = "jfs_tune"
    _defaultInfoOptions = ["-l"]
    _existingSizeFields = ["Physical block size:", "Aggregate size:"]
    partedSystem = fileSystemType["jfs"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        supported = self._supported
        if flags.jfs:
            supported = self.utilsAvailable

        return supported

register_device_format(JFS)


class ReiserFS(FS):
    """ reiserfs filesystem """
    _type = "reiserfs"
    _mkfs = "mkreiserfs"
    _labelfs = fslabeling.ReiserFSLabeling()
    _modules = ["reiserfs"]
    _defaultFormatOptions = ["-f", "-f"]
    _maxSize = Size("16 TiB")
    _formattable = True
    _linuxNative = True
    _dump = True
    _check = True
    _packages = ["reiserfs-utils"]
    _infofs = "debugreiserfs"
    _existingSizeFields = ["Count of blocks on the device:", "Blocksize:"]
    partedSystem = fileSystemType["reiserfs"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        supported = self._supported
        if flags.reiserfs:
            supported = self.utilsAvailable

        return supported

register_device_format(ReiserFS)


class XFS(FS):
    """ XFS filesystem """
    _type = "xfs"
    _mkfs = "mkfs.xfs"
    _modules = ["xfs"]
    _labelfs = fslabeling.XFSLabeling()
    _defaultFormatOptions = ["-f"]
    _maxSize = Size("16 EiB")
    _formattable = True
    _linuxNative = True
    _supported = True
    _packages = ["xfsprogs"]
    _infofs = "xfs_db"
    _defaultInfoOptions = ["-c", "sb 0", "-c", "p dblocks",
                           "-c", "p blocksize"]
    _existingSizeFields = ["dblocks =", "blocksize ="]
    partedSystem = fileSystemType["xfs"]

    def sync(self, root='/'):
        """ Ensure that data we've written is at least in the journal.

            This is a little odd because xfs_freeze will only be
            available under the install root.
        """
        if not self.status or not self._mountpoint.startswith(root):
            return

        try:
            util.run_program(["xfs_freeze", "-f", self.mountpoint], root=root)
        except OSError as e:
            log.error("failed to run xfs_freeze: %s", e)

        try:
            util.run_program(["xfs_freeze", "-u", self.mountpoint], root=root)
        except OSError as e:
            log.error("failed to run xfs_freeze: %s", e)

register_device_format(XFS)


class HFS(FS):
    _type = "hfs"
    _mkfs = "hformat"
    _modules = ["hfs"]
    _labelfs = fslabeling.HFSLabeling()
    _formattable = True
    partedSystem = fileSystemType["hfs"]

register_device_format(HFS)


class AppleBootstrapFS(HFS):
    _type = "appleboot"
    _mountType = "hfs"
    _name = N_("Apple Bootstrap")
    _minSize = Size("768 KiB")
    _maxSize = Size("1 MiB")

    @property
    def supported(self):
        return (isinstance(platform.platform, platform.NewWorldPPC)
                and self.utilsAvailable)

register_device_format(AppleBootstrapFS)


class HFSPlus(FS):
    _type = "hfs+"
    _modules = ["hfsplus"]
    _udevTypes = ["hfsplus"]
    _mkfs = "mkfs.hfsplus"
    _fsck = "fsck.hfsplus"
    _packages = ["hfsplus-tools"]
    _labelfs = fslabeling.HFSPlusLabeling()
    _formattable = True
    _mountType = "hfsplus"
    _minSize = Size("1 MiB")
    _maxSize = Size("2 TiB")
    _check = True
    partedSystem = fileSystemType["hfs+"]

register_device_format(HFSPlus)


class MacEFIFS(HFSPlus):
    _type = "macefi"
    _name = N_("Linux HFS+ ESP")
    _labelfs = fslabeling.HFSPlusLabeling()
    _udevTypes = []
    _minSize = Size("50 MiB")

    @property
    def supported(self):
        return (isinstance(platform.platform, platform.MacEFI) and
                self.utilsAvailable)

    def __init__(self, **kwargs):
        if "label" not in kwargs:
            kwargs["label"] = self._name
        super(MacEFIFS, self).__init__(**kwargs)

register_device_format(MacEFIFS)


class NTFS(FS):
    """ ntfs filesystem. """
    _type = "ntfs"
    _mkfs = "mkntfs"
    _resizefs = "ntfsresize"
    _labelfs = fslabeling.NTFSLabeling()
    _fsck = "ntfsresize"
    _resizable = True
    _minSize = Size("1 MiB")
    _maxSize = Size("16 TiB")
    _defaultMountOptions = ["defaults", "ro"]
    _defaultCheckOptions = ["-c"]
    _packages = ["ntfsprogs"]
    _infofs = "ntfsinfo"
    _defaultInfoOptions = ["-m"]
    _existingSizeFields = ["Cluster Size:", "Volume Size in Clusters:"]
    _resizefsUnit = B
    partedSystem = fileSystemType["ntfs"]

    def _fsckFailed(self, rc):
        if rc != 0:
            return True
        return False

    def _getMinSize(self, info=None):
        """ Set the minimum size for this filesystem.

            :keyword info: filesystem info buffer
            :type info: str (output of :attr:`infofsProg`)
            :rtype: None
        """
        size = self._minSize
        if self.exists and os.path.exists(self.device) and \
           util.find_program_in_path(self.resizefsProg):
            minSize = None
            buf = util.capture_output([self.resizefsProg, "-m", self.device])
            for l in buf.split("\n"):
                if not l.startswith("Minsize"):
                    continue
                try:
                    # ntfsresize uses SI unit prefixes
                    minSize = Size("%d mb" % int(l.split(":")[1].strip()))
                except (IndexError, ValueError) as e:
                    minSize = None
                    log.warning("Unable to parse output for minimum size on %s: %s", self.device, e)

            if minSize is None:
                log.warning("Unable to discover minimum size of filesystem "
                            "on %s", self.device)
            else:
                # add some padding to the min size
                size = min(minSize * Decimal('1.1'),
                           minSize + Size("500 MiB"))
                # make sure the padded and rounded min size is not larger than
                # the current size
                size = min(size.roundToNearest(self._resizefsUnit,
                                               rounding=ROUND_UP),
                           self.currentSize)
                if minSize < size:
                    log.debug("padding min size from %s up to %s", minSize, size)
                else:
                    log.debug("using current size %s as min size", size)

        self._minInstanceSize = size

    @property
    def minSize(self):
        return self._minInstanceSize

    @property
    def resizeArgs(self):
        FMT = {B: "%d", KB: "%dK", MB: "%dM", GB: "%dG"}[self._resizefsUnit]
        size_spec = FMT % self.targetSize.convertTo(self._resizefsUnit)

        # You must supply at least two '-f' options to ntfsresize or
        # the proceed question will be presented to you.
        return ["-ff", "-s", size_spec, self.device]


register_device_format(NTFS)


# if this isn't going to be mountable it might as well not be here
class NFS(FS):
    """ NFS filesystem. """
    _type = "nfs"
    _modules = ["nfs"]

    def _deviceCheck(self, devspec):
        if devspec is not None and ":" not in devspec:
            return "device must be of the form <host>:<path>"
        return None

    @property
    def mountable(self):
        return False

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
    _defaultMountOptions = ["ro"]

register_device_format(Iso9660FS)


class NoDevFS(FS):
    """ nodev filesystem base class """
    _type = "nodev"

    def __init__(self, **kwargs):
        FS.__init__(self, **kwargs)
        self.exists = True
        self.device = self._type

    def _deviceCheck(self, devspec):
        return None

    @property
    def type(self):
        return self.device

    @property
    def mountType(self):
        return self.device  # this is probably set to the real/specific fstype

    def notifyKernel(self):
        # NoDevFS should not need to tell the kernel anything.
        pass

register_device_format(NoDevFS)


class DevPtsFS(NoDevFS):
    """ devpts filesystem. """
    _type = "devpts"
    _defaultMountOptions = ["gid=5", "mode=620"]

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
    _resizefs = "mount"
    _resizefsUnit = MiB
    # as tmpfs is part of the Linux kernel,
    # it is Linux-native
    _linuxNative = True
    # in a sense, I guess tmpfs is formattable
    # in the regard that the format is automatically created
    # once mounted
    _formattable = True

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

    def _getExistingSize(self, info=None):
        """ Get current size of tmpfs filesystem using df.

            :param NoneType info: a dummy parameter
            :rtype: Size
            :returns: the current size of the filesystem, 0 if not found.
        """
        if not self.status:
            return Size(0)

        df = ["df", self._mountpoint, "--output=size"]
        try:
            (ret, out) = util.run_program_and_capture_output(df)
        except OSError:
            return Size(0)

        if ret:
            return Size(0)

        lines = out.split()
        if len(lines) != 2 or lines[0] != "1K-blocks":
            return Size(0)

        return Size("%s KiB" % lines[1])

    @property
    def mountable(self):
        return True

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
        FMT = {KiB: "%dk", MiB: "%dm", GiB: "%dg"}[self._resizefsUnit]
        return "size=%s" % (FMT % size.convertTo(self._resizefsUnit))

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
        if self._mountpoint:
            # If self._mountpoint is defined, it means this tmpfs mount
            # has been mounted and there is a path we can use as a handle to
            # look-up the free space on the filesystem.
            # When running with changeroot, such as during installation,
            # self._mountpoint is set to the full changeroot path once mounted,
            # so even with changeroot, statvfs should still work fine.
            st = os.statvfs(self._mountpoint)
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

    @property
    def resizeArgs(self):
        opts = super(TmpFS, self)._getOptions()
        options = ("remount", opts, self._sizeOption(self.targetSize))
        return ['-o', ",".join(options), self._type, self._mountpoint]

    def doResize(self):
        # Override superclass method to record whether mount options
        # should include an explicit size specification.
        original_size = self._size
        FS.doResize(self)
        self._accept_default_size = self._accept_default_size and original_size == self._size

register_device_format(TmpFS)


class BindFS(FS):
    _type = "bind"

    @property
    def mountable(self):
        return True

register_device_format(BindFS)


class SELinuxFS(NoDevFS):
    _type = "selinuxfs"

    @property
    def mountable(self):
        return flags.selinux and super(SELinuxFS, self).mountable

register_device_format(SELinuxFS)


class USBFS(NoDevFS):
    _type = "usbfs"

register_device_format(USBFS)

