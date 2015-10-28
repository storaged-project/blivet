# dmraid.py
# dmraid device formats
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

from ..storage_log import log_method_call
from ..flags import flags
from ..errors import DMRaidMemberError
from ..i18n import N_
from . import DeviceFormat, register_device_format

import logging
log = logging.getLogger("blivet")


class DMRaidMember(DeviceFormat):

    """ A dmraid member disk. """
    _type = "dmraidmember"
    _name = N_("dm-raid member device")
    # XXX This looks like trouble.
    #
    #     Maybe a better approach is a RaidMember format with subclass
    #     for MDRaidMember, letting all *_raid_member types fall through
    #     to the generic RaidMember format, which is basically read-only.
    #
    #     One problem that presents is the possibility of someone passing
    #     a dmraid member to the MDRaidArrayDevice constructor.
    _udev_types = ["adaptec_raid_member", "ddf_raid_member",
                   "hpt37x_raid_member", "hpt45x_raid_member",
                   "isw_raid_member",
                   "jmicron_raid_member", "lsi_mega_raid_member",
                   "nvidia_raid_member", "promise_fasttrack_raid_member",
                   "silicon_medley_raid_member", "via_raid_member"]
    _supported = True                   # is supported
    _packages = ["dmraid"]              # required packages
    _hidden = True                      # hide devices with this formatting?

    def __init__(self, **kwargs):
        """
                :keyword device: path to the underlying device (required)
                :type device: str
                :keyword uuid: this format's UUID
                :type uuid: str
                :keyword exists: whether this is an existing format
                :type exists: bool

        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        # Initialize the attribute that will hold the block object.
        self._raidmem = None

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  raidmem = %(raidmem)r" % {"raidmem": self.raidmem})
        return s

    def _get_raidmem(self):
        return self._raidmem

    def _set_raidmem(self, raidmem):
        self._raidmem = raidmem

    raidmem = property(lambda d: d._get_raidmem(),
                       lambda d, r: d._set_raidmem(r))

    def create(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        raise DMRaidMemberError("creation of dmraid members is non-sense")

    def destroy(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        raise DMRaidMemberError("destruction of dmraid members is non-sense")


if not flags.noiswmd:
    DMRaidMember._udev_types.remove("isw_raid_member")

# The anaconda cmdline has not been parsed yet when we're first imported,
# so we can not use flags.dmraid here
if not flags.dmraid:
    DMRaidMember._udev_types = []

register_device_format(DMRaidMember)
