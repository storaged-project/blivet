# devices/luks.py
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

# device backend modules
from ..devicelibs import crypto

from ..storage_log import log_method_call
from ..size import Size
from ..tasks import availability

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .dm import DMCryptDevice, DMIntegrityDevice


class LUKSDevice(DMCryptDevice):

    """ A mapped LUKS device. """
    _type = "luks/dm-crypt"
    _resizable = True
    _packages = ["cryptsetup"]
    _external_dependencies = [availability.BLOCKDEV_CRYPTO_PLUGIN]

    def __init__(self, name, fmt=None, size=None, uuid=None,
                 exists=False, sysfs_path='', parents=None):
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
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword uuid: the device UUID
            :type uuid: str
        """
        DMCryptDevice.__init__(self, name, fmt=fmt, size=size,
                               parents=parents, sysfs_path=sysfs_path,
                               uuid=None, exists=exists)

    @property
    def raw_device(self):
        return self.slave

    @property
    def size(self):
        if not self.exists:
            size = self.slave.size - crypto.LUKS_METADATA_SIZE
        elif self.resizable and self.target_size != Size(0):
            size = self.target_size
        else:
            size = self.current_size
        return size

    def _set_target_size(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new size must be of type Size")

        if self.max_size and newsize > self.max_size:
            log.error("requested size %s is larger than maximum %s",
                      newsize, self.max_size)
            raise ValueError("size is larger than the maximum for this device")
        elif self.min_size and newsize < self.min_size:
            log.error("requested size %s is smaller than minimum %s",
                      newsize, self.min_size)
            raise ValueError("size is smaller than the minimum for this device")

        # don't allow larger luks than size (or target size) of backing device
        if newsize > (self.slave.size - crypto.LUKS_METADATA_SIZE):
            log.error("requested size %s is larger than size of the backing device %s",
                      newsize, self.slave.size)
            raise ValueError("size is larger than the size of the backing device")

        if self.align_target_size(newsize) != newsize:
            raise ValueError("new size would violate alignment requirements")

    def _get_target_size(self):
        return self.slave.format.target_size

    @property
    def max_size(self):
        """ The maximum size this luks device can be. Maximum is based on the
            maximum size of the backing device. """
        max_luks = self.slave.max_size - crypto.LUKS_METADATA_SIZE
        max_format = self.format.max_size
        return min(max_luks, max_format) if max_format else max_luks

    @property
    def resizable(self):
        """ Can this device be resized? """
        return (self._resizable and self.exists and self.format.resizable and
                self.slave.resizable)

    def resize(self):
        # size of LUKSDevice depends on size of the LUKS format on backing
        # device; to resize it, resize the format
        log_method_call(self, self.name, status=self.status)

    def _post_create(self):
        self.name = self.slave.format.map_name
        StorageDevice._post_create(self)

    def _post_teardown(self, recursive=False):
        if not recursive:
            # this is handled by StorageDevice._post_teardown if recursive
            # is True
            self.teardown_parents(recursive=recursive)

        StorageDevice._post_teardown(self, recursive=recursive)

    def dracut_setup_args(self):
        return set(["rd.luks.uuid=luks-%s" % self.slave.format.uuid])

    def populate_ksdata(self, data):
        self.slave.populate_ksdata(data)
        data.encrypted = True
        super(LUKSDevice, self).populate_ksdata(data)


class IntegrityDevice(DMIntegrityDevice):

    """ A mapped integrity device. """
    _type = "integrity/dm-crypt"
    _resizable = True
    _packages = ["cryptsetup"]
    _external_dependencies = [availability.BLOCKDEV_CRYPTO_PLUGIN]

    def __init__(self, name, fmt=None, size=None, uuid=None,
                 exists=False, sysfs_path='', parents=None):
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
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword uuid: the device UUID
            :type uuid: str
        """
        DMIntegrityDevice.__init__(self, name, fmt=fmt, size=size,
                                   parents=parents, sysfs_path=sysfs_path,
                                   uuid=None, exists=exists)
