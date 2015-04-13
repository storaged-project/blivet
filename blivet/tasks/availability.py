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

from six import add_metaclass

from gi.repository import BlockDev as blockdev

from .. import util
from ..errors import AvailabilityError

class ExternalResource(object):
    """ An application. """

    def __init__(self, method, name):
        """ Initializes an instance of an application.

            :param method: A method object
            :type method: :class:`Method`
            :param str name: the name of the application
        """
        self._method = method
        self.name = name

    def __str__(self):
        return self.name

    # Results of these methods may change at runtime, depending on system
    # state.

    @property
    def available(self):
        """ Whether the resource is available.

            :returns: True if the resource is available, otherwise False
            :rtype: bool
        """
        return self._method.available(self)

@add_metaclass(abc.ABCMeta)
class Method(object):
    """ A collection of methods for a particular application task. """

    @abc.abstractmethod
    def available(self, resource):
        """ Returns True if the resource is available.

            :param resource: any external resource
            :type resource: :class:`ExternalResource`

            :returns: True if the application is available
            :rtype: bool
        """
        raise NotImplementedError()

class Path(Method):
    """ Methods for when application is found in  PATH. """

    def available(self, resource):
        """ Returns True if the name of the application is in the path.

            :param resource: any application
            :type resource: :class:`ExternalResource`

            :returns: True if the name of the application is in the path
            :rtype: bool
        """
        return bool(util.find_program_in_path(resource.name))

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

class PackageMethod(object):
    """ Methods for checking the package version of the external resource. """

    def __init__(self, package=None):
        """ Initializer.

            :param :class:`PackageInfo` package:
        """
        self.package = package

    @property
    def packageVersion(self):
        args = ["rpm", "-q", "--queryformat", "%{VERSION}", self.package.package_name]
        try:
            (rc, out) = util.run_program_and_capture_output(args)
            if rc != 0:
                raise AvailabilityError("Could not determine package version for %s" % self.package.package_name)
        except OSError as e:
            raise AvailabilityError("Could not determine package version for %s: %s" % (self.package.package_name, e))

        return LooseVersion(out)

    def available(self, resource):
        return Path.available(resource) and \
           self.package.required_version is None or self.packageVersion >= self.package.required_version

class BlockDevMethod(Method):
    """ Methods for when application is actually a libblockdev plugin. """

    def available(self, resource):
        """ Returns True if the plugin is loaded.

            :param resource: a libblockdev plugin
            :type resource: :class:`ExternalResource`

            :returns: True if the name of the plugin is loaded
            :rtype: bool
        """
        return resource.name in blockdev.get_available_plugin_names()

BlockDevMethod = BlockDevMethod()

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
DOSFSLABEL_APP = application("dosfslabel")
E2LABEL_APP = application_by_package("e2label", E2FSPROGS_PACKAGE)
JFSTUNE_APP = application("jfs_tune")
NTFSLABEL_APP = application("ntfslabel")
NTFSRESIZE_APP = application("ntfsresize")
RESIZE2FS_APP = application_by_package("resize2fs", E2FSPROGS_PACKAGE)
XFSADMIN_APP = application("xfs_admin")

MOUNT_APP = application("mount")
