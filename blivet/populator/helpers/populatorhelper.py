# populator/helpers/populatorhelper.py
# Base classes for type-specific helpers for populating a DeviceTree.
#
# Copyright (C) 2009-2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#


class PopulatorHelper:
    """ Class to hold type-specific code for populating the devicetree. """

    priority = 100
    """ Higher priority value gets checked for match first. """

    def __init__(self, populator, data):
        """
            :param :class:`~.Populator` populator: the calling populator
            :param :class:`pyudev.Device` data: udev data describing a device
        """
        self._populator = populator
        self.data = data

    @classmethod
    def match(cls, data):
        """ Return True if this helper is appropriate for the given device.

            :param :class:`pyudev.Device` data: udev data describing a device
            :returns: whether this class is appropriate for the specified device
            :rtype: bool
        """
        raise NotImplementedError()

    def run(self):
        """ Run type-specific processing.

            For device handlers, this method should instantiate the appropriate
            device type and add the instance to the device tree. For format
            handlers, this method should instantiate the appropriate format
            type, associate the instance with the appropriate device, and
            perform all processing related to the device's formatting.
        """
        raise NotImplementedError()
