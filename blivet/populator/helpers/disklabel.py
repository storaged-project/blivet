# populator/helpers/disklabel.py
# Disklabel backend code for populating a DeviceTree.
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

from ... import formats
from ... import udev
from ...errors import InvalidDiskLabelError
from ...i18n import _
from ...storage_log import log_exception_info, log_method_call
from .formatpopulator import FormatPopulator

import logging
log = logging.getLogger("blivet")


class DiskLabelFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "disklabel"

    @classmethod
    def match(cls, data, device):
        is_multipath_member = (device.is_disk and
                               blockdev.mpath_is_mpath_member(device.path))

        # XXX ignore disklabels on multipath or biosraid member disks
        return (bool(udev.device_get_disklabel_type(data)) and
                not udev.device_is_biosraid_member(data) and
                not is_multipath_member and
                udev.device_get_format(data) != "iso9660")

    def _get_kwargs(self):
        kwargs = super()._get_kwargs()
        kwargs["uuid"] = udev.device_get_disklabel_uuid(self.data)
        return kwargs

    def run(self):
        disklabel_type = udev.device_get_disklabel_type(self.data)
        log_method_call(self, device=self.device.name, label_type=disklabel_type)
        # if there is no disklabel on the device
        # blkid doesn't understand dasd disklabels, so bypass for dasd
        if disklabel_type is None and not \
           (self.device.is_disk and udev.device_is_dasd(self.data)):
            log.debug("device %s does not contain a disklabel", self.device.name)
            return

        if self.device.partitioned:
            # this device is already set up
            log.debug("disklabel format on %s already set up", self.device.name)
            return

        try:
            self.device.setup()
        except Exception:  # pylint: disable=broad-except
            log_exception_info(log.warning,
                               "setup of %s failed, aborting disklabel handler",
                               [self.device.name])
            return

        kwargs = self._get_kwargs()

        # special handling for unsupported partitioned devices
        if not self.device.partitionable:
            try:
                fmt = formats.get_format("disklabel", **kwargs)
            except InvalidDiskLabelError:
                log.warning("disklabel detected but not usable on %s",
                            self.device.name)
            else:
                self.device.format = fmt
            return

        try:
            fmt = formats.get_format("disklabel", **kwargs)
        except InvalidDiskLabelError as e:
            log.info("no usable disklabel on %s", self.device.name)
            if disklabel_type == "gpt":
                log.debug(e)
                self.device.format = formats.get_format(_("Invalid Disk Label"))
        else:
            self.device.format = fmt
