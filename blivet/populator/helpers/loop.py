# populator/helpers/loop.py
# Loop device backend code for populating a DeviceTree.
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

import gi
gi.require_version("BlockDev", "2.0")
from gi.repository import BlockDev as blockdev

from ... import udev
from ...devices import FileDevice, LoopDevice
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator


class LoopDevicePopulator(DevicePopulator):
    @classmethod
    def match(cls, data):
        return udev.device_is_loop(data)

    def run(self):
        name = udev.device_get_name(self.data)
        log_method_call(self, name=name)
        sysfs_path = udev.device_get_sysfs_path(self.data)
        backing_file = blockdev.loop.get_backing_file(name)
        if backing_file is None:
            return None
        file_device = self._devicetree.get_device_by_name(backing_file)
        if not file_device:
            file_device = FileDevice(backing_file, exists=True)
            self._devicetree._add_device(file_device)
        device = LoopDevice(name,
                            parents=[file_device],
                            sysfs_path=sysfs_path,
                            exists=True)
        if not self._devicetree._cleanup or file_device not in self._devicetree.disk_images.values():
            # don't allow manipulation of loop devices other than those
            # associated with disk images, and then only during cleanup
            file_device.controllable = False
            device.controllable = False
        self._devicetree._add_device(device)
        return device
