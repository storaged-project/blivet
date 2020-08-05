# devices/device.py
# Base class for all devices.
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

import pprint
from six import add_metaclass

from .. import util
from ..storage_log import log_method_call
from ..threads import SynchronizedMeta

import logging
log = logging.getLogger("blivet")

from .lib import ParentList


@add_metaclass(SynchronizedMeta)
class Device(util.ObjectID):

    """ A generic device.

        Device instances know which devices they depend upon (parents
        attribute). They do not know which devices depend upon them, but
        they do know whether or not they have any dependent devices
        (isleaf attribute).

        A Device's setup method should set up all parent devices as well
        as the device itself. It should not run the resident format's
        setup method.

            Which Device types rely on their parents' formats being active?
                DMCryptDevice

        A Device's teardown method should accept the keyword argument
        recursive, which takes a boolean value and indicates whether or
        not to recursively close parent devices.

        A Device's create method should create all parent devices as well
        as the device itself. It should also run the Device's setup method
        after creating the device. The create method should not create a
        device's resident format.

            Which device type rely on their parents' formats to be created
            before they can be created/assembled?
                VolumeGroup
                DMCryptDevice

        A Device's destroy method should destroy any resident format
        before destroying the device itself.

    """

    _type = "device"
    _packages = []
    _external_dependencies = []

    def __init__(self, name, parents=None):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword parents: a list of parent devices
            :type parents: list of :class:`Device` instances
        """
        util.ObjectID.__init__(self)
        self._name = name
        if parents is not None and not isinstance(parents, list):
            raise ValueError("parents must be a list of Device instances")

        self._tags = set()
        self.parents = parents or []
        self._children = []

    def __deepcopy__(self, memo):
        """ Create a deep copy of a Device instance.

            We can't do copy.deepcopy on parted objects, which is okay.
            For these parted objects, we just do a shallow copy.
        """
        return util.variable_copy(self, memo,
                                  omit=('node',),
                                  shallow=('_parted_partition',))

    def __repr__(self):
        s = ("%(type)s instance (%(id)s) --\n"
             "  name = %(name)s  status = %(status)s"
             "  id = %(dev_id)s\n"
             "  children = %(children)s\n"
             "  parents = %(parents)s\n" %
             {"type": self.__class__.__name__, "id": "%#x" % id(self),
              "name": self.name, "status": self.status,
              "dev_id": self.id,
              "children": pprint.pformat([str(c) for c in self.children]),
              "parents": pprint.pformat([str(p) for p in self.parents])})
        return s

    # Force str and unicode types in case type or name is unicode
    def _to_string(self):
        s = "%s %s (%d)" % (self.type, self.name, self.id)
        return s

    def __str__(self):
        return util.stringize(self._to_string())

    def __unicode__(self):
        return util.unicodeize(self._to_string())

    def _add_parent(self, parent):
        """ Called before adding a parent to this device.

            See :attr:`~.ParentList.appendfunc`.
        """
        parent.add_child(self)

    def _remove_parent(self, parent):
        """ Called before removing a parent from this device.

            See :attr:`~.ParentList.removefunc`.
        """
        parent.remove_child(self)

    def _init_parent_list(self):
        """ Initialize this instance's parent list. """
        if not hasattr(self, "_parents"):
            # pylint: disable=attribute-defined-outside-init
            self._parents = ParentList(appendfunc=self._add_parent,
                                       removefunc=self._remove_parent)

        # iterate over a copy of the parent list because we are altering it in
        # the for-cycle
        for parent in list(self._parents):
            self._parents.remove(parent)

    @property
    def parents(self):
        """ Devices upon which this device is built """
        return self._parents

    @parents.setter
    def parents(self, parents):
        """ Set this instance's parent list. """
        self._init_parent_list()
        for parent in parents:
            self._parents.append(parent)

    @property
    def children(self):
        """List of this device's immediate descendants."""
        return self._children[:]

    @property
    def dict(self):
        d = {"type": self.type, "name": self.name,
             "parents": [p.name for p in self.parents]}
        return d

    def remove_child(self, child):
        """ Decrement the child counter for this device. """
        log_method_call(self, name=self.name, child=child._name, kids=len(self.children))
        self._children.remove(child)

    def add_child(self, child):
        """ Increment the child counter for this device. """
        log_method_call(self, name=self.name, child=child._name, kids=len(self.children))
        if child in self._children:
            raise ValueError("child is already accounted for")

        self._children.append(child)

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        raise NotImplementedError("setup method not defined for Device")

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        raise NotImplementedError("teardown method not defined for Device")

    def create(self):
        """ Create the device. """
        raise NotImplementedError("create method not defined for Device")

    def destroy(self):
        """ Destroy the device. """
        raise NotImplementedError("destroy method not defined for Device")

    def setup_parents(self, orig=False):
        """ Run setup method of all parent devices.

            :keyword orig: set up original format instead of current format
            :type orig: bool
        """
        log_method_call(self, name=self.name, orig=orig)
        for parent in self.parents:
            parent.setup(orig=orig)

    def teardown_parents(self, recursive=None):
        """ Run teardown method of all parent devices.

            :keyword recursive: tear down all ancestor devices recursively
            :type recursive: bool
        """
        for parent in self.parents:
            parent.teardown(recursive=recursive)

    def depends_on(self, dep):
        """ Return True if this device depends on dep.

            This device depends on another device if the other device is an
            ancestor of this device. For example, a PartitionDevice depends on
            the DiskDevice on which it resides.

            :param dep: the other device
            :type dep: :class:`Device`
            :returns: whether this device depends on 'dep'
            :rtype: bool
        """
        # XXX does a device depend on itself?
        if dep in self.parents:
            return True

        for parent in self.parents:
            if parent.depends_on(dep):
                return True

        return False

    def dracut_setup_args(self):
        return set()

    @property
    def status(self):
        """ Is this device currently active and ready for use? """
        return False

    def _get_name(self):
        return self._name

    def _set_name(self, value):
        if not self.is_name_valid(value):
            raise ValueError("%s is not a valid name for this device" % value)
        self._name = value

    name = property(lambda s: s._get_name(),
                    lambda s, v: s._set_name(v),
                    doc="This device's name")

    @property
    def isleaf(self):
        """ True if no other device depends on this one. """
        return not bool(self.children)

    @property
    def type_description(self):
        """ String describing the device type. """
        return self._type

    @property
    def type(self):
        """ Device type. """
        return self._type

    @property
    def ancestors(self):
        """ A list of all of this device's ancestors, including itself. """
        ancestors = set([self])
        for p in [d for d in self.parents if d not in ancestors]:
            ancestors.update(set(p.ancestors))
        return list(ancestors)

    @property
    def packages(self):
        """ List of packages required to manage this device and all its
            ancestor devices. Does not contain duplicates.

            :returns: names of packages required by device and all ancestors
            :rtype: list of str
        """
        packages = self._packages
        for parent in self.parents:
            packages.extend(p for p in parent.packages if p not in packages)

        return packages

    @property
    def tags(self):
        """ set of (str) tags describing this device. """
        return self._tags

    @tags.setter
    def tags(self, newtags):
        self._tags = set(newtags)

    def is_name_valid(self, name):  # pylint: disable=unused-argument
        """Is the device name valid for the device type?"""

        # By default anything goes
        return True

    #
    # dependencies
    #
    @classmethod
    def type_external_dependencies(cls):
        """ A list of external dependencies of this device type.

            :returns: a set of external dependencies
            :rtype: set of availability.ExternalResource

            The external dependencies include the dependencies of this
            device type and of all superclass device types.
        """
        return set(
            d for p in cls.__mro__ if issubclass(p, Device) for d in p._external_dependencies
        )

    @classmethod
    def unavailable_type_dependencies(cls):
        """ A set of unavailable dependencies for this type.

            :return: the unavailable external dependencies for this type
            :rtype: set of availability.ExternalResource
        """
        return set(e for e in cls.type_external_dependencies() if not e.available)

    @property
    def external_dependencies(self):
        """ A list of external dependencies of this device and its parents.

            :returns: the external dependencies of this device and all parents.
            :rtype: set of availability.ExternalResource
        """
        return set(d for p in self.ancestors for d in p.type_external_dependencies())

    @property
    def unavailable_dependencies(self):
        """ Any unavailable external dependencies of this device or its
            parents.

            :returns: A list of unavailable external dependencies.
            :rtype: set of availability.external_resource
        """
        return set(e for e in self.external_dependencies if not e.available)
