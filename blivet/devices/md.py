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

import os

from ..devicelibs import mdraid

from .. import errors
from .. import util
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..size import Size
from ..i18n import P_

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .container import ContainerDevice

class MDRaidArrayDevice(ContainerDevice):
    """ An mdraid (Linux RAID) device. """
    _type = "mdarray"
    _packages = ["mdadm"]
    _devDir = "/dev/md"
    _formatClassName = property(lambda s: "mdmember")
    _formatUUIDAttr = property(lambda s: "mdUuid")

    def __init__(self, name, level=None, major=None, minor=None, size=None,
                 memberDevices=None, totalDevices=None,
                 uuid=None, fmt=None, exists=False, metadataVersion=None,
                 parents=None, sysfsPath=''):
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
            :keyword uuid: the device UUID
            :type uuid: str

            :keyword level: the device's RAID level
            :type level: any valid RAID level descriptor
            :keyword int memberDevices: the number of active member devices
            :keyword int totalDevices: the total number of member devices
            :keyword metadataVersion: the version of the device's md metadata
            :type metadataVersion: str (eg: "0.90")
            :keyword minor: the device minor (obsolete?)
            :type minor: int
        """
        # pylint: disable=unused-argument

        # These attributes are used by _addParent, so they must be initialized
        # prior to instantiating the superclass.
        self._memberDevices = 0     # the number of active (non-spare) members
        self._totalDevices = 0      # the total number of members

        super(MDRaidArrayDevice, self).__init__(name, fmt=fmt, uuid=uuid,
                                                exists=exists, size=size,
                                                parents=parents,
                                                sysfsPath=sysfsPath)

        if level == "container":
            self._type = "mdcontainer"
        self.level = level

        # For new arrays check if we have enough members
        if (not exists and parents and len(parents) < self.level.min_members):
            for dev in self.parents:
                dev.removeChild()
            raise errors.DeviceError(P_("A %(raidLevel)s set requires at least %(minMembers)d member",
                                 "A %(raidLevel)s set requires at least %(minMembers)d members",
                                 self.level.min_members) % \
                                 {"raidLevel": self.level, "minMembers": self.level.min_members})

        self.uuid = uuid
        self._totalDevices = util.numeric_type(totalDevices)
        self.memberDevices = util.numeric_type(memberDevices)

        self.chunkSize = mdraid.MD_CHUNK_SIZE

        if not self.exists and not isinstance(metadataVersion, str):
            self.metadataVersion = "default"
        else:
            self.metadataVersion = metadataVersion

        # For container members probe size now, as we cannot determine it
        # when teared down.
        if self.parents and self.parents[0].type == "mdcontainer":
            self._size = self.currentSize
            self._type = "mdbiosraidarray"

        if self.exists and self.uuid and not flags.testing:
            # this is a hack to work around mdadm's insistence on giving
            # really high minors to arrays it has no config entry for
            open("/etc/mdadm.conf", "a").write("ARRAY %s UUID=%s\n"
                                                % (self.path, self.uuid))

    @property
    def level(self):
        """ Return the raid level

            :returns: raid level value
            :rtype:   an object that represents a RAID level
        """
        return self._level

    @level.setter
    def level(self, value):
        """ Set the RAID level and enforce restrictions based on it.

            :param value: new raid level
            :param type:  a valid raid level descriptor
            :returns:     None
        """
        self._level = mdraid.RAID_levels.raidLevel(value) # pylint: disable=attribute-defined-outside-init

    @property
    def createBitmap(self):
        """ Whether or not a bitmap should be created on the array.

            If the the array is sufficiently small, a bitmap yields no benefit.

            If the array has no redundancy, a bitmap is just pointless.
        """
        try:
            return self.level.has_redundancy() and self.size >= 1000 and  self.format.type != "swap"
        except errors.RaidError:
            # If has_redundancy() raises an exception then this device has
            # a level for which the redundancy question is meaningless. In
            # that case, creating a write-intent bitmap would be a meaningless
            # action.
            return False

    def getSuperBlockSize(self, raw_array_size):
        """Estimate the superblock size for a member of an array,
           given the total available memory for this array and raid level.

           :param raw_array_size: total available for this array and level
           :type raw_array_size: :class:`~.size.Size`
           :returns: estimated superblock size
           :rtype: :class:`~.size.Size`
        """
        return mdraid.get_raid_superblock_size(raw_array_size,
                                               version=self.metadataVersion)

    @property
    def size(self):
        """Returns the actual or estimated size depending on whether or
           not the array exists.
        """
        # For container members return probed size, as we cannot determine it
        # when teared down.
        if self.type == "mdbiosraidarray":
            return self._size

        if not self.exists or not self.partedDevice:
            try:
                size = self.level.get_size([d.size for d in self.devices],
                    self.memberDevices,
                    self.chunkSize,
                    self.getSuperBlockSize)
            except (errors.MDRaidError, errors.RaidError) as e:
                log.info("could not calculate size of device %s for raid level %s: %s", self.name, self.level, e)
                size = 0
            log.debug("non-existent RAID %s size == %s", self.level, size)
        else:
            size = Size(self.partedDevice.getLength(unit="B"))
            log.debug("existing RAID %s size == %s", self.level, size)

        return size

    @property
    def description(self):
        if self.type == "mdcontainer":
            return "BIOS RAID container"
        else:
            levelstr = self.level.nick if self.level.nick else self.level.name
            if self.type == "mdbiosraidarray":
                return "BIOS RAID set (%s)" % levelstr
            else:
                return "MDRAID set (%s)" % levelstr

    def __repr__(self):
        s = StorageDevice.__repr__(self)
        s += ("  level = %(level)s  spares = %(spares)s\n"
              "  members = %(memberDevices)s\n"
              "  total devices = %(totalDevices)s"
              "  metadata version = %(metadataVersion)s" %
              {"level": self.level, "spares": self.spares,
               "memberDevices": self.memberDevices,
               "totalDevices": self.totalDevices,
               "metadataVersion": self.metadataVersion})
        return s

    @property
    def dict(self):
        d = super(MDRaidArrayDevice, self).dict
        d.update({"level": str(self.level),
                  "spares": self.spares, "memberDevices": self.memberDevices,
                  "totalDevices": self.totalDevices,
                  "metadataVersion": self.metadataVersion})
        return d

    @property
    def mdadmConfEntry(self):
        """ This array's mdadm.conf entry. """
        if self.memberDevices is None or not self.uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        # containers and the sets within must only have a UUID= parameter
        if self.type == "mdcontainer" or self.type == "mdbiosraidarray":
            fmt = "ARRAY %s UUID=%s\n"
            return fmt % (self.path, self.uuid)

        fmt = "ARRAY %s level=%s num-devices=%d UUID=%s\n"
        return fmt % (self.path, self.level, self.memberDevices, self.uuid)

    @property
    def totalDevices(self):
        """ Total number of devices in the array, including spares. """
        if not self.exists:
            return self._totalDevices
        else:
            return len(self.parents)

    def _getMemberDevices(self):
        return self._memberDevices

    def _setMemberDevices(self, number):
        if not isinstance(number, int):
            raise ValueError("memberDevices is an integer")

        if not self.exists and number > self.totalDevices:
            raise ValueError("memberDevices cannot be greater than totalDevices")
        self._memberDevices = number

    memberDevices = property(_getMemberDevices, _setMemberDevices,
                             doc="number of member devices")

    def _getSpares(self):
        spares = 0
        if self.memberDevices is not None:
            if self.totalDevices is not None and \
               self.totalDevices > self.memberDevices:
                spares = self.totalDevices - self.memberDevices
            elif self.totalDevices is None:
                spares = self.memberDevices
                self._totalDevices = self.memberDevices
        return spares

    def _setSpares(self, spares):
        max_spares = self.level.get_max_spares(len(self.parents))
        if spares > max_spares:
            log.debug("failed to set new spares value %d (max is %d)",
                      spares, max_spares)
            raise errors.DeviceError("new spares value is too large")

        if self.totalDevices > spares:
            self.memberDevices = self.totalDevices - spares

    spares = property(_getSpares, _setSpares)

    def _addParent(self, member):
        super(MDRaidArrayDevice, self)._addParent(member)

        if self.status and member.format.exists:
            # we always probe since the device may not be set up when we want
            # information about it
            self._size = self.currentSize

        # These should be incremented when adding new member devices except
        # during devicetree.populate. When detecting existing arrays we will
        # have gotten these values from udev and will use them to determine
        # whether we found all of the members, so we shouldn't change them in
        # that case.
        if not member.format.exists:
            self._totalDevices += 1
            self.memberDevices += 1

    def _removeParent(self, member):
        """ If this is a raid array that is not actually redundant and it
            appears to have formatting and therefore probably data on it,
            removing one of its devices is a bad idea.
        """
        try:
            if not self.level.has_redundancy() and self.exists and member.format.exists:
                raise errors.DeviceError("cannot remove members from existing %s array" % self.level)
        except errors.RaidError:
            # If the concept of redundancy is meaningless for this device's
            # raid level, then it is OK to remove a parent device.
            pass

        super(MDRaidArrayDevice, self)._removeParent(member)
        self.memberDevices -= 1

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

        if os.path.exists(self.path) and not self.sysfsPath:
            # the array has been activated from outside of blivet
            self.updateSysfsPath()

            # make sure the active array is the one we expect
            info = udev.get_device(self.sysfsPath)
            uuid = udev.device_get_md_uuid(info)
            if uuid and uuid != self.uuid:
                log.warning("md array %s is active, but has UUID %s -- not %s",
                            self.path, uuid, self.uuid)
                self.sysfsPath = ""
                return status

        state_file = "%s/md/array_state" % self.sysfsPath
        try:
            state = open(state_file).read().strip()
            if state in ("clean", "active", "active-idle", "readonly", "read-auto"):
                status = True
            # mdcontainers have state inactive when started (clear if stopped)
            if self.type == "mdcontainer" and state == "inactive":
                status = True
        except IOError:
            status = False

        return status

    def memberStatus(self, member):
        if not (self.status and member.status):
            return

        member_name = os.path.basename(member.sysfsPath)
        path = "/sys/%s/md/dev-%s/state" % (self.sysfsPath, member_name)
        try:
            state = open(path).read().strip()
        except IOError:
            state = None

        return state

    @property
    def degraded(self):
        """ Return True if the array is running in degraded mode. """
        rc = False
        degraded_file = "%s/md/degraded" % self.sysfsPath
        if os.access(degraded_file, os.R_OK):
            val = open(degraded_file).read().strip()
            if val == "1":
                rc = True

        return rc

    @property
    def members(self):
        """ Returns this array's members.

            If the array is a BIOS RAID array then its unique parent
            is a container and its actual member devices are the
            container's parents.

            :rtype: list of :class:`StorageDevice`
        """
        if self.type == "mdbiosraidarray":
            members = self.parents[0].parents
        else:
            members = self.parents
        return list(members)

    @property
    def complete(self):
        """ An MDRaidArrayDevice is complete if it has at least as many
            component devices as its count of active devices.
        """
        return (self.memberDevices <= len(self.members)) or not self.exists

    @property
    def devices(self):
        """ Return a list of this array's member device instances. """
        return self.parents

    def _postSetup(self):
        super(MDRaidArrayDevice, self)._postSetup()
        self.updateSysfsPath()

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        disks = []
        for member in self.devices:
            member.setup(orig=orig)
            disks.append(member.path)

        mdraid.mdactivate(self.path,
                          members=disks,
                          array_uuid=self.uuid)

    def _postTeardown(self, recursive=False):
        super(MDRaidArrayDevice, self)._postTeardown(recursive=recursive)
        # mdadm reuses minors indiscriminantly when there is no mdadm.conf, so
        # we need to clear the sysfs path now so our status method continues to
        # give valid results
        self.sysfsPath = ''

    def teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # we don't really care about the return value of _preTeardown here.
        # see comment just above mddeactivate call
        self._preTeardown(recursive=recursive)

        # Since BIOS RAID sets (containers in mdraid terminology) never change
        # there is no need to stop them and later restart them. Not stopping
        # (and thus also not starting) them also works around bug 523334
        if self.type == "mdcontainer" or self.type == "mdbiosraidarray":
            return

        # We don't really care what the array's state is. If the device
        # file exists, we want to deactivate it. mdraid has too many
        # states.
        if self.exists and os.path.exists(self.path):
            mdraid.mddeactivate(self.path)

        self._postTeardown(recursive=recursive)

    def preCommitFixup(self, *args, **kwargs):
        """ Determine create parameters for this set """
        mountpoints = kwargs.pop("mountpoints")
        log_method_call(self, self.name, mountpoints)

        if "/boot" in mountpoints:
            bootmountpoint = "/boot"
        else:
            bootmountpoint = "/"

        # If we are used to boot from we cannot use 1.1 metadata
        if getattr(self.format, "mountpoint", None) == bootmountpoint or \
           getattr(self.format, "mountpoint", None) == "/boot/efi" or \
           self.format.type == "prepboot":
            self.metadataVersion = "1.0"

    def _postCreate(self):
        # this is critical since our status method requires a valid sysfs path
        self.exists = True  # this is needed to run updateSysfsPath
        self.updateSysfsPath()
        StorageDevice._postCreate(self)

        # update our uuid attribute with the new array's UUID
        # XXX this won't work for containers since no UUID is reported for them
        info = mdraid.mddetail(self.path)
        self.uuid = info.get("UUID")
        for member in self.devices:
            member.format.mdUuid = self.uuid

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        disks = [disk.path for disk in self.devices]
        spares = len(self.devices) - self.memberDevices
        mdraid.mdcreate(self.path,
                        self.level,
                        disks,
                        spares,
                        metadataVer=self.metadataVersion,
                        bitmap=self.createBitmap)
        udev.settle()

    def _remove(self, member):
        self.setup()
        # see if the device must be marked as failed before it can be removed
        fail = (self.memberStatus(member) == "in_sync")
        mdraid.mdremove(self.path, member.path, fail=fail)

    def _add(self, member):
        """ Add a member device to an array.

           :param str member: the member's path

           :raises: MDRaidError
        """
        self.setup()

        grow_mode = False
        raid_devices = None
        try:
            if not self.level.has_redundancy():
                grow_mode = True
                if self.level is not raid.Linear:
                    raid_devices = int(mdraid.mddetail(self.name)['RAID DEVICES']) + 1
        except errors.RaidError:
            pass

        mdraid.mdadd(self.path, member.path, grow_mode=grow_mode, raid_devices=raid_devices)

    @property
    def formatArgs(self):
        formatArgs = []
        if self.format.type == "ext2":
            recommended_stride = self.level.get_recommended_stride(self.memberDevices)
            if recommended_stride:
                formatArgs = ['-R', 'stride=%d' % recommended_stride ]
        return formatArgs

    @property
    def mediaPresent(self):
        # Containers should not get any format handling done
        # (the device node does not allow read / write calls)
        if self.type == "mdcontainer":
            return False
        # BIOS RAID sets should show as present even when teared down
        elif self.type == "mdbiosraidarray":
            return True
        elif flags.testing:
            return True
        else:
            return self.partedDevice is not None

    @property
    def model(self):
        return self.description

    @property
    def partitionable(self):
        return self.type == "mdbiosraidarray"

    @property
    def isDisk(self):
        return self.type == "mdbiosraidarray"

    def dracutSetupArgs(self):
        return set(["rd.md.uuid=%s" % self.uuid])

    def populateKSData(self, data):
        if self.isDisk:
            return

        super(MDRaidArrayDevice, self).populateKSData(data)
        data.level = self.level.name
        data.spares = self.spares
        data.members = ["raid.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        data.device = self.name
