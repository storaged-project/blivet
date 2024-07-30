# availability.py
# Class for tracking availability of an application.
#
# Copyright (C) 2014-2015  Red Hat, Inc.
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
# Red Hat Author(s): Anne Mulhern <amulhern@redhat.com>

import abc
import shutil

from ..devicelibs.stratis import STRATIS_SERVICE, STRATIS_PATH
from .. import util

import gi
gi.require_version("BlockDev", "3.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")

from gi.repository import BlockDev as blockdev
from gi.repository import GLib, Gio

import logging
log = logging.getLogger("blivet")

CACHE_AVAILABILITY = True


class ExternalResource(object):

    """ An external resource. """

    def __init__(self, method, name):
        """ Initializes an instance of an external resource.

            :param method: A method object
            :type method: :class:`Method`
            :param str name: the name of the external resource
        """
        self._method = method
        self.name = name
        self._availability_errors = None

    def __str__(self):
        return self.name

    @property
    def availability_errors(self):
        """ Whether the resource has any availability errors.

            :returns: [] if the resource is available
            :rtype: list of str
        """
        _errors = list()

        # Prepare error cache and return value based on current caching setting.
        if CACHE_AVAILABILITY:
            _errors = self._availability_errors
        else:
            self._availability_errors = None

        # Check for errors if necessary.
        if self._availability_errors is None:
            _errors = self._method.availability_errors(self)

        # Update error cache if necessary.
        if CACHE_AVAILABILITY and self._availability_errors is None:
            self._availability_errors = _errors[:]

        return _errors

    @property
    def available(self):
        """ Whether the resource is available.

            :returns: True if the resource is available
            :rtype: bool
        """
        return self.availability_errors == []


class Method(object, metaclass=abc.ABCMeta):

    """ Method for determining if external resource is available."""

    @abc.abstractmethod
    def availability_errors(self, resource):
        """ Returns [] if the resource is available.

            :param resource: any external resource
            :type resource: :class:`ExternalResource`

            :returns: [] if the external resource is available
            :rtype: list of str
        """
        raise NotImplementedError()


class Path(Method):

    """ Methods for when application is found in  PATH. """

    def availability_errors(self, resource):
        """ Returns [] if the name of the application is in the path.

            :param resource: any application
            :type resource: :class:`ExternalResource`

            :returns: [] if the name of the application is in the path
            :rtype: list of str
        """
        if not shutil.which(resource.name):
            return ["application %s is not in $PATH" % resource.name]
        else:
            return []


Path = Path()


class AppVersionInfo(object):

    def __init__(self, app_name, required_version, version_opt, version_regex):
        """ Initializer.

            :param str app_name: the name of the application
            :param required_version: the required version for this application
            :param version_opt: command line option to print version of this application
            :param version_regex: regular expression to extract version from
                                  output of @version_opt
            :type required_version: :class:`distutils.LooseVersion` or NoneType
        """
        self.app_name = app_name
        self.required_version = required_version
        self.version_opt = version_opt
        self.version_regex = version_regex

    def __str__(self):
        return "%s-%s" % (self.app_name, self.required_version)


class VersionMethod(Method):

    """ Methods for checking the version of the external resource. """

    def __init__(self, version_info=None):
        """ Initializer.

            :param :class:`AppVersionInfo` version_info:
        """
        self.version_info = version_info
        self._availability_errors = None

    def availability_errors(self, resource):
        if self._availability_errors is not None and CACHE_AVAILABILITY:
            return self._availability_errors[:]

        self._availability_errors = Path.availability_errors(resource)

        if self.version_info.required_version is None:
            return self._availability_errors[:]

        try:
            ret = blockdev.utils.check_util_version(self.version_info.app_name,
                                                    self.version_info.required_version,
                                                    self.version_info.version_opt,
                                                    self.version_info.version_regex)
            if not ret:
                err = "installed version of %s is less than " \
                      "required version %s" % (self.version_info.app_name,
                                               self.version_info.required_version)
                self._availability_errors.append(err)
        except blockdev.UtilsError as e:
            err = "failed to get installed version of %s: %s" % (self.version_info.app_name, e)
            self._availability_errors.append(err)

        return self._availability_errors[:]


class BlockDevTechInfo(object):

    def __init__(self, plugin_name, check_fn, technologies):
        """ Initializer.

            :param str plugin_name: the name of the libblockdev plugin
            :param check_fn: function used to check for support availability
            :param technologies: list of required technologies
        """
        self.plugin_name = plugin_name
        self.check_fn = check_fn
        self.technologies = technologies

    def __str__(self):
        return "blockdev-%s" % self.plugin_name


class BlockDevMethod(Method):

    """ Methods for when application is actually a libblockdev plugin. """

    def __init__(self, tech_info):
        """ Initializer.

            :param :class:`AppVersionInfo` version_info:
        """
        self._tech_info = tech_info
        self._availability_errors = None

    def _check_technologies(self):
        errors = []
        for tech, mode in self._tech_info.technologies.items():
            try:
                self._tech_info.check_fn(tech, mode)
            except GLib.GError as e:
                errors.append("%s: %s" % (tech.value_name, e.message))
        return errors

    def availability_errors(self, resource):
        """ Returns [] if the plugin is loaded.

            :param resource: a libblockdev plugin
            :type resource: :class:`ExternalResource`

            :returns: [] if the name of the plugin is loaded
            :rtype: list of str
        """
        if self._tech_info.plugin_name not in blockdev.get_available_plugin_names():  # pylint: disable=no-value-for-parameter
            return ["libblockdev plugin %s not loaded" % self._tech_info.plugin_name]
        else:
            tech_missing = self._check_technologies()
            if tech_missing:
                return ["libblockdev plugin %s is loaded but some required "
                        "technologies are not available (%s)" % (self._tech_info.plugin_name, "; ".join(tech_missing))]
            else:
                return []


class BlockDevFSMethod(Method):

    """ Methods for when application is actually a libblockdev FS plugin functionality. """

    def __init__(self, operation, check_fn, fstype):
        """ Initializer.

            :param operation: operation to check for support availability
            :param check_fn: function used to check for support availability
            :param fstype: filesystem type to check for the support availability
        """
        self.operation = operation
        self.check_fn = check_fn
        self.fstype = fstype
        self._availability_errors = None

    def availability_errors(self, resource):
        """ Returns [] if the plugin is loaded and functionality available.

            :param resource: a libblockdev plugin
            :type resource: :class:`ExternalResource`

            :returns: [] if the name of the plugin is loaded
            :rtype: list of str
        """
        if "fs" not in blockdev.get_available_plugin_names():
            return ["libblockdev fs plugin not loaded"]
        else:
            try:
                if self.operation in (FSOperation.UUID, FSOperation.LABEL, FSOperation.INFO, FSOperation.MIN_SIZE):
                    avail, utility = self.check_fn(self.fstype)
                elif self.operation == FSOperation.RESIZE:
                    avail, _mode, utility = self.check_fn(self.fstype)
                elif self.operation == FSOperation.MKFS:
                    avail, _options, utility = self.check_fn(self.fstype)
                else:
                    raise RuntimeError("Unknown operation")
            except blockdev.FSError as e:
                return [str(e)]
            if not avail:
                return ["libblockdev fs plugin is loaded but some required runtime "
                        "dependencies are not available: %s" % utility]
            else:
                return []


class DBusMethod(Method):

    """ Methods for when application is actually a DBus service. """

    def __init__(self, dbus_name, dbus_path):
        """ Initializer.

            :param :class:`AppVersionInfo` version_info:
        """
        self.dbus_name = dbus_name
        self.dbus_path = dbus_path
        self._availability_errors = None

    def _service_available(self):
        try:
            avail = blockdev.utils.dbus_service_available(None, Gio.BusType.SYSTEM, self.dbus_name, self.dbus_path)
        except blockdev.UtilsError:
            return False
        else:
            return avail

    def availability_errors(self, resource):
        """ Returns [] if the service is available.

            :param resource: a DBus service
            :type resource: :class:`ExternalResource`

            :returns: [] if the name of the plugin is loaded
            :rtype: list of str
        """
        if not self._service_available():
            # try to start the service first
            ret = util.run_program(["systemctl", "start", resource.name])
            if ret != 0:
                return ["DBus service %s not available" % resource.name]
            # try again now when the service should be started
            else:
                if not self._service_available():
                    return ["DBus service %s not available" % resource.name]
        return []


class _UnavailableMethod(Method):

    """ Method that indicates a resource is unavailable. """

    def __init__(self, error_msg=None):
        self.error_msg = error_msg or "always unavailable"

    def availability_errors(self, resource):
        return [self.error_msg]


UnavailableMethod = _UnavailableMethod()


class _AvailableMethod(Method):

    """ Method that indicates a resource is available. """

    def availability_errors(self, resource):
        return []


AvailableMethod = _AvailableMethod()


def application(name):
    """ Construct an external resource that is an application.

        This application will be available if its name can be found in $PATH.
    """
    return ExternalResource(Path, name)


def application_by_version(name, version_method):
    """ Construct an external resource that is an application.

        This application will be available if its name can be found in $PATH
        AND its version is at least the required version.

        :param :class:`VersionMethod` version_method: the version method
    """
    return ExternalResource(version_method, name)


def blockdev_plugin(name, blockdev_method):
    """ Construct an external resource that is a libblockdev plugin. """
    return ExternalResource(blockdev_method, name)


def blockdev_fs_plugin_operation(blockdev_fs_method):
    """ Construct an external resource that is a libblockdev FS plugin functionality. """
    return ExternalResource(blockdev_fs_method, "libblockdev FS plugin method")


def dbus_service(name, dbus_method):
    """ Construct an external resource that is a DBus service. """
    return ExternalResource(dbus_method, name)


def unavailable_resource(name):
    """ Construct an external resource that is always unavailable. """
    return ExternalResource(UnavailableMethod, name)


def available_resource(name):
    """ Construct an external resource that is always available. """
    return ExternalResource(AvailableMethod, name)


# libblockdev btrfs plugin required technologies and modes
BLOCKDEV_BTRFS_ALL_MODES = (blockdev.BtrfsTechMode.CREATE |
                            blockdev.BtrfsTechMode.DELETE |
                            blockdev.BtrfsTechMode.MODIFY |
                            blockdev.BtrfsTechMode.QUERY)
BLOCKDEV_BTRFS = BlockDevTechInfo(plugin_name="btrfs",
                                  check_fn=blockdev.btrfs_is_tech_avail,
                                  technologies={blockdev.BtrfsTech.MULTI_DEV: BLOCKDEV_BTRFS_ALL_MODES,
                                                blockdev.BtrfsTech.SUBVOL: BLOCKDEV_BTRFS_ALL_MODES,
                                                blockdev.BtrfsTech.SNAPSHOT: BLOCKDEV_BTRFS_ALL_MODES})
BLOCKDEV_BTRFS_TECH = BlockDevMethod(BLOCKDEV_BTRFS)

# libblockdev crypto plugin required technologies and modes
BLOCKDEV_CRYPTO_ALL_MODES = (blockdev.CryptoTechMode.CREATE |
                             blockdev.CryptoTechMode.OPEN_CLOSE |
                             blockdev.CryptoTechMode.QUERY |
                             blockdev.CryptoTechMode.ADD_KEY |
                             blockdev.CryptoTechMode.REMOVE_KEY |
                             blockdev.CryptoTechMode.RESIZE)
BLOCKDEV_CRYPTO = BlockDevTechInfo(plugin_name="crypto",
                                   check_fn=blockdev.crypto_is_tech_avail,
                                   technologies={blockdev.CryptoTech.LUKS: BLOCKDEV_CRYPTO_ALL_MODES,
                                                 blockdev.CryptoTech.ESCROW: blockdev.CryptoTechMode.CREATE})
BLOCKDEV_CRYPTO_TECH = BlockDevMethod(BLOCKDEV_CRYPTO)

BLOCKDEV_CRYPTO_INTEGRITY = BlockDevTechInfo(plugin_name="crypto",
                                             check_fn=blockdev.crypto_is_tech_avail,
                                             technologies={blockdev.CryptoTech.INTEGRITY: (blockdev.CryptoTechMode.CREATE |
                                                                                           blockdev.CryptoTechMode.OPEN_CLOSE |
                                                                                           blockdev.CryptoTechMode.QUERY)})
BLOCKDEV_CRYPTO_TECH_INTEGRITY = BlockDevMethod(BLOCKDEV_CRYPTO_INTEGRITY)

# libblockdev dm plugin required technologies and modes
BLOCKDEV_DM_ALL_MODES = (blockdev.DMTechMode.CREATE_ACTIVATE |
                         blockdev.DMTechMode.REMOVE_DEACTIVATE |
                         blockdev.DMTechMode.QUERY)
BLOCKDEV_DM = BlockDevTechInfo(plugin_name="dm",
                               check_fn=blockdev.dm_is_tech_avail,
                               technologies={blockdev.DMTech.MAP: BLOCKDEV_DM_ALL_MODES})
BLOCKDEV_DM_TECH = BlockDevMethod(BLOCKDEV_DM)

# libblockdev loop plugin required technologies and modes
BLOCKDEV_LOOP_ALL_MODES = (blockdev.LoopTechMode.CREATE |
                           blockdev.LoopTechMode.CREATE |
                           blockdev.LoopTechMode.DESTROY |
                           blockdev.LoopTechMode.MODIFY |
                           blockdev.LoopTechMode.QUERY)
BLOCKDEV_LOOP = BlockDevTechInfo(plugin_name="loop",
                                 check_fn=blockdev.loop_is_tech_avail,
                                 technologies={blockdev.LoopTech.LOOP: BLOCKDEV_LOOP_ALL_MODES})
BLOCKDEV_LOOP_TECH = BlockDevMethod(BLOCKDEV_LOOP)

# libblockdev lvm plugin required technologies and modes
BLOCKDEV_LVM_ALL_MODES = (blockdev.LVMTechMode.CREATE |
                          blockdev.LVMTechMode.REMOVE |
                          blockdev.LVMTechMode.MODIFY |
                          blockdev.LVMTechMode.QUERY)
BLOCKDEV_LVM = BlockDevTechInfo(plugin_name="lvm",
                                check_fn=blockdev.lvm_is_tech_avail,
                                technologies={blockdev.LVMTech.BASIC: BLOCKDEV_LVM_ALL_MODES,
                                              blockdev.LVMTech.BASIC_SNAP: BLOCKDEV_LVM_ALL_MODES,
                                              blockdev.LVMTech.THIN: BLOCKDEV_LVM_ALL_MODES,
                                              blockdev.LVMTech.CACHE: BLOCKDEV_LVM_ALL_MODES,
                                              blockdev.LVMTech.CALCS: blockdev.LVMTechMode.QUERY,
                                              blockdev.LVMTech.THIN_CALCS: blockdev.LVMTechMode.QUERY,
                                              blockdev.LVMTech.CACHE_CALCS: blockdev.LVMTechMode.QUERY,
                                              blockdev.LVMTech.GLOB_CONF: (blockdev.LVMTechMode.QUERY |
                                                                           blockdev.LVMTechMode.MODIFY)})
BLOCKDEV_LVM_TECH = BlockDevMethod(BLOCKDEV_LVM)

BLOCKDEV_LVM_VDO = BlockDevTechInfo(plugin_name="lvm",
                                    check_fn=blockdev.lvm_is_tech_avail,
                                    technologies={blockdev.LVMTech.VDO: (blockdev.LVMTechMode.CREATE |
                                                                         blockdev.LVMTechMode.REMOVE |
                                                                         blockdev.LVMTechMode.QUERY)})
BLOCKDEV_LVM_TECH_VDO = BlockDevMethod(BLOCKDEV_LVM_VDO)

BLOCKDEV_LVM_SHARED = BlockDevTechInfo(plugin_name="lvm",
                                       check_fn=blockdev.lvm_is_tech_avail,
                                       technologies={blockdev.LVMTech.SHARED: blockdev.LVMTechMode.MODIFY})
BLOCKDEV_LVM_TECH_SHARED = BlockDevMethod(BLOCKDEV_LVM_SHARED)

# libblockdev mdraid plugin required technologies and modes
BLOCKDEV_MD_ALL_MODES = (blockdev.MDTechMode.CREATE |
                         blockdev.MDTechMode.DELETE |
                         blockdev.MDTechMode.MODIFY |
                         blockdev.MDTechMode.QUERY)
BLOCKDEV_MD = BlockDevTechInfo(plugin_name="mdraid",
                               check_fn=blockdev.md_is_tech_avail,
                               technologies={blockdev.MDTech.MDRAID: BLOCKDEV_MD_ALL_MODES})
BLOCKDEV_MD_TECH = BlockDevMethod(BLOCKDEV_MD)

# libblockdev mpath plugin required technologies and modes
BLOCKDEV_MPATH_ALL_MODES = (blockdev.MpathTechMode.MODIFY |
                            blockdev.MpathTechMode.QUERY)
BLOCKDEV_MPATH = BlockDevTechInfo(plugin_name="mpath",
                                  check_fn=blockdev.mpath_is_tech_avail,
                                  technologies={blockdev.MpathTech.BASE: BLOCKDEV_MPATH_ALL_MODES,
                                                blockdev.MpathTech.FRIENDLY_NAMES: blockdev.MpathTechMode.MODIFY})
BLOCKDEV_MPATH_TECH = BlockDevMethod(BLOCKDEV_MPATH)

# libblockdev swap plugin required technologies and modes
BLOCKDEV_SWAP_ALL_MODES = (blockdev.SwapTechMode.CREATE |
                           blockdev.SwapTechMode.ACTIVATE_DEACTIVATE |
                           blockdev.SwapTechMode.QUERY |
                           blockdev.SwapTechMode.SET_LABEL)
BLOCKDEV_SWAP = BlockDevTechInfo(plugin_name="swap",
                                 check_fn=blockdev.swap_is_tech_avail,
                                 technologies={blockdev.SwapTech.SWAP: BLOCKDEV_SWAP_ALL_MODES})
BLOCKDEV_SWAP_TECH = BlockDevMethod(BLOCKDEV_SWAP)

# libblockdev fs plugin required technologies
# no modes, we will check for specific functionality separately
BLOCKDEV_FS = BlockDevTechInfo(plugin_name="fs",
                               check_fn=blockdev.fs_is_tech_avail,
                               technologies={blockdev.FSTech.GENERIC: 0,
                                             blockdev.FSTech.MOUNT: 0,
                                             blockdev.FSTech.EXT2: 0,
                                             blockdev.FSTech.EXT3: 0,
                                             blockdev.FSTech.EXT4: 0,
                                             blockdev.FSTech.XFS: 0,
                                             blockdev.FSTech.VFAT: 0,
                                             blockdev.FSTech.NTFS: 0})
BLOCKDEV_FS_TECH = BlockDevMethod(BLOCKDEV_FS)


# libblockdev fs plugin methods
class FSOperation():
    UUID = 0
    LABEL = 1
    RESIZE = 2
    INFO = 3
    MKFS = 4
    MIN_SIZE = 5


BLOCKDEV_EXT_UUID = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.UUID, blockdev.fs.can_set_uuid, "ext2"))
BLOCKDEV_XFS_UUID = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.UUID, blockdev.fs.can_set_uuid, "xfs"))
BLOCKDEV_NTFS_UUID = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.UUID, blockdev.fs.can_set_uuid, "ntfs"))

BLOCKDEV_EXT_LABEL = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.LABEL, blockdev.fs.can_set_label, "ext2"))
BLOCKDEV_XFS_LABEL = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.LABEL, blockdev.fs.can_set_label, "xfs"))
BLOCKDEV_VFAT_LABEL = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.LABEL, blockdev.fs.can_set_label, "vfat"))
BLOCKDEV_NTFS_LABEL = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.LABEL, blockdev.fs.can_set_label, "ntfs"))

BLOCKDEV_EXT_RESIZE = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.RESIZE, blockdev.fs.can_resize, "ext2"))
BLOCKDEV_XFS_RESIZE = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.RESIZE, blockdev.fs.can_resize, "xfs"))
BLOCKDEV_NTFS_RESIZE = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.RESIZE, blockdev.fs.can_resize, "ntfs"))

BLOCKDEV_EXT_INFO = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.INFO, blockdev.fs.can_get_size, "ext2"))
BLOCKDEV_XFS_INFO = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.INFO, blockdev.fs.can_get_size, "xfs"))
BLOCKDEV_NTFS_INFO = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.INFO, blockdev.fs.can_get_size, "ntfs"))
BLOCKDEV_VFAT_INFO = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.INFO, blockdev.fs.can_get_size, "vfat"))

BLOCKDEV_BTRFS_MKFS = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MKFS, blockdev.fs.can_mkfs, "btrfs"))
BLOCKDEV_EXT_MKFS = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MKFS, blockdev.fs.can_mkfs, "ext2"))
BLOCKDEV_XFS_MKFS = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MKFS, blockdev.fs.can_mkfs, "xfs"))
BLOCKDEV_NTFS_MKFS = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MKFS, blockdev.fs.can_mkfs, "ntfs"))
BLOCKDEV_VFAT_MKFS = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MKFS, blockdev.fs.can_mkfs, "vfat"))
BLOCKDEV_F2FS_MKFS = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MKFS, blockdev.fs.can_mkfs, "f2fs"))

BLOCKDEV_EXT_MIN_SIZE = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MIN_SIZE, blockdev.fs.can_get_min_size, "ext2"))
BLOCKDEV_NTFS_MIN_SIZE = blockdev_fs_plugin_operation(BlockDevFSMethod(FSOperation.MIN_SIZE, blockdev.fs.can_get_min_size, "ntfs"))

# libblockdev plugins
# we can't just check if the plugin is loaded, we also need to make sure
# that all technologies required by us our supported (some may be missing
# due to missing dependencies)
BLOCKDEV_BTRFS_PLUGIN = blockdev_plugin("libblockdev btrfs plugin", BLOCKDEV_BTRFS_TECH)
BLOCKDEV_CRYPTO_PLUGIN = blockdev_plugin("libblockdev crypto plugin", BLOCKDEV_CRYPTO_TECH)
BLOCKDEV_CRYPTO_PLUGIN_INTEGRITY = blockdev_plugin("libblockdev crypto plugin (integrity technology)",
                                                   BLOCKDEV_CRYPTO_TECH_INTEGRITY)
BLOCKDEV_DM_PLUGIN = blockdev_plugin("libblockdev dm plugin", BLOCKDEV_DM_TECH)
BLOCKDEV_LOOP_PLUGIN = blockdev_plugin("libblockdev loop plugin", BLOCKDEV_LOOP_TECH)
BLOCKDEV_LVM_PLUGIN = blockdev_plugin("libblockdev lvm plugin", BLOCKDEV_LVM_TECH)
BLOCKDEV_LVM_PLUGIN_VDO = blockdev_plugin("libblockdev lvm plugin (vdo technology)", BLOCKDEV_LVM_TECH_VDO)
BLOCKDEV_LVM_PLUGIN_SHARED = blockdev_plugin("libblockdev lvm plugin (shared LVM technology)", BLOCKDEV_LVM_TECH_SHARED)
BLOCKDEV_MDRAID_PLUGIN = blockdev_plugin("libblockdev mdraid plugin", BLOCKDEV_MD_TECH)
BLOCKDEV_MPATH_PLUGIN = blockdev_plugin("libblockdev mpath plugin", BLOCKDEV_MPATH_TECH)
BLOCKDEV_SWAP_PLUGIN = blockdev_plugin("libblockdev swap plugin", BLOCKDEV_SWAP_TECH)
BLOCKDEV_FS_PLUGIN = blockdev_plugin("libblockdev fs plugin", BLOCKDEV_FS_TECH)

# applications
# fsck
DOSFSCK_APP = application("dosfsck")
E2FSCK_APP = application("e2fsck")
FSCK_HFSPLUS_APP = application("fsck.hfsplus")
XFSREPAIR_APP = application("xfs_repair")
FSCK_F2FS_APP = application("fsck.f2fs")
NTFSRESIZE_APP = application("ntfsresize")

# mkfs
MKFS_GFS2_APP = application("mkfs.gfs2")
MKFS_HFSPLUS_APP = application("mkfs.hfsplus")

# other
KPARTX_APP = application("kpartx")
MULTIPATH_APP = application("multipath")
STRATISPREDICTUSAGE_APP = application("stratis-predict-usage")

# dbus services
STRATIS_SERVICE_METHOD = DBusMethod(STRATIS_SERVICE, STRATIS_PATH)
STRATIS_DBUS = dbus_service("stratisd", STRATIS_SERVICE_METHOD)
