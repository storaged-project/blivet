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
from distutils.version import LooseVersion
import hawkey

from six import add_metaclass

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from .. import util
from ..errors import AvailabilityError

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
        self._availabilityErrors = None

    def __str__(self):
        return self.name

    @property
    def availabilityErrors(self):
        """ Whether the resource has any availability errors.

            :returns: [] if the resource is available
            :rtype: list of str
        """
        if self._availabilityErrors is None or not CACHE_AVAILABILITY:
            self._availabilityErrors = self._method.availabilityErrors(self)
        return self._availabilityErrors[:]

    @property
    def available(self):
        """ Whether the resource is available.

            :returns: True if the resource is available
            :rtype: bool
        """
        return self.availabilityErrors == []

@add_metaclass(abc.ABCMeta)
class Method(object):
    """ Method for determining if external resource is available."""

    @abc.abstractmethod
    def availabilityErrors(self, resource):
        """ Returns [] if the resource is available.

            :param resource: any external resource
            :type resource: :class:`ExternalResource`

            :returns: [] if the external resource is available
            :rtype: list of str
        """
        raise NotImplementedError()

class Path(Method):
    """ Methods for when application is found in  PATH. """

    def availabilityErrors(self, resource):
        """ Returns [] if the name of the application is in the path.

            :param resource: any application
            :type resource: :class:`ExternalResource`

            :returns: [] if the name of the application is in the path
            :rtype: list of str
        """
        if not util.find_program_in_path(resource.name):
            return ["application %s is not in $PATH" % resource.name]
        else:
            return []

Path = Path()

class PackageInfo(object):

    def __init__(self, package_name, required_version=None):
        """ Initializer.

            :param str package_name: the name of the package
            :param required_version: the required version for this package
            :type required_version: :class:`distutils.LooseVersion` or NoneType
        """
        self.package_name = package_name
        self.required_version = required_version

    def __str__(self):
        return "%s-%s" % (self.package_name, self.required_version)

class PackageMethod(Method):
    """ Methods for checking the package version of the external resource. """

    def __init__(self, package=None):
        """ Initializer.

            :param :class:`PackageInfo` package:
        """
        self.package = package
        self._availabilityErrors = None

    @property
    def packageVersion(self):
        """ Returns the version of the installed package.

            :returns: the package version
            :rtype: LooseVersion
            :raises AvailabilityError: on failure to obtain package version
        """
        sack = hawkey.Sack()

        try:
            sack.load_system_repo()
        except IOError as e:
            # hawkey has been observed allowing an IOError to propagate to
            # caller with message "Failed calculating RPMDB checksum."
            # See: https://bugzilla.redhat.com/show_bug.cgi?id=1223914
            raise AvailabilityError("Could not determine package version for %s: %s" % (self.package.package_name, e))

        query = hawkey.Query(sack).filter(name=self.package.package_name, latest=True)
        packages = query.run()
        if len(packages) != 1:
            raise AvailabilityError("Could not determine package version for %s: unable to obtain package information from repo" % self.package.package_name)

        return LooseVersion(packages[0].version)

    def availabilityErrors(self, resource):
        if self._availabilityErrors is not None and CACHE_AVAILABILITY:
            return self._availabilityErrors[:]

        self._availabilityErrors = Path.availabilityErrors(resource)

        if self.package.required_version is None:
            return self._availabilityErrors[:]

        try:
            if self.packageVersion < self.package.required_version:
                self._availabilityErrors.append("installed version %s for package %s is less than required version %s" % (self.packageVersion, self.package.package_name, self.package.required_version))
        except AvailabilityError as e:
            # In contexts like the installer, a package may not be available,
            # but the version of the tools is likely to be correct.
            log.warning(str(e))

        return self._availabilityErrors[:]

class BlockDevMethod(Method):
    """ Methods for when application is actually a libblockdev plugin. """

    def availabilityErrors(self, resource):
        """ Returns [] if the plugin is loaded.

            :param resource: a libblockdev plugin
            :type resource: :class:`ExternalResource`

            :returns: [] if the name of the plugin is loaded
            :rtype: list of str
        """
        if resource.name in blockdev.get_available_plugin_names():
            return []
        else:
            return ["libblockdev plugin %s not loaded" % resource.name]

BlockDevMethod = BlockDevMethod()

class UnavailableMethod(Method):
    """ Method that indicates a resource is unavailable. """

    def availabilityErrors(self, resource):
        return ["always unavailable"]

UnavailableMethod = UnavailableMethod()

class AvailableMethod(Method):
    """ Method that indicates a resource is available. """

    def availabilityErrors(self, resource):
        return []

AvailableMethod = AvailableMethod()

def application(name):
    """ Construct an external resource that is an application.

        This application will be available if its name can be found in $PATH.
    """
    return ExternalResource(Path, name)

def application_by_package(name, package_method):
    """ Construct an external resource that is an application.

        This application will be available if its name can be found in $PATH
        AND its package version is at least the required version.

        :param :class:`PackageMethod` package_method: the package method
    """
    return ExternalResource(package_method, name)

def blockdev_plugin(name):
    """ Construct an external resource that is a libblockdev plugin. """
    return ExternalResource(BlockDevMethod, name)

def unavailable_resource(name):
    """ Construct an external resource that is always unavailable. """
    return ExternalResource(UnavailableMethod, name)

def available_resource(name):
    """ Construct an external resource that is always available. """
    return ExternalResource(AvailableMethod, name)

# blockdev plugins
BLOCKDEV_BTRFS_PLUGIN = blockdev_plugin("btrfs")
BLOCKDEV_CRYPTO_PLUGIN = blockdev_plugin("crypto")
BLOCKDEV_DM_PLUGIN = blockdev_plugin("dm")
BLOCKDEV_LOOP_PLUGIN = blockdev_plugin("loop")
BLOCKDEV_LVM_PLUGIN = blockdev_plugin("lvm")
BLOCKDEV_MDRAID_PLUGIN = blockdev_plugin("mdraid")
BLOCKDEV_MPATH_PLUGIN = blockdev_plugin("mpath")
BLOCKDEV_SWAP_PLUGIN = blockdev_plugin("swap")

# packages
E2FSPROGS_PACKAGE = PackageMethod(PackageInfo("e2fsprogs", LooseVersion("1.41.0")))

# applications
DEBUGREISERFS_APP = application("debugreiserfs")
DF_APP = application("df")
DOSFSCK_APP = application("dosfsck")
DOSFSLABEL_APP = application("dosfslabel")
DUMPE2FS_APP = application_by_package("dumpe2fs", E2FSPROGS_PACKAGE)
E2FSCK_APP = application_by_package("e2fsck", E2FSPROGS_PACKAGE)
E2LABEL_APP = application_by_package("e2label", E2FSPROGS_PACKAGE)
FSCK_HFSPLUS_APP = application("fsck.hfsplus")
HFORMAT_APP = application("hformat")
JFSTUNE_APP = application("jfs_tune")
KPARTX_APP = application("kpartx")
MKDOSFS_APP = application("mkdosfs")
MKE2FS_APP = application_by_package("mke2fs", E2FSPROGS_PACKAGE)
MKFS_BTRFS_APP = application("mkfs.btrfs")
MKFS_GFS2_APP = application("mkfs.gfs2")
MKFS_HFSPLUS_APP = application("mkfs.hfsplus")
MKFS_JFS_APP = application("mkfs.jfs")
MKFS_XFS_APP = application("mkfs.xfs")
MKNTFS_APP = application("mkntfs")
MKREISERFS_APP = application("mkreiserfs")
MULTIPATH_APP = application("multipath")
NTFSINFO_APP = application("ntfsinfo")
NTFSLABEL_APP = application("ntfslabel")
NTFSRESIZE_APP = application("ntfsresize")
REISERFSTUNE_APP = application("reiserfstune")
RESIZE2FS_APP = application_by_package("resize2fs", E2FSPROGS_PACKAGE)
XFSADMIN_APP = application("xfs_admin")
XFSDB_APP = application("xfs_db")
XFSFREEZE_APP = application("xfs_freeze")

MOUNT_APP = application("mount")
