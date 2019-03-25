# devices/nodev.py
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

from ..storage_log import log_method_call

import logging
log = logging.getLogger("blivet")

from ..size import Size
from .storage import StorageDevice


class NoDevice(StorageDevice):

    """ A nodev device for nodev filesystems like tmpfs. """
    _type = "nodev"

    def __init__(self, fmt=None):
        """
            :keyword fmt: the device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
        """
        if fmt:
            name = fmt.device
        else:
            name = "none"

        StorageDevice.__init__(self, name, fmt=fmt, exists=True)

    @property
    def path(self):
        """ Device node representing this device. """
        # the name may have a '.%d' suffix to make it unique
        return self.name.split(".")[0]

    def setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)

    def teardown(self, recursive=False):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # just make sure the format is unmounted
        self._pre_teardown(recursive=recursive)

    def create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)

    def destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        self._pre_destroy()

    def update_size(self, newsize=None):
        pass

    def update_sysfs_path(self):
        pass


class TmpFSDevice(NoDevice):

    """ A nodev device for a tmpfs filesystem. """
    _type = "tmpfs"
    _format_immutable = True

    def __init__(self, *args, **kwargs):
        """Create a tmpfs device"""
        # pylint: disable=unused-argument
        fmt = kwargs.get('fmt')
        NoDevice.__init__(self, fmt)
        # the tmpfs device does not exist until mounted
        self.exists = False
        self._size = kwargs["size"]
        self._target_size = self._size

    @property
    def size(self):
        if self._size is not None:
            return self._size
        elif self.format:
            return self.format.size
        else:
            return Size(0)

    @property
    def fstab_spec(self):
        return self._type

    def populate_ksdata(self, data):
        super(TmpFSDevice, self).populate_ksdata(data)
        # we need to supply a format to ksdata, otherwise the kickstart line
        # would include --noformat, resulting in an invalid command combination
        data.format = self.format
