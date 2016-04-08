# devices/disk.py
# Classes to represent various types of disk-like devices.
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

import block

from .. import errors
from .. import util
from ..flags import flags
from ..size import Size
from ..storage_log import log_method_call
from .. import udev

from ..fcoe import fcoe

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .container import ContainerDevice
from .network import NetworkStorageDevice
from .dm import DMDevice

class DiskDevice(StorageDevice):
    """ A local/generic disk.

        This is not the only kind of device that is treated as a disk. More
        useful than checking isinstance(device, DiskDevice) is checking
        device.isDisk.
    """
    _type = "disk"
    _partitionable = True
    _isDisk = True

    def __init__(self, name, fmt=None,
                 size=None, major=None, minor=None, sysfsPath='',
                 parents=None, serial=None, vendor="", model="", bus="",
                 exists=True):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword uuid: universally unique identifier (device -- not fs)
            :type uuid: str
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword removable: whether or not this is a removable device
            :type removable: bool
            :keyword serial: the ID_SERIAL_SHORT for this device
            :type serial: str
            :keyword vendor: the manufacturer of this Device
            :type vendor: str
            :keyword model: manufacturer's device model string
            :type model: str
            :keyword bus: the interconnect this device uses
            :type bus: str

            DiskDevices always exist.
        """
        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               major=major, minor=minor, exists=exists,
                               sysfsPath=sysfsPath, parents=parents,
                               serial=serial, model=model,
                               vendor=vendor, bus=bus)

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  removable = %(removable)s" % {"removable": self.removable})
        return s

    @property
    def mediaPresent(self):
        if flags.testing:
            return True

        # Some drivers (cpqarray <blegh>) make block device nodes for
        # controllers with no disks attached and then report a 0 size,
        # treat this as no media present
        return self.exists and self.currentSize > Size(0)

    @property
    def description(self):
        return " ".join(s for s in (self.vendor, self.model) if s)

    def _preDestroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        if not self.mediaPresent:
            raise errors.DeviceError("cannot destroy disk with no media", self.name)

        StorageDevice._preDestroy(self)

class DiskFile(DiskDevice):
    """ This is a file that we will pretend is a disk.

        This is intended only for testing purposes. The benefit of this class
        is that you can instantiate a disk-like device with a working disklabel
        class as a non-root user. It is not known how the system will behave if
        partitions are committed to one of these disks.
    """
    _devDir = ""

    def __init__(self, name, fmt=None,
                 size=None, major=None, minor=None, sysfsPath='',
                 parents=None, serial=None, vendor="", model="", bus="",
                 exists=True):
        """
            :param str name: the full path to the backing regular file
            :keyword :class:`~.formats.DeviceFormat` fmt: the device's format
        """
        _name = os.path.basename(name)
        self._devDir = os.path.dirname(name)

        super(DiskFile, self).__init__(_name, fmt=fmt, size=size,
                            major=major, minor=minor, sysfsPath=sysfsPath,
                            parents=parents, serial=serial, vendor=vendor,
                            model=model, bus=bus, exists=exists)

    #
    # Regular files do not have sysfs entries.
    #
    @property
    def sysfsPath(self):
        return ""

    @sysfsPath.setter
    def sysfsPath(self, value):
        pass

    def updateSysfsPath(self):
        pass

class DMRaidArrayDevice(DMDevice, ContainerDevice):
    """ A dmraid (device-mapper RAID) device """
    _type = "dm-raid array"
    _packages = ["dmraid"]
    _partitionable = True
    _isDisk = True
    _formatClassName = property(lambda s: "dmraidmember")
    _formatUUIDAttr = property(lambda s: None)

    def __init__(self, name, raidSet=None, fmt=None,
                 size=None, parents=None, sysfsPath=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword raidSet: the RaidSet object from block
            :type raidSet: :class:`block.RaidSet`

            DMRaidArrayDevices always exist. Blivet cannot create or destroy
            them.
        """
        super(DMRaidArrayDevice, self).__init__(name, fmt=fmt, size=size,
                                                parents=parents, exists=True,
                                                sysfsPath=sysfsPath)

        self._raidSet = raidSet

    @property
    def raidSet(self):
        return self._raidSet

    @property
    def devices(self):
        """ Return a list of this array's member device instances. """
        return self.parents

    def deactivate(self):
        """ Deactivate the raid set. """
        log_method_call(self, self.name, status=self.status)
        # This call already checks if the set is not active.
        self._raidSet.deactivate()

    def activate(self):
        """ Activate the raid set. """
        log_method_call(self, self.name, status=self.status)
        # This call already checks if the set is active.
        self._raidSet.activate(mknod=True)
        udev.settle()

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        self.activate()

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        if not self._preTeardown(recursive=recursive):
            return

        log.debug("not tearing down dmraid device %s", self.name)

    def _add(self, member):
        raise NotImplementedError()

    def _remove(self, member):
        raise NotImplementedError()

    @property
    def description(self):
        return "BIOS RAID set (%s)" % self._raidSet.rs.set_type

    @property
    def model(self):
        return self.description

    def dracutSetupArgs(self):
        return set(["rd.dm.uuid=%s" % self.name])

class MultipathDevice(DMDevice):
    """ A multipath device """
    _type = "dm-multipath"
    _packages = ["device-mapper-multipath"]
    _services = ["multipathd"]
    _partitionable = True
    _isDisk = True

    def __init__(self, name, fmt=None, size=None, serial=None,
                 parents=None, sysfsPath=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword serial: the device's serial number
            :type serial: str

            MultipathDevices always exist. Blivet cannot create or destroy
            them.
        """

        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfsPath=sysfsPath,
                          exists=True)

        self.identity = serial
        self.config = {
            'wwid' : self.identity,
            'mode' : '0600',
            'uid' : '0',
            'gid' : '0',
        }

    @property
    def wwid(self):
        identity = self.identity
        ret = []
        while identity:
            ret.append(identity[:2])
            identity = identity[2:]
        return ":".join(ret)

    @property
    def model(self):
        if not self.parents:
            return ""
        return self.parents[0].model

    @property
    def vendor(self):
        if not self.parents:
            return ""
        return self.parents[0].vendor

    @property
    def description(self):
        return "WWID %s" % (self.wwid,)

    def addParent(self, parent):
        """ Add a parent device to the mpath. """
        log_method_call(self, self.name, status=self.status)
        if self.status:
            self.teardown()
            self.parents.append(parent)
            self.setup()
        else:
            self.parents.append(parent)

    def deactivate(self):
        """
        This is never called, included just for documentation.

        If we called this during teardown(), we wouldn't be able to get parted
        object because /dev/mapper/mpathX wouldn't exist.
        """
        if self.exists and os.path.exists(self.path):
            #self.teardownPartitions()
            #rc = util.run_program(["multipath", '-f', self.name])
            #if rc:
            #    raise MPathError("multipath deactivation failed for '%s'" %
            #                    self.name)
            bdev = block.getDevice(self.name)
            devmap = block.getMap(major=bdev[0], minor=bdev[1])
            if devmap.open_count:
                return
            try:
                block.removeDeviceMap(devmap)
            except Exception as e:
                raise errors.MPathError("failed to tear down multipath device %s: %s"
                                % (self.name, e))

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        udev.settle()
        rc = util.run_program(["multipath", self.name])
        if rc:
            raise errors.MPathError("multipath activation failed for '%s'" %
                            self.name, hardware_fault=True)

    def _postSetup(self):
        StorageDevice._postSetup(self)
        self.setupPartitions()
        udev.settle()

class iScsiDiskDevice(DiskDevice, NetworkStorageDevice):
    """ An iSCSI disk. """
    _type = "iscsi"
    _packages = ["iscsi-initiator-utils", "dracut-network"]

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword node: ???
            :type node: str
            :keyword ibft: use iBFT
            :type ibft: bool
            :keyword nic: name of NIC to use
            :type nic: str
            :keyword initiator: initiator name
            :type initiator: str
            :keyword fw_name: qla4xxx partial offload
            :keyword fw_address: qla4xxx partial offload
            :keyword fw_port: qla4xxx partial offload
        """
        self.node = kwargs.pop("node")
        self.ibft = kwargs.pop("ibft")
        self.nic = kwargs.pop("nic")
        self.initiator = kwargs.pop("initiator")
        self.offload = False

        if self.node is None:
            # qla4xxx partial offload
            self.offload = True
            name = kwargs.pop("fw_name")
            address = kwargs.pop("fw_address")
            port = kwargs.pop("fw_port")
            DiskDevice.__init__(self, device, **kwargs)
            NetworkStorageDevice.__init__(self,
                                          host_address=address,
                                          nic=self.nic)
            log.debug("created new iscsi disk %s %s:%s using fw initiator %s",
                      name, address, port, self.initiator)
        else:
            DiskDevice.__init__(self, device, **kwargs)
            NetworkStorageDevice.__init__(self, host_address=self.node.address,
                                          nic=self.nic)
            log.debug("created new iscsi disk %s %s:%d via %s:%s", self.node.name,
                                                                   self.node.address,
                                                                   self.node.port,
                                                                   self.node.iface,
                                                                   self.nic)

    def dracutSetupArgs(self):
        if self.ibft:
            return set(["iscsi_firmware"])

        # qla4xxx partial offload
        if self.node is None:
            return set()

        address = self.node.address
        # surround ipv6 addresses with []
        if ":" in address:
            address = "[%s]" % address

        netroot="netroot=iscsi:"
        auth = self.node.getAuth()
        if auth:
            netroot += "%s:%s" % (auth.username, auth.password)
            if len(auth.reverse_username) or len(auth.reverse_password):
                netroot += ":%s:%s" % (auth.reverse_username,
                                       auth.reverse_password)

        iface_spec = ""
        if self.nic != "default":
            iface_spec = ":%s:%s" % (self.node.iface, self.nic)
        netroot += "@%s::%d%s::%s" % (address,
                                      self.node.port,
                                      iface_spec,
                                      self.node.name)

        initiator = "rd.iscsi.initiator=%s" % self.initiator

        return set([netroot, initiator])

class FcoeDiskDevice(DiskDevice, NetworkStorageDevice):
    """ An FCoE disk. """
    _type = "fcoe"
    _packages = ["fcoe-utils", "dracut-network"]

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword nic: name of NIC to use
            :keyword identifier: ???
        """
        self.nic = kwargs.pop("nic")
        self.identifier = kwargs.pop("identifier")
        DiskDevice.__init__(self, device, **kwargs)
        NetworkStorageDevice.__init__(self, nic=self.nic)
        log.debug("created new fcoe disk %s (%s) @ %s",
                  device, self.identifier, self.nic)

    def dracutSetupArgs(self):
        dcb = True

        for nic, dcb, _auto_vlan in fcoe().nics:
            if nic == self.nic:
                break
        else:
            return set()

        if dcb:
            dcbOpt = "dcb"
        else:
            dcbOpt = "nodcb"

        if self.nic in fcoe().added_nics:
            return set(["fcoe=%s:%s" % (self.nic, dcbOpt)])
        else:
            return set(["fcoe=edd:%s" % dcbOpt])

class ZFCPDiskDevice(DiskDevice):
    """ A mainframe ZFCP disk. """
    _type = "zfcp"

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword hba_id: ???
            :keyword wwpn: ???
            :keyword fcp_lun: ???
        """
        self.hba_id = kwargs.pop("hba_id")
        self.wwpn = kwargs.pop("wwpn")
        self.fcp_lun = kwargs.pop("fcp_lun")
        DiskDevice.__init__(self, device, **kwargs)

    def __repr__(self):
        s = DiskDevice.__repr__(self)
        s += ("  hba_id = %(hba_id)s  wwpn = %(wwpn)s  fcp_lun = %(fcp_lun)s" %
              {"hba_id": self.hba_id,
               "wwpn": self.wwpn,
               "fcp_lun": self.fcp_lun})
        return s

    @property
    def description(self):
        return "FCP device %(device)s with WWPN %(wwpn)s and LUN %(lun)s" \
               % {'device': self.hba_id,
                  'wwpn': self.wwpn,
                  'lun': self.fcp_lun}

    def dracutSetupArgs(self):
        return set(["rd.zfcp=%s,%s,%s" % (self.hba_id, self.wwpn, self.fcp_lun,)])

class DASDDevice(DiskDevice):
    """ A mainframe DASD. """
    _type = "dasd"

    def __init__(self, device, **kwargs):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword format: this device's formatting
            :type format: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword busid: bus ID
            :keyword opts: options
            :type opts: dict with option name keys and option value values
        """
        self.busid = kwargs.pop('busid')
        self.opts = kwargs.pop('opts')
        DiskDevice.__init__(self, device, **kwargs)

    @property
    def description(self):
        return "DASD device %s" % self.busid

    def getOpts(self):
        return ["%s=%s" % (k, v) for k, v in self.opts.items() if v == '1']

    def dracutSetupArgs(self):
        conf = "/etc/dasd.conf"
        line = None
        if os.path.isfile(conf):
            f = open(conf)
            # grab the first line that starts with our busID
            for l in f.readlines():
                if l.startswith(self.busid):
                    line = l.rstrip()
                    break

            f.close()

        # See if we got a line.  If not, grab our getOpts
        if not line:
            line = self.busid
            for devopt in self.getOpts():
                line += " %s" % devopt

        # Create a translation mapping from dasd.conf format to module format
        translate = {'use_diag': 'diag',
                     'readonly': 'ro',
                     'erplog': 'erplog',
                     'failfast': 'failfast'}

        # this is a really awkward way of determining if the
        # feature found is actually desired (1, not 0), plus
        # translating that feature into the actual kernel module
        # value
        opts = []
        parts = line.split()
        for chunk in parts[1:]:
            try:
                feat, val = chunk.split('=')
                if int(val):
                    opts.append(translate[feat])
            except (ValueError, KeyError):
                # If we don't know what the feature is (feat not in translate
                # or if we get a val that doesn't cleanly convert to an int
                # we can't do anything with it.
                log.warning("failed to parse dasd feature %s", chunk)

        if opts:
            return set(["rd.dasd=%s(%s)" % (self.busid,
                                            ":".join(opts))])
        else:
            return set(["rd.dasd=%s" % self.busid])
