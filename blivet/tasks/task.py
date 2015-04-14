# task.py
# Abstract class for tasks.
#
# Copyright (C) 2015  Red Hat, Inc.
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

import abc

from six import add_metaclass

@add_metaclass(abc.ABCMeta)
class Task(object):
    """ An abstract class that represents some task. """

    # Whether or not the functionality is implemented in the task class.
    # It is True by default. Only NotImplementedClass and its descendants
    # should have a False value.
    implemented = True

    description = abc.abstractproperty(doc="Brief description for this task.")

    @property
    def availabilityErrors(self):
        """ Reasons if this task or the tasks it depends on are unavailable. """
        return self._availabilityErrors + \
           [e for t in self.dependsOn for e in t.availabilityErrors]

    _availabilityErrors = abc.abstractproperty(
       doc="Reasons if the necessary external tools are unavailable.")

    readinessErrors = abc.abstractproperty(
       doc="Reasons if the actual thing, e.g. device, is is not ready for this action.")

    abilityErrors = abc.abstractproperty(
       doc="Reasons if the object is not in a correct state for this task.")

    dependsOn = abc.abstractproperty(doc="tasks that this task depends on")

    @property
    def possibilityErrors(self):
        """ Returns reasons if the task can not succeed.

            :returns: list of reasons the task can not succeed
            :rtype: list of str
        """
        return self.availabilityErrors + self.abilityErrors + self.readinessErrors

    @abc.abstractmethod
    def doTask(self, *args, **kwargs):
        """ Do the task for this class. """
        raise NotImplementedError()

class UnimplementedTask(Task):
    """ A null Task, which returns a negative or empty for all properties."""

    description = "an unimplemented task"
    implemented = False

    @property
    def _availabilityErrors(self):
        return ["Not implemented task can not succeed."]

    @property
    def readinessErrors(self):
        return ["Not implemented task can not succeed."]

    @property
    def abilityErrors(self):
        return ["Not implemented task can not succeed."]

    dependsOn = []

    def doTask(self, *args, **kwargs):
        raise NotImplementedError()

@add_metaclass(abc.ABCMeta)
class BasicApplication(Task):
    """ A task representing an application. """

    ext = abc.abstractproperty(doc="The object representing the external resource.")

    # TASK methods

    @property
    def _availabilityErrors(self):
        errors = []
        if not self.ext.available:
            errors.append("application %s is not available" % self.ext)

        return errors

    @property
    def dependsOn(self):
        return []

    @property
    def abilityErrors(self):
        return []

    @property
    def readinessErrors(self):
        return []
