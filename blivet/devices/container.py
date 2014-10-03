# devices/container.py
#
# Copyright (C) 2009-2014  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

import abc

from six import add_metaclass

from .. import errors
from ..storage_log import log_method_call
from ..formats import get_device_format_class

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice

@add_metaclass(abc.ABCMeta)
class ContainerDevice(StorageDevice):
    """ A device that aggregates a set of member devices.

        The only interfaces provided by this class are for addition and removal
        of member devices -- one set for modifying the member set of the
        python objects, and one for writing the changes to disk.

        The member set of the instance can be manipulated using the methods
        :meth:`~.ParentList.append` and :meth:`~.ParentList.remove` of the
        instance's :attr:`~.Device.parents` attribute.

        :meth:`add` and :meth:`remove` remove a member from the container's on-
        disk representation. These methods should normally only be called from
        within :meth:`.deviceaction.ActionAddMember.execute` and
        :meth:`.deviceaction.ActionRemoveMember.execute`.
    """

    _formatClassName = abc.abstractproperty(lambda s: None,
        doc="The type of member devices' required format")
    _formatUUIDAttr = abc.abstractproperty(lambda s: None,
        doc="The container UUID attribute in the member format class")

    def __init__(self, *args, **kwargs):
        self.formatClass = get_device_format_class(self._formatClassName)
        if not self.formatClass:
            raise errors.StorageError("cannot find '%s' class" % self._formatClassName)

        super(ContainerDevice, self).__init__(*args, **kwargs)

    def _addParent(self, member):
        """ Add a member device to the container.

            :param member: the member device to add
            :type member: :class:`.StorageDevice`

            This operates on the in-memory model and does not alter disk
            contents at all.
        """
        log_method_call(self, self.name, member=member.name)
        if not isinstance(member.format, self.formatClass):
            raise ValueError("member has wrong format")

        if member.format.exists and self.uuid and self._formatUUIDAttr and \
           getattr(member.format, self._formatUUIDAttr) != self.uuid:
            raise ValueError("cannot add member with mismatched UUID")

        super(ContainerDevice, self)._addParent(member)

    @abc.abstractmethod
    def _add(self, member):
        """ Device-type specific code to add a member to the container.

            :param member: the member device to add
            :type member: :class:`.StorageDevice`

            This method writes the member addition to disk.
        """
        raise NotImplementedError()

    def add(self, member):
        """ Add a member to the container.

            :param member: the member device to add
            :type member: :class:`.StorageDevice`

            This method writes the member addition to disk.
        """
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if member.format.exists and self.uuid and self._formatUUIDAttr and \
           getattr(member.format, self._formatUUIDAttr) == self.uuid:
            log.error("cannot re-add member: %s", member)
            raise ValueError("cannot add members that are already part of the container")

        self._add(member)

        if member not in self.parents:
            self.parents.append(member)

    @abc.abstractmethod
    def _remove(self, member):
        """ Device-type specific code to remove a member from the container.

            :param member: the member device to remove
            :type member: :class:`.StorageDevice`

            This method writes the member removal to disk.
        """
        raise NotImplementedError()

    def remove(self, member):
        """ Remove a member from the container.

            :param member: the member device to remove
            :type member: :class:`.StorageDevice`

            This method writes the member removal to disk.
        """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        if self._formatUUIDAttr and self.uuid and \
           getattr(member.format, self._formatUUIDAttr) != self.uuid:
            log.error("cannot remove non-member: %s (%s/%s)", member, getattr(member.format, self._formatUUIDAttr), self.uuid)
            raise ValueError("cannot remove members that are not part of the container")

        self._remove(member)

        if member in self.parents:
            self.parents.remove(member)
