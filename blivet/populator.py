# populator.py
# Backend code for populating a DeviceTree.
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

import os
import re
import shutil
import pprint
import copy
import parted

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from .errors import CorruptGPTError, DeviceError, DeviceTreeError, DiskLabelScanError, DuplicateVGError, FSError, InvalidDiskLabelError, LUKSError, NoSlavesError
from .devices import BTRFSSubVolumeDevice, BTRFSVolumeDevice, BTRFSSnapShotDevice
from .devices import DASDDevice, DMDevice, DMLinearDevice, DMRaidArrayDevice, DiskDevice
from .devices import FcoeDiskDevice, FileDevice, LoopDevice, LUKSDevice
from .devices import LVMLogicalVolumeDevice, LVMVolumeGroupDevice
from .devices import LVMThinPoolDevice, LVMThinLogicalVolumeDevice
from .devices import LVMSnapShotDevice, LVMThinSnapShotDevice
from .devices import MDRaidArrayDevice, MDBiosRaidArrayDevice
from .devices import MDContainerDevice
from .devices import MultipathDevice, OpticalDevice
from .devices import PartitionDevice, ZFCPDiskDevice, iScsiDiskDevice
from .devices import devicePathToName
from .devices.lvm import get_internal_lv_class
from . import formats
from .devicelibs import lvm
from .devicelibs import raid
from . import udev
from . import util
from .util import open  # pylint: disable=redefined-builtin
from .flags import flags
from .storage_log import log_exception_info, log_method_call
from .i18n import _
from .size import Size

import logging
log = logging.getLogger("blivet")

def parted_exn_handler(exn_type, exn_options, exn_msg):
    """ Answer any of parted's yes/no questions in the affirmative.

        This allows us to proceed with partially corrupt gpt disklabels.
    """
    log.info("parted exception: %s", exn_msg)
    ret = parted.EXCEPTION_RESOLVE_UNHANDLED
    if exn_type == parted.EXCEPTION_TYPE_ERROR and \
       exn_options == parted.EXCEPTION_OPT_YES_NO:
        ret = parted.EXCEPTION_RESOLVE_YES
    return ret

class Populator(object):
    def __init__(self, devicetree=None, conf=None, passphrase=None,
                 luksDict=None, iscsi=None, dasd=None):
        """
            :keyword conf: storage discovery configuration
            :type conf: :class:`~.StorageDiscoveryConfig`
            :keyword passphrase: default LUKS passphrase
            :keyword luksDict: a dict with UUID keys and passphrase values
            :type luksDict: dict
            :keyword iscsi: ISCSI control object
            :type iscsi: :class:`~.iscsi.iscsi`
            :keyword dasd: DASD control object
            :type dasd: :class:`~.dasd.DASD`

        """
        self.devicetree = devicetree

        # indicates whether or not the tree has been fully populated
        self.populated = False

        self.exclusiveDisks = getattr(conf, "exclusiveDisks", [])
        self.ignoredDisks = getattr(conf, "ignoredDisks", [])
        self.iscsi = iscsi
        self.dasd = dasd

        self.diskImages = {}
        images = getattr(conf, "diskImages", {})
        if images:
            # this will overwrite self.exclusiveDisks
            self.setDiskImages(images)

        # protected device specs as provided by the user
        self.protectedDevSpecs = getattr(conf, "protectedDevSpecs", [])
        self.liveBackingDevice = None

        # names of protected devices at the time of tree population
        self.protectedDevNames = []

        self.unusedRaidMembers = []

        self.__passphrases = []
        if passphrase:
            self.__passphrases.append(passphrase)

        self.__luksDevs = {}
        if luksDict and isinstance(luksDict, dict):
            self.__luksDevs = luksDict
            self.__passphrases.extend([p for p in luksDict.values() if p])

        self._cleanup = False

    def setDiskImages(self, images):
        """ Set the disk images and reflect them in exclusiveDisks.

            :param images: dict with image name keys and filename values
            :type images: dict

            .. note::

                Disk images are automatically exclusive. That means that, in the
                presence of disk images, any local storage not associated with
                the disk images is ignored.
        """
        self.diskImages = images
        # disk image files are automatically exclusive
        self.exclusiveDisks = list(self.diskImages.keys())

    def addIgnoredDisk(self, disk):
        self.ignoredDisks.append(disk)
        lvm.lvm_cc_addFilterRejectRegexp(disk)

    def isIgnored(self, info):
        """ Return True if info is a device we should ignore.

            :param info: udevdb device entry
            :type info: dict
            :returns: whether the device will be ignored
            :rtype: bool

        """
        sysfs_path = udev.device_get_sysfs_path(info)
        name = udev.device_get_name(info)
        if not sysfs_path:
            return None

        # Special handling for mdraid external metadata sets (mdraid BIOSRAID):
        # 1) The containers are intermediate devices which will never be
        # in exclusiveDisks
        # 2) Sets get added to exclusive disks with their dmraid set name by
        # the filter ui.  Note that making the ui use md names instead is not
        # possible as the md names are simpy md# and we cannot predict the #
        if udev.device_is_md(info) and \
           udev.device_get_md_level(info) == "container":
            return False

        if udev.device_get_md_container(info) and \
               udev.device_is_md(info) and \
               udev.device_get_md_name(info):
            md_name = udev.device_get_md_name(info)
            # mdadm may have appended _<digit>+ if the current hostname
            # does not match the one in the array metadata
            alt_name = re.sub(r"_\d+$", "", md_name)
            raw_pattern = "isw_[a-z]*_%s"
            # XXX FIXME: This is completely insane.
            for i in range(0, len(self.exclusiveDisks)):
                if re.match(raw_pattern % md_name, self.exclusiveDisks[i]) or \
                   re.match(raw_pattern % alt_name, self.exclusiveDisks[i]):
                    self.exclusiveDisks[i] = name
                    return False

        # never ignore mapped disk images. if you don't want to use them,
        # don't specify them in the first place
        if udev.device_is_dm_anaconda(info) or udev.device_is_dm_livecd(info):
            return False

        # Ignore loop and ram devices, we normally already skip these in
        # udev.py: enumerate_block_devices(), but we can still end up trying
        # to add them to the tree when they are slaves of other devices, this
        # happens for example with the livecd
        if name.startswith("ram"):
            return True

        if name.startswith("loop"):
            # ignore loop devices unless they're backed by a file
            return (not blockdev.loop.get_backing_file(name))

        # FIXME: check for virtual devices whose slaves are on the ignore list

    def _isIgnoredDisk(self, disk):
        return self.devicetree._isIgnoredDisk(disk)

    def udevDeviceIsDisk(self, info):
        """ Return True if the udev device looks like a disk.

            :param info: udevdb device entry
            :type info: dict
            :returns: whether the device is a disk
            :rtype: bool

            We want exclusiveDisks to operate on anything that could be
            considered a directly usable disk, ie: fwraid array, mpath, or disk.

            Unfortunately, since so many things are represented as disks by
            udev/sysfs, we have to define what is a disk in terms of what is
            not a disk.
        """
        return (udev.device_is_disk(info) and
                not (udev.device_is_cdrom(info) or
                     udev.device_is_partition(info) or
                     udev.device_is_dm_partition(info) or
                     udev.device_is_dm_lvm(info) or
                     udev.device_is_dm_crypt(info) or
                     (udev.device_is_md(info) and
                      not udev.device_get_md_container(info))))

    def _addSlaveDevices(self, info):
        """ Add all slaves of a device, raising DeviceTreeError on failure.

            :param :class:`pyudev.Device` info: the device's udev info
            :raises: :class:`~.errors.DeviceTreeError if no slaves are found or
                     if we fail to add any slave
            :returns: a list of slave devices
            :rtype: list of :class:`~.StorageDevice`
        """
        name = udev.device_get_name(info)
        sysfs_path = udev.device_get_sysfs_path(info)
        slave_dir = os.path.normpath("%s/slaves" % sysfs_path)
        slave_names = os.listdir(slave_dir)
        slave_devices = []
        if not slave_names:
            log.error("no slaves found for %s", name)
            raise NoSlavesError("no slaves found for device %s" % name)

        for slave_name in slave_names:
            path = os.path.normpath("%s/%s" % (slave_dir, slave_name))
            slave_info = udev.get_device(os.path.realpath(path))

            # cciss in sysfs is "cciss!cXdYpZ" but we need "cciss/cXdYpZ"
            slave_name = udev.device_get_name(slave_info).replace("!", "/")

            if not slave_info:
                log.warning("unable to get udev info for %s", slave_name)

            slave_dev = self.getDeviceByName(slave_name)
            if not slave_dev and slave_info:
                # we haven't scanned the slave yet, so do it now
                self.addUdevDevice(slave_info)
                slave_dev = self.getDeviceByName(slave_name)
                if slave_dev is None:
                    if udev.device_is_dm_lvm(info):
                        if slave_name not in self.devicetree.lvInfo:
                            # we do not expect hidden lvs to be in the tree
                            continue

                    # if the current slave is still not in
                    # the tree, something has gone wrong
                    log.error("failure scanning device %s: could not add slave %s", name, slave_name)
                    msg = "failed to add slave %s of device %s" % (slave_name,
                                                                   name)
                    raise DeviceTreeError(msg)

            slave_devices.append(slave_dev)

        return slave_devices

    def addUdevLVDevice(self, info):
        name = udev.device_get_name(info)
        log_method_call(self, name=name)

        vg_name = udev.device_get_lv_vg_name(info)
        device = self.getDeviceByName(vg_name, hidden=True)
        if device and not isinstance(device, LVMVolumeGroupDevice):
            log.warning("found non-vg device with name %s", vg_name)
            device = None

        self._addSlaveDevices(info)

        # LVM provides no means to resolve conflicts caused by duplicated VG
        # names, so we're just being optimistic here. Woo!
        vg_name = udev.device_get_lv_vg_name(info)
        vg_device = self.getDeviceByName(vg_name)
        if not vg_device:
            log.error("failed to find vg '%s' after scanning pvs", vg_name)

        return self.getDeviceByName(name)

    def addUdevDMDevice(self, info):
        name = udev.device_get_name(info)
        log_method_call(self, name=name)
        sysfs_path = udev.device_get_sysfs_path(info)
        slave_devices = self._addSlaveDevices(info)
        device = self.getDeviceByName(name)

        # if this is a luks device whose map name is not what we expect,
        # fix up the map name and see if that sorts us out
        handle_luks = (udev.device_is_dm_luks(info) and
                        (self._cleanup or not flags.installer_mode))
        if device is None and handle_luks and slave_devices:
            slave_dev = slave_devices[0]
            slave_dev.format.mapName = name
            slave_info = udev.get_device(slave_dev.sysfsPath)
            self.handleUdevLUKSFormat(slave_info, slave_dev)

            # try once more to get the device
            device = self.getDeviceByName(name)

        # create a device for the livecd OS image(s)
        if device is None and udev.device_is_dm_livecd(info):
            device = DMDevice(name, dmUuid=info.get('DM_UUID'),
                              sysfsPath=sysfs_path, exists=True,
                              parents=[slave_devices[0]])
            device.protected = True
            device.controllable = False
            self.devicetree._addDevice(device)

        # if we get here, we found all of the slave devices and
        # something must be wrong -- if all of the slaves are in
        # the tree, this device should be as well
        if device is None:
            lvm.lvm_cc_addFilterRejectRegexp(name)
            log.warning("ignoring dm device %s", name)

        return device

    def addUdevMultiPathDevice(self, info):
        name = udev.device_get_name(info)
        log_method_call(self, name=name)

        slave_devices = self._addSlaveDevices(info)

        device = None
        if slave_devices:
            try:
                serial = info["DM_UUID"].split("-", 1)[1]
            except (IndexError, AttributeError):
                log.error("multipath device %s has no DM_UUID", name)
                raise DeviceTreeError("multipath %s has no DM_UUID" % name)

            device = MultipathDevice(name, parents=slave_devices,
                                     sysfsPath=udev.device_get_sysfs_path(info),
                                     serial=serial)
            self.devicetree._addDevice(device)

        return device

    def addUdevMDDevice(self, info):
        name = udev.device_get_md_name(info)
        log_method_call(self, name=name)

        try:
            self._addSlaveDevices(info)
        except NoSlavesError:
            log.error("no slaves found for mdarray %s, skipping", name)
            return None

        # try to get the device again now that we've got all the slaves
        device = self.getDeviceByName(name, incomplete=flags.allow_imperfect_devices)

        if device is None:
            try:
                uuid = udev.device_get_md_uuid(info)
            except KeyError:
                log.warning("failed to obtain uuid for mdraid device")
            else:
                device = self.getDeviceByUuid(uuid, incomplete=flags.allow_imperfect_devices)

        if device and name:
            # update the device instance with the real name in case we had to
            # look it up by something other than name
            device.name = name

        if device is None:
            # if we get here, we found all of the slave devices and
            # something must be wrong -- if all of the slaves are in
            # the tree, this device should be as well
            if name is None:
                name = udev.device_get_name(info)
                path = "/dev/" + name
            else:
                path = "/dev/md/" + name

            log.error("failed to scan md array %s", name)
            try:
                blockdev.md.deactivate(path)
            except blockdev.MDRaidError:
                log.error("failed to stop broken md array %s", name)

        return device

    def addUdevPartitionDevice(self, info, disk=None):
        name = udev.device_get_name(info)
        log_method_call(self, name=name)
        sysfs_path = udev.device_get_sysfs_path(info)

        if name.startswith("md"):
            name = blockdev.md.name_from_node(name)
            device = self.getDeviceByName(name)
            if device:
                return device

        if disk is None:
            disk_name = os.path.basename(os.path.dirname(sysfs_path))
            disk_name = disk_name.replace('!','/')
            if disk_name.startswith("md"):
                disk_name = blockdev.md.name_from_node(disk_name)

            disk = self.getDeviceByName(disk_name)

        if disk is None:
            # create a device instance for the disk
            new_info = udev.get_device(os.path.dirname(sysfs_path))
            if new_info:
                self.addUdevDevice(new_info)
                disk = self.getDeviceByName(disk_name)

            if disk is None:
                # if the current device is still not in
                # the tree, something has gone wrong
                log.error("failure scanning device %s", disk_name)
                lvm.lvm_cc_addFilterRejectRegexp(name)
                return

        # If this is the live device protect the whole disk
        if self.liveBackingDevice == name and not disk.protected \
           and disk.name not in self.protectedDevNames:
            log.info("Protecting %s, parent of live device %s", disk.name, name)
            disk.protected = True
            self.protectedDevNames.append(disk.name)

        if not disk.partitioned:
            # Ignore partitions on:
            #  - devices we do not support partitioning of, like logical volumes
            #  - devices that do not have a usable disklabel
            #  - devices that contain disklabels made by isohybrid
            #
            if disk.partitionable and \
               disk.format.type != "iso9660" and \
               not disk.format.hidden and \
               not self._isIgnoredDisk(disk):
                if info.get("ID_PART_TABLE_TYPE") == "gpt":
                    msg = "corrupt gpt disklabel on disk %s" % disk.name
                    cls = CorruptGPTError
                else:
                    msg = "failed to scan disk %s" % disk.name
                    cls = DiskLabelScanError

                raise cls(msg)

            # there's no need to filter partitions on members of multipaths or
            # fwraid members from lvm since multipath and dmraid are already
            # active and lvm should therefore know to ignore them
            if not disk.format.hidden:
                lvm.lvm_cc_addFilterRejectRegexp(name)

            log.debug("ignoring partition %s on %s", name, disk.format.type)
            return

        device = None
        try:
            device = PartitionDevice(name, sysfsPath=sysfs_path,
                                     major=udev.device_get_major(info),
                                     minor=udev.device_get_minor(info),
                                     exists=True, parents=[disk])
        except DeviceError as e:
            # corner case sometime the kernel accepts a partition table
            # which gets rejected by parted, in this case we will
            # prompt to re-initialize the disk, so simply skip the
            # faulty partitions.
            # XXX not sure about this
            log.error("Failed to instantiate PartitionDevice: %s", e)
            return

        self.devicetree._addDevice(device)
        return device

    def addUdevDiskDevice(self, info):
        name = udev.device_get_name(info)
        log_method_call(self, name=name)
        sysfs_path = udev.device_get_sysfs_path(info)
        serial = udev.device_get_serial(info)
        bus = udev.device_get_bus(info)

        vendor = util.get_sysfs_attr(sysfs_path, "device/vendor")
        model = util.get_sysfs_attr(sysfs_path, "device/model")

        kwargs = { "serial": serial, "vendor": vendor, "model": model, "bus": bus }
        if udev.device_is_iscsi(info) and not self._cleanup:
            diskType = iScsiDiskDevice
            initiator = udev.device_get_iscsi_initiator(info)
            target = udev.device_get_iscsi_name(info)
            address = udev.device_get_iscsi_address(info)
            port = udev.device_get_iscsi_port(info)
            nic = udev.device_get_iscsi_nic(info)
            kwargs["initiator"] = initiator
            if initiator == self.iscsi.initiator:
                node = self.iscsi.getNode(target, address, port, nic)
                kwargs["node"] = node
                kwargs["ibft"] = node in self.iscsi.ibftNodes
                kwargs["nic"] = self.iscsi.ifaces.get(node.iface, node.iface)
                log.info("%s is an iscsi disk", name)
            else:
                # qla4xxx partial offload
                kwargs["node"] = None
                kwargs["ibft"] = False
                kwargs["nic"] = "offload:not_accessible_via_iscsiadm"
                kwargs["fw_address"] = address
                kwargs["fw_port"] = port
                kwargs["fw_name"] = name
        elif udev.device_is_fcoe(info):
            diskType = FcoeDiskDevice
            kwargs["nic"]        = udev.device_get_fcoe_nic(info)
            kwargs["identifier"] = udev.device_get_fcoe_identifier(info)
            log.info("%s is an fcoe disk", name)
        elif udev.device_get_md_container(info):
            name = udev.device_get_md_name(info)
            diskType = MDBiosRaidArrayDevice
            parentPath = udev.device_get_md_container(info)
            parentName = devicePathToName(parentPath)
            container = self.getDeviceByName(parentName)
            if not container:
                parentSysName = blockdev.md.node_from_name(parentName)
                container_sysfs = "/sys/class/block/" + parentSysName
                container_info = udev.get_device(container_sysfs)
                if not container_info:
                    log.error("failed to find md container %s at %s",
                                parentName, container_sysfs)
                    return

                self.addUdevDevice(container_info)
                container = self.getDeviceByName(parentName)
                if not container:
                    log.error("failed to scan md container %s", parentName)
                    return

            kwargs["parents"] = [container]
            kwargs["level"]  = udev.device_get_md_level(info)
            kwargs["memberDevices"] = udev.device_get_md_devices(info)
            kwargs["uuid"] = udev.device_get_md_uuid(info)
            kwargs["exists"]  = True
            del kwargs["model"]
            del kwargs["serial"]
            del kwargs["vendor"]
            del kwargs["bus"]
        elif udev.device_is_dasd(info) and not self._cleanup:
            diskType = DASDDevice
            kwargs["busid"] = udev.device_get_dasd_bus_id(info)
            kwargs["opts"] = {}

            for attr in ['readonly', 'use_diag', 'erplog', 'failfast']:
                kwargs["opts"][attr] = udev.device_get_dasd_flag(info, attr)

            log.info("%s is a dasd device", name)
        elif udev.device_is_zfcp(info):
            diskType = ZFCPDiskDevice

            for attr in ['hba_id', 'wwpn', 'fcp_lun']:
                kwargs[attr] = udev.device_get_zfcp_attribute(info, attr=attr)

            log.info("%s is a zfcp device", name)
        else:
            diskType = DiskDevice
            log.info("%s is a disk", name)

        device = diskType(name,
                          major=udev.device_get_major(info),
                          minor=udev.device_get_minor(info),
                          sysfsPath=sysfs_path, **kwargs)

        if diskType == DASDDevice:
            self.dasd.append(device)

        self.devicetree._addDevice(device)
        return device

    def addUdevOpticalDevice(self, info):
        log_method_call(self)
        # XXX should this be RemovableDevice instead?
        #
        # Looks like if it has ID_INSTANCE=0:1 we can ignore it.
        device = OpticalDevice(udev.device_get_name(info),
                               major=udev.device_get_major(info),
                               minor=udev.device_get_minor(info),
                               sysfsPath=udev.device_get_sysfs_path(info),
                               vendor=udev.device_get_vendor(info),
                               model=udev.device_get_model(info))
        self.devicetree._addDevice(device)
        return device

    def addUdevLoopDevice(self, info):
        name = udev.device_get_name(info)
        log_method_call(self, name=name)
        sysfs_path = udev.device_get_sysfs_path(info)
        sys_file = "%s/loop/backing_file" % sysfs_path
        backing_file = open(sys_file).read().strip()
        file_device = self.getDeviceByName(backing_file)
        if not file_device:
            file_device = FileDevice(backing_file, exists=True)
            self.devicetree._addDevice(file_device)
        device = LoopDevice(name,
                            parents=[file_device],
                            sysfsPath=sysfs_path,
                            exists=True)
        if not self._cleanup or file_device not in self.diskImages.values():
            # don't allow manipulation of loop devices other than those
            # associated with disk images, and then only during cleanup
            file_device.controllable = False
            device.controllable = False
        self.devicetree._addDevice(device)
        return device

    def addUdevDevice(self, info, updateOrigFmt=False):
        """
            :param :class:`pyudev.Device` info: udev info for the device
            :keyword bool updateOrigFmt: update original format unconditionally

            If a device is added to the tree based on info its original format
            will be saved after the format has been detected. If the device
            that corresponds to info is already in the tree, its original format
            will not be updated unless updateOrigFmt is True.
        """
        name = udev.device_get_name(info)
        log_method_call(self, name=name, info=pprint.pformat(dict(info)))
        uuid = udev.device_get_uuid(info)
        sysfs_path = udev.device_get_sysfs_path(info)

        # make sure this device was not scheduled for removal and also has not
        # been hidden
        removed = [a.device for a in self.devicetree.actions.find(
                                                        action_type="destroy",
                                                        object_type="device")]
        for ignored in removed + self.devicetree._hidden:
            if (sysfs_path and ignored.sysfsPath == sysfs_path) or \
               (uuid and uuid in (ignored.uuid, ignored.format.uuid)):
                if ignored in removed:
                    reason = "removed"
                else:
                    reason = "hidden"

                log.debug("skipping %s device %s", reason, name)
                return

        # make sure we note the name of every device we see
        if name not in self.names:
            self.names.append(name)

        if self.isIgnored(info):
            log.info("ignoring %s (%s)", name, sysfs_path)
            if name not in self.ignoredDisks:
                self.addIgnoredDisk(name)

            return

        log.info("scanning %s (%s)...", name, sysfs_path)
        device = self.getDeviceByName(name)
        if device is None and udev.device_is_md(info):

            # If the md name is None, then some udev info is missing. Likely,
            # this is because the array is degraded, and mdadm has deactivated
            # it. Try to activate it and re-get the udev info.
            if flags.allow_imperfect_devices and udev.device_get_md_name(info) is None:
                devname = udev.device_get_devname(info)
                if devname:
                    try:
                        blockdev.md.run(devname)
                    except blockdev.MDRaidError as e:
                        log.warning("Failed to start possibly degraded md array: %s", e)
                    else:
                        udev.settle()
                        info = udev.get_device(sysfs_path)
                else:
                    log.warning("Failed to get devname for possibly degraded md array.")

            md_name = udev.device_get_md_name(info)
            if md_name is None:
                log.warning("No name for possibly degraded md array.")
            else:
                device = self.getDeviceByName(md_name, incomplete=flags.allow_imperfect_devices)

            if device and not isinstance(device, MDRaidArrayDevice):
                log.warning("Found device %s, but it turns out not be an md array device after all.", device.name)
                device = None

        if device and device.isDisk and \
           blockdev.mpath.is_mpath_member(device.path):
            # newly added device (eg iSCSI) could make this one a multipath member
            if device.format and device.format.type != "multipath_member":
                log.debug("%s newly detected as multipath member, dropping old format and removing kids", device.name)
                # remove children from tree so that we don't stumble upon them later
                for child in self.devicetree.getChildren(device):
                    self.devicetree.recursiveRemove(child, actions=False)

                device.format = None

        #
        # The first step is to either look up or create the device
        #
        device_added = True
        if device:
            device_added = False
        elif udev.device_is_loop(info):
            log.info("%s is a loop device", name)
            device = self.addUdevLoopDevice(info)
        elif udev.device_is_dm_mpath(info) and \
             not udev.device_is_dm_partition(info):
            log.info("%s is a multipath device", name)
            device = self.addUdevMultiPathDevice(info)
        elif udev.device_is_dm_lvm(info):
            log.info("%s is an lvm logical volume", name)
            device = self.addUdevLVDevice(info)
        elif udev.device_is_dm(info):
            log.info("%s is a device-mapper device", name)
            device = self.addUdevDMDevice(info)
        elif udev.device_is_md(info) and not udev.device_get_md_container(info):
            log.info("%s is an md device", name)
            device = self.addUdevMDDevice(info)
        elif udev.device_is_cdrom(info):
            log.info("%s is a cdrom", name)
            device = self.addUdevOpticalDevice(info)
        elif udev.device_is_disk(info):
            device = self.addUdevDiskDevice(info)
        elif udev.device_is_partition(info):
            log.info("%s is a partition", name)
            device = self.addUdevPartitionDevice(info)
        else:
            log.error("Unknown block device type for: %s", name)
            return

        if not device:
            log.debug("no device obtained for %s", name)
            return

        # If this device is read-only, mark it as such now.
        if self.udevDeviceIsDisk(info) and \
                util.get_sysfs_attr(udev.device_get_sysfs_path(info), 'ro') == '1':
            device.readonly = True

        # If this device is protected, mark it as such now. Once the tree
        # has been populated, devices' protected attribute is how we will
        # identify protected devices.
        if device.name in self.protectedDevNames:
            device.protected = True
            # if this is the live backing device we want to mark its parents
            # as protected also
            if device.name == self.liveBackingDevice:
                for parent in device.parents:
                    parent.protected = True

        # If we just added a multipath or fwraid disk that is in exclusiveDisks
        # we have to make sure all of its members are in the list too.
        mdclasses = (DMRaidArrayDevice, MDRaidArrayDevice, MultipathDevice)
        if device.isDisk and isinstance(device, mdclasses):
            if device.name in self.exclusiveDisks:
                for parent in device.parents:
                    if parent.name not in self.exclusiveDisks:
                        self.exclusiveDisks.append(parent.name)

        log.info("got device: %r", device)

        # now handle the device's formatting
        self.handleUdevDeviceFormat(info, device)
        if device_added or updateOrigFmt:
            device.originalFormat = copy.deepcopy(device.format)
        device.deviceLinks = udev.device_get_symlinks(info)

    def handleUdevDiskLabelFormat(self, info, device):
        disklabel_type = udev.device_get_disklabel_type(info)
        log_method_call(self, device=device.name, label_type=disklabel_type)
        # if there is no disklabel on the device
        # blkid doesn't understand dasd disklabels, so bypass for dasd
        if disklabel_type is None and not \
           (device.isDisk and udev.device_is_dasd(info)):
            log.debug("device %s does not contain a disklabel", device.name)
            return

        if device.partitioned:
            # this device is already set up
            log.debug("disklabel format on %s already set up", device.name)
            return

        try:
            device.setup()
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.warning, "setup of %s failed, aborting disklabel handler", [device.name])
            return

        # special handling for unsupported partitioned devices
        if not device.partitionable:
            try:
                fmt = formats.getFormat("disklabel",
                                        device=device.path,
                                        labelType=disklabel_type,
                                        exists=True)
            except InvalidDiskLabelError:
                log.warning("disklabel detected but not usable on %s",
                            device.name)
            else:
                device.format = fmt
            return

        try:
            fmt = formats.getFormat("disklabel",
                                    device=device.path,
                                    exists=True)
        except InvalidDiskLabelError as e:
            log.info("no usable disklabel on %s", device.name)
            if disklabel_type == "gpt":
                log.debug(e)
                device.format = formats.getFormat(_("Invalid Disk Label"))
        else:
            device.format = fmt

    def handleUdevLUKSFormat(self, info, device):
        # pylint: disable=unused-argument
        log_method_call(self, name=device.name, type=device.format.type)
        if not device.format.uuid:
            log.info("luks device %s has no uuid", device.path)
            return

        # look up or create the mapped device
        if not self.getDeviceByName(device.format.mapName):
            passphrase = self.__luksDevs.get(device.format.uuid)
            if device.format.configured:
                pass
            elif passphrase:
                device.format.passphrase = passphrase
            elif device.format.uuid in self.__luksDevs:
                log.info("skipping previously-skipped luks device %s",
                            device.name)
            elif self._cleanup or flags.testing:
                # if we're only building the devicetree so that we can
                # tear down all of the devices we don't need a passphrase
                if device.format.status:
                    # this makes device.configured return True
                    device.format.passphrase = 'yabbadabbadoo'
            else:
                # Try each known passphrase. Include luksDevs values in case a
                # passphrase has been set for a specific device without a full
                # reset/populate, in which case the new passphrase would not be
                # in self.__passphrases.
                for passphrase in self.__passphrases + list(self.__luksDevs.values()):
                    device.format.passphrase = passphrase
                    try:
                        device.format.setup()
                    except LUKSError:
                        device.format.passphrase = None
                    else:
                        break

            luks_device = LUKSDevice(device.format.mapName,
                                     parents=[device],
                                     exists=True)
            try:
                luks_device.setup()
            except (LUKSError, blockdev.CryptoError, DeviceError) as e:
                log.info("setup of %s failed: %s", device.format.mapName, e)
                device.removeChild()
            else:
                luks_device.updateSysfsPath()
                self.devicetree._addDevice(luks_device)
                luks_info = udev.get_device(luks_device.sysfsPath)
                if not luks_info:
                    log.error("failed to get udev data for %s", luks_device.name)
                    return

                self.addUdevDevice(luks_info, updateOrigFmt=True)
        else:
            log.warning("luks device %s already in the tree",
                        device.format.mapName)

    def handleVgLvs(self, vg_device):
        """ Handle setup of the LV's in the vg_device. """
        vg_name = vg_device.name
        lv_info = dict((k, v) for (k, v) in iter(self.devicetree.lvInfo.items())
                                if v.vg_name == vg_name)

        self.names.extend(n for n in lv_info.keys() if n not in self.names)

        if not vg_device.complete:
            log.warning("Skipping LVs for incomplete VG %s", vg_name)
            return

        if not lv_info:
            log.debug("no LVs listed for VG %s", vg_name)
            return

        all_lvs = []
        internal_lvs = []

        def addRequiredLV(name, msg):
            """ Add a prerequisite/parent LV.

                The parent is strictly required in order to be able to add
                some other LV that depends on it. For this reason, failure to
                add the specified LV results in a DeviceTreeError with the
                message string specified in the msg parameter.

                :param str name: the full name of the LV (including vgname)
                :param str msg: message to pass DeviceTreeError ctor on error
                :returns: None
                :raises: :class:`~.errors.DeviceTreeError` on failure

            """
            vol = self.getDeviceByName(name)
            if vol is None:
                new_lv = addLV(lv_info[name])
                if new_lv:
                    all_lvs.append(new_lv)
                vol = self.getDeviceByName(name)

                if vol is None:
                    log.error("%s: %s", msg, name)
                    raise DeviceTreeError(msg)

        def addLV(lv):
            """ Instantiate and add an LV based on data from the VG. """
            lv_name = lv.lv_name
            lv_uuid = lv.uuid
            lv_attr = lv.attr
            lv_size = Size(lv.size)
            lv_type = lv.segtype

            lv_class = LVMLogicalVolumeDevice
            lv_parents = [vg_device]
            lv_kwargs = {}
            name = "%s-%s" % (vg_name, lv_name)

            if self.getDeviceByName(name):
                # some lvs may have been added on demand below
                log.debug("already added %s", name)
                return

            if lv_attr[0] in 'Ss':
                log.info("found lvm snapshot volume '%s'", name)
                origin_name = blockdev.lvm.lvorigin(vg_name, lv_name)
                if not origin_name:
                    log.error("lvm snapshot '%s-%s' has unknown origin",
                                vg_name, lv_name)
                    return

                if origin_name.endswith("_vorigin]"):
                    lv_kwargs["vorigin"] = True
                    origin = None
                else:
                    origin_device_name = "%s-%s" % (vg_name, origin_name)
                    addRequiredLV(origin_device_name,
                                  "failed to locate origin lv")
                    origin = self.getDeviceByName(origin_device_name)

                lv_kwargs["origin"] = origin
                lv_class = LVMSnapShotDevice
            elif lv_attr[0] == 'v':
                # skip vorigins
                return
            elif lv_attr[0] in 'IielTCo' and lv_name.endswith(']'):
                # an internal LV, add the an instance of the appropriate class
                # to internal_lvs for later processing when non-internal LVs are
                # processed
                internal_lvs.append(lv_name)
                return
            elif lv_attr[0] == 't':
                # thin pool
                lv_class = LVMThinPoolDevice
            elif lv_attr[0] == 'V':
                # thin volume
                pool_name = blockdev.lvm.thlvpoolname(vg_name, lv_name)
                pool_device_name = "%s-%s" % (vg_name, pool_name)
                addRequiredLV(pool_device_name, "failed to look up thin pool")

                origin_name = blockdev.lvm.lvorigin(vg_name, lv_name)
                if origin_name:
                    origin_device_name = "%s-%s" % (vg_name, origin_name)
                    addRequiredLV(origin_device_name, "failed to locate origin lv")
                    origin = self.getDeviceByName(origin_device_name)
                    lv_kwargs["origin"] = origin
                    lv_class = LVMThinSnapShotDevice
                else:
                    lv_class = LVMThinLogicalVolumeDevice

                lv_parents = [self.getDeviceByName(pool_device_name)]
            elif lv_name.endswith(']'):
                # unrecognized Internal LVM2 device
                return
            elif lv_attr[0] not in '-mMrRoOC':
                # Ignore anything else except for the following:
                #   - normal lv
                #   m mirrored
                #   M mirrored without initial sync
                #   r raid
                #   R raid without initial sync
                #   o origin
                #   O origin with merging snapshot
                #   C cached LV
                return

            lv_dev = self.getDeviceByUuid(lv_uuid)
            if lv_dev is None:
                lv_device = lv_class(lv_name, parents=lv_parents,
                                     uuid=lv_uuid, size=lv_size,segType=lv_type,
                                     exists=True, **lv_kwargs)
                self.devicetree._addDevice(lv_device)
                if flags.installer_mode:
                    lv_device.setup()

                if lv_device.status:
                    lv_device.updateSysfsPath()
                    lv_device.updateSize()
                    lv_info = udev.get_device(lv_device.sysfsPath)
                    if not lv_info:
                        log.error("failed to get udev data for lv %s", lv_device.name)
                        return lv_device

                    # do format handling now
                    self.addUdevDevice(lv_info, updateOrigFmt=True)

                return lv_device

            return None

        def createInternalLV(lv):
            lv_name = lv.lv_name
            lv_uuid = lv.uuid
            lv_attr = lv.attr
            lv_size = Size(lv.size)
            lv_type = lv.segtype

            matching_cls = get_internal_lv_class(lv_attr)
            if matching_cls is None:
                raise DeviceTreeError("No internal LV class supported for type '%s'" % lv_attr[0])

            # strip the "[]"s marking the LV as internal
            lv_name = lv_name.strip("[]")

            # don't know the parent LV yet, will be set later
            new_lv = matching_cls(lv_name, vg_device, parent_lv=None, size=lv_size, uuid=lv_uuid, exists=True, segType=lv_type)
            if new_lv.status:
                new_lv.updateSysfsPath()
                new_lv.updateSize()

                lv_info = udev.get_device(new_lv.sysfsPath)
                if not lv_info:
                    log.error("failed to get udev data for lv %s", new_lv.name)
                    return new_lv

            return new_lv

        # add LVs
        for lv in lv_info.values():
            # add the LV to the DeviceTree
            new_lv = addLV(lv)

            if new_lv:
                # save the reference for later use
                all_lvs.append(new_lv)

        # Instead of doing a topological sort on internal LVs to make sure the
        # parent LV is always created before its internal LVs (an internal LV
        # can have internal LVs), we just create all the instances here and
        # assign their parents later. Those who are not assinged a parent (which
        # would hold a reference to them) will get eaten by the garbage
        # collector.

        # create device instances for the internal LVs
        orphan_lvs = dict()
        for lv_name in internal_lvs:
            full_name = "%s-%s" % (vg_name, lv_name)
            try:
                new_lv = createInternalLV(lv_info[full_name])
            except DeviceTreeError as e:
                log.warning("Failed to process an internal LV '%s': %s", full_name, e)
            else:
                orphan_lvs[full_name] = new_lv
                all_lvs.append(new_lv)

        # assign parents to internal LVs (and vice versa, see
        # :class:`~.devices.lvm.LVMInternalLogicalVolumeDevice`)
        for lv in orphan_lvs.values():
            parent_lv = lvm.determine_parent_lv(vg_name, lv, all_lvs)
            if parent_lv:
                lv.parent_lv = parent_lv
            else:
                log.warning("Failed to determine parent LV for an internal LV '%s'", lv.name)

    def handleUdevLVMPVFormat(self, info, device):
        # pylint: disable=unused-argument
        log_method_call(self, name=device.name, type=device.format.type)
        pv_info = self.devicetree.pvInfo.get(device.path, None)
        if pv_info:
            vg_name = pv_info.vg_name
            vg_uuid = pv_info.vg_uuid
        else:
            # no info about the PV -> we're done
            return

        if not vg_name:
            log.info("lvm pv %s has no vg", device.name)
            return

        vg_device = self.getDeviceByUuid(vg_uuid, incomplete=True)
        if vg_device:
            vg_device.parents.append(device)
        else:
            same_name = self.getDeviceByName(vg_name)
            if isinstance(same_name, LVMVolumeGroupDevice):
                raise DuplicateVGError("multiple LVM volume groups with the same name (%s)" % vg_name)

            try:
                vg_size = Size(pv_info.vg_size)
                vg_free = Size(pv_info.vg_free)
                pe_size = Size(pv_info.vg_extent_size)
                pe_count = pv_info.vg_extent_count
                pe_free = pv_info.vg_free_count
                pv_count = pv_info.vg_pv_count
            except (KeyError, ValueError) as e:
                log.warning("invalid data for %s: %s", device.name, e)
                return

            vg_device = LVMVolumeGroupDevice(vg_name,
                                             parents=[device],
                                             uuid=vg_uuid,
                                             size=vg_size,
                                             free=vg_free,
                                             peSize=pe_size,
                                             peCount=pe_count,
                                             peFree=pe_free,
                                             pvCount=pv_count,
                                             exists=True)
            self.devicetree._addDevice(vg_device)

        self.handleVgLvs(vg_device)

    def handleUdevMDMemberFormat(self, info, device):
        # pylint: disable=unused-argument
        log_method_call(self, name=device.name, type=device.format.type)
        md_info = blockdev.md.examine(device.path)

        # Use mdadm info if udev info is missing
        md_uuid = md_info.uuid
        device.format.mdUuid = device.format.mdUuid or md_uuid
        md_array = self.getDeviceByUuid(device.format.mdUuid, incomplete=True)

        if md_array:
            md_array.parents.append(device)
        else:
            # create the array with just this one member
            # level is reported as, eg: "raid1"
            md_level = md_info.level
            md_devices = md_info.num_devices

            if md_level is None:
                log.warning("invalid data for %s: no RAID level", device.name)
                return

            # md_examine yields metadata (MD_METADATA) only for metadata version > 0.90
            # if MD_METADATA is missing, assume metadata version is 0.90
            md_metadata = md_info.metadata or "0.90"
            md_name = None

            # check the list of devices udev knows about to see if the array
            # this device belongs to is already active
            # XXX This is mainly for containers now since their name/device is
            #     not given by mdadm examine as we run it.
            for dev in udev.get_devices():
                if not udev.device_is_md(dev):
                    continue

                try:
                    dev_uuid = udev.device_get_md_uuid(dev)
                    dev_level = udev.device_get_md_level(dev)
                except KeyError:
                    continue

                if dev_uuid is None or dev_level is None:
                    continue

                if dev_uuid == md_uuid and dev_level == md_level:
                    md_name = udev.device_get_md_name(dev)
                    break

            md_path = md_info.device or ""
            if md_path and not md_name:
                md_name = devicePathToName(md_path)
                if re.match(r'md\d+$', md_name):
                    # md0 -> 0
                    md_name = md_name[2:]

                if md_name:
                    array = self.getDeviceByName(md_name, incomplete=True)
                    if array and array.uuid != md_uuid:
                        log.error("found multiple devices with the name %s", md_name)

            if md_name:
                log.info("using name %s for md array containing member %s",
                         md_name, device.name)
            else:
                log.error("failed to determine name for the md array %s", (md_uuid or "unknown"))
                return

            array_type = MDRaidArrayDevice
            try:
                if raid.getRaidLevel(md_level) is raid.Container and \
                   getattr(device.format, "biosraid", False):
                    array_type = MDContainerDevice
            except raid.RaidError as e:
                log.error("failed to create md array: %s", e)
                return

            try:
                md_array = array_type(
                   md_name,
                   level=md_level,
                   memberDevices=md_devices,
                   uuid=md_uuid,
                   metadataVersion=md_metadata,
                   exists=True
                )
            except (ValueError, DeviceError) as e:
                log.error("failed to create md array: %s", e)
                return

            md_array.updateSysfsPath()
            md_array.parents.append(device)
            self.devicetree._addDevice(md_array)
            if md_array.status:
                array_info = udev.get_device(md_array.sysfsPath)
                if not array_info:
                    log.error("failed to get udev data for %s", md_array.name)
                    return

                self.addUdevDevice(array_info, updateOrigFmt=True)

    def handleUdevDMRaidMemberFormat(self, info, device):
        # if dmraid usage is disabled skip any dmraid set activation
        if not flags.dmraid:
            return

        log_method_call(self, name=device.name, type=device.format.type)
        name = udev.device_get_name(info)
        uuid = udev.device_get_uuid(info)
        major = udev.device_get_major(info)
        minor = udev.device_get_minor(info)

        # Have we already created the DMRaidArrayDevice?
        rs_names = blockdev.dm.get_member_raid_sets(uuid, name, major, minor)
        if len(rs_names) == 0:
            log.warning("dmraid member %s does not appear to belong to any "
                        "array", device.name)
            return

        for rs_name in rs_names:
            dm_array = self.getDeviceByName(rs_name, incomplete=True)
            if dm_array is not None:
                # We add the new device.
                dm_array.parents.append(device)
            else:
                # Activate the Raid set.
                blockdev.dm.activate_raid_set(rs_name)
                dm_array = DMRaidArrayDevice(rs_name,
                                             parents=[device])

                self.devicetree._addDevice(dm_array)

                # Wait for udev to scan the just created nodes, to avoid a race
                # with the udev.get_device() call below.
                udev.settle()

                # Get the DMRaidArrayDevice a DiskLabel format *now*, in case
                # its partitions get scanned before it does.
                dm_array.updateSysfsPath()
                dm_array_info = udev.get_device(dm_array.sysfsPath)
                self.handleUdevDiskLabelFormat(dm_array_info, dm_array)

                # Use the rs's object on the device.
                # pyblock can return the memebers of a set and the
                # device has the attribute to hold it.  But ATM we
                # are not really using it. Commenting this out until
                # we really need it.
                #device.format.raidmem = block.getMemFromRaidSet(dm_array,
                #        major=major, minor=minor, uuid=uuid, name=name)

    def handleBTRFSFormat(self, info, device):
        log_method_call(self, name=device.name)
        uuid = udev.device_get_uuid(info)

        btrfs_dev = None
        for d in self.devicetree.devices:
            if isinstance(d, BTRFSVolumeDevice) and d.uuid == uuid:
                btrfs_dev = d
                break

        if btrfs_dev:
            log.info("found btrfs volume %s", btrfs_dev.name)
            btrfs_dev.parents.append(device)
        else:
            label = udev.device_get_label(info)
            log.info("creating btrfs volume btrfs.%s", label)
            btrfs_dev = BTRFSVolumeDevice(label, parents=[device], uuid=uuid,
                                          exists=True)
            self.devicetree._addDevice(btrfs_dev)

        if not btrfs_dev.subvolumes:
            snapshots = btrfs_dev.listSubVolumes(snapshotsOnly=True)
            snapshot_ids = [s.id for s in snapshots]
            for subvol_dict in btrfs_dev.listSubVolumes():
                vol_id = subvol_dict.id
                vol_path = subvol_dict.path
                parent_id = subvol_dict.parent_id
                if vol_path in [sv.name for sv in btrfs_dev.subvolumes]:
                    continue

                # look up the parent subvol
                parent = None
                subvols = [btrfs_dev] + btrfs_dev.subvolumes
                for sv in subvols:
                    if sv.vol_id == parent_id:
                        parent = sv
                        break

                if parent is None:
                    log.error("failed to find parent (%d) for subvol %s",
                              parent_id, vol_path)
                    raise DeviceTreeError("could not find parent for subvol")

                fmt = formats.getFormat("btrfs",
                                        device=btrfs_dev.path,
                                        exists=True,
                                        volUUID=btrfs_dev.format.volUUID,
                                        subvolspec=vol_path,
                                        mountopts="subvol=%s" % vol_path)
                if vol_id in snapshot_ids:
                    device_class = BTRFSSnapShotDevice
                else:
                    device_class = BTRFSSubVolumeDevice

                subvol = device_class(vol_path,
                                      vol_id=vol_id,
                                      fmt=fmt,
                                      parents=[parent],
                                      exists=True)
                self.devicetree._addDevice(subvol)

    def handleUdevDeviceFormat(self, info, device):
        log_method_call(self, name=getattr(device, "name", None))

        if not info:
            log.debug("no information for device %s", device.name)
            return
        if not device.mediaPresent:
            log.debug("no media present for device %s", device.name)
            return

        name = udev.device_get_name(info)
        uuid = udev.device_get_uuid(info)
        label = udev.device_get_label(info)
        format_type = udev.device_get_format(info)
        serial = udev.device_get_serial(info)

        is_multipath_member = (device.isDisk and
                               blockdev.mpath_is_mpath_member(device.path))
        if is_multipath_member:
            format_type = "multipath_member"

        # Now, if the device is a disk, see if there is a usable disklabel.
        # If not, see if the user would like to create one.
        # XXX ignore disklabels on multipath or biosraid member disks
        if not udev.device_is_biosraid_member(info) and \
           not is_multipath_member and \
           format_type != "iso9660":
            self.handleUdevDiskLabelFormat(info, device)
            if device.partitioned or self.isIgnored(info) or \
               (not device.partitionable and
                device.format.type == "disklabel"):
                # If the device has a disklabel, or the user chose not to
                # create one, we are finished with this device. Otherwise
                # it must have some non-disklabel formatting, in which case
                # we fall through to handle that.
                return

        if (not device) or (not format_type) or device.format.type:
            # this device has no formatting or it has already been set up
            # FIXME: this probably needs something special for disklabels
            log.debug("no type or existing type for %s, bailing", name)
            return

        # set up the common arguments for the format constructor
        format_designator = format_type
        kwargs = {"uuid": uuid,
                  "label": label,
                  "device": device.path,
                  "serial": serial,
                  "exists": True}

        # set up type-specific arguments for the format constructor
        if format_type == "crypto_LUKS":
            # luks/dmcrypt
            kwargs["name"] = "luks-%s" % uuid
        elif format_type in formats.mdraid.MDRaidMember._udevTypes:
            # mdraid
            try:
                # ID_FS_UUID contains the array UUID
                kwargs["mdUuid"] = udev.device_get_uuid(info)
            except KeyError:
                log.warning("mdraid member %s has no md uuid", name)

            # reset the uuid to the member-specific value
            # this will be None for members of v0 metadata arrays
            kwargs["uuid"] = udev.device_get_md_device_uuid(info)

            kwargs["biosraid"] = udev.device_is_biosraid_member(info)
        elif format_type == "LVM2_member":
            # lvm
            pv_info = self.devicetree.pvInfo.get(device.path, None)
            if pv_info:
                if pv_info.vg_name:
                    kwargs["vgName"] = pv_info.vg_name
                else:
                    log.warning("PV %s has no vg_name", name)
                if pv_info.vg_uuid:
                    kwargs["vgUuid"] = pv_info.vg_uuid
                else:
                    log.warning("PV %s has no vg_uuid", name)
                if pv_info.pe_start:
                    kwargs["peStart"] = Size(pv_info.pe_start)
                else:
                    log.warning("PV %s has no pe_start", name)
        elif format_type == "vfat":
            # efi magic
            if isinstance(device, PartitionDevice) and device.bootable:
                efi = formats.getFormat("efi")
                if efi.minSize <= device.size <= efi.maxSize:
                    format_designator = "efi"
        elif format_type == "hfsplus":
            if isinstance(device, PartitionDevice):
                macefi = formats.getFormat("macefi")
                if macefi.minSize <= device.size <= macefi.maxSize and \
                   device.partedPartition.name == macefi.name:
                    format_designator = "macefi"
        elif format_type == "hfs":
            # apple bootstrap magic
            if isinstance(device, PartitionDevice) and device.bootable:
                apple = formats.getFormat("appleboot")
                if apple.minSize <= device.size <= apple.maxSize:
                    format_designator = "appleboot"
        elif format_type == "btrfs":
            # the format's uuid attr will contain the UUID_SUB, while the
            # overarching volume UUID will be stored as volUUID
            kwargs["uuid"] = info["ID_FS_UUID_SUB"]
            kwargs["volUUID"] = uuid
        elif format_type == "multipath_member":
            # blkid does not care that the UUID it sees on a multipath member is
            # for the multipath set's (and not the member's) formatting, so we
            # have to discard it.
            kwargs.pop("uuid")
            kwargs.pop("label")

        try:
            log.info("type detected on '%s' is '%s'", name, format_designator)
            device.format = formats.getFormat(format_designator, **kwargs)
            if device.format.type:
                log.info("got format: %s", device.format)
        except FSError:
            log.warning("type '%s' on '%s' invalid, assuming no format",
                      format_designator, name)
            device.format = formats.DeviceFormat()
            return

        #
        # now do any special handling required for the device's format
        #
        if device.format.type == "luks":
            self.handleUdevLUKSFormat(info, device)
        elif device.format.type == "mdmember":
            self.handleUdevMDMemberFormat(info, device)
        elif device.format.type == "dmraidmember":
            self.handleUdevDMRaidMemberFormat(info, device)
        elif device.format.type == "lvmpv":
            self.handleUdevLVMPVFormat(info, device)
        elif device.format.type == "btrfs":
            self.handleBTRFSFormat(info, device)

    def updateDeviceFormat(self, device):
        log.info("updating format of device: %s", device)
        try:
            util.notify_kernel(device.sysfsPath)
        except (ValueError, IOError) as e:
            log.warning("failed to notify kernel of change: %s", e)

        udev.settle()
        info = udev.get_device(device.sysfsPath)

        self.handleUdevDeviceFormat(info, device)

    def _handleInconsistencies(self):
        for vg in [d for d in self.devicetree.devices if d.type == "lvmvg"]:
            if vg.complete:
                continue

            # Make sure lvm doesn't get confused by PVs that belong to
            # incomplete VGs. We will remove the PVs from the blacklist when/if
            # the time comes to remove the incomplete VG and its PVs.
            for pv in vg.pvs:
                lvm.lvm_cc_addFilterRejectRegexp(pv.name)

    def setupDiskImages(self):
        """ Set up devices to represent the disk image files. """
        for (name, path) in self.diskImages.items():
            log.info("setting up disk image file '%s' as '%s'", path, name)
            dmdev = self.getDeviceByName(name)
            if dmdev and isinstance(dmdev, DMLinearDevice) and \
               path in (d.path for d in dmdev.ancestors):
                log.debug("using %s", dmdev)
                dmdev.setup()
                continue

            try:
                filedev = FileDevice(path, exists=True)
                filedev.setup()
                log.debug("%s", filedev)

                loop_name = blockdev.loop.get_loop_name(filedev.path)
                loop_sysfs = None
                if loop_name:
                    loop_sysfs = "/class/block/%s" % loop_name
                loopdev = LoopDevice(name=loop_name,
                                     parents=[filedev],
                                     sysfsPath=loop_sysfs,
                                     exists=True)
                loopdev.setup()
                log.debug("%s", loopdev)
                dmdev = DMLinearDevice(name,
                                       dmUuid="ANACONDA-%s" % name,
                                       parents=[loopdev],
                                       exists=True)
                dmdev.setup()
                dmdev.updateSysfsPath()
                dmdev.updateSize()
                log.debug("%s", dmdev)
            except (ValueError, DeviceError) as e:
                log.error("failed to set up disk image: %s", e)
            else:
                self.devicetree._addDevice(filedev)
                self.devicetree._addDevice(loopdev)
                self.devicetree._addDevice(dmdev)
                info = udev.get_device(dmdev.sysfsPath)
                self.addUdevDevice(info, updateOrigFmt=True)

    def teardownDiskImages(self):
        """ Tear down any disk image stacks. """
        for (name, _path) in self.diskImages.items():
            dm_device = self.getDeviceByName(name)
            if not dm_device:
                continue

            dm_device.deactivate()
            loop_device = dm_device.parents[0]
            loop_device.teardown()

    def backupConfigs(self, restore=False):
        """ Create a backup copies of some storage config files. """
        configs = ["/etc/mdadm.conf"]
        for cfg in configs:
            if restore:
                src = cfg + ".anacbak"
                dst = cfg
                func = os.rename
                op = "restore from backup"
            else:
                src = cfg
                dst = cfg + ".anacbak"
                func = shutil.copy2
                op = "create backup copy"

            if os.access(dst, os.W_OK):
                try:
                    os.unlink(dst)
                except OSError as e:
                    msg = str(e)
                    log.info("failed to remove %s: %s", dst, msg)

            if os.access(src, os.W_OK):
                # copy the config to a backup with extension ".anacbak"
                try:
                    func(src, dst)
                except (IOError, OSError) as e:
                    msg = str(e)
                    log.error("failed to %s of %s: %s", op, cfg, msg)
            elif restore and os.access(cfg, os.W_OK):
                # remove the config since we created it
                log.info("removing anaconda-created %s", cfg)
                try:
                    os.unlink(cfg)
                except OSError as e:
                    msg = str(e)
                    log.error("failed to remove %s: %s", cfg, msg)
            else:
                # don't try to backup non-existent configs
                log.info("not going to %s of non-existent %s", op, cfg)

    def restoreConfigs(self):
        self.backupConfigs(restore=True)

    def saveLUKSpassphrase(self, device):
        """ Save a device's LUKS passphrase in case of reset. """

        passphrase = device.format._LUKS__passphrase
        if passphrase:
            self.__luksDevs[device.format.uuid] = passphrase
            self.__passphrases.append(passphrase)

    def populate(self, cleanupOnly=False):
        """ Locate all storage devices.

            Everything should already be active. We just go through and gather
            details as needed and set up the relations between various devices.

            Devices excluded via disk filtering (or because of disk images) are
            scanned just the rest, but then they are hidden at the end of this
            process.
        """
        self.backupConfigs()
        if cleanupOnly:
            self._cleanup = True

        parted.register_exn_handler(parted_exn_handler)
        try:
            self._populate()
        except Exception:
            raise
        finally:
            parted.clear_exn_handler()
            self.restoreConfigs()

    def _populate(self):
        log.info("DeviceTree.populate: ignoredDisks is %s ; exclusiveDisks is %s",
                    self.ignoredDisks, self.exclusiveDisks)

        self.devicetree.dropLVMCache()

        if flags.installer_mode and not flags.image_install:
            blockdev.mpath.set_friendly_names(flags.multipath_friendly_names)

        self.setupDiskImages()

        # mark the tree as unpopulated so exception handlers can tell the
        # exception originated while finding storage devices
        self.populated = False

        # resolve the protected device specs to device names
        for spec in self.protectedDevSpecs:
            name = udev.resolve_devspec(spec)
            log.debug("protected device spec %s resolved to %s", spec, name)
            if name:
                self.protectedDevNames.append(name)

        # FIXME: the backing dev for the live image can't be used as an
        # install target.  note that this is a little bit of a hack
        # since we're assuming that /run/initramfs/live will exist
        for mnt in open("/proc/mounts").readlines():
            if " /run/initramfs/live " not in mnt:
                continue

            live_device_name = mnt.split()[0].split("/")[-1]
            log.info("%s looks to be the live device; marking as protected",
                     live_device_name)
            self.protectedDevNames.append(live_device_name)
            self.liveBackingDevice = live_device_name
            break

        old_devices = {}

        # Now, loop and scan for devices that have appeared since the two above
        # blocks or since previous iterations.
        while True:
            devices = []
            new_devices = udev.get_devices()

            for new_device in new_devices:
                new_name = udev.device_get_name(new_device)
                if new_name not in old_devices:
                    old_devices[new_name] = new_device
                    devices.append(new_device)

            if len(devices) == 0:
                # nothing is changing -- we are finished building devices
                break

            log.info("devices to scan: %s", [udev.device_get_name(d) for d in devices])
            for dev in devices:
                self.addUdevDevice(dev)

        self.populated = True

        # After having the complete tree we make sure that the system
        # inconsistencies are ignored or resolved.
        self._handleInconsistencies()

    @property
    def names(self):
        return self.devicetree.names

    def getDeviceByName(self, *args, **kwargs):
        return self.devicetree.getDeviceByName(*args, **kwargs)

    def getDeviceByUuid(self, *args, **kwargs):
        return self.devicetree.getDeviceByUuid(*args, **kwargs)
