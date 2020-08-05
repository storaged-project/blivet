# devices/lib.py
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
from enum import Enum
import os

from .. import errors
from .. import udev
from ..size import Size

LINUX_SECTOR_SIZE = Size(512)


class Tags(str, Enum):
    """Tags that describe various classes of disk."""
    local = 'local'
    nvdimm = 'nvdimm'
    remote = 'remote'
    removable = 'removable'
    ssd = 'ssd'
    usb = 'usb'


def _collect_device_major_data():
    by_major = {}
    by_device = {}
    for line in open("/proc/devices").readlines():
        try:
            (major, device) = line.split()
        except ValueError:
            continue
        try:
            by_major[int(major)] = device
            if device not in by_device:
                by_device[device] = []

            by_device[device].append(int(major))
        except ValueError:
            continue
    return (by_major, by_device)


_devices_by_major, _majors_by_device = _collect_device_major_data()


def get_majors_by_device_type(device_type):
    """ Return a list of major numbers for the given device type.

        :param str device_type: device type string (eg: 'device-mapper', 'md')
        :rtype: list of int

        .. note::

            Type strings are taken directly from /proc/devices.

    """
    return _majors_by_device.get(device_type, [])


def get_device_type_by_major(major):
    """ Return a device-type string for the given major number.

        :param int major: major number
        :rtype: str

        .. note::

            Type strings are taken directly from /proc/devices.

    """
    return _devices_by_major.get(major)


def device_path_to_name(device_path):
    """ Return a name based on the given path to a device node.

        :param device_path: the path to a device node
        :type device_path: str
        :returns: the name
        :rtype: str
    """
    if not device_path:
        return None

    if device_path.startswith("/dev/"):
        name = device_path[5:]
    else:
        name = device_path

    if name.startswith("mapper/"):
        name = name[7:]

    if name.startswith("md/"):
        name = name[3:]

    if name.startswith("/"):
        name = os.path.basename(name)

    return name


def device_name_to_disk_by_path(device_name=None):
    """ Return a /dev/disk/by-path/ symlink path for the given device name.

        :param device_name: the device name
        :type device_name: str
        :returns: the full path to a /dev/disk/by-path/ symlink, or None
        :rtype: str or NoneType
    """
    if not device_name:
        return ""

    ret = None
    for dev in udev.get_devices():
        if udev.device_get_name(dev) == device_name:
            ret = udev.device_get_by_path(dev)
            break

    if ret:
        return ret
    raise errors.DeviceNotFoundError(device_name)


class ParentList(object):

    """ A list with auditing and side-effects for additions and removals.

        The class provides an ordered list with guaranteed unique members and
        optional functions to run before adding or removing a member. It
        provides a subset of the functionality provided by :class:`list`,
        making it easy to ensure that changes pass through the check functions.

        The following operations are implemented:

        .. code::

            ml.append(x)
            ml.remove(x)
            iter(ml)
            len(ml)
            x in ml
            x = ml[i]   # not ml[i] = x
    """

    def __init__(self, items=None, appendfunc=None, removefunc=None):
        """
            :keyword items: initial contents
            :type items: any iterable
            :keyword appendfunc: a function to call before adding an item
            :type appendfunc: callable
            :keyword removefunc: a function to call before removing an item
            :type removefunc: callable

            appendfunc and removefunc should take the item to be added or
            removed and perform any checks or other processing. The appropriate
            function will be called immediately before adding or removing the
            item. The function should raise an exception if the addition/removal
            should not take place. :class:`~.ParentList` instance is not passed
            to the function. While this is not optimal for general-purpose use,
            it is ideal for the intended use as part of :class:`~.Device`. The
            functions themselves should not modify the :class:`~.ParentList`.
        """
        self.items = list()
        if items:
            self.items.extend(items)

        self.appendfunc = appendfunc or (lambda i: True)
        """ a function to call before adding an item """

        self.removefunc = removefunc or (lambda i: True)
        """ a function to call before removing an item """

    def __iter__(self):
        return iter(self.items)

    def __contains__(self, y):
        return y in self.items

    def __getitem__(self, i):
        return self.items[i]

    def __len__(self):
        return len(self.items)

    def append(self, y):
        """ Add an item to the list after running a callback. """
        if y in self.items:
            raise ValueError("item is already in the list")

        self.appendfunc(y)
        self.items.append(y)

    def remove(self, y):
        """ Remove an item from the list after running a callback. """
        if y not in self.items:
            raise ValueError("item is not in the list")

        self.removefunc(y)
        self.items.remove(y)
