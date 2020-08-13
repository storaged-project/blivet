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
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import re

from ... import udev
from ...devicelibs import raid
from ...devices import MDRaidArrayDevice, MDContainerDevice
from ...devices import device_path_to_name
from ...errors import DeviceError, NoParentsError
from ...flags import flags
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator
from .formatpopulator import FormatPopulator

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

        try:
            self._devicetree._add_parent_devices(self.data)
        except NoParentsError:
            log.error("no parents found for mdarray %s, skipping", name)
            return None

        # try to get the device again now that we've got all the parents
        device = self._devicetree.get_device_by_name(name, incomplete=flags.allow_imperfect_devices)

        if device is None:
            try:
                uuid = udev.device_get_md_uuid(self.data)
            except KeyError:
                log.warning("failed to obtain uuid for mdraid device")
            else:
                device = self._devicetree.get_device_by_uuid(uuid, incomplete=flags.allow_imperfect_devices)

        if device and name:
            # update the device instance with the real name in case we had to
            # look it up by something other than name
            device.name = name

        if device is None:
            # if we get here, we found all of the parent devices and
            # something must be wrong -- if all of the parents are in
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


class MDFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "mdmember"

    def _get_kwargs(self):
        kwargs = super(MDFormatPopulator, self)._get_kwargs()
        try:
            # ID_FS_UUID contains the array UUID
            kwargs["md_uuid"] = udev.device_get_uuid(self.data)
        except KeyError:
            log.warning("mdraid member %s has no md uuid", udev.device_get_name(self.data))

        # reset the uuid to the member-specific value
        # this will be None for members of v0 metadata arrays
        kwargs["uuid"] = udev.device_get_md_device_uuid(self.data)

        kwargs["biosraid"] = udev.device_is_biosraid_member(self.data)
        return kwargs

    def run(self):
        super(MDFormatPopulator, self).run()
        try:
            md_info = blockdev.md.examine(self.device.path)
        except blockdev.MDRaidError as e:
            # This could just mean the member is not part of any array.
            log.debug("blockdev.md.examine error: %s", str(e))
            return

        # Use mdadm info if udev info is missing
        md_uuid = md_info.uuid
        self.device.format.md_uuid = self.device.format.md_uuid or md_uuid
        md_array = self._devicetree.get_device_by_uuid(self.device.format.md_uuid, incomplete=True)

        if md_array:
            md_array.parents.append(self.device)
        else:
            # create the array with just this one member
            # level is reported as, eg: "raid1"
            md_level = md_info.level
            md_devices = md_info.num_devices

            if md_level is None:
                log.warning("invalid data for %s: no RAID level", self.device.name)
                return

            # md_examine yields metadata (MD_METADATA) only for metadata version > 0.90
            # if MD_METADATA is missing, assume metadata version is 0.90
            md_metadata = md_info.metadata or "0.90"
            md_name = None

            # check the list of devices udev knows about to see if the array
            # this device belongs to is already active
            # XXX This is mainly for containers now since their name/device is
            #     not given by mdadm examine as we run it.
            for dev in udev.get_devices():
                if not udev.device_is_md(dev):
                    continue

                try:
                    dev_uuid = udev.device_get_md_uuid(dev)
                    dev_level = udev.device_get_md_level(dev)
                except KeyError:
                    continue

                if dev_uuid is None or dev_level is None:
                    continue

                if dev_uuid == md_uuid and dev_level == md_level:
                    md_name = udev.device_get_md_name(dev)
                    break

            md_path = md_info.device or ""
            if md_path and not md_name:
                md_name = device_path_to_name(md_path)
                if re.match(r'md\d+$', md_name):
                    # md0 -> 0
                    md_name = md_name[2:]

                if md_name:
                    array = self._devicetree.get_device_by_name(md_name, incomplete=True)
                    if array and array.uuid != md_uuid:
                        log.error("found multiple devices with the name %s", md_name)

            if md_name:
                log.info("using name %s for md array containing member %s",
                         md_name, self.device.name)
            else:
                log.error("failed to determine name for the md array %s", (md_uuid or "unknown"))
                return

            array_type = MDRaidArrayDevice
            try:
                if raid.get_raid_level(md_level) is raid.Container and \
                   getattr(self.device.format, "biosraid", False):
                    array_type = MDContainerDevice
            except raid.RaidError as e:
                log.error("failed to create md array: %s", e)
                return

            try:
                md_array = array_type(
                    md_name,
                    level=md_level,
                    member_devices=md_devices,
                    uuid=md_uuid,
                    metadata_version=md_metadata,
                    exists=True
                )
            except (ValueError, DeviceError) as e:
                log.error("failed to create md array: %s", e)
                return

            md_array.update_sysfs_path()
            md_array.parents.append(self.device)
            self._devicetree._add_device(md_array)
            if md_array.status:
                array_info = udev.get_device(md_array.sysfs_path)
                if not array_info:
                    log.error("failed to get udev data for %s", md_array.name)
                    return

                self._devicetree.handle_device(array_info, update_orig_fmt=True)

    def update(self):
        # update array based on current md data
        pass
