# populator/helpers/dmraid.py
# DM RAID backend code for populating a DeviceTree.
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
from ...devices import DMRaidArrayDevice
from ...flags import flags
from ...storage_log import log_method_call
from .formatpopulator import FormatPopulator

import logging
log = logging.getLogger("blivet")


class DMRaidFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "dmraidmember"

    def run(self):
        super(DMRaidFormatPopulator, self).run()

        # if dmraid usage is disabled skip any dmraid set activation
        if not flags.dmraid:
            return

        log_method_call(self, name=self.device.name)
        name = udev.device_get_name(self.data)
        uuid = udev.device_get_uuid(self.data)
        major = udev.device_get_major(self.data)
        minor = udev.device_get_minor(self.data)

        # Have we already created the DMRaidArrayDevice?
        try:
            rs_names = blockdev.dm.get_member_raid_sets(name, uuid, major, minor)
        except blockdev.DMError as e:
            log.error("Failed to get RAID sets information for '%s': %s", name, str(e))
            return

        if len(rs_names) == 0:
            log.warning("dmraid member %s does not appear to belong to any "
                        "array", self.device.name)
            return

        for rs_name in rs_names:
            dm_array = self._devicetree.get_device_by_name(rs_name, incomplete=True)
            if dm_array is not None:
                # We add the new device.
                dm_array.parents.append(self.device)
            else:
                if not blockdev.dm.map_exists(rs_name, True, True):
                    # Activate the Raid set.
                    try:
                        blockdev.dm.activate_raid_set(rs_name)
                    except blockdev.DMError:
                        log.warning("Failed to activate the RAID set '%s'", rs_name)
                        return

                dm_array = DMRaidArrayDevice(rs_name,
                                             parents=[self.device],
                                             wwn=self.device.wwn)

                self._devicetree._add_device(dm_array)

                # Wait for udev to scan the just created nodes, to avoid a race
                # with the udev.get_device() call below.
                udev.settle()

                # Get the DMRaidArrayDevice a DiskLabel format *now*, in case
                # its partitions get scanned before it does.
                dm_array.update_sysfs_path()
                dm_array.update_size()
                dm_array_info = udev.get_device(dm_array.sysfs_path)
                if dm_array_info:
                    dm_array.wwn = udev.device_get_wwn(dm_array_info)
                self._devicetree.handle_device(dm_array_info, update_orig_fmt=True)
