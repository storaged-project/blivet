# devices/cache.py
#
# Copyright (C) 2015  Red Hat, Inc.
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
# Red Hat Author(s): Vratislav Podzimek <vpodzime@redhat.com>
#

"""Module providing common helper classes, functions and other things related to
cached devices (like bcache, LVM cache and whatever appears in the future).

"""

import abc


class Cache(object, metaclass=abc.ABCMeta):

    """Abstract base class for cache objects providing the cache-related
    functionality on cached devices. Instances of this class are not expected to
    be devices (both in what they represent as well as not instances of the
    :class:`~.devices.Device` class) since they just provide the cache-related
    functionality of cached devices and are not devices on their own.

    """

    @property
    @abc.abstractmethod
    def size(self):
        """Size of the cache"""

    @property
    @abc.abstractmethod
    def exists(self):
        """Whether the cache (device) exists or not"""

    @property
    @abc.abstractmethod
    def stats(self):
        """Statistics for the cache
        :rtype: :class:`CacheStats`
        """

    @property
    @abc.abstractmethod
    def backing_device_name(self):
        """Name of the backing (big/slow) device of the cache (if any)"""

    @property
    @abc.abstractmethod
    def cache_device_name(self):
        """Name of the cache (small/fast) device of the cache (if any)"""

    @abc.abstractmethod
    def detach(self):
        """Detach the cache
        :returns: identifier of the detached cache that can be later used for attaching it back

        """


class CacheStats(object, metaclass=abc.ABCMeta):

    """Abstract base class for common statistics of caches (cached
    devices). Inheriting classes are expected to add (cache-)type-specific
    attributes on top of the common set.

    """

    @property
    @abc.abstractmethod
    def block_size(self):
        """block size of the cache"""

    @property
    @abc.abstractmethod
    def size(self):
        """size of the cache"""

    @property
    @abc.abstractmethod
    def used(self):
        """how much of the cache is used"""

    @property
    @abc.abstractmethod
    def hits(self):
        """number of hits"""

    @property
    @abc.abstractmethod
    def misses(self):
        """number of misses"""


class CacheRequest(object, metaclass=abc.ABCMeta):

    """Abstract base class for cache requests specifying cache parameters for a
    cached device

    """
    @property
    @abc.abstractmethod
    def size(self):
        """Requested size"""

    @property
    @abc.abstractmethod
    def fast_devs(self):
        """Devices (type-specific) to allocate/create the cache on"""

    @property
    @abc.abstractmethod
    def mode(self):
        """Mode the cache should use"""
