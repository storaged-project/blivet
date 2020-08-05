#
# Copyright (C) 2016  Red Hat, Inc.
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
# Red Hat Author(s): Vratislav Podzimek <vpodzime@redhat.com>
#

import os
import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")

from ..tasks import availability


class MpathMembers(object):
    """A cache for querying multipath member devices"""

    def __init__(self):
        self._members = None

    def is_mpath_member(self, device):
        """Checks if the given device is a member of some multipath mapping or not.

        :param str device: path of the device to query

        """
        if self._members is None:
            if availability.BLOCKDEV_MPATH_PLUGIN.available:
                self._members = set(blockdev.mpath.get_mpath_members())
            else:
                self._members = set()

        device = os.path.realpath(device)
        device = device[len("/dev/"):]

        return device in self._members

    def update_cache(self, device):
        """Update the cache with the given device (checks and adds it is an mpath member)

        :param str device: path of the device to check and add

        """
        device = os.path.realpath(device)
        device = device[len("/dev/"):]

        if availability.BLOCKDEV_MPATH_PLUGIN.available and blockdev.mpath.is_mpath_member(device):
            self._members.add(device)

    def drop_cache(self):
        self._members = None


mpath_members = MpathMembers()
