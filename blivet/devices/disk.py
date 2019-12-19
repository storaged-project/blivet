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

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import os

from .. import errors
from .. import util
from ..devicelibs import disk as disklib
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..size import Size
from ..tasks import availability

from ..fcoe import fcoe

import logging
log = logging.getLogger("blivet")

from .lib import Tags
from .storage import StorageDevice
from .container import ContainerDevice
from .network import NetworkStorageDevice
from .dm import DMDevice


class DiskDevice(StorageDevice):

    """ A local/generic disk.

        This is not the only kind of device that is treated as a disk. More
        useful than checking isinstance(device, DiskDevice) is checking
        device.is_disk.
    """
    _type = "disk"
    _partitionable = True
    _is_disk = True

    def __init__(self, name, fmt=None,
                 size=None, major=None, minor=None, sysfs_path='',
                 parents=None, serial=None, vendor="", model="", bus="", wwn=None,
                 uuid=None, exists=True):
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
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword removable: whether or not this is a removable device
            :type removable: bool
            :keyword serial: the ID_SERIAL_RAW, ID_SERIAL or ID_SERIAL_SHORT for
                             this device (which one is available)
            :type serial: str
            :keyword vendor: the manufacturer of this Device
            :type vendor: str
            :keyword model: manufacturer's device model string
            :type model: str
            :keyword bus: the interconnect this device uses
            :type bus: str
            :keyword str wwn: the disk's WWN

            DiskDevices always exist.
        """
        StorageDevice.__init__(self, name, fmt=fmt, size=size,
                               major=major, minor=minor, exists=exists,
                               sysfs_path=sysfs_path, parents=parents,
                               serial=serial, model=model,
                               vendor=vendor, bus=bus, uuid=uuid)

        self.wwn = wwn or None

        try:
            ssd = int(util.get_sysfs_attr(self.sysfs_path, "queue/rotational")) == 0
        except TypeError:  # get_sysfs_attr returns None from all error paths
            ssd = False

        self.tags.add(Tags.local)
        if ssd:
            self.tags.add(Tags.ssd)
        if bus == "usb":
            self.tags.add(Tags.usb)
        if self.removable:
            self.tags.add(Tags.removable)

    def _clear_local_tags(self):
        local_tags = set([Tags.local, Tags.ssd, Tags.usb, Tags.removable])
        self.tags = self.tags.difference(local_tags)

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  removable = %(removable)s  wwn = %(wwn)s" % {"removable": self.removable,
                                                              "wwn": self.wwn})
        return s

    @property
    def media_present(self):
        if flags.testing:
            return True

        # Some drivers (cpqarray <blegh>) make block device nodes for
        # controllers with no disks attached and then report a 0 size,
        # treat this as no media present
        return self.exists and self.current_size > Size(0)

    @property
    def description(self):
        return " ".join(s for s in (self.vendor, self.model, self.wwn) if s)

    def _pre_destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        if not self.media_present:
            raise errors.DeviceError("cannot destroy disk with no media", self.name)

        StorageDevice._pre_destroy(self)

    @property
    def _volume(self):
        return disklib.volumes.get(self.path)

    @property
    def raid_system(self):
        return self._volume.system if self._volume is not None else None

    @property
    def raid_level(self):
        return self._volume.raid_type if self._volume is not None else None

    @property
    def raid_stripe_size(self):
        return self._volume.raid_stripe_size if self._volume is not None else None

    @property
    def raid_disk_count(self):
        return self._volume.raid_disk_count if self._volume is not None else None


class DiskFile(DiskDevice):

    """ This is a file that we will pretend is a disk.

        This is intended only for testing purposes. The benefit of this class
        is that you can instantiate a disk-like device with a working disklabel
        class as a non-root user. It is not known how the system will behave if
        partitions are committed to one of these disks.
    """
    _dev_dir = ""

    def __init__(self, name, fmt=None,
                 size=None, major=None, minor=None, sysfs_path='',
                 parents=None, serial=None, vendor="", model="", bus="",
                 exists=True):
        """
            :param str name: the full path to the backing regular file
            :keyword :class:`~.formats.DeviceFormat` fmt: the device's format
        """
        _name = os.path.basename(name)
        self._dev_dir = os.path.dirname(name)

        super(DiskFile, self).__init__(_name, fmt=fmt, size=size,
                                       major=major, minor=minor, sysfs_path=sysfs_path,
                                       parents=parents, serial=serial, vendor=vendor,
                                       model=model, bus=bus, exists=exists)

    #
    # Regular files do not have sysfs entries.
    #
    @property
    def sysfs_path(self):
        return ""

    @sysfs_path.setter
    def sysfs_path(self, value):
        pass

    def update_sysfs_path(self):
        pass

    def read_current_size(self):
        size = Size(0)
        if self.exists and os.path.exists(self.path):
            st = os.stat(self.path)
            size = Size(st.st_size)

        return size


class DMRaidArrayDevice(DMDevice, ContainerDevice):

    """ A dmraid (device-mapper RAID) device """
    _type = "dm-raid array"
    _packages = ["dmraid"]
    _partitionable = True
    _is_disk = True
    _format_class_name = property(lambda s: "dmraidmember")
    _format_uuid_attr = property(lambda s: None)
    _external_dependencies = [availability.BLOCKDEV_DM_PLUGIN_RAID]

    def __init__(self, name, fmt=None,
                 size=None, parents=None, sysfs_path='', wwn=None):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword str wwn: the device's WWN

            DMRaidArrayDevices always exist. Blivet cannot create or destroy
            them.
        """
        super(DMRaidArrayDevice, self).__init__(name, fmt=fmt, size=size,
                                                parents=parents, exists=True,
                                                sysfs_path=sysfs_path)
        self.wwn = wwn or None
        self.tags.add(Tags.local)

    @property
    def devices(self):
        """ Return a list of this array's member device instances. """
        return self.parents

    def deactivate(self):
        """ Deactivate the raid set. """
        log_method_call(self, self.name, status=self.status)
        # This call already checks if the set is not active.
        blockdev.dm.deactivate_raid_set(self.name)

    def activate(self):
        """ Activate the raid set. """
        log_method_call(self, self.name, status=self.status)
        # This call already checks if the set is active.
        blockdev.dm.activate_raid_set(self.name)
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
        if not self._pre_teardown(recursive=recursive):
            return

        log.debug("not tearing down dmraid device %s", self.name)

    def _add(self, member):
        raise NotImplementedError()

    def _remove(self, member):
        raise NotImplementedError()

    @property
    def description(self):
        return "BIOS RAID set (%s)" % blockdev.dm.get_raid_set_type(self.name)

    @property
    def model(self):
        return self.description

    def dracut_setup_args(self):
        return set(["rd.dm.uuid=%s" % self.name])


class MultipathDevice(DMDevice):

    """ A multipath device """
    _type = "dm-multipath"
    _packages = ["device-mapper-multipath"]
    _partitionable = True
    _is_disk = True
    _external_dependencies = [availability.MULTIPATH_APP]

    def __init__(self, name, fmt=None, size=None, wwn=None,
                 parents=None, sysfs_path=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword size: the device's size
            :type size: :class:`~.size.Size`
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat` or a subclass of it
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword str wwn: the device's WWN

            MultipathDevices always exist. Blivet cannot create or destroy
            them.
        """
        DMDevice.__init__(self, name, fmt=fmt, size=size,
                          parents=parents, sysfs_path=sysfs_path,
                          exists=True)
        self.wwn = wwn or None

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
        return "WWID %s" % self.wwn

    def add_parent(self, parent):
        """ Add a parent device to the mpath. """
        log_method_call(self, self.name, status=self.status)
        if self.status:
            self.teardown()
            self.parents.append(parent)
            self.setup()
        else:
            self.parents.append(parent)

    def _add_parent(self, parent):
        super(MultipathDevice, self)._add_parent(parent)
        if Tags.remote not in self.tags and Tags.remote in parent.tags:
            self.tags.add(Tags.remote)

    def _remove_parent(self, parent):
        super(MultipathDevice, self)._remove_parent(parent)
        if Tags.remote in self.tags and Tags.remote in parent.tags and \
           not any(p for p in self.parents if Tags.remote in p.tags and p != parent):
            self.tags.remove(Tags.remote)

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        udev.settle()
        rc = util.run_program(["multipath", self.name])
        if rc:
            raise errors.MPathError("multipath activation failed for '%s'" %
                                    self.name, hardware_fault=True)

    def _post_setup(self):
        StorageDevice._post_setup(self)
        self.setup_partitions()
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
            :keyword str wwn: the disk's WWN
            :keyword target: the name of the iscsi target
            :type target: str
            :keyword lun: lun of the target
            :type node: str
            :keyword iface: name of network interface to use for operation
            :type iface: str
            :keyword initiator: initiator name
            :type initiator: str
            :keyword offload: a partial offload device (qla4xxx)
            :type: bool
            :keyword address: ip address of the target
            :type: str
            :keyword port: port of the target
            :type: str
        """
        # Backward compatibility attributes - to be removed
        self.node = kwargs.pop("node")
        self.ibft = kwargs.pop("ibft")
        self.nic = kwargs.pop("nic")

        self.initiator = kwargs.pop("initiator")
        self.offload = kwargs.pop("offload")
        name = kwargs.pop("name")
        self.target = kwargs.pop("target")
        try:
            self.lun = int(kwargs.pop("lun"))
        except TypeError as e:
            log.warning("Failed to set lun attribute of iscsi disk: %s", e)
            self.lun = None

        self.address = kwargs.pop("address")
        self.port = kwargs.pop("port")
        self.iface = kwargs.pop("iface")
        self.id_path = kwargs.pop("id_path")
        DiskDevice.__init__(self, device, **kwargs)
        NetworkStorageDevice.__init__(self, host_address=self.address, nic=self.iface)
        log.debug("created new iscsi disk %s from target: %s lun: %s portal: %s:%s interface: %s partial offload: %s)",
                  name, self.target, self.lun, self.address, self.port, self.iface, self.offload)

        self._clear_local_tags()

    def dracut_setup_args(self):
        if self.ibft:
            return set(["rd.iscsi.firmware"])

        # qla4xxx partial offload
        if self.node is None:
            return set()

        address = self.node.address
        # surround ipv6 addresses with []
        if ":" in address:
            address = "[%s]" % address

        netroot = "netroot=iscsi:"
        if self.node.username and self.node.password:
            netroot += "%s:%s" % (self.node.username, self.node.password)
            if self.node.r_username and self.node.r_password:
                netroot += ":%s:%s" % (self.node.r_username,
                                       self.node.r_password)

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
            :keyword str wwn: the disk's WWN
            :keyword nic: name of NIC to use
            :keyword identifier: ???
        """
        self.nic = kwargs.pop("nic")
        self.identifier = kwargs.pop("identifier")
        self.id_path = kwargs.pop("id_path")
        DiskDevice.__init__(self, device, **kwargs)
        NetworkStorageDevice.__init__(self, nic=self.nic)
        log.debug("created new fcoe disk %s (%s) @ %s",
                  device, self.identifier, self.nic)

        self._clear_local_tags()

    def dracut_setup_args(self):
        dcb = True

        for nic, dcb, _auto_vlan in fcoe().nics:
            if nic == self.nic:
                break
        else:
            return set()

        if dcb:
            dcb_opt = "dcb"
        else:
            dcb_opt = "nodcb"

        if self.nic in fcoe().added_nics:
            return set(["fcoe=%s:%s" % (self.nic, dcb_opt)])
        else:
            return set(["fcoe=edd:%s" % dcb_opt])


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
            :keyword str wwn: the disk's WWN
            :keyword hba_id: ???
            :keyword wwpn: ???
            :keyword fcp_lun: ???
        """
        self.hba_id = kwargs.pop("hba_id")
        self.wwpn = kwargs.pop("wwpn")
        self.fcp_lun = kwargs.pop("fcp_lun")
        DiskDevice.__init__(self, device, **kwargs)
        self._clear_local_tags()
        self.tags.add(Tags.remote)

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

    def dracut_setup_args(self):
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
            :keyword str wwn: the disk's WWN
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

    def get_opts(self):
        return ["%s=%s" % (k, v) for k, v in self.opts.items() if v == '1']

    def dracut_setup_args(self):
        conf = "/etc/dasd.conf"
        line = None
        if os.path.isfile(conf):
            f = open(conf)
            # grab the first line that starts with our bus_id
            for l in f.readlines():
                if l.startswith(self.busid):
                    line = l.rstrip()
                    break

            f.close()

        # See if we got a line.  If not, grab our get_opts
        if not line:
            line = self.busid
            for devopt in self.get_opts():
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


class NVDIMMNamespaceDevice(DiskDevice):

    """ Non-volatile memory namespace """
    _type = "nvdimm"
    _packages = ["ndctl"]

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
            :keyword mode: mode of the namespace
            :type mode: str
            :keyword devname: name of the namespace (e.g. 'namespace0.0')
            :type devname: str
            :keyword sector_size: sector size of the namespace in sector mode
            :type sector_size: str
        """
        self.mode = kwargs.pop("mode")
        self.devname = kwargs.pop("devname")
        self.id_path = kwargs.pop("id_path")
        self._sector_size = kwargs.pop("sector_size")

        DiskDevice.__init__(self, device, **kwargs)

        self._clear_local_tags()
        self.tags.add(Tags.local)
        self.tags.add(Tags.nvdimm)

    def __repr__(self):
        s = DiskDevice.__repr__(self)
        s += ("  mode = %(mode)s  devname = %(devname)s" %
              {"mode": self.mode,
               "devname": self.devname})
        if self.sector_size:
            s += ("  sector size = %(sector_size)s" % {"sector_size": self.sector_size})
        return s

    @property
    def description(self):
        return "NVDIMM namespace %(devname)s in %(mode)s mode exported as %(path)s" \
               % {'devname': self.devname,
                  'mode': self.mode,
                  'path': self.path}

    @property
    def sector_size(self):
        return self._sector_size
