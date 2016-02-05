# populator/helpers/devicepopulator.py
# Base class for device-type-specific helpers for populating a DeviceTree.
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

from .populatorhelper import PopulatorHelper
from ... import udev


# pylint: disable=abstract-method
class DevicePopulator(PopulatorHelper):
    """ Populator helper base class for devices.

        Subclasses must define a match method and, if they want to instantiate
        a device, a run method.
    """
    @classmethod
    def match(cls, data):
        return False

    def _handle_rename(self):
        name = udev.device_get_name(self.data)
        if self.device.name != name:
            self.device.name = name
        # TODO: update name registry -- better yet, generate the name list on demand

    def _handle_resize(self):
        old_size = self.device.current_size
        self.device.update_size()
        if old_size != self.device.current_size:
            self._devicetree.cancel_disk_actions(self.device.disks)

    def update(self):
        self._handle_rename()
        self._handle_resize()
