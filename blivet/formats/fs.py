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
import uuid as uuid_mod
import random

from parted import fileSystemType, PARTITION_BOOT

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
from ..tasks import fsuuid
from ..tasks import fswritelabel
from ..tasks import fswriteuuid
from ..errors import FormatCreateError, FSError, FSReadLabelError
from ..errors import FSWriteLabelError, FSWriteUUIDError
from . import DeviceFormat, register_device_format
from .. import util
from ..flags import flags
from ..storage_log import log_exception_info, log_method_call
from .. import arch
from ..size import Size, ROUND_UP
from ..i18n import N_
from .. import udev
from ..mounts import mounts_cache

from .fslib import kernel_filesystems

import logging
log = logging.getLogger("blivet")


AVAILABLE_FILESYSTEMS = kernel_filesystems


class FS(DeviceFormat):

    """ Filesystem base class. """
    _type = "Abstract Filesystem Class"  # fs type name
    _name = None
    _modules = []                        # kernel modules required for support
    _labelfs = None                      # labeling functionality
    _uuidfs = None                       # functionality for UUIDs
    _fsck_class = fsck.UnimplementedFSCK
    _mkfs_class = fsmkfs.UnimplementedFSMkfs
    _min_size = Size("2 MiB")            # default minimal size
    _mount_class = fsmount.FSMount
    _readlabel_class = fsreadlabel.UnimplementedFSReadLabel
    _sync_class = fssync.UnimplementedFSSync
    _writelabel_class = fswritelabel.UnimplementedFSWriteLabel
    _writeuuid_class = fswriteuuid.UnimplementedFSWriteUUID
    _selinux_supported = True
    # This constant is aquired by testing some filesystems
    # and it's giving us percentage of space left after the format.
    # This number is more guess than precise number because this
    # value is already unpredictable and can change in the future...
    _metadata_size_factor = 1.0

    config_actions_map = {"label": "write_label"}

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
        self._fsck = self._fsck_class(self)
        self._mkfs = self._mkfs_class(self)
        self._mount = self._mount_class(self)
        self._readlabel = self._readlabel_class(self)
        self._sync = self._sync_class(self)
        self._writelabel = self._writelabel_class(self)
        self._writeuuid = self._writeuuid_class(self)

        self._current_info = None  # info obtained by _info task
        self._chrooted_mountpoint = None

        self.mountpoint = kwargs.get("mountpoint")
        self.mountopts = kwargs.get("mountopts", "")
        self.label = kwargs.get("label")
        self.fsprofile = kwargs.get("fsprofile")

        self._user_mountopts = self.mountopts

        if flags.auto_dev_updates and self._resize.available:
            # if you want current/min size you have to call update_size_info
            try:
                self.update_size_info()
            except FSError:
                log.warning("%s filesystem on %s needs repair", self.type,
                            self.device)

        self._target_size = self._size

        if self.supported:
            self.check_module()

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  mountpoint = %(mountpoint)s  mountopts = %(mountopts)s\n"
              "  label = %(label)s  size = %(size)s"
              "  target_size = %(target_size)s\n" %
              {"mountpoint": self.mountpoint, "mountopts": self.mountopts,
               "label": self.label, "size": self._size,
               "target_size": self.target_size})
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
                  "label": self.label, "target_size": self.target_size,
                  "mountable": self.mountable})
        return d

    @classmethod
    def free_space_estimate(cls, device_size):
        """ Get estimated free space when format will be done on device
            with size ``device_size``.

            .. note::

                This is more guess than precise number. To get precise
                space taken the FS must provide this number to us.

            :param device_size: original device size
            :type device_size: :class:`~.size.Size` object
            :return: estimated free size after format
            :rtype: :class:`~.size.Size`
        """
        return device_size * cls._metadata_size_factor

    @classmethod
    def get_required_size(cls, free_space):
        """ Get device size we need to get a ``free_space`` on the device.
            This calculation will add metadata to usable device on the FS.

            .. note::

                This is more guess than precise number. To get precise
                space taken the FS must provide this number to us.

            :param free_space: how much usable size we want on newly created device
            :type free_space: :class:`~.size.Size` object
            :return: estimated size of the device which will have given amount of
                ``free_space``
            :rtype: :class:`~.size.Size`
        """
        # to get usable size without metadata we will use
        # usable_size = device_size * _metadata_size_factor
        # we can change this to get device size with required usable_size
        # device_size = usable_size / _metadata_size_factor
        return Size(Decimal(int(free_space)) / Decimal(cls._metadata_size_factor))

    @classmethod
    def biggest_overhead_FS(cls, fs_list=None):
        """ Get format class from list of format classes with largest space taken
            by metadata.

            :param fs_list: list of input filesystems
            :type fs_list: list of classes with parent :class:`~.FS`
            :return: FS which takes most space by metadata
        """
        if fs_list is None:
            from . import device_formats
            fs_list = []
            for fs_class in device_formats.values():
                if issubclass(fs_class, cls):
                    fs_list.append(fs_class)
        elif not fs_list:
            raise ValueError("Empty list is not allowed here!")
        # all items in the list must be subclass of FS class
        elif not all(issubclass(fs_class, cls) for fs_class in fs_list):
            raise ValueError("Only filesystem classes may be provided!")

        return min(fs_list, key=lambda x: x._metadata_size_factor)

    def labeling(self):
        """Returns True if this filesystem uses labels, otherwise False.

           :rtype: bool
        """
        return (self._mkfs.can_label and self._mkfs.available) or self._writelabel.available

    def relabels(self):
        """Returns True if it is possible to relabel this filesystem
           after creation, otherwise False.

           :rtype: bool
        """
        return self._writelabel.available

    def label_format_ok(self, label):
        """Return True if the label has an acceptable format for this
           filesystem. None, which represents accepting the default for this
           device, is always acceptable.

           :param label: A possible label
           :type label: str or None
        """
        return label is None or (self._labelfs is not None and self._labelfs.label_format_ok(label))

    label = property(lambda s: s._get_label(), lambda s, l: s._set_label(l),
                     doc="this filesystem's label")

    def can_set_uuid(self):
        """Returns True if this filesystem supports setting an UUID during
           creation, otherwise False.

           :rtype: bool
        """
        return self._mkfs.can_set_uuid and self._mkfs.available

    def can_modify_uuid(self):
        """Returns True if it's possible to set the UUID of this filesystem
           after it has been created, otherwise False.

           :rtype: bool
        """
        return self._writeuuid.available

    def uuid_format_ok(self, uuid):
        """Return True if the UUID has an acceptable format for this
           filesystem.

           :param uuid: An UUID
           :type uuid: str
        """
        return self._uuidfs is not None and self._uuidfs.uuid_format_ok(uuid)

    def generate_new_uuid(self):
        """Generate a new random UUID in the RFC 4122 format.

           :rtype: str

           .. note:
                Sub-classes that require a different format of UUID has to
                override this method!
        """
        return str(uuid_mod.uuid4())  # uuid4() returns a random UUID

    def update_size_info(self):
        """ Update this filesystem's current and minimum size (for resize). """

        #   This method ensures:
        #   * If it is not possible to obtain the current size of the
        #       filesystem by interrogating the filesystem, self._resizable
        #       is False (and self._size is 0).
        #   * _min_instance_size is obtained or it is set to _size. Effectively
        #     this means that it is the actual minimum size, or if that
        #     cannot be obtained the actual current size of the device.
        #     If it was not possible to obtain the current size of the device
        #     then _min_instance_size is 0, but since _resizable is False
        #     that information can not be used to shrink the filesystem below
        #     its unknown actual minimum size.
        #   * self._get_min_size() is only run if fsck succeeds and a current
        #     existing size can be obtained.
        if not self.exists:
            return

        self._current_info = None
        self._min_instance_size = Size(0)
        self._resizable = self.__class__._resizable

        # try to gather current size info
        self._size = Size(0)
        try:
            if self._info.available:
                self._current_info = self._info.do_task()
        except FSError as e:
            log.info("Failed to obtain info for device %s: %s", self.device, e)
        try:
            self._size = self._size_info.do_task()
        except (FSError, NotImplementedError) as e:
            log.warning("Failed to obtain current size for device %s: %s", self.device, e)
        else:
            self._min_instance_size = self._size

        # We absolutely need a current size to enable resize. To shrink the
        # filesystem we need a real minimum size provided by the resize
        # tool. Failing that, we can default to the current size,
        # effectively disabling shrink.
        if self._size == Size(0):
            self._resizable = False

        try:
            result = self._minsize.do_task()
            size = self._pad_size(result)
            if result < size:
                log.debug("padding min size from %s up to %s", result, size)
            else:
                log.debug("using current size %s as min size", size)
            self._min_instance_size = size
        except (FSError, NotImplementedError) as e:
            log.warning("Failed to obtain minimum size for device %s: %s", self.device, e)

    def _pad_size(self, size):
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
        padded = min(padded.round_to_nearest(self._resize.unit, rounding=ROUND_UP), self.current_size)

        return padded

    @property
    def free(self):
        """ The amount of space that can be gained by resizing this
            filesystem to its minimum size.
        """
        return max(Size(0), self.current_size - self.min_size)

    def _pre_create(self, **kwargs):
        super(FS, self)._pre_create(**kwargs)
        if not self._mkfs.available:
            return

    def _create(self, **kwargs):
        """ Create the filesystem.

            :param options: options to pass to mkfs
            :type options: list of strings
            :raises: FormatCreateError, FSError
        """
        log_method_call(self, type=self.mount_type, device=self.device,
                        mountpoint=self.mountpoint)
        if not self.formattable:
            return

        super(FS, self)._create()
        try:
            self._mkfs.do_task(options=kwargs.get("options"),
                               label=not self.relabels(),
                               set_uuid=self.can_set_uuid())
        except FSWriteLabelError as e:
            log.warning("Choosing not to apply label (%s) during creation of filesystem %s. Label format is unacceptable for this filesystem.", self.label, self.type)
        except FSWriteUUIDError as e:
            log.warning("Choosing not to apply UUID (%s) during"
                        " creation of filesystem %s. UUID format"
                        " is unacceptable for this filesystem.",
                        self.uuid, self.type)
        except FSError as e:
            raise FormatCreateError(e, self.device)

    def _post_create(self, **kwargs):
        super(FS, self)._post_create(**kwargs)
        if self.label is not None and self.relabels():
            try:
                self.write_label()
            except FSError as e:
                log.warning("Failed to write label (%s) for filesystem %s: %s", self.label, self.type, e)
        if self.uuid is not None and not self.can_set_uuid() and \
           self.can_modify_uuid():
            self.write_uuid()

    def _pre_resize(self):
        # file systems need a check before being resized
        self.do_check()
        super(FS, self)._pre_resize()

    def _post_resize(self):
        self.do_check()
        super(FS, self)._post_resize()

    def do_check(self):
        """ Run a filesystem check.

            :raises: FSError
        """
        if not self.exists:
            raise FSError("filesystem has not been created")

        if not self._fsck.available:
            return

        if not os.path.exists(self.device):
            raise FSError("device does not exist")

        self._fsck.do_task()

    def check_module(self):
        """Check if kernel module required to support this filesystem is available."""
        if not self._modules or self.mount_type in AVAILABLE_FILESYSTEMS:
            return

        for module in self._modules:
            try:
                rc = util.run_program(["modprobe", "--dry-run", module])
            except OSError as e:
                log.error("Could not check kernel module availability %s: %s", module, e)
                self._supported = False
                return

            if rc:
                log.debug("Kernel module %s not available", module)
                self._supported = False
                return

        # If we successfully tried to load a kernel module for this filesystem, we
        # also need to update the list of supported filesystems to avoid unnecessary check.
        AVAILABLE_FILESYSTEMS.extend(self._modules)

    @property
    def system_mountpoint(self):
        """ Get current mountpoint

            returns: mountpoint
            rtype: str or None

            If there are multiple mountpoints it returns the most recent one.
        """

        if not self.exists:
            return None

        if self._chrooted_mountpoint:
            return self._chrooted_mountpoint

        # It is possible to have multiple mountpoints, return the last one
        try:
            return mounts_cache.get_mountpoints(self.device,
                                                getattr(self, "subvolspec", None))[-1]
        except IndexError:
            return None

    def test_mount(self):
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
        except Exception:  # pylint: disable=broad-except
            log_exception_info(log.info, "test mount failed")

        if ret:
            self.unmount()

        os.rmdir(mountpoint)

        return ret

    def _pre_setup(self, **kwargs):
        """ Check to see if the filesystem should be mounted.

            :keyword chroot: prefix to apply to mountpoint
            :keyword mountpoint: mountpoint (overrides self.mountpoint)
            :returns: True if it is ok to mount, False if it is not.
            :raises: FSError
        """
        chroot = kwargs.get("chroot", "/")
        mountpoint = kwargs.get("mountpoint") or self.mountpoint

        if not self.exists:
            raise FSError("filesystem has not been created")

        if not mountpoint:
            raise FSError("no mountpoint given")

        if not isinstance(self, NoDevFS) and not os.path.exists(self.device):
            raise FSError("device %s does not exist" % self.device)

        chrooted_mountpoint = os.path.normpath("%s/%s" % (chroot, mountpoint))
        return self.system_mountpoint != chrooted_mountpoint

    def _setup(self, **kwargs):
        """ Mount this filesystem.

            :keyword options: mount options (overrides all other option strings)
            :type options: str.
            :keyword chroot: prefix to apply to mountpoint
            :keyword mountpoint: mountpoint (overrides self.mountpoint)
            :raises: FSError
        """
        options = kwargs.get("options", "")
        chroot = kwargs.get("chroot", "/")
        mountpoint = kwargs.get("mountpoint") or self.mountpoint

        # XXX os.path.join is FUBAR:
        #
        #         os.path.join("/mnt/foo", "/") -> "/"
        #
        # mountpoint = os.path.join(chroot, mountpoint)
        chrooted_mountpoint = os.path.normpath("%s/%s" % (chroot, mountpoint))
        self._mount.do_task(chrooted_mountpoint, options=options)

        if chroot != "/":
            self._chrooted_mountpoint = chrooted_mountpoint

    def _post_setup(self, **kwargs):
        options = kwargs.get("options", "")
        chroot = kwargs.get("chroot", "/")
        mountpoint = kwargs.get("mountpoint") or self.mountpoint

        if self._selinux_supported and flags.selinux and "ro" not in self._mount.mount_options(options).split(",") and flags.selinux_reset_fcon:
            ret = util.reset_file_context(mountpoint, chroot)
            if not ret:
                log.warning("Failed to reset SElinux context for newly mounted filesystem root directory to default.")

    def _pre_teardown(self, **kwargs):
        if not super(FS, self)._pre_teardown(**kwargs):
            return False

        # Prefer the explicit mountpoint path, fall back to most recent mountpoint
        mountpoint = kwargs.get("mountpoint") or self.system_mountpoint

        if not mountpoint:
            # not mounted
            return False

        if not os.path.exists(mountpoint):
            raise FSError("mountpoint does not exist")

        udev.settle()
        return True

    def _teardown(self, **kwargs):
        """ Unmount this filesystem.

            :param str mountpoint: Optional mountpoint to be unmounted.
            :raises: FSError

            If mountpoint isn't passed this will unmount the most recent mountpoint listed
            by the system. Override this behavior by passing a specific mountpoint. FSError
            will be raised in either case if the path doesn't exist.
        """

        mountpoint = kwargs.get("mountpoint") or self.system_mountpoint
        rc = util.umount(mountpoint)
        if rc:
            # try and catch whatever is causing the umount problem
            util.run_program(["lsof", mountpoint])
            raise FSError("umount of %s failed (%d)" % (mountpoint, rc))

        if mountpoint == self._chrooted_mountpoint:
            self._chrooted_mountpoint = None

    def read_label(self):
        """Read this filesystem's label.

           :return: the filesystem's label
           :rtype: str

           Raises a FSReadLabelError if the label can not be read.
        """
        if not self.exists:
            raise FSReadLabelError("filesystem has not been created")

        if not os.path.exists(self.device):
            raise FSReadLabelError("device does not exist")

        if not self._readlabel.available:
            raise FSReadLabelError("can not read label for filesystem %s" % self.type)
        return self._readlabel.do_task()

    def write_label(self, dry_run=False):
        """ Create a label for this filesystem.

            :raises: FSError

            If self.label is None, this means accept the default, so raise
            an FSError in this case.

            Raises a FSError if the label can not be set.
        """

        if not self._writelabel.available:
            raise FSError("no application to set label for filesystem %s" % self.type)

        if not dry_run:
            if not self.exists:
                raise FSError("filesystem has not been created")

            if not os.path.exists(self.device):
                raise FSError("device does not exist")

            if self.label is None:
                raise FSError("makes no sense to write a label when accepting default label")

            if not self.label_format_ok(self.label):
                raise FSError("bad label format for labelling application %s" % self._writelabel)

            self._writelabel.do_task()

    def write_uuid(self):
        """Set an UUID for this filesystem.

           :raises: FSError

           Raises an FSError if the UUID can not be set.
        """
        err = None

        if self.uuid is None:
            err = "makes no sense to write an UUID when not requested"

        if not self.exists:
            err = "filesystem has not been created"

        if not self._writeuuid.available:
            err = "no application to set UUID for filesystem %s" % self.type

        if not self.uuid_format_ok(self.uuid):
            err = "bad UUID format for application %s" % self._writeuuid

        if not os.path.exists(self.device):
            err = "device does not exist"

        if err is not None:
            raise FSError(err)

        self._writeuuid.do_task()

    def reset_uuid(self):
        """Generate a new UUID for the file system and set/write it."""

        orig_uuid = self.uuid
        self.uuid = self.generate_new_uuid()

        if self.status:
            # XXX: does any FS support this?
            raise FSError("Cannot reset UUID on a mounted file system")

        try:
            self.write_uuid()
        except Exception:  # pylint: disable=broad-except
            # something went wrong, restore the original UUID
            self.uuid = orig_uuid
            raise

    @property
    def utils_available(self):
        # we aren't checking for fsck because we shouldn't need it
        tasks = (self._mkfs, self._resize, self._writelabel, self._info)
        return all(not t.implemented or t.available for t in tasks)

    @property
    def supported(self):
        log_method_call(self, supported=self._supported)
        return super(FS, self).supported and self.utils_available

    @property
    def controllable(self):
        return super(FS, self).controllable and self.mountable

    @property
    def mountable(self):
        return self._mount.available

    @property
    def formattable(self):
        return super(FS, self).formattable and self._mkfs.available

    @property
    def resizable(self):
        """ Can formats of this filesystem type be resized? """
        return super(FS, self).resizable and self._resize.available

    def _get_options(self):
        return self.mountopts or ",".join(self._mount.options)

    def _set_options(self, options):
        self.mountopts = options

    @property
    def mount_type(self):
        return self._mount.mount_type

    # These methods just wrap filesystem-specific methods in more
    # generically named methods so filesystems and formatted devices
    # like swap and LVM physical volumes can have a common API.
    def mount(self, **kwargs):
        """ Mount this filesystem.

            :keyword options: mount options (overrides all other option strings)
            :type options: str.
            :keyword chroot: prefix to apply to mountpoint
            :keyword mountpoint: mountpoint (overrides self.mountpoint)
            :raises: FSError

        .. note::

            When mounted multiple times the unmount method needs to be called with
            a specific mountpoint to unmount, otherwise it will try to unmount the most
            recent one listed by the system.
        """
        return self.setup(**kwargs)

    def unmount(self, **kwargs):
        """ Unmount this filesystem.

            :param str mountpoint: Optional mountpoint to be unmounted.
            :raises: FSError

            If mountpoint isn't passed this will unmount the most recent mountpoint listed
            by the system. Override this behavior by passing a specific mountpoint. FSError
            will be raised in either case if the path doesn't exist.
        """
        return self.teardown(**kwargs)

    @property
    def status(self):
        if not self.exists:
            return False
        return self.system_mountpoint is not None

    def sync(self, root='/'):
        """ Ensure that data we've written is at least in the journal.

            .. note::

            This is a little odd because xfs_freeze will only be
            available under the install root.
        """
        if not self.status or not self.system_mountpoint or \
                not self.system_mountpoint.startswith(root) or \
                not self._sync.available:
            return

        try:
            self._sync.do_task(root)
        except FSError as e:
            log.error(e)

    def populate_ksdata(self, data):
        super(FS, self).populate_ksdata(data)
        data.mountpoint = self.mountpoint or "none"
        data.label = self.label or ""
        if self.options != "defaults":
            data.fsopts = self.options
        else:
            data.fsopts = ""

        data.mkfsopts = self.create_options or ""
        data.fsprofile = self.fsprofile or ""


class Ext2FS(FS):

    """ ext2 filesystem. """
    _type = "ext2"
    _modules = ["ext2"]
    _labelfs = fslabeling.Ext2FSLabeling()
    _uuidfs = fsuuid.Ext2FSUUID()
    _packages = ["e2fsprogs"]
    _formattable = True
    _supported = True
    _resizable = True
    _linux_native = True
    _max_size = Size("8 TiB")
    _dump = True
    _check = True
    _fsck_class = fsck.Ext2FSCK
    _info_class = fsinfo.Ext2FSInfo
    _minsize_class = fsminsize.Ext2FSMinSize
    _mkfs_class = fsmkfs.Ext2FSMkfs
    _readlabel_class = fsreadlabel.Ext2FSReadLabel
    _resize_class = fsresize.Ext2FSResize
    _size_info_class = fssize.Ext2FSSize
    _writelabel_class = fswritelabel.Ext2FSWriteLabel
    _writeuuid_class = fswriteuuid.Ext2FSWriteUUID
    parted_system = fileSystemType["ext2"]
    _metadata_size_factor = 0.93  # ext2 metadata may take 7% of space

    def _post_setup(self, **kwargs):
        super(Ext2FS, self)._post_setup(**kwargs)

        options = kwargs.get("options", "")
        chroot = kwargs.get("chroot", "/")
        mountpoint = kwargs.get("mountpoint") or self.mountpoint

        if flags.selinux and "ro" not in self._mount.mount_options(options).split(",") and flags.selinux_reset_fcon:
            lost_and_found_context = util.match_path_context("/lost+found")
            lost_and_found_path = os.path.join(mountpoint, "lost+found")
            ret = util.set_file_context(lost_and_found_path, lost_and_found_context, chroot)
            if not ret:
                log.warning("Failed to set SELinux context for newly mounted filesystem lost+found directory at %s to %s", lost_and_found_path, lost_and_found_context)


register_device_format(Ext2FS)


class Ext3FS(Ext2FS):

    """ ext3 filesystem. """
    _type = "ext3"
    _modules = ["ext3"]
    parted_system = fileSystemType["ext3"]
    _mkfs_class = fsmkfs.Ext3FSMkfs

    # It is possible for a user to specify an fsprofile that defines a blocksize
    # smaller than the default of 4096 bytes and therefore to make liars of us
    # with regard to this maximum filesystem size, but if they're doing such
    # things they should know the implications of their chosen block size.
    _max_size = Size("16 TiB")
    _metadata_size_factor = 0.90  # ext3 metadata may take 10% of space


register_device_format(Ext3FS)


class Ext4FS(Ext3FS):

    """ ext4 filesystem. """
    _type = "ext4"
    _modules = ["ext4"]
    _mkfs_class = fsmkfs.Ext4FSMkfs
    parted_system = fileSystemType["ext4"]
    _max_size = Size("1 EiB")
    _metadata_size_factor = 0.85  # ext4 metadata may take 15% of space


register_device_format(Ext4FS)


class FATFS(FS):

    """ FAT filesystem. """
    _type = "vfat"
    _modules = ["vfat"]
    _labelfs = fslabeling.FATFSLabeling()
    _uuidfs = fsuuid.FATFSUUID()
    _supported = True
    _formattable = True
    _max_size = Size("1 TiB")
    _packages = ["dosfstools"]
    _fsck_class = fsck.DosFSCK
    _mkfs_class = fsmkfs.FATFSMkfs
    _mount_class = fsmount.FATFSMount
    _readlabel_class = fsreadlabel.DosFSReadLabel
    _writelabel_class = fswritelabel.DosFSWriteLabel
    _metadata_size_factor = 0.99  # fat metadata may take 1% of space
    # FIXME this should be fat32 in some cases
    parted_system = fileSystemType["fat16"]
    _selinux_supported = False

    def generate_new_uuid(self):
        ret = ""
        for _i in range(8):
            ret += random.choice("0123456789ABCDEF")
        return ret[:4] + "-" + ret[4:]


register_device_format(FATFS)


class EFIFS(FATFS):
    _type = "efi"
    _name = N_("EFI System Partition")
    _min_size = Size("50 MiB")
    _check = True
    _mount_class = fsmount.EFIFSMount
    parted_flag = PARTITION_BOOT

    @property
    def supported(self):
        return super(EFIFS, self).supported and arch.is_efi()


register_device_format(EFIFS)


class BTRFS(FS):

    """ btrfs filesystem """
    _type = "btrfs"
    _modules = ["btrfs"]
    _formattable = True
    _linux_native = True
    _supported = True
    _packages = ["btrfs-progs"]
    _min_size = Size("256 MiB")
    _max_size = Size("16 EiB")
    _mkfs_class = fsmkfs.BTRFSMkfs
    _metadata_size_factor = 0.80  # btrfs metadata may take 20% of space
    # FIXME parted needs to be taught about btrfs so that we can set the
    # partition table type correctly for btrfs partitions
    # parted_system = fileSystemType["btrfs"]

    def __init__(self, **kwargs):
        super(BTRFS, self).__init__(**kwargs)
        self.vol_uuid = kwargs.pop("vol_uuid", None)
        self.subvolspec = kwargs.pop("subvolspec", None)

    def create(self, **kwargs):
        # filesystem creation is done in blockdev.btrfs.create_volume
        self.exists = True

    def destroy(self, **kwargs):
        # filesystem deletion is done in blockdev.btrfs.delete_volume
        self.exists = False

    def _pre_setup(self, **kwargs):
        log_method_call(self, type=self.mount_type, device=self.device,
                        mountpoint=self.mountpoint or kwargs.get("mountpoint"))
        # Since btrfs vols have subvols the format setup is automatic.
        # Don't try to mount it if there's no mountpoint.
        return bool(self.mountpoint or kwargs.get("mountpoint"))

    @property
    def container_uuid(self):
        return self.vol_uuid

    @container_uuid.setter
    def container_uuid(self, uuid):
        self.vol_uuid = uuid


register_device_format(BTRFS)


class GFS2(FS):

    """ gfs2 filesystem. """
    _type = "gfs2"
    _modules = ["dlm", "gfs2"]
    _formattable = True
    _linux_native = True
    _dump = True
    _check = True
    _packages = ["gfs2-utils"]
    _mkfs_class = fsmkfs.GFS2Mkfs
    # FIXME parted needs to be thaught about btrfs so that we can set the
    # partition table type correctly for btrfs partitions
    # parted_system = fileSystemType["gfs2"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        return self.utils_available if flags.gfs2 else self._supported


register_device_format(GFS2)


class JFS(FS):

    """ JFS filesystem """
    _type = "jfs"
    _modules = ["jfs"]
    _labelfs = fslabeling.JFSLabeling()
    _uuidfs = fsuuid.JFSUUID()
    _max_size = Size("8 TiB")
    _formattable = True
    _linux_native = True
    _dump = True
    _check = True
    _info_class = fsinfo.JFSInfo
    _mkfs_class = fsmkfs.JFSMkfs
    _size_info_class = fssize.JFSSize
    _writelabel_class = fswritelabel.JFSWriteLabel
    _writeuuid_class = fswriteuuid.JFSWriteUUID
    _metadata_size_factor = 0.99  # jfs metadata may take 1% of space
    parted_system = fileSystemType["jfs"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        return self.utils_available if flags.jfs else self._supported


register_device_format(JFS)


class ReiserFS(FS):

    """ reiserfs filesystem """
    _type = "reiserfs"
    _labelfs = fslabeling.ReiserFSLabeling()
    _uuidfs = fsuuid.ReiserFSUUID()
    _modules = ["reiserfs"]
    _max_size = Size("16 TiB")
    _formattable = True
    _linux_native = True
    _dump = True
    _check = True
    _packages = ["reiserfs-utils"]
    _info_class = fsinfo.ReiserFSInfo
    _mkfs_class = fsmkfs.ReiserFSMkfs
    _size_info_class = fssize.ReiserFSSize
    _writelabel_class = fswritelabel.ReiserFSWriteLabel
    _writeuuid_class = fswriteuuid.ReiserFSWriteUUID
    _metadata_size_factor = 0.98  # reiserfs metadata may take 2% of space
    parted_system = fileSystemType["reiserfs"]

    @property
    def supported(self):
        """ Is this filesystem a supported type? """
        return self.utils_available if flags.reiserfs else self._supported


register_device_format(ReiserFS)


class XFS(FS):

    """ XFS filesystem """
    _type = "xfs"
    _modules = ["xfs"]
    _labelfs = fslabeling.XFSLabeling()
    _uuidfs = fsuuid.XFSUUID()
    _min_size = Size("16 MiB")
    _max_size = Size("16 EiB")
    _formattable = True
    _linux_native = True
    _supported = True
    _resizable = True
    _packages = ["xfsprogs"]
    _fsck_class = fsck.XFSCK
    _info_class = fsinfo.XFSInfo
    _mkfs_class = fsmkfs.XFSMkfs
    _readlabel_class = fsreadlabel.XFSReadLabel
    _size_info_class = fssize.XFSSize
    _resize_class = fsresize.XFSResize
    _sync_class = fssync.XFSSync
    _writelabel_class = fswritelabel.XFSWriteLabel
    _writeuuid_class = fswriteuuid.XFSWriteUUID
    _metadata_size_factor = 0.97  # xfs metadata may take 3% of space
    parted_system = fileSystemType["xfs"]

    def write_uuid(self):
        """Set an UUID for this filesystem.

           :raises: FSError

           Raises an FSError if the UUID can not be set.
        """

        # try to mount and umount the FS first to make sure it is clean
        tmpdir = tempfile.mkdtemp(prefix="fs-tmp-mnt")
        try:
            self.mount(mountpoint=tmpdir, options="nouuid")
            self.unmount()
        finally:
            os.rmdir(tmpdir)

        super(XFS, self).write_uuid()


register_device_format(XFS)


class HFS(FS):
    _type = "hfs"
    _modules = ["hfs"]
    _labelfs = fslabeling.HFSLabeling()
    _formattable = True
    _mkfs_class = fsmkfs.HFSMkfs
    parted_system = fileSystemType["hfs"]


register_device_format(HFS)


class AppleBootstrapFS(HFS):
    _type = "appleboot"
    _name = N_("Apple Bootstrap")
    _min_size = Size("768 KiB")
    _max_size = Size("1 MiB")
    _supported = True
    _mount_class = fsmount.AppleBootstrapFSMount

    @property
    def supported(self):
        return super(AppleBootstrapFS, self).supported and arch.is_pmac()


register_device_format(AppleBootstrapFS)


class HFSPlus(FS):
    _type = "hfs+"
    _modules = ["hfsplus"]
    _udev_types = ["hfsplus"]
    _packages = ["hfsplus-tools"]
    _labelfs = fslabeling.HFSPlusLabeling()
    _uuidfs = fsuuid.HFSPlusUUID()
    _formattable = True
    _min_size = Size("1 MiB")
    _max_size = Size("2 TiB")
    _check = True
    parted_system = fileSystemType["hfs+"]
    _fsck_class = fsck.HFSPlusFSCK
    _mkfs_class = fsmkfs.HFSPlusMkfs
    _mount_class = fsmount.HFSPlusMount


register_device_format(HFSPlus)


class MacEFIFS(HFSPlus):
    _type = "macefi"
    _name = N_("Linux HFS+ ESP")
    _udev_types = []
    _min_size = Size("50 MiB")
    _supported = True

    @property
    def supported(self):
        return super(MacEFIFS, self).supported and arch.is_efi() and arch.is_mactel()

    def __init__(self, **kwargs):
        if "label" not in kwargs:
            kwargs["label"] = self._name
        super(MacEFIFS, self).__init__(**kwargs)


register_device_format(MacEFIFS)


class NTFS(FS):

    """ ntfs filesystem. """
    _type = "ntfs"
    _labelfs = fslabeling.NTFSLabeling()
    _uuidfs = fsuuid.NTFSUUID()
    _resizable = True
    _formattable = True
    _min_size = Size("1 MiB")
    _max_size = Size("16 TiB")
    _packages = ["ntfsprogs"]
    _fsck_class = fsck.NTFSFSCK
    _info_class = fsinfo.NTFSInfo
    _minsize_class = fsminsize.NTFSMinSize
    _mkfs_class = fsmkfs.NTFSMkfs
    _mount_class = fsmount.NTFSMount
    _readlabel_class = fsreadlabel.NTFSReadLabel
    _resize_class = fsresize.NTFSResize
    _size_info_class = fssize.NTFSSize
    _writelabel_class = fswritelabel.NTFSWriteLabel
    _writeuuid_class = fswriteuuid.NTFSWriteUUID
    parted_system = fileSystemType["ntfs"]

    def generate_new_uuid(self):
        ret = ""
        for _i in range(16):
            ret += random.choice("0123456789ABCDEF")
        return ret


register_device_format(NTFS)


class ExFATFS(FS):
    _type = "exfat"


register_device_format(ExFATFS)


class F2FS(FS):

    """ f2fs filesystem. """
    _type = "f2fs"
    _labelfs = fslabeling.F2FSLabeling()
    _formattable = True
    _linux_native = True
    _supported = True
    _min_size = Size("1 MiB")
    _max_size = Size("16 TiB")
    _packages = ["f2fs-tools"]
    _fsck_class = fsck.F2FSFSCK
    _mkfs_class = fsmkfs.F2FSMkfs


register_device_format(F2FS)


# if this isn't going to be mountable it might as well not be here
class NFS(FS):

    """ NFS filesystem. """
    _type = "nfs"
    _modules = ["nfs"]
    _mount_class = fsmount.NFSMount

    def _device_check(self, devspec):
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
    _modules = ["iso9660"]
    _supported = True
    _mount_class = fsmount.Iso9660FSMount


register_device_format(Iso9660FS)


class NoDevFS(FS):

    """ nodev filesystem base class """
    _type = "nodev"
    _mount_class = fsmount.NoDevFSMount
    _selinux_supported = False
    _min_size = Size(0)

    def __init__(self, **kwargs):
        FS.__init__(self, **kwargs)
        self.exists = True
        self.device = self._type

    def _device_check(self, devspec):
        return None

    @property
    def type(self):
        return self.device


register_device_format(NoDevFS)


class DevPtsFS(NoDevFS):

    """ devpts filesystem. """
    _type = "devpts"
    _mount_class = fsmount.DevPtsFSMount


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
    _linux_native = True
    # in a sense, I guess tmpfs is formattable
    # in the regard that the format is automatically created
    # once mounted
    _formattable = True
    _size_info_class = fssize.TmpFSSize
    _mount_class = fsmount.TmpFSMount
    _resize_class = fsresize.TmpFSResize

    def __init__(self, **kwargs):
        NoDevFS.__init__(self, **kwargs)
        self._device = "tmpfs"

        # according to the following Kernel ML thread:
        # http://www.gossamer-threads.com/lists/linux/kernel/875278
        # maximum tmpfs mount size is 16TB on 32 bit systems
        # and 16EB on 64 bit systems
        bits = arch.num_bits()
        if bits == 32:
            self._max_size = Size("16TiB")
        elif bits == 64:
            self._max_size = Size("16EiB")
        # if the architecture is other than 32 or 64 bit or unknown
        # just use the default maxsize, which is 0, this disables
        # resizing but other operations such as mounting should work fine

        # if the size is 0, which is probably not set, accept the default
        # size when mounting.
        self._accept_default_size = not(self._size)

    def create(self, **kwargs):
        """ A filesystem is created automatically once tmpfs is mounted. """

    def destroy(self, **kwargs):
        """ The device and its filesystem are automatically destroyed once the
        mountpoint is unmounted.
        """

    def _size_option(self, size):
        """ Returns a size option string appropriate for mounting tmpfs.

            :param Size size: any size
            :returns: size option
            :rtype: str

            This option should be appended to other mount options, in
            case the regular mountopts also contain a size option.
            This is not impossible, since a special option for mounting
            is size=<percentage>%.
        """
        return "size=%s" % (self._resize.size_fmt % size.convert_to(self._resize.unit))

    def _get_options(self):
        # Returns the regular mount options with the special size option,
        # if any, appended.
        # The size option should be last, as the regular mount options may
        # also contain a size option, but the later size option supercedes
        # the earlier one.
        opts = super(TmpFS, self)._get_options()
        if self._accept_default_size:
            size_opt = None
        else:
            size_opt = self._size_option(self._size)
        return ",".join(o for o in (opts, size_opt) if o)

    @property
    def free(self):
        if self.system_mountpoint:
            # If self.system_mountpoint is defined, it means this tmpfs mount
            # has been mounted and there is a path we can use as a handle to
            # look-up the free space on the filesystem.
            # When running with changeroot, such as during installation,
            # self.system_mountpoint is set to the full changeroot path once
            # mounted so even with changeroot, statvfs should still work fine.
            st = os.statvfs(self.system_mountpoint)
            free_space = Size(st.f_bavail * st.f_frsize)
        else:
            # Free might be called even if the tmpfs mount has not been
            # mounted yet, in this case just return the size set for the mount.
            # Once mounted, the tmpfs mount will be empty
            # and therefore free space will correspond to its size.
            free_space = self._size
        return free_space

    def _get_device(self):
        """ All the tmpfs mounts use the same "tmpfs" device. """
        return self._type

    def _set_device(self, devspec):
        # the DeviceFormat parent class does a
        # self.device = kwargs["device"]
        # assignment, so we need a setter for the
        # device property, but as the device is always the
        # same, nothing actually needs to be set
        pass

    def do_resize(self):
        # Override superclass method to record whether mount options
        # should include an explicit size specification.
        original_size = self._size
        FS.do_resize(self)
        self._accept_default_size = self._accept_default_size and original_size == self._size


register_device_format(TmpFS)


class BindFS(FS):
    _type = "bind"
    _mount_class = fsmount.BindFSMount


register_device_format(BindFS)


class SELinuxFS(NoDevFS):
    _type = "selinuxfs"
    _mount_class = fsmount.SELinuxFSMount


register_device_format(SELinuxFS)


class USBFS(NoDevFS):
    _type = "usbfs"


register_device_format(USBFS)


class EFIVarFS(NoDevFS):
    _type = "efivarfs"


register_device_format(EFIVarFS)
