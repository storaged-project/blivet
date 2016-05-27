# devices/dm.py
# Classes to represent various device-mapper devices.
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

import os

from ..devicelibs import dm
import block

from .. import errors
from .. import util
from ..storage_log import log_method_call
from .. import udev

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .lib import LINUX_SECTOR_SIZE

class DMDevice(StorageDevice):
    """ A device-mapper device """
    _type = "dm"
    _devDir = "/dev/mapper"

    def __init__(self, name, fmt=None, size=None, dmUuid=None, uuid=None,
                 target=None, exists=False, parents=None, sysfsPath=''):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword dmUuid: device-mapper UUID (see note below)
            :type dmUuid: str
            :type str uuid: device UUID (see note below)
            :keyword target: device mapper table/target name (eg: "linear")
            :type target: str

            .. note::

                The dmUuid is not necessarily persistent, as it is based on
                map name in many cases. The uuid, however, is a persistent UUID
                stored in device metadata on disk.
        """
        super(DMDevice, self).__init__(name, fmt=fmt, size=size,
                               exists=exists, uuid=uuid,
                               parents=parents, sysfsPath=sysfsPath)
        self.target = target
        self.dmUuid = dmUuid

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  target = %(target)s  dmUuid = %(dmUuid)s" %
              {"target": self.target, "dmUuid": self.dmUuid})
        return s

    @property
    def dict(self):
        d = super(DMDevice, self).dict
        d.update({"target": self.target, "dmUuid": self.dmUuid})
        return d

    @property
    def fstabSpec(self):
        """ Return the device specifier for use in /etc/fstab. """
        return self.path

    @property
    def mapName(self):
        """ This device's device-mapper map name """
        return self.name

    @property
    def status(self):
        match = next((m for m in block.dm.maps() if m.name == self.mapName),
           None)
        return super(DMDevice, self).status and \
               (match.live_table and not match.suspended) if match else False

    #def getTargetType(self):
    #    return dm.getDmTarget(name=self.name)

    def getDMNode(self):
        """ Return the dm-X (eg: dm-0) device node for this device. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        return dm.dm_node_from_name(self.name)

    def setupPartitions(self):
        log_method_call(self, name=self.name, kids=self.kids)
        rc = util.run_program(["kpartx", "-a", "-s", self.path])
        if rc:
            raise errors.DMError("partition activation failed for '%s'" % self.name)
        udev.settle()

    def teardownPartitions(self):
        log_method_call(self, name=self.name, kids=self.kids)
        rc = util.run_program(["kpartx", "-d", "-s", self.path])
        if rc:
            raise errors.DMError("partition deactivation failed for '%s'" % self.name)
        udev.settle()
        for dev in os.listdir("/dev/mapper/"):
            prefix = self.name + "p"
            if dev.startswith(prefix) and dev[len(prefix):].isdigit():
                dm.dm_remove(dev)

    def _setName(self, value):
        """ Set the device's map name. """
        if value == self._name:
            return

        log_method_call(self, self.name, status=self.status)
        if self.status:
            raise errors.DeviceError("cannot rename active device", self.name)

        super(DMDevice, self)._setName(value)
        #self.sysfsPath = "/dev/disk/by-id/dm-name-%s" % self.name

    @property
    def slave(self):
        """ This device's backing device. """
        return self.parents[0]

class DMLinearDevice(DMDevice):
    _type = "dm-linear"
    _partitionable = True
    _isDisk = True

    def __init__(self, name, fmt=None, size=None, dmUuid=None,
                 exists=False, parents=None, sysfsPath=''):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword dmUuid: device-mapper UUID
            :type dmUuid: str
        """
        if not parents:
            raise ValueError("DMLinearDevice requires a backing block device")

        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfsPath=sysfsPath,
                          exists=exists, target="linear", dmUuid=dmUuid)

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        slave_length = self.slave.currentSize / LINUX_SECTOR_SIZE
        dm.dm_create_linear(self.name, self.slave.path, slave_length,
                            self.dmUuid)

    def _postSetup(self):
        StorageDevice._postSetup(self)
        self.setupPartitions()
        udev.settle()

    def _teardown(self, recursive=False):
        self.teardownPartitions()
        udev.settle()
        dm.dm_remove(self.name)
        udev.settle()

    def deactivate(self, recursive=False):
        StorageDevice.teardown(self, recursive=recursive)

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._preTeardown(recursive=recursive):
            return

        log.debug("not tearing down dm-linear device %s", self.name)

    @property
    def description(self):
        return self.model

class DMCryptDevice(DMDevice):
    """ A dm-crypt device """
    _type = "dm-crypt"
    _encrypted = True

    def __init__(self, name, fmt=None, size=None, uuid=None,
                 exists=False, sysfsPath='', parents=None):
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
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
        """
        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfsPath=sysfsPath,
                          exists=exists, target="crypt")
