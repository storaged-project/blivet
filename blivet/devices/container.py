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
from ..threads import SynchronizedABCMeta

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice


@add_metaclass(SynchronizedABCMeta)
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

    _format_class_name = abc.abstractproperty(lambda s: None,
                                              doc="The type of member devices' required format")
    _format_uuid_attr = abc.abstractproperty(lambda s: None,
                                             doc="The container UUID attribute in the member format class")

    def __init__(self, *args, **kwargs):
        self.format_class = get_device_format_class(self._format_class_name)
        if not self.format_class:
            raise errors.StorageError("cannot find '%s' class" % self._format_class_name)

        super(ContainerDevice, self).__init__(*args, **kwargs)

    def _verify_member_uuid(self, member, expect_equality=True, require_existence=True):
        """ Whether the member's array UUID has the proper relationship
            with its array's UUID.

            :param member: the member device to add
            :type member: :class:`.StorageDevice`
            :param bool expect_equality: if True, expect UUIDs to be equal, otherwise, expect them to be unequal
            :param bool require_existence: if True, checking UUIDs is only meaningful if member format exists
            :returns: error msg if the UUIDs lack the correct relationship
            :rtype: str or NoneType
        """
        if not self._format_uuid_attr:
            log.info("No attribute name corresponding to member's array UUID.")
            return None

        if not hasattr(member.format, self._format_uuid_attr):
            log.warning("Attribute name (%s) which specifies member format's array UUID does not exist for this object (%s).", self._format_uuid_attr, member)
            return None

        member_fmt_uuid = getattr(member.format, self._format_uuid_attr)

        # If either UUID can not be obtained, nothing to check.
        if self.exists and (not member_fmt_uuid or not self.uuid):
            log.warning("At least one UUID missing.")
            return None

        # Below this line, the data obtained is considered to be correct.

        # If existence is required and not present, nothing to check
        if require_existence and not member.format.exists:
            return None

        uuids_equal = member_fmt_uuid == self.uuid

        if expect_equality and not uuids_equal:
            return "Member format's UUID %s does not match expected UUID %s." % (member_fmt_uuid, self.uuid)

        if not expect_equality and uuids_equal:
            return "Member format's UUID %s matches expected UUID %s." % (member_fmt_uuid, self.uuid)

        return None

    def _add_parent(self, parent):
        """ Add a parent device to the container.

            :param parent: the parent device to add
            :type parent: :class:`.StorageDevice`

            This operates on the in-memory model and does not alter disk
            contents at all.
        """
        log_method_call(self, self.name, parent=parent.name)
        if not isinstance(parent.format, self.format_class):
            raise ValueError("parent has wrong format")

        error = self._verify_member_uuid(parent)
        if error:
            raise ValueError("cannot add parent with mismatched UUID")

        super(ContainerDevice, self)._add_parent(parent)

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

        error = self._verify_member_uuid(member, expect_equality=False)
        if error:
            log.error("cannot re-add member: %s (%s)", member, error)
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

        error = self._verify_member_uuid(member, require_existence=False)
        if error:
            log.error("cannot remove non-member: %s (%s)", member, error)
            raise ValueError("cannot remove members that are not part of the container")

        self._remove(member)

        if member in self.parents:
            self.parents.remove(member)

    def update_size(self, newsize=None):
        pass
