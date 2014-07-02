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

import os

from ..storage_log import log_method_call
from parted import PARTITION_RAID
from ..errors import MDMemberError
from ..devicelibs import mdraid
from . import DeviceFormat, register_device_format
from ..flags import flags
from ..i18n import N_

import logging
log = logging.getLogger("blivet")


class MDRaidMember(DeviceFormat):
    """ An mdraid member disk. """
    _type = "mdmember"
    _name = N_("software RAID")
    _udevTypes = ["linux_raid_member"]
    partedFlag = PARTITION_RAID
    _formattable = True                 # can be formatted
    _supported = True                   # is supported
    _linuxNative = True                 # for clearpart
    _packages = ["mdadm"]               # required packages
    _ksMountpoint = "raid."

    def __init__(self, **kwargs):
        """
            :keyword device: path to block device node
            :keyword uuid: this member device's uuid
            :keyword exists: whether this is an existing format
            :type exists: bool
            :keyword mdUuid: the uuid of the array this device belongs to

            .. note::

                The 'device' kwarg is required for existing formats.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)
        self.mdUuid = kwargs.get("mdUuid")
        self.raidMinor = None

        #self.probe()
        self.biosraid = kwargs.get("biosraid")

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  mdUUID = %(mdUUID)s  biosraid = %(biosraid)s" %
              {"mdUUID": self.mdUuid, "biosraid": self.biosraid})
        return s

    @property
    def dict(self):
        d = super(MDRaidMember, self).dict
        d.update({"mdUUID": self.mdUuid, "biosraid": self.biosraid})
        return d

    def probe(self):
        """ Probe for any missing information about this format. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self.exists:
            raise MDMemberError("format does not exist")

        info = mdraid.mdexamine(self.device)
        if self.uuid is None:
            self.uuid = info['uuid']
        if self.raidMinor is None:
            self.raidMinor = info['mdMinor']

    def destroy(self, **kwargs):
        """ Remove the formatting from the associated block device.

            :raises: FormatDestroyError
            :returns: None.
        """
        if not self.exists:
            raise MDMemberError("format does not exist")

        if not os.access(self.device, os.W_OK):
            raise MDMemberError("device path does not exist")

        mdraid.mddestroy(self.device)
        self.exists = False

    @property
    def status(self):
        # XXX hack -- we don't have a nice way to see if the array is active
        return False

    @property
    def hidden(self):
        return (self._hidden or self.biosraid)

# nodmraid -> Wether to use BIOS RAID or not
# Note the anaconda cmdline has not been parsed yet when we're first imported,
# so we can not use flags.dmraid here
if not flags.noiswmd and flags.dmraid:
    MDRaidMember._udevTypes.append("isw_raid_member")

register_device_format(MDRaidMember)

