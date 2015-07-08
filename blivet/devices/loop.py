# devices/loop.py
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

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

import os

from .. import errors
from ..storage_log import log_method_call
from ..tasks import availability

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice

class LoopDevice(StorageDevice):
    """ A loop device. """
    _type = "loop"
    _external_dependencies = [availability.BLOCKDEV_LOOP_PLUGIN]

    def __init__(self, name=None, fmt=None, size=None, sysfsPath=None,
                 exists=False, parents=None):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it

            Loop devices always exist.
        """
        if not parents:
            raise ValueError("LoopDevice requires a backing device")

        if not name:
            # set up a temporary name until we've activated the loop device
            name = "tmploop%d" % self.id

        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               exists=True, parents=parents)

    def _setName(self, value):
        self._name = value  # actual name is set by losetup

    def updateName(self):
        """ Update this device's name. """
        if not self.slave.status:
            # if the backing device is inactive, so are we
            return self.name

        if self.name.startswith("loop"):
            # if our name is loopN we must already be active
            return self.name

        name = blockdev.loop.get_loop_name(self.slave.path)
        if name.startswith("loop"):
            self.name = name

        return self.name

    @property
    def status(self):
        return (self.slave.status and
                self.name.startswith("loop") and
                blockdev.loop.get_loop_name(self.slave.path) == self.name)

    @property
    def size(self):
        return self.slave.size

    def _preSetup(self, orig=False):
        if not os.path.exists(self.slave.path):
            raise errors.DeviceError("specified file (%s) does not exist" % self.slave.path)
        return StorageDevice._preSetup(self, orig=orig)

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        blockdev.loop.setup(self.slave.path)

    def _postSetup(self):
        StorageDevice._postSetup(self)
        self.updateName()
        self.updateSysfsPath()

    def _teardown(self, recursive=False):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        blockdev.loop.teardown(self.path)

    def _postTeardown(self, recursive=False):
        StorageDevice._postTeardown(self, recursive=recursive)
        self.name = "tmploop%d" % self.id
        self.sysfsPath = ''

    @property
    def slave(self):
        return self.parents[0]
