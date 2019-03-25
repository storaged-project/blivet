# devices/raid.py
#
# Copyright (C) 2014  Red Hat, Inc.
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
# Red Hat Author(s): Anne Mulhern <amulhern@redhat.com>
#

import abc

from six import add_metaclass

from .. import errors
from ..i18n import _, P_
from ..threads import SynchronizedABCMeta

from .storage import StorageDevice


@add_metaclass(SynchronizedABCMeta)
class RaidDevice(StorageDevice):

    """ Metaclass for devices that support RAID in some form. """
    members = abc.abstractproperty(lambda s: [],
                                   doc="A list of the member device instances")

    def _validate_raid_level(self, level, parent_diff=0):
        """ Returns an error message if the RAID level is invalid for this
            device, otherwise None.

            :param level: a RAID level
            :type level: :class:`~.devicelibs.raid.RAIDLevel`
            :param int parent_diff: number of parents being removed or added
            :returns: an error message if the RAID level is invalid, else None
            :rtype: str or NoneType

            The default number of parents being removed or added is 0,
            indicating that the level is to be checked against the current
            number of parents. The number is positive for added parents,
            negative for removed parents.
        """
        num_members = len(self.members) + parent_diff  # pylint: disable=no-member
        if not self.exists and num_members < level.min_members:
            message = P_(
                "RAID level %(raid_level)s requires that device have at least %(min_members)d member.",
                "RAID level %(raid_level)s requires that device have at least %(min_members)d members.",
                level.min_members
            )
            return message % {"raid_level": level, "min_members": level.min_members}
        return None

    def _get_level(self, value, levels):
        """ Obtains a valid level for the allowed set of levels.

            :param value: a RAID level
            :type value: a valid RAID level descriptor
            :param levels: a list of valid levels
            :type levels: :class:`~.devicelibs.raid.RAIDLevels`
            :returns: a valid RAID level
            :rtype: :class:`~.devicelibs.raid.RAIDLevel`
            :raises ValueError: if invalid RAID level
        """
        try:
            level = levels.raid_level(value)
        except errors.RaidError:
            message = _("RAID level %(raid_level)s is an invalid value. Must be one of (%(levels)s).")
            choices = ", ".join([str(l) for l in levels])
            raise ValueError(message % {"raid_level": value, "levels": choices})

        error_msg = self._validate_raid_level(level)
        if error_msg:
            raise ValueError(error_msg)

        return level

    def _validate_parent_removal(self, level, parent):
        """ Check if it is possible to remove a parent from this device.

            :param level: a RAID level
            :type level: :class:`~.devicelibs.raid.RAIDLevel`
            :param parent: the parent to be removed
            :type parent: :class:`~.devices.StorageDevice`
            :returns: An error message if there is a problem
            :rtype: str or None
        """
        # If this is a raid array that is not actually redundant and it
        # appears to have formatting and therefore probably data on it,
        # removing one of its devices is a bad idea.
        try:
            if not level.has_redundancy() and self.exists and parent.format.exists:
                return _("Cannot remove a member from existing %s array") % level
        except errors.RaidError:
            # If the concept of redundancy is meaningless for this device's
            # raid level, then it is OK to remove a parent device.
            pass

        # Removing a member may invalidate the RAID level
        return self._validate_raid_level(level, -1)
