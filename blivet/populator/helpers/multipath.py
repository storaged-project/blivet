# populator/helpers/multipath.py
# Multipath backend code for populating a DeviceTree.
#
# Copyright (C) 2009-2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from ... import udev
from ...devices import MultipathDevice
from ...errors import DeviceTreeError
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator

import logging
log = logging.getLogger("blivet")


class MultipathDevicePopulator(DevicePopulator):
    @classmethod
    def match(cls, data):
        return (udev.device_is_dm_mpath(data) and
                not udev.device_is_dm_partition(data))

    def run(self):
        name = udev.device_get_name(self.data)
        log_method_call(self, name=name)

        slave_devices = self._populator._add_slave_devices(self.data)

        device = None
        if slave_devices:
            try:
                serial = self.data["DM_UUID"].split("-", 1)[1]
            except (IndexError, AttributeError):
                log.error("multipath device %s has no DM_UUID", name)
                raise DeviceTreeError("multipath %s has no DM_UUID" % name)

            device = MultipathDevice(name, parents=slave_devices,
                                     sysfs_path=udev.device_get_sysfs_path(self.data),
                                     serial=serial)
            self._populator.devicetree._add_device(device)

        return device
