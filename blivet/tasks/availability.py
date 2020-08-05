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
from distutils.spawn import find_executable

from six import add_metaclass

import gi
gi.require_version("BlockDev", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import BlockDev as blockdev
from gi.repository import GLib

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


@add_metaclass(abc.ABCMeta)
class Method(object):

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
        if not find_executable(resource.name):
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
                errors.append(str(e))
        return errors

    def availability_errors(self, resource):
        """ Returns [] if the plugin is loaded.

            :param resource: a libblockdev plugin
            :type resource: :class:`ExternalResource`

            :returns: [] if the name of the plugin is loaded
            :rtype: list of str
        """
        if resource.name not in blockdev.get_available_plugin_names():  # pylint: disable=no-value-for-parameter
            return ["libblockdev plugin %s not loaded" % resource.name]
        else:
            tech_missing = self._check_technologies()
            if tech_missing:
                return ["libblockdev plugin %s is loaded but some required "
                        "technologies are not available:\n%s" % (resource.name, tech_missing)]
            else:
                return []


class UnavailableMethod(Method):

    """ Method that indicates a resource is unavailable. """

    def availability_errors(self, resource):
        return ["always unavailable"]


UnavailableMethod = UnavailableMethod()


class AvailableMethod(Method):

    """ Method that indicates a resource is available. """

    def availability_errors(self, resource):
        return []


AvailableMethod = AvailableMethod()


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
                                                 blockdev.CryptoTech.LUKS2: BLOCKDEV_CRYPTO_ALL_MODES,
                                                 blockdev.CryptoTech.ESCROW: blockdev.CryptoTechMode.CREATE})
BLOCKDEV_CRYPTO_TECH = BlockDevMethod(BLOCKDEV_CRYPTO)

# libblockdev dm plugin required technologies and modes
BLOCKDEV_DM_ALL_MODES = (blockdev.DMTechMode.CREATE_ACTIVATE |
                         blockdev.DMTechMode.REMOVE_DEACTIVATE |
                         blockdev.DMTechMode.QUERY)
BLOCKDEV_DM = BlockDevTechInfo(plugin_name="dm",
                               check_fn=blockdev.dm_is_tech_avail,
                               technologies={blockdev.DMTech.MAP: BLOCKDEV_DM_ALL_MODES})
BLOCKDEV_DM_TECH = BlockDevMethod(BLOCKDEV_DM)

BLOCKDEV_DM_RAID = BlockDevTechInfo(plugin_name="dm",
                                    check_fn=blockdev.dm_is_tech_avail,
                                    technologies={blockdev.DMTech.RAID: BLOCKDEV_DM_ALL_MODES})
BLOCKDEV_DM_TECH_RAID = BlockDevMethod(BLOCKDEV_DM_RAID)

# libblockdev loop plugin required technologies and modes
BLOCKDEV_LOOP_ALL_MODES = (blockdev.LoopTechMode.CREATE |
                           blockdev.LoopTechMode.CREATE |
                           blockdev.LoopTechMode.DESTROY |
                           blockdev.LoopTechMode.MODIFY |
                           blockdev.LoopTechMode.QUERY)
BLOCKDEV_LOOP = BlockDevTechInfo(plugin_name="loop",
                                 check_fn=blockdev.loop_is_tech_avail,
                                 technologies={blockdev.LoopTech.LOOP_TECH_LOOP: BLOCKDEV_LOOP_ALL_MODES})
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

# libblockdev mdraid plugin required technologies and modes
BLOCKDEV_MD_ALL_MODES = (blockdev.MDTechMode.CREATE |
                         blockdev.MDTechMode.DELETE |
                         blockdev.MDTechMode.MODIFY |
                         blockdev.MDTechMode.QUERY)
BLOCKDEV_MD = BlockDevTechInfo(plugin_name="mdraid",
                               check_fn=blockdev.md_is_tech_avail,
                               technologies={blockdev.MDTech.MD_TECH_MDRAID: BLOCKDEV_MD_ALL_MODES})
BLOCKDEV_MD_TECH = BlockDevMethod(BLOCKDEV_MD)

# libblockdev mpath plugin required technologies and modes
BLOCKDEV_MPATH_ALL_MODES = (blockdev.MpathTechMode.MODIFY |
                            blockdev.MpathTechMode.QUERY)
BLOCKDEV_MPATH = BlockDevTechInfo(plugin_name="mpath",
                                  check_fn=blockdev.mpath_is_tech_avail,
                                  technologies={blockdev.MpathTech.BASE: BLOCKDEV_MPATH_ALL_MODES})
BLOCKDEV_MPATH_TECH = BlockDevMethod(BLOCKDEV_MPATH)

# libblockdev swap plugin required technologies and modes
BLOCKDEV_SWAP_ALL_MODES = (blockdev.SwapTechMode.CREATE |
                           blockdev.SwapTechMode.ACTIVATE_DEACTIVATE |
                           blockdev.SwapTechMode.QUERY |
                           blockdev.SwapTechMode.SET_LABEL)
BLOCKDEV_SWAP = BlockDevTechInfo(plugin_name="swap",
                                 check_fn=blockdev.swap_is_tech_avail,
                                 technologies={blockdev.SwapTech.SWAP_TECH_SWAP: BLOCKDEV_SWAP_ALL_MODES})
BLOCKDEV_SWAP_TECH = BlockDevMethod(BLOCKDEV_SWAP)

# libblockdev plugins
# we can't just check if the plugin is loaded, we also need to make sure
# that all technologies required by us our supported (some may be missing
# due to missing dependencies)
BLOCKDEV_BTRFS_PLUGIN = blockdev_plugin("btrfs", BLOCKDEV_BTRFS_TECH)
BLOCKDEV_CRYPTO_PLUGIN = blockdev_plugin("crypto", BLOCKDEV_CRYPTO_TECH)
BLOCKDEV_DM_PLUGIN = blockdev_plugin("dm", BLOCKDEV_DM_TECH)
BLOCKDEV_DM_PLUGIN_RAID = blockdev_plugin("dm", BLOCKDEV_DM_TECH_RAID)
BLOCKDEV_LOOP_PLUGIN = blockdev_plugin("loop", BLOCKDEV_LOOP_TECH)
BLOCKDEV_LVM_PLUGIN = blockdev_plugin("lvm", BLOCKDEV_LVM_TECH)
BLOCKDEV_MDRAID_PLUGIN = blockdev_plugin("mdraid", BLOCKDEV_MD_TECH)
BLOCKDEV_MPATH_PLUGIN = blockdev_plugin("mpath", BLOCKDEV_MPATH_TECH)
BLOCKDEV_SWAP_PLUGIN = blockdev_plugin("swap", BLOCKDEV_SWAP_TECH)

# applications with versions
# we need e2fsprogs newer than 1.41 and we are checking the version by running
# the "e2fsck" tool and parsing its ouput for version number
E2FSPROGS_INFO = AppVersionInfo(app_name="e2fsck",
                                required_version="1.41.0",
                                version_opt="-V",
                                version_regex=r"e2fsck ([0-9+\.]+) .*")
E2FSPROGS_VERSION = VersionMethod(E2FSPROGS_INFO)

# applications
DEBUGREISERFS_APP = application("debugreiserfs")
DF_APP = application("df")
DOSFSCK_APP = application("dosfsck")
DOSFSLABEL_APP = application("dosfslabel")
DUMPE2FS_APP = application_by_version("dumpe2fs", E2FSPROGS_VERSION)
E2FSCK_APP = application_by_version("e2fsck", E2FSPROGS_VERSION)
E2LABEL_APP = application_by_version("e2label", E2FSPROGS_VERSION)
FSCK_HFSPLUS_APP = application("fsck.hfsplus")
HFORMAT_APP = application("hformat")
JFSTUNE_APP = application("jfs_tune")
KPARTX_APP = application("kpartx")
MKDOSFS_APP = application("mkdosfs")
MKE2FS_APP = application_by_version("mke2fs", E2FSPROGS_VERSION)
MKFS_BTRFS_APP = application("mkfs.btrfs")
MKFS_GFS2_APP = application("mkfs.gfs2")
MKFS_HFSPLUS_APP = application("mkfs.hfsplus")
MKFS_JFS_APP = application("mkfs.jfs")
MKFS_XFS_APP = application("mkfs.xfs")
MKNTFS_APP = application("mkntfs")
MKREISERFS_APP = application("mkreiserfs")
MLABEL_APP = application("mlabel")
MULTIPATH_APP = application("multipath")
NTFSINFO_APP = application("ntfsinfo")
NTFSLABEL_APP = application("ntfslabel")
NTFSRESIZE_APP = application("ntfsresize")
REISERFSTUNE_APP = application("reiserfstune")
RESIZE2FS_APP = application_by_version("resize2fs", E2FSPROGS_VERSION)
TUNE2FS_APP = application_by_version("tune2fs", E2FSPROGS_VERSION)
XFSADMIN_APP = application("xfs_admin")
XFSDB_APP = application("xfs_db")
XFSFREEZE_APP = application("xfs_freeze")
XFSRESIZE_APP = application("xfs_growfs")
XFSREPAIR_APP = application("xfs_repair")

FSCK_F2FS_APP = application("fsck.f2fs")
MKFS_F2FS_APP = application("mkfs.f2fs")

MOUNT_APP = application("mount")
