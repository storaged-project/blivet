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

from .. import util
from ..storage_log import log_method_call

import logging
log = logging.getLogger("blivet")

from .lib import ParentList

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
    _services = []

    def __init__(self, name, parents=None):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword parents: a list of parent devices
            :type parents: list of :class:`Device` instances
        """
        util.ObjectID.__init__(self)
        self.kids = 0

        # Copy only the validity check from _setName so we don't try to check a
        # bunch of inappropriate state properties during __init__ in subclasses
        if not self.isNameValid(name):
            raise ValueError("%s is not a valid name for this device" % name)
        self._name = name

        self.parents = []
        if parents and not isinstance(parents, list):
            raise ValueError("parents must be a list of Device instances")

        if parents:
            self.parents = parents

    def __deepcopy__(self, memo):
        """ Create a deep copy of a Device instance.

            We can't do copy.deepcopy on parted objects, which is okay.
            For these parted objects, we just do a shallow copy.
        """
        return util.variable_copy(self, memo,
           omit=('_raidSet', 'node'),
           shallow=('_partedPartition',))

    def __repr__(self):
        s = ("%(type)s instance (%(id)s) --\n"
             "  name = %(name)s  status = %(status)s"
             "  kids = %(kids)s id = %(dev_id)s\n"
             "  parents = %(parents)s\n" %
             {"type": self.__class__.__name__, "id": "%#x" % id(self),
              "name": self.name, "kids": self.kids, "status": self.status,
              "dev_id": self.id,
              "parents": pprint.pformat([str(p) for p in self.parents])})
        return s

    def __str__(self):
        s = "%s %s (%d)" % (self.type, self.name, self.id)
        return s

    def _addParent(self, parent):
        """ Called before adding a parent to this device.

            See :attr:`~.ParentList.appendfunc`.
        """
        parent.addChild()

    def _removeParent(self, parent):
        """ Called before removing a parent from this device.

            See :attr:`~.ParentList.removefunc`.
        """
        parent.removeChild()

    def _initParentList(self):
        """ Initialize this instance's parent list. """
        if not hasattr(self, "_parents"):
            # pylint: disable=attribute-defined-outside-init
            self._parents = ParentList(appendfunc=self._addParent,
                                       removefunc=self._removeParent)

        # iterate over a copy of the parent list because we are altering it in
        # the for-cycle
        for parent in list(self._parents):
            self._parents.remove(parent)

    def _setParentList(self, parents):
        """ Set this instance's parent list. """
        self._initParentList()
        for parent in parents:
            self._parents.append(parent)

    def _getParentList(self):
        return self._parents

    parents = property(_getParentList, _setParentList,
                       doc="devices upon which this device is built")

    @property
    def dict(self):
        d =  {"type": self.type, "name": self.name,
              "parents": [p.name for p in self.parents]}
        return d

    def removeChild(self):
        """ Decrement the child counter for this device. """
        log_method_call(self, name=self.name, kids=self.kids)
        self.kids -= 1

    def addChild(self):
        """ Increment the child counter for this device. """
        log_method_call(self, name=self.name, kids=self.kids)
        self.kids += 1

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

    def setupParents(self, orig=False):
        """ Run setup method of all parent devices.

            :keyword orig: set up original format instead of current format
            :type orig: bool
        """
        log_method_call(self, name=self.name, orig=orig, kids=self.kids)
        for parent in self.parents:
            parent.setup(orig=orig)

    def teardownParents(self, recursive=None):
        """ Run teardown method of all parent devices.

            :keyword recursive: tear down all ancestor devices recursively
            :type recursive: bool
        """
        for parent in self.parents:
            parent.teardown(recursive=recursive)

    def dependsOn(self, dep):
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
            if parent.dependsOn(dep):
                return True

        return False

    def dracutSetupArgs(self):
        return set()

    @property
    def status(self):
        """ Is this device currently active and ready for use? """
        return False

    def _getName(self):
        return self._name

    def _setName(self, value):
        if not self.isNameValid(value):
            raise ValueError("%s is not a valid name for this device" % value)
        self._name = value

    name = property(lambda s: s._getName(),
                    lambda s, v: s._setName(v),
                    doc="This device's name")

    @property
    def isleaf(self):
        """ True if no other device depends on this one. """
        return self.kids == 0

    @property
    def typeDescription(self):
        """ String describing the device type. """
        return self._type

    @property
    def type(self):
        """ Device type. """
        return self._type

    @property
    def ancestors(self):
        """ A list of all of this device's ancestors, including itself. """
        l = set([self])
        for p in [d for d in self.parents if d not in l]:
            l.update(set(p.ancestors))
        return list(l)

    @property
    def packages(self):
        """ List of packages required to manage devices of this type.

            This list includes the packages required by its parent devices.
        """
        packages = self._packages
        for parent in self.parents:
            for package in parent.packages:
                if package not in packages:
                    packages.append(package)

        return packages

    @property
    def services(self):
        """ List of services required to manage devices of this type.

            This list includes the services required by its parent devices."
        """
        services = self._services
        for parent in self.parents:
            for service in parent.services:
                if service not in services:
                    services.append(service)

        return services

    @classmethod
    def isNameValid(cls, name): # pylint: disable=unused-argument
        """Is the device name valid for the device type?"""

        # By default anything goes
        return True
