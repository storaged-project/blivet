# mdraid.py
# Device format classes for anaconda's storage configuration module.
#
# Copyright (C) 2009  Red Hat, Inc.
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
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from ..storage_log import log_method_call
from parted import PARTITION_RAID
from . import DeviceFormat, register_device_format
from ..flags import flags
from ..i18n import N_
from ..tasks import availability

import logging
log = logging.getLogger("blivet")


class MDRaidMember(DeviceFormat):

    """ An mdraid member disk. """
    _type = "mdmember"
    _name = N_("software RAID")
    _udev_types = ["linux_raid_member"]
    parted_flag = PARTITION_RAID
    _formattable = True                 # can be formatted
    _supported = True                   # is supported
    _linux_native = True                 # for clearpart
    _packages = ["mdadm"]               # required packages
    _ks_mountpoint = "raid."
    _plugin = availability.BLOCKDEV_MDRAID_PLUGIN

    def __init__(self, **kwargs):
        """
            :keyword device: path to block device node
            :keyword uuid: this member device's uuid
            :keyword exists: whether this is an existing format
            :type exists: bool
            :keyword md_uuid: the uuid of the array this device belongs to

            .. note::

                The 'device' kwarg is required for existing formats.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)
        self.md_uuid = kwargs.get("md_uuid")

        self.biosraid = kwargs.get("biosraid")

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  md_uuid = %(md_uuid)s  biosraid = %(biosraid)s" %
              {"md_uuid": self.md_uuid, "biosraid": self.biosraid})
        return s

    @property
    def dict(self):
        d = super(MDRaidMember, self).dict
        d.update({"md_uuid": self.md_uuid, "biosraid": self.biosraid})
        return d

    @property
    def formattable(self):
        return super(MDRaidMember, self).formattable and self._plugin.available

    @property
    def supported(self):
        return super(MDRaidMember, self).supported and self._plugin.available

    def _destroy(self, **kwargs):
        blockdev.md.destroy(self.device)

    @property
    def destroyable(self):
        return self._plugin.available

    @property
    def status(self):
        # XXX hack -- we don't have a nice way to see if the array is active
        return False

    @property
    def hidden(self):
        return super(MDRaidMember, self).hidden or self.biosraid

    @property
    def container_uuid(self):
        return self.md_uuid

    @container_uuid.setter
    def container_uuid(self, uuid):
        self.md_uuid = uuid


# nodmraid -> Wether to use BIOS RAID or not
# Note the anaconda cmdline has not been parsed yet when we're first imported,
# so we can not use flags.dmraid here
if not flags.noiswmd and flags.dmraid:
    MDRaidMember._udev_types.append("isw_raid_member")


register_device_format(MDRaidMember)
