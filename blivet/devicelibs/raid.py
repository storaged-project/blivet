#
# raid.py
# representation of RAID levels
#
# Copyright (C) 2009  Red Hat, Inc.  All rights reserved.
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
# Author(s): Dave Lehman <dlehman@redhat.com>
#            Anne Mulhern <amulhern@redhat.com>
#

from ..errors import RaidError

def div_up(a,b):
    """Rounds up integer division."""
    return (a + (b - 1))/b

class RAIDLevel(object):

    """An abstract class which is the parent of classes which represent a
       RAID level. A better word would be classification, since 'level'
       implies an ordering, but level is the canonical word.

       The fields of the class are:
         _level --- A string containing the number that designates this level
         _min_members --- The minimum number of members required for this
           level to be sensibly used.
         _nick --- A single nickname for this level, may be None

        All methods in this class fall into these categories:
        1) May not be overrridden in any subclass.
        2) Are private methods that must be overridden in every subclass.
        3) Are special Python methods, e.g., __str__

        Note that each subclass in this file is instantiated immediately after
        it is defined, effectively yielding a singleton object of the class.
    """

    # FIELDS
    _level = None
    _min_members = None
    _nick = None

    # PROPERTIES
    level = property(lambda s: s._level,
       doc="A code representing the level")

    min_members = property(lambda s: s._min_members,
       doc="The minimum number of members required for this level")

    number = property(lambda s : int(s._level),
       doc="A numeric code for this level")

    name = property(lambda s : "raid" + s.level,
       doc="The canonical name for this level")

    nick = property(lambda s : s._nick,
       doc="A nickname for this level")

    alt_synth_names = property(lambda s : ["RAID" + s.level, s.level, s.number],
       doc="names that can be synthesized from level but are not name")

    names = property(lambda s :
       [n for n in [s.name] + [s.nick] + s.alt_synth_names if n is not None],
       doc="all valid names for this level")

    # METHODS
    def get_max_spares(self, member_count):
        """Return the maximum number of spares for this level given
           member_count participating members.
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        return self._get_max_spares(member_count)

    def _get_max_spares(self, member_count):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def get_base_member_size(self, size, member_count):
        """Return the required size for each member of the array for
           storing only data.
           :param size: size of data to be stored
           :type size: natural number

           :param member_count: number of members in this array
           :param member_count: int
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        if size < 0:
            raise RaidError("size is a negative number")
        return self._get_base_member_size(size, member_count)

    def _get_base_member_size(self, size, member_count):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def get_raw_array_size(self, member_count, smallest_member_size):
        """Calculate the raw arraysize, i.e., the number of MB available.
           :param member_count: the number of members in the array
           :param type: int
           :param smallest_member_size: the size (MB) of the smallest
             member of this array
           :param type: int
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        if smallest_member_size < 0:
            raise RaidError("size is a negative number")
        return self._get_raw_array_size(member_count, smallest_member_size)

    def _get_raw_array_size(self, member_count, smallest_member_size):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def get_size(self, member_count, smallest_member_size, chunk_size):
        size = self.get_raw_array_size(member_count, smallest_member_size)
        return self._get_size(size, chunk_size)

    def _get_size(self, size, chunk_size):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def get_recommended_stride(self, member_count):
        """Get a recommended stride size in blocks. Returns None if there
           is no recommended size.
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        return self._get_recommended_stride(member_count)

    def _get_recommended_stride(member_count):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def __str__(self):
        return self.name


class RAIDLevels(object):
    """A class which keeps track of registered RAID levels. This class
       may be extended, overriding the isRaid method to include any
       additional properties that a client of this package may require
       for its RAID levels.
    """

    def __init__(self, levels=True):
        """Add the specified standard levels to the levels in this object.
           If levels is True, add all standard levels. Else, levels
           must be a list of valid level descriptors of standard levels.
           Duplicate descriptors are ignored.
        """
        self._raid_levels = []
        if levels is False:
            pass
        elif levels is True:
            for l in self.standard_levels:
                self.addRaidLevel(l)
        else:
            try:
                for level in levels:
                    matches = [l for l in self.standard_levels if level in l.names]
                    if len(matches) != 1:
                        raise RaidError("invalid standard raid level descriptor %s" % level)
                    else:
                        self.addRaidLevel(matches[0])
            except TypeError:
                raise RaidError("levels must be a boolean or an iterable")


    _standard_levels = []

    standard_levels = property(lambda s: s._standard_levels,
       doc="any standard raid level classes defined in this package.")

    @classmethod
    def isRaidLevel(cls, level):
        """Return False if level does not satisfy minimum requirements for
           a RAID level.

           There must be at least one element in the names list, or the level
           will be impossible to look up by any string.

           The name must be defined; it should be one of the elements in the
           names list.

           All RAID objects in standard_levels are guaranteed to pass these
           minimum requirements.

           This method should not be overridden in any subclass so that it
           is so restrictive that a RAID object in standard_levels does
           not satisfy it.
        """
        try:
            name = level.names[0]
            name = level.name
            if name not in level.names:
                return False
        except (TypeError, AttributeError, IndexError):
            return False
        return True

    @classmethod
    def addRAIDLevelToStandardLevels(cls, level):
        """Adds this raid level to the internal list of standard raid levels
           defined in this package.
        """
        if not cls.isRaidLevel(level):
            raise RaidError('level is not a valid RAID level')
        if not level in cls._standard_levels:
            cls._standard_levels.append(level)

    def raidLevel(self, descriptor):
        """Return raid object corresponding to descriptor. Raises RaidError
           if no raid object can be found for this descriptor.
        """
        for level in self._raid_levels:
            if descriptor in level.names:
                return level
        raise RaidError("invalid raid level descriptor %s" % descriptor)

    def addRaidLevel(self, level):
        """Adds level to the list of levels if it is not already there.
           Raises a RaidError if it is not a valid level.
        """
        if not self.isRaidLevel(level):
            raise RaidError("level is not a valid RAID level")
        if not level in self._raid_levels:
            self._raid_levels.append(level)

class RAID0(RAIDLevel):
    _level = "0"
    _min_members = 2
    _nick = "stripe"

    def _get_max_spares(self, member_count):
        return 0

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count)

    def _get_raw_array_size(self, member_count, smallest_member_size):
        return member_count * smallest_member_size

    def _get_size(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return member_count * 16

RAID0 = RAID0()
RAIDLevels.addRAIDLevelToStandardLevels(RAID0)

class RAID1(RAIDLevel):
    _level = "1"
    _min_members = 2
    _nick = "mirror"

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return size

    def _get_raw_array_size(self, member_count, smallest_member_size):
        return smallest_member_size

    def _get_size(self, size, chunk_size):
        return size

    def _get_recommended_stride(self, member_count):
        return None

RAID1 = RAID1()
RAIDLevels.addRAIDLevelToStandardLevels(RAID1)

class RAID4(RAIDLevel):
    _level = "4"
    _min_members = 3
    _nick = None

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count - 1)

    def _get_raw_array_size(self, member_count, smallest_member_size):
        return (member_count - 1) * smallest_member_size

    def _get_size(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return (member_count - 1) * 16

RAID4 = RAID4()
RAIDLevels.addRAIDLevelToStandardLevels(RAID4)

class RAID5(RAIDLevel):
    _level = "5"
    _min_members = 3
    _nick = None

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, (member_count - 1))

    def _get_raw_array_size(self, member_count, smallest_member_size):
        return (member_count - 1) * smallest_member_size

    def _get_size(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return (member_count - 1) * 16

RAID5 = RAID5()
RAIDLevels.addRAIDLevelToStandardLevels(RAID5)

class RAID6(RAIDLevel):
    _level = "6"
    _min_members = 4
    _nick = None

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count - 2)

    def _get_raw_array_size(self, member_count, smallest_member_size):
        return (member_count - 2) * smallest_member_size

    def _get_size(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return None

RAID6 = RAID6()
RAIDLevels.addRAIDLevelToStandardLevels(RAID6)

class RAID10(RAIDLevel):
    _level = "10"
    _min_members = 4
    _nick = None

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, (member_count / 2))

    def _get_raw_array_size(self, member_count, smallest_member_size):
        return (member_count / 2) * smallest_member_size

    def _get_size(self, size, chunk_size):
        return size

    def _get_recommended_stride(self, member_count):
        return None

RAID10 = RAID10()
RAIDLevels.addRAIDLevelToStandardLevels(RAID10)
