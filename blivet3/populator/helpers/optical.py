# populator.py
# Backend code for populating a DeviceTree.
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
from ...devices import OpticalDevice
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator


class OpticalDevicePopulator(DevicePopulator):
    @classmethod
    def match(cls, data):
        return udev.device_is_cdrom(data)

    def run(self):
        log_method_call(self)
        # XXX should this be RemovableDevice instead?
        #
        # Looks like if it has ID_INSTANCE=0:1 we can ignore it.
        device = OpticalDevice(udev.device_get_name(self.data),
                               major=udev.device_get_major(self.data),
                               minor=udev.device_get_minor(self.data),
                               sysfs_path=udev.device_get_sysfs_path(self.data),
                               vendor=udev.device_get_vendor(self.data),
                               model=udev.device_get_model(self.data))
        self._devicetree._add_device(device)
        return device
