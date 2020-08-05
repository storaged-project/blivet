# devices/md.py
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

import math
import os
import six
import time

from six.moves import reduce

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from ..devicelibs import mdraid, raid

from .. import errors
from ..formats import DeviceFormat
from .. import util
from ..static_data import pvs_info
from ..storage_log import log_method_call
from .. import udev
from ..size import Size
from ..tasks import availability

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .container import ContainerDevice
from .raid import RaidDevice
from .lib import get_majors_by_device_type

MD_MAJORS = get_majors_by_device_type("md")


class MDRaidArrayDevice(ContainerDevice, RaidDevice):

    """ An mdraid (Linux RAID) device. """
    _type = "mdarray"
    _packages = ["mdadm"]
    _dev_dir = "/dev/md"
    _format_class_name = property(lambda s: "mdmember")
    _format_uuid_attr = property(lambda s: "md_uuid")
    _external_dependencies = [availability.BLOCKDEV_MDRAID_PLUGIN]

    def __init__(self, name, level=None, major=None, minor=None, size=None,
                 member_devices=None, total_devices=None,
                 uuid=None, fmt=None, exists=False, metadata_version=None,
                 parents=None, sysfs_path='', chunk_size=None):
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
            :keyword chunk_size: chunk size for the device
            :type chunk_size: :class:`~.size.Size`
            :keyword uuid: the device UUID
            :type uuid: str

            :keyword level: the device's RAID level
            :type level: any valid RAID level descriptor
            :keyword int member_devices: the number of active member devices
            :keyword int total_devices: the total number of member devices
            :keyword metadata_version: the version of the device's md metadata
            :type metadata_version: str (eg: "0.90")
            :keyword minor: the device minor (obsolete?)
            :type minor: int

            .. note::

                An instance of this class whose :attr:`exists` attribute is
                True and whose parent/member devices are all partitionable is
                also considered to be partitionable.

            .. note::

                An instance of this class whose :attr:`exists` attribute is
                True and whose parent/member devices are all disks is also
                treated like a disk.

        """
        # pylint: disable=unused-argument

        # These attributes are used by _add_parent, so they must be initialized
        # prior to instantiating the superclass.
        self._member_devices = 0     # the number of active (non-spare) members
        self._total_devices = 0      # the total number of members

        # avoid attribute-defined-outside-init pylint warning
        self._level = None

        super(MDRaidArrayDevice, self).__init__(name, uuid=uuid,
                                                exists=exists, size=size,
                                                parents=parents,
                                                sysfs_path=sysfs_path)

        try:
            self.level = level
        except errors.DeviceError as e:
            # Could not set the level, so set loose the parents that were
            # added in superclass constructor.
            for dev in self.parents:
                dev.remove_child(self)
            raise e

        self.uuid = uuid
        self._total_devices = util.numeric_type(total_devices)
        self.member_devices = util.numeric_type(member_devices)

        if self.exists:
            self._chunk_size = self.read_chunk_size()
        else:
            self._chunk_size = chunk_size or mdraid.MD_CHUNK_SIZE

        if not self.exists and not isinstance(metadata_version, str):
            self.metadata_version = "default"
        else:
            self.metadata_version = metadata_version

        self.format = fmt

        if self.parents and self.parents[0].type == "mdcontainer" and self.type != "mdbiosraidarray":
            raise errors.DeviceError("A device with mdcontainer member must be mdbiosraidarray.")

    @property
    def mdadm_format_uuid(self):
        """ This array's UUID, formatted for external use.

            :returns: the array's UUID in mdadm format, if available
            :rtype: str or NoneType
        """
        formatted_uuid = None

        if self.uuid is not None:
            try:
                formatted_uuid = blockdev.md.get_md_uuid(self.uuid)
            except blockdev.MDRaidError:
                pass

        return formatted_uuid

    @property
    def level(self):
        """ Return the raid level

            :returns: raid level value
            :rtype:   an object that represents a RAID level
        """
        return self._level

    @property
    def _levels(self):
        """ Allowed RAID level for this type of device."""
        return mdraid.raid_levels

    @level.setter
    def level(self, value):
        """ Set the RAID level and enforce restrictions based on it.

            :param value: new raid level
            :param type:  object
            :raises :class:`~.errors.DeviceError`: if value does not describe
            a valid RAID level
            :returns:     None
        """
        try:
            level = self._get_level(value, self._levels)
        except ValueError as e:
            raise errors.DeviceError(e)

        self._level = level

    @property
    def sector_size(self):
        if not self.exists:
            # Least common multiple of parents' sector sizes
            return reduce(lambda a, b: a * b // math.gcd(a, b), (int(p.sector_size) for p in self.parents))

        return super(MDRaidArrayDevice, self).sector_size

    @property
    def chunk_size(self):
        if self.exists and self._chunk_size == Size(0):
            self._chunk_size = self.read_chunk_size()
        return self._chunk_size

    @chunk_size.setter
    def chunk_size(self, newsize):
        if not isinstance(newsize, Size):
            raise ValueError("new chunk size must be of type Size")

        if newsize % Size("4 KiB") != Size(0):
            raise ValueError("new chunk size must be multiple of 4 KiB")

        if self.exists:
            raise ValueError("cannot set chunk size for an existing device")

        self._chunk_size = newsize

    def read_chunk_size(self):
        log_method_call(self, exists=self.exists, path=self.path,
                        sysfs_path=self.sysfs_path)
        chunk_size = Size(0)
        if self.status:
            chunk_size = Size(util.get_sysfs_attr(self.sysfs_path, "md/chunk_size") or "0")

        return chunk_size

    @property
    def create_bitmap(self):
        """ Whether or not a bitmap should be created on the array.

            If the array is sufficiently small, a bitmap yields no benefit.

            If the array has no redundancy, a bitmap is just pointless.
        """
        try:
            return self.level.has_redundancy() and self.size >= Size(1000) and self.format.type != "swap"
        except errors.RaidError:
            # If has_redundancy() raises an exception then this device has
            # a level for which the redundancy question is meaningless. In
            # that case, creating a write-intent bitmap would be a meaningless
            # action.
            return False

    def get_superblock_size(self, raw_array_size):
        """Estimate the superblock size for a member of an array,
           given the total available memory for this array and raid level.

           :param raw_array_size: total available for this array and level
           :type raw_array_size: :class:`~.size.Size`
           :returns: estimated superblock size
           :rtype: :class:`~.size.Size`
        """
        return blockdev.md.get_superblock_size(raw_array_size,
                                               version=self.metadata_version)

    @property
    def size(self):
        """Returns the actual or estimated size depending on whether or
           not the array exists.
        """
        if not self.exists or not self.media_present:
            try:
                size = self.level.get_size([d.size for d in self.members],
                                           self.member_devices,
                                           self.chunk_size,
                                           self.get_superblock_size)
            except (blockdev.MDRaidError, errors.RaidError) as e:
                log.info("could not calculate size of device %s for raid level %s: %s", self.name, self.level, e)
                size = Size(0)
            log.debug("non-existent RAID %s size == %s", self.level, size)
        else:
            size = self.current_size
            log.debug("existing RAID %s size == %s", self.level, size)

        return size

    def update_size(self, newsize=None):
        # container size is determined by the member disks, so there is nothing
        # to update in that case
        if self.type != "mdcontainer":
            # pylint: disable=bad-super-call
            super(ContainerDevice, self).update_size(newsize=newsize)

    @property
    def description(self):
        levelstr = self.level.nick if self.level.nick else self.level.name
        return "MDRAID set (%s)" % levelstr

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  level = %(level)s  spares = %(spares)s\n"
              "  members = %(member_devices)s\n"
              "  total devices = %(total_devices)s"
              "  metadata version = %(metadata_version)s" %
              {"level": self.level, "spares": self.spares,
               "member_devices": self.member_devices,
               "total_devices": self.total_devices,
               "metadata_version": self.metadata_version})
        return s

    @property
    def dict(self):
        d = super(MDRaidArrayDevice, self).dict
        d.update({"level": str(self.level),
                  "spares": self.spares, "member_devices": self.member_devices,
                  "total_devices": self.total_devices,
                  "metadata_version": self.metadata_version})
        return d

    @property
    def mdadm_conf_entry(self):
        """ This array's mdadm.conf entry. """
        uuid = self.mdadm_format_uuid
        if self.member_devices is None or not uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        fmt = "ARRAY %s level=%s num-devices=%d UUID=%s\n"
        return fmt % (self.path, self.level, self.member_devices, uuid)

    @property
    def total_devices(self):
        """ Total number of devices in the array, including spares. """
        if not self.exists:
            return self._total_devices
        else:
            return len(self.parents)

    def _get_member_devices(self):
        return self._member_devices

    def _set_member_devices(self, number):
        if not isinstance(number, six.integer_types):
            raise ValueError("member_devices must be an integer")

        if not self.exists and number > self.total_devices:
            raise ValueError("member_devices cannot be greater than total_devices")
        self._member_devices = number

    member_devices = property(lambda d: d._get_member_devices(),
                              lambda d, m: d._set_member_devices(m),
                              doc="number of member devices")

    def _get_spares(self):
        spares = 0
        if self.member_devices is not None:
            if self.total_devices is not None and \
               self.total_devices > self.member_devices:
                spares = self.total_devices - self.member_devices
            elif self.total_devices is None:
                spares = self.member_devices
                self._total_devices = self.member_devices
        return spares

    def _set_spares(self, spares):
        max_spares = self.level.get_max_spares(len(self.parents))
        if spares > max_spares:
            log.debug("failed to set new spares value %d (max is %d)",
                      spares, max_spares)
            raise errors.DeviceError("new spares value is too large")

        if self.total_devices > spares:
            self.member_devices = self.total_devices - spares

    spares = property(_get_spares, _set_spares)

    def _add_parent(self, parent):
        super(MDRaidArrayDevice, self)._add_parent(parent)

        if self.status and parent.format.exists:
            # we always probe since the device may not be set up when we want
            # information about it
            self._size = self.current_size

        # These should be incremented when adding new parent devices except
        # during devicetree.populate. When detecting existing arrays we will
        # have gotten these values from udev and will use them to determine
        # whether we found all of the parents, so we shouldn't change them in
        # that case.
        if not parent.format.exists:
            self._total_devices += 1
            self.member_devices += 1

        # The new parent hasn't been added yet, so account for it explicitly.
        is_disk = self.is_disk and parent.is_disk
        for p in self.parents:
            p.format._hidden = is_disk

        parent.format._hidden = is_disk

    def _remove_parent(self, parent):
        error_msg = self._validate_parent_removal(self.level, parent)
        if error_msg:
            raise errors.DeviceError(error_msg)

        super(MDRaidArrayDevice, self)._remove_parent(parent)
        self.member_devices -= 1

    @property
    def _true_status_strings(self):
        """ Strings in state file for which status() should return True."""
        return ("clean", "active", "active-idle", "readonly", "read-auto")

    @property
    def status(self):
        """ This device's status.

            For now, this should return a boolean:
                True    the device is open and ready for use
                False   the device is not open
        """
        # check the status in sysfs
        status = False
        if not self.exists:
            return status

        if os.path.exists(self.path) and not self.sysfs_path:
            # the array has been activated from outside of blivet
            self.update_sysfs_path()

            # make sure the active array is the one we expect
            info = udev.get_device(self.sysfs_path)
            uuid = udev.device_get_md_uuid(info)
            if uuid and uuid != self.uuid:
                log.warning("md array %s is active, but has UUID %s -- not %s",
                            self.path, uuid, self.uuid)
                self.sysfs_path = ""
                return status

        state_file = "%s/md/array_state" % self.sysfs_path
        try:
            state = open(state_file).read().strip()
            if state in self._true_status_strings:
                status = True
        except IOError:
            status = False

        return status

    def member_status(self, member):
        if not (self.status and member.status):
            return

        member_name = os.path.basename(member.sysfs_path)
        path = "/sys/%s/md/dev-%s/state" % (self.sysfs_path, member_name)
        try:
            state = open(path).read().strip()
        except IOError:
            state = None

        return state

    @property
    def degraded(self):
        """ Return True if the array is running in degraded mode. """
        rc = False
        degraded_file = "%s/md/degraded" % self.sysfs_path
        if os.access(degraded_file, os.R_OK):
            val = open(degraded_file).read().strip()
            if val == "1":
                rc = True

        return rc

    @property
    def members(self):
        """ Returns this array's members.

            :rtype: list of :class:`StorageDevice`
        """
        return list(self.parents)

    @property
    def complete(self):
        """ An MDRaidArrayDevice is complete if it has at least as many
            component devices as its count of active devices.
        """
        return (self.member_devices <= len(self.members)) or not self.exists

    @property
    def bootable(self):
        return (self.level == raid.RAID1 and
                self.metadata_version in ("0.90", "1.0") and
                all(getattr(p, "bootable", False) for p in self.parents))

    def _post_setup(self):
        super(MDRaidArrayDevice, self)._post_setup()
        self.update_sysfs_path()

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        disks = []
        for member in self.members:
            member.setup(orig=orig)
            disks.append(member.path)

        blockdev.md.activate(self.path, members=disks, uuid=self.mdadm_format_uuid)

    def _post_teardown(self, recursive=False):
        super(MDRaidArrayDevice, self)._post_teardown(recursive=recursive)
        # mdadm reuses minors indiscriminantly when there is no mdadm.conf, so
        # we need to clear the sysfs path now so our status method continues to
        # give valid results
        self.sysfs_path = ''

        # make sure the /dev/mdXXX path is removed after stopping the array
        udev.settle()

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # we don't really care about the return value of _pre_teardown here.
        # see comment just above md_deactivate call
        self._pre_teardown(recursive=recursive)

        if self.is_disk:
            # treat arrays whose members are disks as partitionable disks
            return

        # We don't really care what the array's state is. If the device
        # file exists, we want to deactivate it. mdraid has too many
        # states.
        if self.exists and os.path.exists(self.path):
            blockdev.md.deactivate(self.path)

        self._post_teardown(recursive=recursive)

    def pre_commit_fixup(self, current_fmt=False):
        """ Determine create parameters for this set """
        log_method_call(self, self.name)
        # UEFI firmware/bootloader cannot read 1.1 or 1.2 metadata arrays
        if getattr(self.format, "mountpoint", None) == "/boot/efi":
            self.metadata_version = "1.0"

    def _post_create(self):
        # this is critical since our status method requires a valid sysfs path
        self.exists = True  # this is needed to run update_sysfs_path
        self.update_sysfs_path()
        StorageDevice._post_create(self)

        # update our uuid attribute with the new array's UUID
        # XXX this won't work for containers since no UUID is reported for them
        info = blockdev.md.detail(self.path)
        self.uuid = info.uuid
        for member in self.members:
            member.format.md_uuid = self.uuid

        def remove_stale_lvm():
            """ Remove any stale LVM metadata that pre-existed in a new array's on-disk footprint. """
            log.debug("waiting 5s for activation of stale lvm on new md array %s", self.path)
            time.sleep(5)
            udev.settle()
            pvs_info.drop_cache()
            pv_info = pvs_info.cache.get(self.path)
            if pv_info is None:
                return

            if pv_info.vg_uuid:
                log.info("removing stale LVM metadata found on %s", self.name)
                try:
                    blockdev.lvm.vgremove(pv_info.vg_name, extra={"--select": "vg_uuid=%s" % pv_info.vg_uuid})
                except blockdev.LVMError as e:
                    log.error("Failed to remove stale volume group from newly-created md array %s: %s",
                              self.path, str(e))
                    raise

            # lvm says it is a pv whether or not there is vg metadata, so wipe the pv signature
            blockdev.lvm.pvremove(self.path)

        remove_stale_lvm()

        # remove any other stale metadata before proceeding
        DeviceFormat(device=self.path, exists=True).destroy()

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        disks = [disk.path for disk in self.members]
        spares = len(self.members) - self.member_devices
        level = None
        if self.level:
            level = str(self.level)
        blockdev.md.create(self.path, level, disks, spares,
                           version=self.metadata_version,
                           bitmap=self.create_bitmap,
                           chunk_size=int(self.chunk_size))
        udev.settle()

    def _remove(self, member):
        self.setup()
        # see if the device must be marked as failed before it can be removed
        fail = (self.member_status(member) == "in_sync")
        blockdev.md.remove(self.path, member.path, fail)

    def _add(self, member):
        """ Add a member device to an array.

           :param str member: the member's path

           :raises: blockdev.MDRaidError
        """
        self.setup()

        raid_devices = None
        try:
            if not self.level.has_redundancy():
                if self.level is not raid.Linear:
                    raid_devices = int(blockdev.md.detail(self.name).raid_devices) + 1
        except errors.RaidError:
            pass

        blockdev.md.add(self.path, member.path, raid_devs=raid_devices)

    @property
    def format_args(self):
        format_args = []
        if self.format.type == "ext2":
            recommended_stride = self.level.get_recommended_stride(self.member_devices)
            if recommended_stride:
                format_args = ['-R', 'stride=%d' % recommended_stride]
        return format_args

    @property
    def model(self):
        return self.description

    @property
    def partitionable(self):
        return self.exists and self.parents and all(p.partitionable for p in self.members)

    @property
    def is_disk(self):
        return self.exists and self.parents and all(p.is_disk for p in self.members)

    def dracut_setup_args(self):
        return set(["rd.md.uuid=%s" % self.mdadm_format_uuid])

    def populate_ksdata(self, data):
        if self.is_disk:
            return

        super(MDRaidArrayDevice, self).populate_ksdata(data)
        data.level = self.level.name
        data.spares = self.spares
        data.members = ["raid.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        data.device = self.name

        if not self.exists:
            # chunk size is meaningless on RAID1, so do not add our default value
            # to generated kickstart
            if self.level != raid.RAID1:
                data.chunk_size = self.chunk_size.convert_to("KiB")


class MDContainerDevice(MDRaidArrayDevice):

    _type = "mdcontainer"

    def __init__(self, name, **kwargs):
        kwargs['level'] = raid.Container
        super(MDContainerDevice, self).__init__(name, **kwargs)

    @property
    def _levels(self):
        return mdraid.MDRaidLevels(["container"])

    @property
    def description(self):
        return "BIOS RAID container"

    @property
    def mdadm_conf_entry(self):
        uuid = self.mdadm_format_uuid
        if not uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        return "ARRAY %s UUID=%s\n" % (self.path, uuid)

    @property
    def _true_status_strings(self):
        return ("clean", "active", "active-idle", "readonly", "read-auto", "inactive")

    def teardown(self, recursive=None):
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # we don't really care about the return value of _pre_teardown here.
        # see comment just above md_deactivate call
        self._pre_teardown(recursive=recursive)

        # Since BIOS RAID sets (containers in mdraid terminology) never change
        # there is no need to stop them and later restart them. Not stopping
        # (and thus also not starting) them also works around bug 523334
        return

    @property
    def media_present(self):
        # Containers should not get any format handling done
        # (the device node does not allow read / write calls)
        return False

    @property
    def is_disk(self):
        return False

    @property
    def partitionable(self):
        return False


class MDBiosRaidArrayDevice(MDRaidArrayDevice):

    _type = "mdbiosraidarray"
    _format_class_name = property(lambda s: None)
    _is_disk = True
    _partitionable = True

    def __init__(self, name, **kwargs):
        super(MDBiosRaidArrayDevice, self).__init__(name, **kwargs)

        # For container members probe size now, as we cannot determine it
        # when teared down.
        self._size = self.current_size

    @property
    def is_disk(self):
        # pylint: disable=bad-super-call
        # skip MDRaidArrayDevice and use the version in StorageDevice
        return super(MDRaidArrayDevice, self).is_disk

    @property
    def partitionable(self):
        # pylint: disable=bad-super-call
        # skip MDRaidArrayDevice and use the version in StorageDevice
        return super(MDRaidArrayDevice, self).partitionable

    @property
    def size(self):
        # For container members return probed size, as we cannot determine it
        # when teared down.
        return self._size

    @property
    def description(self):
        levelstr = self.level.nick if self.level.nick else self.level.name
        return "BIOS RAID set (%s)" % levelstr

    @property
    def mdadm_conf_entry(self):
        uuid = self.mdadm_format_uuid
        if not uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        return "ARRAY %s UUID=%s\n" % (self.path, uuid)

    @property
    def members(self):
        # If the array is a BIOS RAID array then its unique parent
        # is a container and its actual member devices are the
        # container's parents.
        return self.parents[0].members

    @property
    def total_devices(self):
        return self.parents[0].total_devices

    def _get_member_devices(self):
        return self.parents[0].member_devices

    def _add_parent(self, parent):
        # pylint: disable=bad-super-call
        super(MDRaidArrayDevice, self)._add_parent(parent)

        if self.status and parent.format.exists:
            # we always probe since the device may not be set up when we want
            # information about it
            self._size = self.current_size

    def _remove_parent(self, parent):
        error_msg = self._validate_parent_removal(self.level, parent)
        if error_msg:
            raise errors.DeviceError(error_msg)

        # pylint: disable=bad-super-call
        super(MDRaidArrayDevice, self)._remove_parent(parent)

    def teardown(self, recursive=None):
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # we don't really care about the return value of _pre_teardown here.
        # see comment just above md_deactivate call
        self._pre_teardown(recursive=recursive)

        # Since BIOS RAID sets (containers in mdraid terminology) never change
        # there is no need to stop them and later restart them. Not stopping
        # (and thus also not starting) them also works around bug 523334
        return
