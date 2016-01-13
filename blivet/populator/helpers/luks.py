# populator/helpers/luks.py
# LUKS backend code for populating a DeviceTree.
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
from ...devices import LUKSDevice
from ...errors import DeviceError, LUKSError
from ...flags import flags
from .formatpopulator import FormatPopulator

import logging
log = logging.getLogger("blivet")


class LUKSFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "luks"

    def _get_kwargs(self):
        kwargs = super()._get_kwargs()
        kwargs["name"] = "luks-%s" % udev.device_get_uuid(self.data)
        return kwargs

    def run(self):
        super().run()
        if not self.device.format.uuid:
            log.info("luks device %s has no uuid", self.device.path)
            return

        # look up or create the mapped device
        if not self._devicetree.get_device_by_name(self.device.format.map_name):
            passphrase = self._devicetree._PopulatorMixin__luks_devs.get(self.device.format.uuid)
            if self.device.format.configured:
                pass
            elif passphrase:
                self.device.format.passphrase = passphrase
            elif self.device.format.uuid in self._devicetree._PopulatorMixin__luks_devs:
                log.info("skipping previously-skipped luks device %s",
                         self.device.name)
            elif self._devicetree._cleanup or flags.testing:
                # if we're only building the devicetree so that we can
                # tear down all of the devices we don't need a passphrase
                if self.device.format.status:
                    # this makes device.configured return True
                    self.device.format.passphrase = 'yabbadabbadoo'
            else:
                # Try each known passphrase. Include luks_devs values in case a
                # passphrase has been set for a specific device without a full
                # reset/populate, in which case the new passphrase would not be
                # in self.__passphrases.
                passphrases = self._devicetree._PopulatorMixin__passphrases + list(self._devicetree._PopulatorMixin__luks_devs.values())
                for passphrase in passphrases:
                    self.device.format.passphrase = passphrase
                    try:
                        self.device.format.setup()
                    except blockdev.BlockDevError:
                        self.device.format.passphrase = None
                    else:
                        break

            luks_device = LUKSDevice(self.device.format.map_name,
                                     parents=[self.device],
                                     exists=True)
            try:
                luks_device.setup()
            except (LUKSError, blockdev.CryptoError, DeviceError) as e:
                log.info("setup of %s failed: %s", self.device.format.map_name, e)
                self.device.remove_child(luks_device)
            else:
                luks_device.update_sysfs_path()
                self._devicetree._add_device(luks_device)
                luks_info = udev.get_device(luks_device.sysfs_path)
                if not luks_info:
                    log.error("failed to get udev data for %s", luks_device.name)
                    return

                self._devicetree.handle_device(luks_info, update_orig_fmt=True)
        else:
            log.warning("luks device %s already in the tree",
                        self.device.format.map_name)
