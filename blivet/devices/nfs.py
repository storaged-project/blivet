# devices/nfs.py
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

from ..storage_log import log_method_call

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .network import NetworkStorageDevice


class NFSDevice(StorageDevice, NetworkStorageDevice):

    """ An NFS device """
    _type = "nfs"
    _packages = ["dracut-network"]

    def __init__(self, device, fmt=None, parents=None):
        """
            :param device: the device name (generally a device node's basename)
            :type device: str
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
        """
        # we could make host/ip, path, &c but will anything use it?
        StorageDevice.__init__(self, device, fmt=fmt, parents=parents)
        NetworkStorageDevice.__init__(self, device.split(":")[0])

    @property
    def path(self):
        """ Device node representing this device. """
        return self.name

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        self._pre_create()

    def destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)

    def update_size(self, newsize=None):
        pass

    def is_name_valid(self, name):
        # Override StorageDevice.is_name_valid to allow /
        return not('\x00' in name or name == '.' or name == '..')

    def update_sysfs_path(self):
        pass
