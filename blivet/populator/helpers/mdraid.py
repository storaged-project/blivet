# populator/helpers/mdraid.py
# MD RAID backend code for populating a DeviceTree.
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
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

from ... import udev
from ...flags import flags
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator

import logging
log = logging.getLogger("blivet")


class MDDevicePopulator(DevicePopulator):
    @classmethod
    def match(cls, data):
        return (udev.device_is_md(data) and
                not udev.device_get_md_container(data))

    def run(self):
        name = udev.device_get_md_name(self.data)
        log_method_call(self, name=name)

        self._populator._add_slave_devices(self.data)

        # try to get the device again now that we've got all the slaves
        device = self._populator.devicetree.get_device_by_name(name, incomplete=flags.allow_imperfect_devices)

        if device is None:
            try:
                uuid = udev.device_get_md_uuid(self.data)
            except KeyError:
                log.warning("failed to obtain uuid for mdraid device")
            else:
                device = self._populator.devicetree.get_device_by_uuid(uuid, incomplete=flags.allow_imperfect_devices)

        if device and name:
            # update the device instance with the real name in case we had to
            # look it up by something other than name
            device.name = name

        if device is None:
            # if we get here, we found all of the slave devices and
            # something must be wrong -- if all of the slaves are in
            # the tree, this device should be as well
            if name is None:
                name = udev.device_get_name(self.data)
                path = "/dev/" + name
            else:
                path = "/dev/md/" + name

            log.error("failed to scan md array %s", name)
            try:
                blockdev.md.deactivate(path)
            except blockdev.MDRaidError:
                log.error("failed to stop broken md array %s", name)

        return device
