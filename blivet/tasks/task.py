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

    @classmethod
    @abc.abstractmethod
    def available(cls):
        """ A class-level method indicating whether tasks of this class
            are available.
        """
        raise NotImplementedError()

    description = abc.abstractproperty(doc="Brief description for this task.")

    # Note that unavailable is able to obtain more precise information than
    # available, since it is able to access the filesystem object.

    @property
    def unavailable(self):
        """ Reason if this task or the tasks it depends on are unavailable. """
        return self._unavailable or next((t.unavailable for t in self.dependsOn), False)

    _unavailable = abc.abstractproperty(
       doc="Reason if the necessary external tools are unavailable.")

    unready = abc.abstractproperty(
       doc="Reason if the external resource is not ready for this action.")

    unable = abc.abstractproperty(
       doc="Reason if the object is not in a correct state for this task.")

    dependsOn = abc.abstractproperty(doc="tasks that this task depends on")

    @property
    def impossible(self):
        """ Returns a reason if the task can not succeed, otherwise False.

            :returns: reason or False
            :rtype: str or bool
        """
        return self.unavailable or self.unable or self.unready

    @abc.abstractmethod
    def doTask(self, *args, **kwargs):
        """ Do the task for this class. """
        raise NotImplementedError()
