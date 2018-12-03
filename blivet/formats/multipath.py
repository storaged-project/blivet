# multipath.py
# multipath device formats
#
# Copyright (C) 2009  Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Any Red Hat trademarks that are incorporated in the source code or
# documentation are not subject to the GNU General Public License and
# may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Peter Jones <pjones@redhat.com>
#

from ..storage_log import log_method_call
from ..errors import MultipathMemberError
from ..i18n import N_
from . import DeviceFormat, register_device_format

import logging
log = logging.getLogger("blivet")


class MultipathMember(DeviceFormat):

    """ A multipath member disk. """
    _type = "multipath_member"
    _name = N_("multipath member device")
    _udev_types = ["mpath_member"]
    _supported = True                   # is supported
    _packages = ["device-mapper-multipath"]  # required packages
    _hidden = True                      # hide devices with this formatting?

    def __init__(self, **kwargs):
        """
            :keyword device: path to the underlying device (required)
            :keyword uuid: this format's UUID
            :keyword exists: whether this is an existing format
            :type exists: bool
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        # Initialize the attribute that will hold the block object.
        self._member = None

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  member = %(member)r" % {"member": self.member})
        return s

    def _get_member(self):
        return self._member

    def _set_member(self, member):
        self._member = member

    member = property(lambda s: s._get_member(),
                      lambda s, m: s._set_member(m))

    def create(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        raise MultipathMemberError("creation of multipath members is non-sense")

    def destroy(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        raise MultipathMemberError("destruction of multipath members is non-sense")


register_device_format(MultipathMember)
