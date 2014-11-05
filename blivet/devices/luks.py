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

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .dm import DMCryptDevice

class LUKSDevice(DMCryptDevice):
    """ A mapped LUKS device. """
    _type = "luks/dm-crypt"
    _packages = ["cryptsetup"]

    def __init__(self, name, fmt=None, size=None, uuid=None,
                 exists=False, sysfsPath='', parents=None):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword uuid: the device UUID
            :type uuid: str
        """
        DMCryptDevice.__init__(self, name, fmt=fmt, size=size,
                               parents=parents, sysfsPath=sysfsPath,
                               uuid=None, exists=exists)

    @property
    def raw_device(self):
        return self.slave

    @property
    def size(self):
        if not self.exists:
            size = self.slave.size - crypto.LUKS_METADATA_SIZE
        else:
            size = self.currentSize
        return size

    def _postCreate(self):
        self.name = self.slave.format.mapName
        StorageDevice._postCreate(self)

    def _postTeardown(self, recursive=False):
        if not recursive:
            # this is handled by StorageDevice._postTeardown if recursive
            # is True
            self.teardownParents(recursive=recursive)

        StorageDevice._postTeardown(self, recursive=recursive)

    def dracutSetupArgs(self):
        return set(["rd.luks.uuid=luks-%s" % self.slave.format.uuid])

    def populateKSData(self, data):
        self.slave.populateKSData(data)
        data.encrypted = True
        super(LUKSDevice, self).populateKSData(data)
