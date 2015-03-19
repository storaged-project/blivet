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

from six import add_metaclass

from gi.repository import BlockDev as blockdev

from .. import util

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
