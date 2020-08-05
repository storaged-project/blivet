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

from six import add_metaclass

from ..errors import RaidError
from ..size import Size


def div_up(a, b):
    """Rounds up integer division.  For example, div_up(3, 2) is 2.

       :param int a: the dividend
       :param int b: the divisor
    """
    return (a + (b - 1)) // b


@add_metaclass(abc.ABCMeta)
class RAIDLevel(object):

    """An abstract class which is the parent of all classes which represent
       a RAID level.

       It ensures that RAIDLevel objects will really be singleton objects
       by overriding copy methods.
    """

    name = abc.abstractproperty(doc="The canonical name for this level")
    names = abc.abstractproperty(doc="List of recognized names for this level.")
    min_members = abc.abstractproperty(doc="The minimum number of members required to make a fully functioning array.")

    @abc.abstractmethod
    def has_redundancy(self):
        """ Whether this RAID level incorporates inherent redundancy.

            Note that for some RAID levels, the notion of redundancy is
            meaningless.

            :rtype: boolean
            :returns: True if this RAID level has inherent redundancy
        """
        raise NotImplementedError()

    is_uniform = abc.abstractproperty(doc="Whether data is uniformly distributed across all devices.")

    def __str__(self):
        return self.name

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        # pylint: disable=unused-argument
        return self


@add_metaclass(abc.ABCMeta)
class RAIDn(RAIDLevel):

    """An abstract class which is the parent of classes which represent a
       numeric RAID level. A better word would be classification, since 'level'
       implies an ordering, but level is the canonical word.

       The abstract properties of the class are:

       - level: A string containing the number that designates this level

       - nick: A single nickname for this level, may be None

        All methods in this class fall into these categories:

        1) May not be overrridden in any subclass.

        2) Are private abstract methods.

        3) Are special Python methods, e.g., __str__


        Note that each subclass in this file is instantiated immediately after
        it is defined and using the same name, effectively yielding a
        singleton object of the class.
    """

    # ABSTRACT PROPERTIES
    level = abc.abstractproperty(doc="A code representing the level")
    nick = abc.abstractproperty(doc="A nickname for this level")

    # PROPERTIES
    is_uniform = property(lambda s: True)

    number = property(lambda s: int(s.level),
                      doc="A numeric code for this level")

    name = property(lambda s: "raid" + s.level,
                    doc="The canonical name for this level")

    alt_synth_names = property(lambda s: ["RAID" + s.level, s.level, s.number],
                               doc="names that can be synthesized from level but are not name")

    names = property(lambda s:
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
        if smallest_member_size < Size(0):
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

    @abc.abstractmethod
    def _pad(self, size, chunk_size):
        """Helper function; not to be called directly.

           Pads size to the smallest size greater than size that is in units
           of chunk_size.

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
           :param chunk_size: the smallest unit of size read or written
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
            return Size(0)

        if num_members is None:
            num_members = len(member_sizes)

        if chunk_size is None or chunk_size == Size(0):
            raise RaidError("chunk_size parameter value %s is not acceptable")

        if superblock_size_func is None:
            raise RaidError("superblock_size_func value of None is not acceptable")

        min_size = min(member_sizes)
        superblock_size = superblock_size_func(min_size)
        min_data_size = self._trim(min_size - superblock_size, chunk_size)
        return self.get_net_array_size(num_members, min_data_size)

    def get_space(self, size, num_members, chunk_size=None, superblock_size_func=None):
        """Estimate the amount of memory required by this array, including
           memory allocated for metadata.

           :param size: the amount of data on this array
           :type size: :class:`~.size.Size`
           :param int num_members: the number of members in the array
           :param chunk_size: the smallest unit of size read or written
           :type chunk_size: :class:`~.size.Size`
           :param superblock_size_func: a function that estimates the
              superblock size for this array
           :type superblock_size_func: a function from :class:`~.size.Size` to
              :class:`~.size.Size`
           :returns: an estimate of the memory required, including metadata
           :rtype: :class:`~.size.Size`
        """
        if superblock_size_func is None:
            raise RaidError("superblock_size_func value of None is not acceptable")

        size_per_member = self.get_base_member_size(size, num_members)
        size_per_member += superblock_size_func(size)
        if chunk_size is not None:
            size_per_member = self._pad(size_per_member, chunk_size)
        return size_per_member * num_members


class RAIDLevels(object):

    """A class which keeps track of registered RAID levels. This class
       may be extended, overriding the is_raid method to include any
       additional properties that a client of this package may require
       for its RAID levels.
    """

    def __init__(self, levels=None):
        """Add the specified standard levels to the levels in this object.

           :param levels: the levels to be added to this object
           :type levels: list of valid RAID level descriptors

           If levels is True, add all standard levels. Else, levels
           must be a list of valid level descriptors of standard levels.
           Duplicate descriptors are ignored.
        """
        levels = levels or []
        self._raid_levels = set()
        for level in levels:
            matches = [l for l in ALL_LEVELS if level in l.names]
            if len(matches) != 1:
                raise RaidError("invalid standard RAID level descriptor %s" % level)
            else:
                self.add_raid_level(matches[0])

    @classmethod
    def is_raid_level(cls, level):
        """Return False if level does not satisfy minimum requirements for
           a RAID level, otherwise return True.

           :param object level: an object representing a RAID level

           There must be at least one element in the names list, or the level
           will be impossible to look up by any string.

           The name property must be defined; it should be one of the
           elements in the names list.

           All RAID objects that extend RAIDlevel are guaranteed to pass these
           minimum requirements.

           This method should not be overridden in any subclass so that it
           is so restrictive that a RAIDlevel object does not satisfy it.
        """
        return len(level.names) > 0 and level.name in level.names

    def raid_level(self, descriptor):
        """Return RAID object corresponding to descriptor.

           :param object descriptor: a RAID level descriptor

           Note that descriptor may be any object that identifies a
           RAID level, including the RAID object itself.

           Raises a RaidError if no RAID object can be found for this
           descriptor.
        """
        for level in self._raid_levels:
            if descriptor in level.names or descriptor is level:
                return level
        raise RaidError("invalid RAID level descriptor %s" % descriptor)

    def add_raid_level(self, level):
        """Adds level to levels if it is not already there.

           :param object level: an object representing a RAID level

           Raises a RaidError if level is not valid.

           Does not allow duplicate level objects.
        """
        if not self.is_raid_level(level):
            raise RaidError("level is not a valid RAID level")
        self._raid_levels.add(level)

    def __iter__(self):
        return iter(self._raid_levels)


ALL_LEVELS = RAIDLevels()


class RAID0(RAIDn):

    level = property(lambda s: "0")
    min_members = property(lambda s: 2)
    nick = property(lambda s: "stripe")

    def has_redundancy(self):
        return False

    def _get_max_spares(self, member_count):
        return 0

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count)

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * member_count

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _pad(self, size, chunk_size):
        return size + (chunk_size - (size % chunk_size)) % chunk_size

    def _get_recommended_stride(self, member_count):
        return member_count * 16


class Striped(RAID0):
    """ subclass with canonical lvm name """
    name = 'striped'
    names = [name]


RAID0 = RAID0()
ALL_LEVELS.add_raid_level(RAID0)
Striped = Striped()
ALL_LEVELS.add_raid_level(Striped)


class RAID1(RAIDn):
    level = property(lambda s: "1")
    min_members = property(lambda s: 2)
    nick = property(lambda s: "mirror")

    def has_redundancy(self):
        return True

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return size

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size

    def _trim(self, size, chunk_size):
        return size

    def _pad(self, size, chunk_size):
        return size

    def _get_recommended_stride(self, member_count):
        return None


RAID1 = RAID1()
ALL_LEVELS.add_raid_level(RAID1)


class RAID4(RAIDn):
    level = property(lambda s: "4")
    min_members = property(lambda s: 3)
    nick = property(lambda s: None)

    def has_redundancy(self):
        return True

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count - 1)

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count - 1)

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _pad(self, size, chunk_size):
        return size + (chunk_size - (size % chunk_size)) % chunk_size

    def _get_recommended_stride(self, member_count):
        return (member_count - 1) * 16


RAID4 = RAID4()
ALL_LEVELS.add_raid_level(RAID4)


class RAID5(RAIDn):
    level = property(lambda s: "5")
    min_members = property(lambda s: 3)
    nick = property(lambda s: None)

    def has_redundancy(self):
        return True

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, (member_count - 1))

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count - 1)

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _pad(self, size, chunk_size):
        return size + (chunk_size - (size % chunk_size)) % chunk_size

    def _get_recommended_stride(self, member_count):
        return (member_count - 1) * 16


RAID5 = RAID5()
ALL_LEVELS.add_raid_level(RAID5)


class RAID6(RAIDn):
    level = property(lambda s: "6")
    min_members = property(lambda s: 4)
    nick = property(lambda s: None)

    def has_redundancy(self):
        return True

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, member_count - 2)

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count - 2)

    def _trim(self, size, chunk_size):
        return size - size % chunk_size

    def _pad(self, size, chunk_size):
        return size + (chunk_size - (size % chunk_size)) % chunk_size

    def _get_recommended_stride(self, member_count):
        return None


RAID6 = RAID6()
ALL_LEVELS.add_raid_level(RAID6)


class RAID10(RAIDn):
    level = property(lambda s: "10")
    min_members = property(lambda s: 4)
    nick = property(lambda s: None)

    def has_redundancy(self):
        return True

    def _get_max_spares(self, member_count):
        return member_count - self.min_members

    def _get_base_member_size(self, size, member_count):
        return div_up(size, (member_count // 2))

    def _get_net_array_size(self, member_count, smallest_member_size):
        return smallest_member_size * (member_count // 2)

    def _trim(self, size, chunk_size):
        return size

    def _pad(self, size, chunk_size):
        return size + (chunk_size - (size % chunk_size)) % chunk_size

    def _get_recommended_stride(self, member_count):
        return None


RAID10 = RAID10()
ALL_LEVELS.add_raid_level(RAID10)


class Container(RAIDLevel):
    name = "container"
    names = [name]
    min_members = 1
    nick = property(lambda s: None)
    is_uniform = property(lambda s: False)

    def has_redundancy(self):
        raise RaidError("redundancy is not a concept that applies to containers")

    def get_max_spares(self, member_count):
        # pylint: disable=unused-argument
        raise RaidError("get_max_spares is not defined for level container")

    def get_space(self, size, num_members, chunk_size=None, superblock_size_func=None):
        # pylint: disable=unused-argument
        return size

    def get_recommended_stride(self, member_count):
        # pylint: disable=unused-argument
        raise RaidError("get_recommended_stride is not defined for level container")

    def get_size(self, member_sizes, num_members=None, chunk_size=None, superblock_size_func=None):
        # pylint: disable=unused-argument
        return sum(member_sizes, Size(0))


Container = Container()
ALL_LEVELS.add_raid_level(Container)


class ErsatzRAID(RAIDLevel):

    """ A superclass for a raid level which is not really a raid level at
        all, just a bunch of block devices of possibly differing sizes
        thrown together. This concept has different names depending on where
        it crops up. btrfs's name is single, lvm's is linear. Consequently,
        this abstract class implements all the functionality, but there are
        distinct subclasses which have different names.
    """
    min_members = 1
    nick = property(lambda s: None)
    is_uniform = property(lambda s: False)

    def has_redundancy(self):
        return False

    def get_max_spares(self, member_count):
        return member_count - self.min_members

    def get_space(self, size, num_members, chunk_size=None, superblock_size_func=None):
        # pylint: disable=unused-argument
        if superblock_size_func is None:
            raise RaidError("superblock_size_func value of None is not acceptable")
        return size + num_members * superblock_size_func(size)

    def get_recommended_stride(self, member_count):
        # pylint: disable=unused-argument
        return None

    def get_size(self, member_sizes, num_members=None, chunk_size=None, superblock_size_func=None):
        # pylint: disable=unused-argument
        if not member_sizes:
            return Size(0)

        if superblock_size_func is None:
            raise RaidError("superblock_size_func value of None is not acceptable")

        total_space = sum(member_sizes, Size(0))
        superblock_size = superblock_size_func(total_space)
        return total_space - len(member_sizes) * superblock_size


class Linear(ErsatzRAID):

    """ subclass with canonical lvm name """
    name = 'linear'
    names = [name, 'jbod']


Linear = Linear()
ALL_LEVELS.add_raid_level(Linear)


class Single(ErsatzRAID):

    """ subclass with canonical btrfs name. """
    name = 'single'
    names = [name]


Single = Single()
ALL_LEVELS.add_raid_level(Single)


class Dup(RAIDLevel):

    """ A RAID level which expresses one way btrfs metadata may be distributed.

        For this RAID level, duplication occurs within a single block device.
    """
    name = 'dup'
    names = [name]
    min_members = 1
    nick = property(lambda s: None)
    is_uniform = property(lambda s: False)

    def has_redundancy(self):
        return True


Dup = Dup()
ALL_LEVELS.add_raid_level(Dup)


def get_raid_level(descriptor):
    """ Convenience function to return a RAID level for the descriptor.

        :param object descriptor: a RAID level descriptor
        :rtype: RAIDLevel
        :returns: The RAIDLevel object for this descriptor

        Note that descriptor may be any object that identifies a
        RAID level, including the RAID object itself.

        Raises a RaidError is there is no RAID object for the descriptor.
    """
    return ALL_LEVELS.raid_level(descriptor)
