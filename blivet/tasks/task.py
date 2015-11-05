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
    def availability_errors(self):
        """ Reasons if this task or the tasks it depends on are unavailable. """
        return self._availability_errors + \
            [e for t in self.depends_on for e in t.availability_errors]

    @property
    def available(self):
        """ True if the task is available, otherwise False.

            :returns: True if the task is available
            :rtype: bool
        """
        return self.availability_errors == []

    _availability_errors = abc.abstractproperty(
        doc="Reasons if the necessary external tools are unavailable.")

    depends_on = abc.abstractproperty(doc="tasks that this task depends on")

    @abc.abstractmethod
    def do_task(self, *args, **kwargs):
        """ Do the task for this class. """
        raise NotImplementedError()


class UnimplementedTask(Task):

    """ A null Task, which returns a negative or empty for all properties."""

    description = "an unimplemented task"
    implemented = False

    @property
    def _availability_errors(self):
        return ["Not implemented task can not succeed."]

    depends_on = []

    def __str__(self):
        return "unimplemented task"

    def do_task(self, *args, **kwargs):
        raise NotImplementedError()


@add_metaclass(abc.ABCMeta)
class BasicApplication(Task):

    """ A task representing an application. """

    ext = abc.abstractproperty(doc="The object representing the external resource.")

    # TASK methods

    def __str__(self):
        return str(self.ext)

    @property
    def _availability_errors(self):
        errors = self.ext.availability_errors
        if errors:
            return ["application %s is not available: %s" % (self.ext, " and ".join(errors))]
        else:
            return []

    @property
    def depends_on(self):
        return []
