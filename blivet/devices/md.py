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
import six

from gi.repository import BlockDev as blockdev

from ..devicelibs import mdraid, raid

from .. import errors
from .. import util
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..size import Size

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .container import ContainerDevice
from .raid import RaidDevice

class MDRaidArrayDevice(ContainerDevice, RaidDevice):
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

        # avoid attribute-defined-outside-init pylint warning
        self._level = None

        super(MDRaidArrayDevice, self).__init__(name, fmt=fmt, uuid=uuid,
                                                exists=exists, size=size,
                                                parents=parents,
                                                sysfsPath=sysfsPath)

        try:
            self.level = level
        except errors.DeviceError as e:
            # Could not set the level, so set loose the parents that were
            # added in superclass constructor.
            for dev in self.parents:
                dev.removeChild()
            raise e

        self.uuid = uuid
        self._totalDevices = util.numeric_type(totalDevices)
        self.memberDevices = util.numeric_type(memberDevices)

        self.chunkSize = mdraid.MD_CHUNK_SIZE

        if not self.exists and not isinstance(metadataVersion, str):
            self.metadataVersion = "default"
        else:
            self.metadataVersion = metadataVersion

        if self.parents and self.parents[0].type == "mdcontainer" and self.type != "mdbiosraidarray":
            raise errors.DeviceError("A device with mdcontainer member must be mdbiosraidarray.")

        if self.exists and self.mdadmFormatUUID and not flags.testing:
            # this is a hack to work around mdadm's insistence on giving
            # really high minors to arrays it has no config entry for
            with open("/etc/mdadm.conf", "a") as c:
                c.write("ARRAY %s UUID=%s\n" % (self.path, self.mdadmFormatUUID))

    @property
    def mdadmFormatUUID(self):
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
        return mdraid.RAID_levels

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
            level = self._getLevel(value, self._levels)
        except ValueError as e:
            raise errors.DeviceError(e)

        self._level = level

    @property
    def createBitmap(self):
        """ Whether or not a bitmap should be created on the array.

            If the the array is sufficiently small, a bitmap yields no benefit.

            If the array has no redundancy, a bitmap is just pointless.
        """
        try:
            return self.level.has_redundancy() and self.size >= Size(1000) and  self.format.type != "swap"
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
        return blockdev.md.get_superblock_size(raw_array_size,
                                               version=self.metadataVersion)

    @property
    def size(self):
        """Returns the actual or estimated size depending on whether or
           not the array exists.
        """
        if not self.exists or not self.mediaPresent:
            try:
                size = self.level.get_size([d.size for d in self.devices],
                    self.memberDevices,
                    self.chunkSize,
                    self.getSuperBlockSize)
            except (blockdev.MDRaidError, errors.RaidError) as e:
                log.info("could not calculate size of device %s for raid level %s: %s", self.name, self.level, e)
                size = Size(0)
            log.debug("non-existent RAID %s size == %s", self.level, size)
        else:
            size = self.currentSize
            log.debug("existing RAID %s size == %s", self.level, size)

        return size

    def updateSize(self):
        # pylint: disable=bad-super-call
        super(ContainerDevice, self).updateSize()

    @property
    def description(self):
        levelstr = self.level.nick if self.level.nick else self.level.name
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
        uuid = self.mdadmFormatUUID
        if self.memberDevices is None or not uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        fmt = "ARRAY %s level=%s num-devices=%d UUID=%s\n"
        return fmt % (self.path, self.level, self.memberDevices, uuid)

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
        if not isinstance(number, six.integer_types):
            raise ValueError("memberDevices must be an integer")

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
        error_msg = self._validateParentRemoval(self.level, member)
        if error_msg:
            raise errors.DeviceError(error_msg)

        super(MDRaidArrayDevice, self)._removeParent(member)
        self.memberDevices -= 1

    @property
    def _trueStatusStrings(self):
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
            if state in self._trueStatusStrings:
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

            :rtype: list of :class:`StorageDevice`
        """
        return list(self.parents)

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

        blockdev.md.activate(self.path, members=disks, uuid=self.mdadmFormatUUID)

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
        # see comment just above md_deactivate call
        self._preTeardown(recursive=recursive)

        # We don't really care what the array's state is. If the device
        # file exists, we want to deactivate it. mdraid has too many
        # states.
        if self.exists and os.path.exists(self.path):
            blockdev.md.deactivate(self.path)

        self._postTeardown(recursive=recursive)

    def _postCreate(self):
        # this is critical since our status method requires a valid sysfs path
        self.exists = True  # this is needed to run updateSysfsPath
        self.updateSysfsPath()
        StorageDevice._postCreate(self)

        # update our uuid attribute with the new array's UUID
        # XXX this won't work for containers since no UUID is reported for them
        info = blockdev.md.detail(self.path)
        self.uuid = info.uuid
        for member in self.devices:
            member.format.mdUuid = self.uuid

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        disks = [disk.path for disk in self.devices]
        spares = len(self.devices) - self.memberDevices
        level = None
        if self.level:
            level = str(self.level)
        blockdev.md.create(self.path, level, disks, spares,
                           version=self.metadataVersion,
                           bitmap=self.createBitmap)
        udev.settle()

    def _remove(self, member):
        self.setup()
        # see if the device must be marked as failed before it can be removed
        fail = (self.memberStatus(member) == "in_sync")
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
    def formatArgs(self):
        formatArgs = []
        if self.format.type == "ext2":
            recommended_stride = self.level.get_recommended_stride(self.memberDevices)
            if recommended_stride:
                formatArgs = ['-R', 'stride=%d' % recommended_stride ]
        return formatArgs

    @property
    def model(self):
        return self.description

    def dracutSetupArgs(self):
        return set(["rd.md.uuid=%s" % self.mdadmFormatUUID])

    def populateKSData(self, data):
        if self.isDisk:
            return

        super(MDRaidArrayDevice, self).populateKSData(data)
        data.level = self.level.name
        data.spares = self.spares
        data.members = ["raid.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        data.device = self.name

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
    def mdadmConfEntry(self):
        uuid = self.mdadmFormatUUID
        if not uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        return "ARRAY %s UUID=%s\n" % (self.path, uuid)

    @property
    def _trueStatusStrings(self):
        return ("clean", "active", "active-idle", "readonly", "read-auto", "inactive")

    def teardown(self, recursive=None):
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # we don't really care about the return value of _preTeardown here.
        # see comment just above md_deactivate call
        self._preTeardown(recursive=recursive)

        # Since BIOS RAID sets (containers in mdraid terminology) never change
        # there is no need to stop them and later restart them. Not stopping
        # (and thus also not starting) them also works around bug 523334
        return

    @property
    def mediaPresent(self):
        # Containers should not get any format handling done
        # (the device node does not allow read / write calls)
        return False

class MDBiosRaidArrayDevice(MDRaidArrayDevice):

    _type = "mdbiosraidarray"
    _formatClassName = property(lambda s: None)
    _isDisk = True
    _partitionable = True

    def __init__(self, name, **kwargs):
        super(MDBiosRaidArrayDevice, self).__init__(name, **kwargs)

        # For container members probe size now, as we cannot determine it
        # when teared down.
        self._size = self.currentSize

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
    def mdadmConfEntry(self):
        uuid = self.mdadmFormatUUID
        if not uuid:
            raise errors.DeviceError("array is not fully defined", self.name)

        return "ARRAY %s UUID=%s\n" % (self.path, uuid)

    @property
    def members(self):
        # If the array is a BIOS RAID array then its unique parent
        # is a container and its actual member devices are the
        # container's parents.
        return list(self.parents[0].parents)

    def teardown(self, recursive=None):
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        # we don't really care about the return value of _preTeardown here.
        # see comment just above md_deactivate call
        self._preTeardown(recursive=recursive)

        # Since BIOS RAID sets (containers in mdraid terminology) never change
        # there is no need to stop them and later restart them. Not stopping
        # (and thus also not starting) them also works around bug 523334
        return
