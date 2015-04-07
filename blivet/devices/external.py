# devices/external.py
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
# Red Hat Author(s): Anne Mulhern <amulhern@redhat.com>
#

import abc

from six import add_metaclass

class ExternalDependencies(object):
    """ Very simple class that tracks categories of external dependencies. """

    def __init__(self, default=None, destroy=None):
        """ Set the dependencies categories.

            Note that a value of None means unset entirely, while [] means
            has no dependencies.
        """
        self.default = default
        self.destroy = destroy

@add_metaclass(abc.ABCMeta)
class ExternalDependenciesMode(object):
    """ Class determining in what mode to search for external dependencies. """

    @abc.abstractmethod
    def dependencies(self, deps):
        """ Selects the appropriate dependencies from the dependencies object.

            :param ExternalDependencies deps: external dependencies
            :returns: a list of dependencies in the proper mode
            :rtype: list of ExternalResource
        """
        raise NotImplementedError()

class DefaultMode(ExternalDependenciesMode):
    """ When planning a mode that requires no special external dependencies. """
    def dependencies(self, deps):
        return deps.default or []

DefaultMode = DefaultMode()

class DestroyMode(ExternalDependenciesMode):
    """ When planning an action to destroy a device. """
    def dependencies(self, deps):
        dependencies = deps.destroy
        if dependencies is None:
            dependencies = DefaultMode.dependencies(deps)
        return dependencies

DestroyMode = DestroyMode()
