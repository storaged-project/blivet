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

import abc

from ..errors import RaidError

def div_up(a,b):
    """Rounds up integer division.  For example, div_up(3, 2) is 2.

       :param int a: the dividend
       :param int b: the divisor
    """
    return (a + (b - 1))//b

class RAIDLevel(object):

    """An abstract class which is the parent of classes which represent a
       RAID level. A better word would be classification, since 'level'
       implies an ordering, but level is the canonical word.

       The abstract properties of the class are:

       - level: A string containing the number that designates this level

       - min_members: The minimum number of members required for this
           level to be sensibly used.

       - nick: A single nickname for this level, may be None

        All methods in this class fall into these categories:

        1) May not be overrridden in any subclass.

        2) Are private abstract methods.

        3) Are special Python methods, e.g., __str__


        Note that each subclass in this file is instantiated immediately after
        it is defined and using the same name, effectively yielding a
        singleton object of the class.
    """

    __metaclass__ = abc.ABCMeta

    # ABSTRACT PROPERTIES
    level = abc.abstractproperty(doc="A code representing the level")

    min_members = abc.abstractproperty(
       doc="The minimum number of members required for this level")

    nick = abc.abstractproperty(doc="A nickname for this level")

    # PROPERTIES
    number = property(lambda s : int(s.level),
       doc="A numeric code for this level")

    name = property(lambda s : "raid" + s.level,
       doc="The canonical name for this level")

    alt_synth_names = property(lambda s : ["RAID" + s.level, s.level, s.number],
       doc="names that can be synthesized from level but are not name")

    names = property(lambda s :
       [n for n in [s.name] + [s.nick] + s.alt_synth_names if n is not None],
       doc="all valid names for this level")

    # METHODS
    def get_max_spares(self, member_count):
        """The maximum number of spares for this level.

           :param int member_count: the number of members belonging to the array
           :rtype: int

           Raiess a RaidError if member_count is fewer than the minimum
           number of members required for this level.
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        return self._get_max_spares(member_count)

    @abc.abstractmethod
    def _get_max_spares(self, member_count):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def get_base_member_size(self, size, member_count):
        """The required size for each member of the array for
           storing only data.

           :param size: size of data to be stored
           :type size: :class:`~.size.Size`
           :param int member_count: number of members in this array
           :rtype: :class:`~.size.Size`

           Raises a RaidError if member_count is fewer than the minimum
           number of members required for this array or if size is less
           than 0.
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        if size < 0:
            raise RaidError("size is a negative number")
        return self._get_base_member_size(size, member_count)

    @abc.abstractmethod
    def _get_base_member_size(self, size, member_count):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def get_net_array_size(self, member_count, smallest_member_size):
        """Return the space, essentially the number of bits available
           for storage. This value is generally a function of the
           smallest member size. If the smallest member size represents
           the amount of data that can be stored on the smallest member,
           then the result will represent the amount of data that can be
           stored on the array. If the smallest member size represents
           both data and metadata, then the result will represent the
           available space in the array for both data and metadata.

           :param int member_count: the number of members in the array
           :param smallest_member_size: the size of the smallest
             member of this array
           :type smallest_member_size: :class:`~.size.Size`
           :returns: the array size
           :rtype: :class:`~.size.Size`

           Raises a RaidError if member_count is fewer than the minimum
           number of members required for this array or if size is less
           than 0.
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        if smallest_member_size < 0:
            raise RaidError("size is a negative number")
        return self._get_net_array_size(member_count, smallest_member_size)

    @abc.abstractmethod
    def _get_net_array_size(self, member_count, smallest_member_size):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    @abc.abstractmethod
    def _trim(self, size, chunk_size):
        """Helper function; not to be called directly.

           Trims size to the largest size that the level allows based on the
           chunk_size.

           :param size: the size of the array
           :type size: :class:`~.size.Size`
           :param chunk_size: the smallest unit of size this array allows
           :type chunk_size: :class:`~.size.Size`
           :rtype: :class:`~.size.Size`
        """
        raise NotImplementedError()

    def get_recommended_stride(self, member_count):
        """Return a recommended stride size in blocks.

           Returns None if there is no recommended size.

           :param int member_count: the number of members in the array
           :rtype: int or None

           Raises a RaidError if member_count is fewer than the
           minimum number of members required for this level
        """
        if member_count < self.min_members:
            raise RaidError("%s requires at least %d disks" % (self.name, self.min_members))
        return self._get_recommended_stride(member_count)

    @abc.abstractmethod
    def _get_recommended_stride(self, member_count):
        """Helper function; not to be called directly."""
        raise NotImplementedError()

    def get_size(self, member_sizes, num_members=None, chunk_size=None, superblock_size_func=None):
        """Estimate the amount of data that can be stored on this array.

           :param member_size: a list of the sizes of members of this array
           :type member_size: list of :class:`~.size.Size`
           :param int num_members: the number of members in the array
           :param chunk_size: the smallest unit of size for
           :type chunk_size: :class:`~.size.Size`
           :param superblock_size_func: a function that estimates the
              superblock size for this array
           :type superblock_size_func: a function from :class:`~.size.Size` to
              :class:`~.size.Size`
           :returns: an estimate of the amount of data that can be stored on
              this array
           :rtype: :class:`~.size.Size`

           Note that the number of members in the array may not be the same
           as the length of member_sizes if the array is still
           under construction.
        """
        if not member_sizes:
            return 0

        if num_members is None:
            num_members = len(member_sizes)

        if chunk_size is None or chunk_size == 0:
            raise RaidError("chunk_size parameter value %s is not acceptable")

        if superblock_size_func is None:
            raise RaidError("superblock_size_func value of None is not acceptable")

        min_size = min(member_sizes)
        total_space = self.get_net_array_size(num_members, min_size)
        superblock_size = superblock_size_func(total_space)
        min_data_size = min_size - superblock_size
        total_data_size = self.get_net_array_size(num_members, min_data_size)
        return self._trim(total_data_size, chunk_size)

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

           :param levels: the standard levels to be added to this object
           :type levels: bool or a list of valid RAID level descriptors

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
                        raise RaidError("invalid standard RAID level descriptor %s" % level)
                    else:
                        self.addRaidLevel(matches[0])
            except TypeError:
                raise RaidError("levels must be a boolean or an iterable")


    _standard_levels = []

    standard_levels = property(lambda s: s._standard_levels,
       doc="any standard RAID level classes defined in this package.")

    @classmethod
    def isRaidLevel(cls, level):
        """Return False if level does not satisfy minimum requirements for
           a RAID level, otherwise return True.

           :param object level: an object representing a RAID level

           There must be at least one element in the names list, or the level
           will be impossible to look up by any string.

           The name property must be defined; it should be one of the
           elements in the names list.

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
        """Adds this RAID level to the internal list of standard RAID levels
           defined in this package.

           :param level: an object representing a RAID level
           :type level: object

           Raises a RaidError if level is not a valid RAID level.

           Does not allow duplicate level objects.
        """
        if not cls.isRaidLevel(level):
            raise RaidError('level is not a valid RAID level')
        if not level in cls._standard_levels:
            cls._standard_levels.append(level)

    def raidLevel(self, descriptor):
        """Return RAID object corresponding to descriptor.

           :param object descriptor: a RAID level descriptor

           Raises a RaidError if no RAID object can be found for this
           descriptor.
        """
        for level in self._raid_levels:
            if descriptor in level.names:
                return level
        raise RaidError("invalid RAID level descriptor %s" % descriptor)

    def addRaidLevel(self, level):
        """Adds level to the list of levels if it is not already there.

           :param object level: an object representing a RAID level

           Raises a RaidError if level is not valid.

           Does not allow duplicate level objects.
        """
        if not self.isRaidLevel(level):
            raise RaidError("level is not a valid RAID level")
        if not level in self._raid_levels:
            self._raid_levels.append(level)

    def __iter__(self):
        return iter(self._raid_levels)

class RAID0(RAIDLevel):

    level = property(lambda s: "0")
    min_members = property(lambda s: 2)
    nick = property(lambda s: "stripe")

    def _get_max_spares(self, member_count):
        return 0

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count)

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * member_count

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return member_count * 16

RAID0 = RAID0()
RAIDLevels.addRAIDLevelToStandardLevels(RAID0)

class RAID1(RAIDLevel):
    level = property(lambda s: "1")
    min_members = property(lambda s: 2)
    nick = property(lambda s: "mirror")

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return size

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size

    def _trim(self, size, chunk_size):
        return size

    def _get_recommended_stride(self, member_count):
        return None

RAID1 = RAID1()
RAIDLevels.addRAIDLevelToStandardLevels(RAID1)

class RAID4(RAIDLevel):
    level = property(lambda s: "4")
    min_members = property(lambda s: 3)
    nick = property(lambda s: None)

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count - 1)

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count - 1)

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return (member_count - 1) * 16

RAID4 = RAID4()
RAIDLevels.addRAIDLevelToStandardLevels(RAID4)

class RAID5(RAIDLevel):
    level = property(lambda s: "5")
    min_members = property(lambda s: 3)
    nick = property(lambda s: None)

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, (member_count - 1))

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count - 1)

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return (member_count - 1) * 16

RAID5 = RAID5()
RAIDLevels.addRAIDLevelToStandardLevels(RAID5)

class RAID6(RAIDLevel):
    level = property(lambda s: "6")
    min_members = property(lambda s: 4)
    nick = property(lambda s: None)

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count - 2)

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count - 2)

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _get_recommended_stride(self, member_count):
        return None

RAID6 = RAID6()
RAIDLevels.addRAIDLevelToStandardLevels(RAID6)

class RAID10(RAIDLevel):
    level = property(lambda s: "10")
    min_members = property(lambda s: 4)
    nick = property(lambda s: None)

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, (member_count // 2))

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count // 2)

    def _trim(self, size, chunk_size):
        return size

    def _get_recommended_stride(self, member_count):
        return None

RAID10 = RAID10()
RAIDLevels.addRAIDLevelToStandardLevels(RAID10)
