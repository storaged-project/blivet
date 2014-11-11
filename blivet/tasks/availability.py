# availability.py
# Class for tracking availability of an application.
#
# Copyright (C) 2014  Red Hat, Inc.
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

from .. import util

class Application(object):
    """ An application. """

    def __init__(self, method, name):
        """ Initializes an instance of an application.

            :param method: A method object
            :type method: Method
            :param str name: the name of the application
        """
        self._method = method
        self.name = name

    def __str__(self):
        return self.name

    # Results of these methods may change at runtime, depending on system
    # state.

    @property
    def available(self):
        """ Whether the resource is available.

            :returns: True if the resource is available, otherwise False
            :rtype: bool
        """
        return self._method.available(self)

    @property
    def path(self):
        """ Absolute path of directory containing the executable.

            :returns: Absolute path of directory containing executable.
            :rtype: str or NoneType

            Returns None if available is False.
        """
        return self._method.path(self)


@add_metaclass(abc.ABCMeta)
class Method(object):
    """ A collection of methods for a particular application task. """

    @abc.abstractmethod
    def available(self, application):
        """ Returns True if the application is available.

            :param application: any application
            :type application: applications.application.Application

            :returns: True if the application is available
            :rtype: bool
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def path(self, application):
        """ Returns the absolute path of the application.

            :param application: any application
            :type application: applications.application.Application

            :returns: the absolute path of the application
            :rtype: str or NoneType

            Returns None when available is False
        """
        raise NotImplementedError()

class Path(Method):
    """ Methods for when application is found in  PATH. """

    def available(self, application):
        """ Returns True if the name of the application is in the path.

            :param application: any application
            :type application: applications.application.Application

            :returns: True if the name of the application is in the path
            :rtype: bool
        """
        return bool(self.path(application))

    def path(self, application):
        """ Obtain absolute path of executable.

            :param application: The application to locate.
            :type application: applications.application.Application

            :returns: path of executable
            :rtype: str
        """
        return util.find_program_in_path(application.name)
