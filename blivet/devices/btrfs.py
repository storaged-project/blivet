# devices/btrfs.py
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
import copy
import tempfile

from ..devicelibs import btrfs
from ..devicelibs import raid

from .. import errors
from ..flags import flags
from ..storage_log import log_method_call
from .. import udev
from ..formats import getFormat, DeviceFormat

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice
from .container import ContainerDevice

class BTRFSDevice(StorageDevice):
    """ Base class for BTRFS volume and sub-volume devices. """
    _type = "btrfs"
    _packages = ["btrfs-progs"]

    def __init__(self, *args, **kwargs):
        """ Passing None or no name means auto-generate one like btrfs.%d """
        if not args or not args[0]:
            args = ("btrfs.%d" % self.id,)

        if kwargs.get("parents") is None:
            raise errors.BTRFSValueError("BTRFSDevice must have at least one parent")

        self.req_size = kwargs.pop("size", None)
        super(BTRFSDevice, self).__init__(*args, **kwargs)

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        self.parents[0].updateSysfsPath()
        self.sysfsPath = self.parents[0].sysfsPath
        log.debug("%s sysfsPath set to %s", self.name, self.sysfsPath)

    def updateSize(self):
        pass

    def _postCreate(self):
        super(BTRFSDevice, self)._postCreate()
        self.format.exists = True
        self.format.device = self.path

    def _preDestroy(self):
        """ Preparation and precondition checking for device destruction. """
        super(BTRFSDevice, self)._preDestroy()
        self.setupParents(orig=True)

    def _getSize(self):
        size = sum([d.size for d in self.parents])
        return size

    def _setSize(self, newsize):
        raise RuntimeError("cannot directly set size of btrfs volume")

    @property
    def currentSize(self):
        return self.size

    @property
    def status(self):
        return self.exists and all(d.status for d in self.parents)

    @property
    def _temp_dir_prefix(self):
        return "btrfs-tmp.%s" % self.id

    def _do_temp_mount(self, orig=False):
        if self.format.status or not self.exists:
            return

        tmpdir = tempfile.mkdtemp(prefix=self._temp_dir_prefix)
        if orig:
            fmt = self.originalFormat
        else:
            fmt = self.format

        fmt.mount(mountpoint=tmpdir)

    def _undo_temp_mount(self):
        if getattr(self.format, "_mountpoint", None):
            fmt = self.format
        elif getattr(self.originalFormat, "_mountpoint", None):
            fmt = self.originalFormat
        else:
            return

        mountpoint = fmt._mountpoint

        if os.path.basename(mountpoint).startswith(self._temp_dir_prefix):
            fmt.unmount()
            os.rmdir(mountpoint)

    @property
    def path(self):
        return self.parents[0].path if self.parents else None

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return True

    @property
    def fstabSpec(self):
        if self.format.volUUID:
            spec = "UUID=%s" % self.format.volUUID
        else:
            spec = super(BTRFSDevice, self).fstabSpec
        return spec

    @classmethod
    def isNameValid(cls, name):
        # Override StorageDevice.isNameValid to allow pretty much anything
        return not('\x00' in name)

class BTRFSVolumeDevice(BTRFSDevice, ContainerDevice):
    _type = "btrfs volume"
    vol_id = btrfs.MAIN_VOLUME_ID
    _formatClassName = property(lambda s: "btrfs")
    _formatUUIDAttr = property(lambda s: "volUUID")

    def __init__(self, *args, **kwargs):
        """
            :param str name: the volume name
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: a list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str uuid: UUID of top-level filesystem/volume
            :keyword str sysfsPath: sysfs device path
            :keyword dataLevel: RAID level for data
            :type dataLevel: any valid raid level descriptor
            :keyword metaDataLevel: RAID level for metadata
            :type metaDataLevel: any valid raid level descriptor
        """
        # pop these arguments before the constructor call to avoid
        # unrecognized keyword error in superclass constructor
        dataLevel = kwargs.pop("dataLevel", None)
        metaDataLevel = kwargs.pop("metaDataLevel", None)
        createOptions = kwargs.pop("createOptions", None)

        super(BTRFSVolumeDevice, self).__init__(*args, **kwargs)

        # avoid attribute-defined-outside-init pylint warning
        self._dataLevel = self._metaDataLevel = None

        # assign after constructor to avoid AttributeErrors in setter functions
        self.dataLevel = dataLevel
        self.metaDataLevel = metaDataLevel

        self.subvolumes = []
        self.size_policy = self.size

        if self.parents and not self.format.type:
            label = getattr(self.parents[0].format, "label", None)
            self.format = getFormat("btrfs",
                                    exists=self.exists,
                                    label=label,
                                    volUUID=self.uuid,
                                    device=self.path,
                                    mountopts="subvolid=%d" % self.vol_id,
                                    createOptions=createOptions)
            self.originalFormat = copy.copy(self.format)

        self._defaultSubVolumeID = None

    def _validateRaidLevel(self, level):
        """ Returns an error message if the RAID level is invalid for this
            device, otherwise None.

            :param level: a RAID level
            :type level: :class:`~.devicelibs.raid.RAIDLevel`
            :returns: an error message if the RAID level is invalid, else None
            :rtype: str or NoneType
        """
        if not self.exists and len(self.parents) < level.min_members:
            return "RAID level %s requires that device have at least %d members, but device has only %d members." % (level, level.min_members, len(self.parents))
        return None

    def _setLevel(self, value, data):
        """ Sets a valid level for this device and level type.

            :param object value: value for this RAID level
            :param bool data: True if for data, False if for metadata

            :returns: a valid level for value, if any, else None
            :rtype: :class:`~.devicelibs.raid.RAIDLevel` or NoneType

            :raises: :class:`~.errors.BTRFSValueError` if value represents
            an invalid level.
        """
        level = None
        if value:
            try:
                levels = btrfs.RAID_levels if data else btrfs.metadata_levels
                level = levels.raidLevel(value)
            except errors.RaidError:
                data_type_str = "data" if data else "metadata"
                raise errors.BTRFSValueError("%s is an invalid value for %s RAID level." % (value, data_type_str))

            error_msg = self._validateRaidLevel(level)
            if error_msg:
                raise errors.BTRFSValueError(error_msg)

        if data:
            self._dataLevel = level
        else:
            self._metaDataLevel = level

    @property
    def dataLevel(self):
        """ Return the RAID level for data.

            :returns: raid level
            :rtype: an object that represents a raid level
        """
        return self._dataLevel

    @dataLevel.setter
    def dataLevel(self, value):
        """ Set the RAID level for data.

            :param object value: new raid level
            :returns:     None
            :raises: :class:`~.errors.BTRFSValueError`
        """
        self._setLevel(value, True)

    @property
    def metaDataLevel(self):
        """ Return the RAID level for metadata.

            :returns: raid level
            :rtype: an object that represents a raid level
        """
        return self._metaDataLevel

    @metaDataLevel.setter
    def metaDataLevel(self, value):
        """ Set the RAID level for metadata.

            :param object value: new raid level
            :returns:     None
            :raises: :class:`~.errors.BTRFSValueError`
        """
        self._setLevel(value, False)

    @property
    def formatImmutable(self):
        return self.exists

    def _setName(self, value):
        self._name = value  # name is not used outside of blivet

    def _setFormat(self, fmt):
        """ Set the Device's format. """
        super(BTRFSVolumeDevice, self)._setFormat(fmt)
        self.name = "btrfs.%d" % self.id
        label = getattr(self.format, "label", None)
        if label:
            self.name = label

        if not self.exists:
            # propagate mount options specified for members via kickstart
            self.format.mountopts = self.parents[0].format.mountopts

    def _getSize(self):
        size = sum([d.size for d in self.parents])
        if self.dataLevel in (raid.RAID1, raid.RAID10):
            size /= len(self.parents)

        return size

    def _removeParent(self, member):
        """ Raises a DeviceError if the device has a raid level and the
            resulting number of parents would be fewer than the minimum
            number required by the raid level.

            Note: btrfs does not permit degrading an array.
        """
        levels = [l for l in [self.dataLevel, self.metaDataLevel] if l]
        if levels:
            min_level = min(levels, key=lambda l: l.min_members)
            min_members = min_level.min_members
            if len(self.parents) - 1 < min_members:
                raise errors.DeviceError("device %s requires at least %d membersfor raid level %s" % (self.name, min_members, min_level))
        super(BTRFSVolumeDevice, self)._removeParent(member)

    def _addSubVolume(self, vol):
        if vol.name in [v.name for v in self.subvolumes]:
            raise errors.BTRFSValueError("subvolume %s already exists" % vol.name)

        self.subvolumes.append(vol)

    def _removeSubVolume(self, name):
        if name not in [v.name for v in self.subvolumes]:
            raise errors.BTRFSValueError("cannot remove non-existent subvolume %s" % name)

        names = [v.name for v in self.subvolumes]
        self.subvolumes.pop(names.index(name))

    def listSubVolumes(self, snapshotsOnly=False):
        subvols = []
        if flags.installer_mode or flags.rescue_mode:
            self.setup(orig=True)

            try:
                self._do_temp_mount(orig=True)
            except errors.FSError as e:
                log.debug("btrfs temp mount failed: %s", e)
                return subvols
        elif not (self.originalFormat.status or self.format.status):
            return subvols

        try:
            mountpoint = (self.originalFormat._mountpoint or
                          self.format._mountpoint)
            subvols = btrfs.list_subvolumes(mountpoint,
                                            snapshots_only=snapshotsOnly)
        except errors.BTRFSError as e:
            log.debug("failed to list subvolumes: %s", e)
        else:
            self._getDefaultSubVolumeID(mountpoint)
        finally:
            if flags.installer_mode or flags.rescue_mode:
                self._undo_temp_mount()

        return subvols

    def createSubVolumes(self):
        self._do_temp_mount()

        for _name, subvol in self.subvolumes:
            if subvol.exists:
                continue
            subvol.create(mountpoint=self._temp_dir_prefix)
        self._undo_temp_mount()

    def removeSubVolume(self, name):
        raise NotImplementedError()

    def _getDefaultSubVolumeID(self, mountpoint=None):
        subvolid = None
        if not mountpoint:
            mountpoint = self.originalFormat._mountpoint
        try:
            subvolid = btrfs.get_default_subvolume(mountpoint)
        except errors.BTRFSError as e:
            log.debug("failed to get default subvolume id: %s", e)

        self._defaultSubVolumeID = subvolid

    def _setDefaultSubVolumeID(self, vol_id):
        """ Set a new default subvolume by id.

            This writes the change to the filesystem, which must be mounted.
        """
        try:
            btrfs.set_default_subvolume(self.originalFormat._mountpoint, vol_id)
        except errors.BTRFSError as e:
            log.error("failed to set new default subvolume id (%s): %s",
                      vol_id, e)
            # The only time we set a new default subvolume is so we can remove
            # the current default. If we can't change the default, we won't be
            # able to remove the subvolume.
            raise
        else:
            self._defaultSubVolumeID = vol_id

    @property
    def defaultSubVolume(self):
        default = None
        if self._defaultSubVolumeID is None:
            return None

        if self._defaultSubVolumeID == self.vol_id:
            return self

        for sv in self.subvolumes:
            if sv.vol_id == self._defaultSubVolumeID:
                default = sv
                break

        return default

    def _create(self):
        log_method_call(self, self.name, status=self.status)
        btrfs.create_volume(devices=[d.path for d in self.parents],
                            label=self.format.label,
                            data=self.dataLevel,
                            metadata=self.metaDataLevel)

    def _postCreate(self):
        super(BTRFSVolumeDevice, self)._postCreate()
        info = udev.get_device(self.sysfsPath)
        if not info:
            log.error("failed to get updated udev info for new btrfs volume")
        else:
            self.format.volUUID = udev.device_get_uuid(info)

        self.format.exists = True
        self.originalFormat.exists = True

    def _destroy(self):
        log_method_call(self, self.name, status=self.status)
        for device in self.parents:
            device.setup(orig=True)
            DeviceFormat(device=device.path, exists=True).destroy()

    def _remove(self, member):
        log_method_call(self, self.name, status=self.status)
        try:
            self._do_temp_mount(orig=True)
        except errors.FSError as e:
            log.debug("btrfs temp mount failed: %s", e)
            raise

        try:
            btrfs.remove(self.originalFormat._mountpoint, member.path)
        finally:
            self._undo_temp_mount()

    def _add(self, member):
        try:
            self._do_temp_mount(orig=True)
        except errors.FSError as e:
            log.debug("btrfs temp mount failed: %s", e)
            raise

        try:
            btrfs.add(self.originalFormat._mountpoint, member.path)
        finally:
            self._undo_temp_mount()

    def populateKSData(self, data):
        super(BTRFSVolumeDevice, self).populateKSData(data)
        data.dataLevel = self.dataLevel.name if self.dataLevel else None
        data.metaDataLevel = self.metaDataLevel.name if self.metaDataLevel else None
        data.devices = ["btrfs.%d" % p.id for p in self.parents]
        data.preexist = self.exists

class BTRFSSubVolumeDevice(BTRFSDevice):
    """ A btrfs subvolume pseudo-device. """
    _type = "btrfs subvolume"
    _formatImmutable = True

    def __init__(self, *args, **kwargs):
        """
            :param str name: the subvolume name
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: a list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str sysfsPath: sysfs device path
        """
        self.vol_id = kwargs.pop("vol_id", None)

        super(BTRFSSubVolumeDevice, self).__init__(*args, **kwargs)

        if len(self.parents) != 1:
            raise errors.DeviceError("%s %s must have exactly one parent." % (self.type, self.name))

        if not isinstance(self.parents[0], BTRFSDevice):
            raise errors.DeviceError("%s %s's unique parent must be a BTRFSDevice." % (self.type, self.name))

        self.volume._addSubVolume(self)

    def _setFormat(self, fmt):
        """ Set the Device's format. """
        super(BTRFSSubVolumeDevice, self)._setFormat(fmt)
        if self.exists:
            return

        # propagate mount options specified for members via kickstart
        opts = "subvol=%s" % self.name
        if self.volume.format.mountopts:
            opts = "%s,%s" % (self.volume.format.mountopts, opts)

        self.format.mountopts = opts

    @property
    def volume(self):
        """Return the first ancestor that is not a BTRFSSubVolumeDevice.

           Note: Assumes that each ancestor in traversal has only one parent.

           Raises a DeviceError if the ancestor found is not a
           BTRFSVolumeDevice.
        """
        parent = self.parents[0]
        vol = None
        while True:
            if not isinstance(parent, BTRFSSubVolumeDevice):
                vol = parent
                break

            parent = parent.parents[0]

        if not isinstance(vol, BTRFSVolumeDevice):
            raise errors.DeviceError("%s %s's first non subvolume ancestor must be a btrfs volume" % (self.type, self.name))
        return vol

    @property
    def container(self):
        return self.volume

    def setupParents(self, orig=False):
        """ Run setup method of all parent devices. """
        log_method_call(self, name=self.name, orig=orig, kids=self.kids)
        self.volume.setup(orig=orig)

    def _create(self):
        log_method_call(self, self.name, status=self.status)
        self.volume._do_temp_mount()
        mountpoint = self.volume.format._mountpoint
        if not mountpoint:
            raise RuntimeError("btrfs subvol create requires mounted volume")

        try:
            btrfs.create_subvolume(mountpoint, self.name)
        finally:
            self.volume._undo_temp_mount()

    def _postCreate(self):
        super(BTRFSSubVolumeDevice, self)._postCreate()
        self.format.volUUID = self.volume.format.volUUID

    def _destroy(self):
        log_method_call(self, self.name, status=self.status)
        self.volume._do_temp_mount(orig=True)
        if self.volume._defaultSubVolumeID == self.vol_id:
            # btrfs does not allow removal of the default subvolume
            self.volume._setDefaultSubVolumeID(self.volume.vol_id)

        mountpoint = self.volume.originalFormat._mountpoint
        if not mountpoint:
            raise RuntimeError("btrfs subvol destroy requires mounted volume")
        btrfs.delete_subvolume(mountpoint, self.name)
        self.volume._undo_temp_mount()

    def removeHook(self, modparent=True):
        if modparent:
            self.volume._removeSubVolume(self.name)

        super(BTRFSSubVolumeDevice, self).removeHook(modparent=modparent)

    def addHook(self, new=True):
        super(BTRFSSubVolumeDevice, self).addHook(new=new)
        if new:
            return

        if self not in self.volume.subvolumes:
            self.volume._addSubVolume(self)

    def populateKSData(self, data):
        super(BTRFSSubVolumeDevice, self).populateKSData(data)
        data.subvol = True
        data.name = self.name
        data.preexist = self.exists

        # Identify the volume this subvolume belongs to by means of its
        # label. If the volume has no label, do nothing.
        # Note that doing nothing will create an invalid kickstart.
        # See rhbz#1072060
        label = self.parents[0].format.label
        if label:
            data.devices = ["LABEL=%s" % label]

class BTRFSSnapShotDevice(BTRFSSubVolumeDevice):
    """ A btrfs snapshot pseudo-device.

        BTRFS snapshots are a specialized type of subvolume that contains a
        source attribute which identifies which subvolume the snapshot was taken
        from. They do not have to be removed when removing the source subvolume.
    """
    _type = "btrfs snapshot"

    def __init__(self, *args, **kwargs):
        """
            :param str name: the subvolume name
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: a list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str sysfsPath: sysfs device path
            :keyword :class:`~.BTRFSDevice` source: the snapshot source
            :keyword bool readOnly: create a read-only snapshot

            Snapshot source can be either a subvolume or a top-level volume.

        """
        source = kwargs.pop("source", None)
        if not kwargs.get("exists") and not source:
            # it is possible to remove a source subvol and keep snapshots of it
            raise errors.BTRFSValueError("non-existent btrfs snapshots must have a source")

        if source and not isinstance(source, BTRFSDevice):
            raise errors.BTRFSValueError("btrfs snapshot source must be a btrfs subvolume")

        if source and not source.exists:
            raise errors.BTRFSValueError("btrfs snapshot source must already exist")

        self.source = source
        """ the snapshot's source subvolume """

        self.readOnly = kwargs.pop("readOnly", False)

        super(BTRFSSnapShotDevice, self).__init__(*args, **kwargs)

        if source and getattr(source, "volume", source) != self.volume:
            self.volume._removeSubVolume(self.name)
            self.parents = []
            raise errors.BTRFSValueError("btrfs snapshot and source must be in the same volume")

    def _create(self):
        log_method_call(self, self.name, status=self.status)
        self.volume._do_temp_mount()
        mountpoint = self.volume.format._mountpoint
        if not mountpoint:
            raise RuntimeError("btrfs subvol create requires mounted volume")

        if isinstance(self.source, BTRFSVolumeDevice):
            source_path = mountpoint
        else:
            source_path = "%s/%s" % (mountpoint, self.source.name)

        dest_path = "%s/%s" % (mountpoint, self.name)
        try:
            btrfs.create_snapshot(source_path, dest_path, ro=self.readOnly)
        finally:
            self.volume._undo_temp_mount()

    def dependsOn(self, dep):
        return (dep == self.source or
                super(BTRFSSnapShotDevice, self).dependsOn(dep))
