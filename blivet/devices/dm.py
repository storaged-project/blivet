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

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import os

from .. import errors
from .. import util
from ..storage_log import log_method_call
from .. import udev
from ..tasks import availability

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .lib import LINUX_SECTOR_SIZE, get_majors_by_device_type

DM_MAJORS = get_majors_by_device_type("device-mapper")


class DMDevice(StorageDevice):

    """ A device-mapper device """
    _type = "dm"
    _dev_dir = "/dev/mapper"
    _external_dependencies = [
        availability.KPARTX_APP,
        availability.BLOCKDEV_DM_PLUGIN
    ]

    def __init__(self, name, fmt=None, size=None, dm_uuid=None, uuid=None,
                 target=None, exists=False, parents=None, sysfs_path=''):
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
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword dm_uuid: device-mapper UUID (see note below)
            :type dm_uuid: str
            :type str uuid: device UUID (see note below)
            :keyword target: device mapper table/target name (eg: "linear")
            :type target: str

            .. note::

                The dm_uuid is not necessarily persistent, as it is based on
                map name in many cases. The uuid, however, is a persistent UUID
                stored in device metadata on disk.
        """
        super(DMDevice, self).__init__(name, fmt=fmt, size=size,
                                       exists=exists, uuid=uuid,
                                       parents=parents, sysfs_path=sysfs_path)
        self.target = target
        self.dm_uuid = dm_uuid

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  target = %(target)s  dm_uuid = %(dm_uuid)s" %
              {"target": self.target, "dm_uuid": self.dm_uuid})
        return s

    @property
    def dict(self):
        d = super(DMDevice, self).dict
        d.update({"target": self.target, "dm_uuid": self.dm_uuid})
        return d

    @property
    def fstab_spec(self):
        """ Return the device specifier for use in /etc/fstab. """
        return self.path

    @property
    def map_name(self):
        """ This device's device-mapper map name """
        return self.name

    @property
    def status(self):
        try:
            return blockdev.dm.map_exists(self.map_name, True, True)
        except blockdev.DMError as e:
            if "Not running as root" in str(e):
                return False
            else:
                raise

    # def get_target_type(self):
    #    return dm.get_dm_target(name=self.name)

    def get_dm_node(self):
        """ Return the dm-X (eg: dm-0) device node for this device. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        return blockdev.dm.node_from_name(self.name)

    def setup_partitions(self):
        log_method_call(self, name=self.name)
        rc = util.run_program(["kpartx", "-a", "-s", self.path])
        if rc:
            raise errors.DMError("partition activation failed for '%s'" % self.name)
        udev.settle()

    def teardown_partitions(self):
        log_method_call(self, name=self.name)
        rc = util.run_program(["kpartx", "-d", "-s", self.path])
        if rc:
            raise errors.DMError("partition deactivation failed for '%s'" % self.name)
        udev.settle()
        for dev in os.listdir("/dev/mapper/"):
            prefix = self.name + "p"
            if dev.startswith(prefix) and dev[len(prefix):].isdigit():
                blockdev.dm.remove(dev)

    def _set_name(self, value):
        """ Set the device's map name. """
        if value == self._name:
            return

        log_method_call(self, self.name, status=self.status)
        super(DMDevice, self)._set_name(value)


class DMLinearDevice(DMDevice):
    _type = "dm-linear"
    _partitionable = True
    _is_disk = True

    def __init__(self, name, fmt=None, size=None, dm_uuid=None,
                 exists=False, parents=None, sysfs_path=''):
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
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword dm_uuid: device-mapper UUID
            :type dm_uuid: str
        """
        if not parents:
            raise ValueError("DMLinearDevice requires a backing block device")

        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfs_path=sysfs_path,
                          exists=exists, target="linear", dm_uuid=dm_uuid)

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        parent_length = self.parents[0].current_size / LINUX_SECTOR_SIZE
        blockdev.dm.create_linear(self.name, self.parents[0].path, parent_length,
                                  self.dm_uuid)

    def _post_setup(self):
        StorageDevice._post_setup(self)
        self.setup_partitions()
        udev.settle()

    def _teardown(self, recursive=False):
        self.teardown_partitions()
        udev.settle()
        blockdev.dm.remove(self.name)
        udev.settle()

    def deactivate(self, recursive=False):
        StorageDevice.teardown(self, recursive=recursive)

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._pre_teardown(recursive=recursive):
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
                 exists=False, sysfs_path='', parents=None):
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
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
        """
        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfs_path=sysfs_path,
                          exists=exists, target="crypt")


class DMIntegrityDevice(DMDevice):

    """ A dm-integrity device """
    _type = "dm-integrity"
    _encrypted = True

    def __init__(self, name, fmt=None, size=None, uuid=None,
                 exists=False, sysfs_path='', parents=None):
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
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
        """
        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfs_path=sysfs_path,
                          exists=exists, target="integrity")
