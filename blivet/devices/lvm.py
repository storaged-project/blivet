# devices/lvm.py
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

from decimal import Decimal
import abc
import copy
import pprint
import re
import time
from collections import namedtuple

# device backend modules
from ..devicelibs import lvm
from ..devicelibs import dm

from .. import errors
from ..flags import flags
from .. import util
from ..storage_log import log_method_call
from .. import udev
from ..size import Size

import logging
log = logging.getLogger("blivet")

from .device import Device
from .storage import StorageDevice
from .container import ContainerDevice
from .dm import DMDevice
from .md import MDRaidArrayDevice

ThPoolReserveSpec = namedtuple("ThPoolReserveSpec", ["percent", "min", "max"])
""" A namedtuple class for specifying restrictions of space reserved for a thin pool to grow """

class LVMVolumeGroupDevice(ContainerDevice):
    """ An LVM Volume Group """
    _type = "lvmvg"
    _packages = ["lvm2"]
    _formatClassName = property(lambda s: "lvmpv")
    _formatUUIDAttr = property(lambda s: "vgUuid")

    def __init__(self, name, parents=None, size=None, free=None,
                 peSize=None, peCount=None, peFree=None, pvCount=None,
                 uuid=None, exists=False, sysfsPath=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword sysfsPath: sysfs device path
            :type sysfsPath: str
            :keyword peSize: physical extent size
            :type peSize: :class:`~.size.Size`

            For existing VG's only:

            :keyword size: the VG's size
            :type size: :class:`~.size.Size`
            :keyword free -- amount of free space in the VG
            :type free: :class:`~.size.Size`
            :keyword peFree: number of free extents
            :type peFree: int
            :keyword peCount -- total number of extents
            :type peCount: int
            :keyword pvCount: number of PVs in this VG
            :type pvCount: int
            :keyword uuid: the VG UUID
            :type uuid: str
        """
        # These attributes are used by _addParent, so they must be initialized
        # prior to instantiating the superclass.
        self._lvs = []
        self.hasDuplicate = False
        self._complete = False  # have we found all of this VG's PVs?
        self.pvCount = util.numeric_type(pvCount)
        if exists and not pvCount:
            self._complete = True

        super(LVMVolumeGroupDevice, self).__init__(name, parents=parents,
                                            uuid=uuid, size=size,
                                            exists=exists, sysfsPath=sysfsPath)

        self.free = util.numeric_type(free)
        self.peSize = util.numeric_type(peSize)
        self.peCount = util.numeric_type(peCount)
        self.peFree = util.numeric_type(peFree)
        self.reserved_percent = 0
        self.reserved_space = Size(0)
        self._thpool_reserve = None

        # this will have to be covered by the 20% pad for non-existent pools
        self.poolMetaData = 0

        # TODO: validate peSize if given
        if not self.peSize:
            self.peSize = lvm.LVM_PE_SIZE

        if not self.exists:
            self.pvCount = len(self.parents)

        # >0 is fixed
        self.size_policy = self.size

    def __repr__(self):
        s = super(LVMVolumeGroupDevice, self).__repr__()
        s += ("  free = %(free)s  PE Size = %(peSize)s  PE Count = %(peCount)s\n"
              "  PE Free = %(peFree)s  PV Count = %(pvCount)s\n"
              "  modified = %(modified)s"
              "  extents = %(extents)s  free space = %(freeSpace)s\n"
              "  free extents = %(freeExtents)s"
              "  reserved percent = %(rpct)s  reserved space = %(res)s\n"
              "  PVs = %(pvs)s\n"
              "  LVs = %(lvs)s" %
              {"free": self.free, "peSize": self.peSize, "peCount": self.peCount,
               "peFree": self.peFree, "pvCount": self.pvCount,
               "modified": self.isModified,
               "extents": self.extents, "freeSpace": self.freeSpace,
               "freeExtents": self.freeExtents,
               "rpct": self.reserved_percent, "res": self.reserved_space,
               "pvs": pprint.pformat([str(p) for p in self.pvs]),
               "lvs": pprint.pformat([str(l) for l in self.lvs])})
        return s

    @property
    def dict(self):
        d = super(LVMVolumeGroupDevice, self).dict
        d.update({"free": self.free, "peSize": self.peSize,
                  "peCount": self.peCount, "peFree": self.peFree,
                  "pvCount": self.pvCount, "extents": self.extents,
                  "freeSpace": self.freeSpace,
                  "freeExtents": self.freeExtents,
                  "reserved_percent": self.reserved_percent,
                  "reserved_space": self.reserved_space,
                  "lvNames": [lv.name for lv in self.lvs]})
        return d

    @property
    def mapName(self):
        """ This device's device-mapper map name """
        # Thank you lvm for this lovely hack.
        return self.name.replace("-","--")

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._devDir, self.mapName)

    def updateSysfsPath(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        self.sysfsPath = ''

    @property
    def status(self):
        """ The device's status (True means active). """
        if not self.exists:
            return False

        # certainly if any of this VG's LVs are active then so are we
        for lv in self.lvs:
            if lv.status:
                return True

        # if any of our PVs are not active then we cannot be
        for pv in self.pvs:
            if not pv.status:
                return False

        # if we are missing some of our PVs we cannot be active
        if not self.complete:
            return False

        return True

    def _preSetup(self, orig=False):
        if self.exists and not self.complete:
            raise errors.DeviceError("cannot activate VG with missing PV(s)", self.name)
        return StorageDevice._preSetup(self, orig=orig)

    def _teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        lvm.vgdeactivate(self.name)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        pv_list = [pv.path for pv in self.parents]
        lvm.vgcreate(self.name, pv_list, self.peSize)

    def _postCreate(self):
        self._complete = True
        super(LVMVolumeGroupDevice, self)._postCreate()

    def _preDestroy(self):
        StorageDevice._preDestroy(self)
        # set up the pvs since lvm needs access to them to do the vgremove
        self.setupParents(orig=True)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        if not self.complete:
            for pv in self.pvs:
                # Remove the PVs from the ignore filter so we can wipe them.
                lvm.lvm_cc_removeFilterRejectRegexp(pv.name)

            # Don't run vgremove or vgreduce since there may be another VG with
            # the same name that we want to keep/use.
            return

        lvm.vgreduce(self.name, None, missing=True)
        lvm.vgdeactivate(self.name)
        lvm.vgremove(self.name)

    def _remove(self, member):
        status = []
        for lv in self.lvs:
            status.append(lv.status)
            if lv.exists:
                lv.setup()

        lvm.pvmove(member.path)
        lvm.vgreduce(self.name, member.path)

        for (lv, status) in zip(self.lvs, status):
            if lv.status and not status:
                lv.teardown()

    def _add(self, member):
        lvm.vgextend(self.name, member.path)

    def _addLogVol(self, lv):
        """ Add an LV to this VG. """
        if lv in self._lvs:
            raise ValueError("lv is already part of this vg")

        # verify we have the space, then add it
        # do not verify for growing vg (because of ks)
        # FIXME: add a "isthin" property and/or "ispool"?
        if not lv.exists and not self.growable and \
           not isinstance(lv, LVMThinLogicalVolumeDevice) and \
           lv.size > self.freeSpace:
            raise errors.DeviceError("new lv is too large to fit in free space", self.name)

        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.append(lv)

    def _removeLogVol(self, lv):
        """ Remove an LV from this VG. """
        if lv not in self.lvs:
            raise ValueError("specified lv is not part of this vg")

        self._lvs.remove(lv)

        if self.poolMetaData and not self.thinpools:
            self.poolMetaData = 0

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.remove(lv)

    def _addParent(self, member):
        super(LVMVolumeGroupDevice, self)._addParent(member)

        # now see if the VG can be activated
        ## XXX TODO: remove this activation code
        if self.exists and member.format.exists and self.complete and \
           flags.installer_mode:
            self.setup()

        if (self.exists and member.format.exists and
            len(self.parents) + 1 == self.pvCount):
            self._complete = True

    def _removeParent(self, member):
        # XXX It would be nice to raise an exception if removing this member
        #     would not leave enough space, but the devicefactory relies on it
        #     being possible to _temporarily_ overcommit the VG.
        #
        #     Maybe removeMember could be a wrapper with the checks and the
        #     devicefactory could call the _ versions to bypass the checks.
        super(LVMVolumeGroupDevice, self)._removeParent(member)

    # We can't rely on lvm to tell us about our size, free space, &c
    # since we could have modifications queued, unless the VG and all of
    # its PVs already exist.
    #
    #        -- liblvm may contain support for in-memory devices

    @property
    def isModified(self):
        """ Return True if the VG has changes queued that LVM is unaware of. """
        modified = True
        if self.exists and not [d for d in self.pvs if not d.exists]:
            modified = False

        return modified

    @property
    def thpool_reserve(self):
        return self._thpool_reserve

    @thpool_reserve.setter
    def thpool_reserve(self, value):
        if value is not None and not isinstance(value, ThPoolReserveSpec):
            raise ValueError("Invalid thpool_reserve given, must be of type ThPoolReserveSpec")
        self._thpool_reserve = value

    @property
    def reservedSpace(self):
        """ Reserved space in this VG """
        reserved = Size(0)
        if self.reserved_percent > 0:
            reserved = self.reserved_percent * Decimal('0.01') * self.size
        elif self.reserved_space > 0:
            reserved = self.reserved_space
        elif self._thpool_reserve and any(self.thinpools):
            reserved = min(max(self._thpool_reserve.percent * Decimal(0.01) * self.size,
                               self._thpool_reserve.min),
                           self._thpool_reserve.max)

        return self.align(reserved, roundup=True)

    @property
    def size(self):
        """ The size of this VG """
        # TODO: just ask lvm if isModified returns False

        # sum up the sizes of the PVs, subtract the unusable (meta data) space
        # and align to pesize
        # NOTE: we either specify data alignment in a PV or the default is used
        #       which is both handled by pv.format.peStart, but LVM takes into
        #       account also the underlying block device which means that e.g.
        #       for an MD RAID device, it tries to align everything also to chunk
        #       size and alignment offset of such device which may result in up
        #       to a twice as big non-data area
        # TODO: move this to either LVMPhysicalVolume's peStart property once
        #       formats know about their devices or to a new LVMPhysicalVolumeDevice
        #       class once it exists
        avail = Size(0)
        for pv in self.pvs:
            if isinstance(pv, MDRaidArrayDevice):
                avail += self.align(pv.size - 2 * pv.format.peStart)
            else:
                avail += self.align(pv.size - pv.format.peStart)

        return avail

    @property
    def extents(self):
        """ Number of extents in this VG """
        # TODO: just ask lvm if isModified returns False

        return int(self.size / self.peSize)

    @property
    def freeSpace(self):
        """ The amount of free space in this VG. """
        # TODO: just ask lvm if isModified returns False

        # get the number of disks used by PVs on RAID (if any)
        raid_disks = 0
        for pv in self.pvs:
            if isinstance(pv, MDRaidArrayDevice):
                raid_disks = max([raid_disks, len(pv.disks)])

        # total the sizes of any LVs
        log.debug("%s size is %s", self.name, self.size)
        used = sum(lv.vgSpaceUsed for lv in self.lvs if not isinstance(lv, LVMThinLogicalVolumeDevice))
        used += self.reservedSpace
        used += self.poolMetaData
        free = self.size - used
        log.debug("vg %s has %s free", self.name, free)
        return free

    @property
    def freeExtents(self):
        """ The number of free extents in this VG. """
        # TODO: just ask lvm if isModified returns False
        return int(self.freeSpace / self.peSize)

    def align(self, size, roundup=None):
        """ Align a size to a multiple of physical extent size. """
        size = util.numeric_type(size)

        return lvm.clampSize(size, self.peSize, roundup=roundup)

    @property
    def pvs(self):
        """ A list of this VG's PVs """
        return self.parents[:]

    @property
    def lvs(self):
        """ A list of this VG's LVs """
        return self._lvs[:]

    @property
    def thinpools(self):
        return [l for l in self._lvs if isinstance(l, LVMThinPoolDevice)]

    @property
    def thinlvs(self):
        return [l for l in self._lvs if isinstance(l, LVMThinLogicalVolumeDevice)]

    @property
    def complete(self):
        """Check if the vg has all its pvs in the system
        Return True if complete.
        """
        # vgs with duplicate names are overcomplete, which is not what we want
        if self.hasDuplicate:
            return False

        return self._complete or not self.exists

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return False

    def populateKSData(self, data):
        super(LVMVolumeGroupDevice, self).populateKSData(data)
        data.vgname = self.name
        data.physvols = ["pv.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        if not self.exists:
            data.pesize = self.peSize.convertTo(spec="KiB")

        # reserved percent/space

    @classmethod
    def isNameValid(cls, name):
        # No . or ..
        if name == '.' or name == '..':
            return False

        # Check that all characters are in the allowed set and that the name
        # does not start with a -
        if not re.match('^[a-zA-Z0-9+_.][a-zA-Z0-9+_.-]*$', name):
            return False

        # According to the LVM developers, vgname + lvname is limited to 126 characters
        # minus the number of hyphens, and possibly minus up to another 8 characters
        # in some unspecified set of situations. Instead of figuring all of that out,
        # no one gets a vg or lv name longer than, let's say, 55.
        if len(name) > 55:
            return False

        return True

class LVMLogicalVolumeDevice(DMDevice):
    """ An LVM Logical Volume """
    _type = "lvmlv"
    _resizable = True
    _packages = ["lvm2"]

    def __init__(self, name, parents=None, size=None, uuid=None,
                 copies=1, logSize=0, segType=None,
                 fmt=None, exists=False, sysfsPath='',
                 grow=None, maxsize=None, percent=None, cacheRequest=None):
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

            For existing LVs only:

            :keyword copies: number of copies in the vg (>1 for mirrored lvs)
            :type copies: int
            :keyword logSize: size of log volume (for mirrored lvs)
            :type logSize: :class:`~.size.Size`
            :keyword segType: segment type (eg: "linear", "raid1")
            :type segType: str

            For non-existent LVs only:

            :keyword grow: whether to grow this LV
            :type grow: bool
            :keyword maxsize: maximum size for growable LV
            :type maxsize: :class:`~.size.Size`
            :keyword percent -- percent of VG space to take
            :type percent: int
            :keyword cacheRequest: parameters of the requested cache (if any)
            :type cacheRequest: :class:`LVMCacheRequest`

        """
        if self.__class__.__name__ == "LVMLogicalVolumeDevice":
            if isinstance(parents, list):
                if len(parents) != 1:
                    raise ValueError("constructor requires a single LVMVolumeGroupDevice instance")
                elif not isinstance(parents[0], LVMVolumeGroupDevice):
                    raise ValueError("constructor requires a LVMVolumeGroupDevice instance")
            elif not isinstance(parents, LVMVolumeGroupDevice):
                raise ValueError("constructor requires a LVMVolumeGroupDevice instance")

        # When this device's format is set in the superclass constructor it will
        # try to access self.snapshots.
        self.snapshots = []
        DMDevice.__init__(self, name, size=size, fmt=fmt,
                          sysfsPath=sysfsPath, parents=parents,
                          exists=exists)

        self.uuid = uuid
        self.copies = copies
        self.logSize = logSize
        self.metaDataSize = 0
        self.segType = segType or "linear"
        self._cache = None

        self.req_grow = None
        self.req_max_size = Size(0)
        self.req_size = Size(0)
        self.req_percent = 0

        if not self.exists:
            self.req_grow = grow
            self.req_max_size = Size(util.numeric_type(maxsize))
            # XXX should we enforce that req_size be pe-aligned?
            self.req_size = self._size
            self.req_percent = util.numeric_type(percent)

        if cacheRequest:
            self._cache = LVMCache(self, cacheRequest.size, exists=False,
                                   fast_pv_names=cacheRequest.fast_devs_names,
                                   mode=cacheRequest.mode)

        # here we go with the circular references
        self.parents[0]._addLogVol(self)

    def __repr__(self):
        s = DMDevice.__repr__(self)
        s += ("  VG device = %(vgdev)r\n"
              "  segment type = %(type)s percent = %(percent)s\n"
              "  mirror copies = %(copies)d"
              "  VG space used = %(vgspace)s" %
              {"vgdev": self.vg, "percent": self.req_percent,
               "copies": self.copies, "type": self.segType,
               "vgspace": self.vgSpaceUsed })
        return s

    @property
    def dict(self):
        d = super(LVMLogicalVolumeDevice, self).dict
        if self.exists:
            d.update({"copies": self.copies,
                      "vgspace": self.vgSpaceUsed})
        else:
            d.update({"percent": self.req_percent})

        return d

    @property
    def mirrored(self):
        return self.copies > 1

    def _setSize(self, size):
        if not isinstance(size, Size):
            raise ValueError("new size must of type Size")

        size = self.vg.align(size)
        log.debug("trying to set lv %s size to %s", self.name, size)
        if size <= self.vg.freeSpace + self.vgSpaceUsed:
            self._size = size
            self.targetSize = size
        else:
            log.debug("failed to set size: %s short", size - (self.vg.freeSpace + self.vgSpaceUsed))
            raise ValueError("not enough free space in volume group")

    size = property(StorageDevice._getSize, _setSize)

    @property
    def maxSize(self):
        """ The maximum size this lv can be. """
        max_lv = self.size + self.vg.freeSpace
        max_format = self.format.maxSize
        return min(max_lv, max_format) if max_format else max_lv

    @property
    def vgSpaceUsed(self):
        """ Space occupied by this LV, not including snapshots. """
        cache_size = Size(0)
        if self.cached:
            cache_size = self.cache.size
        return (self.vg.align(self.size, roundup=True) * self.copies
                + self.logSize + 2 * self.metaDataSize + cache_size)

    def _setFormat(self, fmt):
        super(LVMLogicalVolumeDevice, self)._setFormat(fmt)
        for snapshot in (s for s in self.snapshots if not s.exists):
            snapshot._updateFormatFromOrigin()

    @property
    def vg(self):
        """ This Logical Volume's Volume Group. """
        return self.parents[0]

    @property
    def container(self):
        return self.vg

    @property
    def mapName(self):
        """ This device's device-mapper map name """
        # Thank you lvm for this lovely hack.
        return "%s-%s" % (self.vg.mapName, self._name.replace("-","--"))

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._devDir, self.mapName)

    def getDMNode(self):
        """ Return the dm-X (eg: dm-0) device node for this device. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        return dm.dm_node_from_name(self.mapName)

    def _getName(self):
        """ This device's name. """
        return "%s-%s" % (self.vg.name, self._name)

    @property
    def lvname(self):
        """ The LV's name (not including VG name). """
        return self._name

    @property
    def complete(self):
        """ Test if vg exits and if it has all pvs. """
        return self.vg.complete

    def setupParents(self, orig=False):
        # parent is a vg, which has no formatting (or device for that matter)
        Device.setupParents(self, orig=orig)

    def _preSetup(self, orig=False):
        # If the lvmetad socket exists and any PV is inactive before we call
        # setupParents (via _preSetup, below), we should wait for auto-
        # activation before trying to manually activate this LV.
        auto_activate = (lvm.lvmetad_socket_exists() and
                         any(not pv.status for pv in self.vg.pvs))
        if not super(LVMLogicalVolumeDevice, self)._preSetup(orig=orig):
            return False

        if auto_activate:
            log.debug("waiting for lvm auto-activation of %s", self.name)
            # Wait for auto-activation for up to 30 seconds. If this LV hasn't
            # been activated when the timeout is reached, there may be some
            # lvm.conf content preventing auto-activation of this LV, so we
            # have to do it ourselves.
            # The timeout value of 30 seconds was suggested by prajnoha. He
            # noted that udev uses the same value, for whatever that's worth.
            timeout = 30 # seconds
            start = time.time()
            while time.time() - start < timeout:
                if self.status:
                    # already active -- don't try to activate it manually
                    log.debug("%s has been auto-activated", self.name)
                    return False
                else:
                    log.debug("%s not active yet; sleeping...", self.name)
                    time.sleep(0.5)

            log.debug("lvm auto-activation timeout reached for %s", self.name)

        return True

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        lvm.lvactivate(self.vg.name, self._name)

    def _teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        lvm.lvdeactivate(self.vg.name, self._name)

    def _postTeardown(self, recursive=False):
        try:
            # It's likely that teardown of a VG will fail due to other
            # LVs being active (filesystems mounted, &c), so don't let
            # it bring everything down.
            StorageDevice._postTeardown(self, recursive=recursive)
        except errors.StorageError:
            if recursive:
                log.debug("vg %s teardown failed; continuing", self.vg.name)
            else:
                raise

    def _preCreate(self):
        super(LVMLogicalVolumeDevice, self)._preCreate()

        try:
            vg_info = lvm.vginfo(self.vg.name)
        except errors.LVMError as lvmerr:
            log.error("Failed to get free space for the %s VG: %s", self.vg.name, lvmerr)
            # nothing more can be done, we don't know the VG's free space
            return

        extent_size = Size(vg_info["LVM2_VG_EXTENT_SIZE"] + "MiB")
        extents_free = int(vg_info["LVM2_VG_FREE_COUNT"])
        can_use = extent_size * extents_free

        if self.size > can_use:
            msg = ("%s LV's size (%s) exceeds the VG's usable free space (%s),"
                  "shrinking the LV") % (self.name, self.size, can_use)
            log.warning(msg)
            self.size = can_use

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        # should we use --zero for safety's sake?
        if self.cached:
            # prepare the list of fast PV devices
            fast_pvs = []
            for pv in self.cache.fast_pv_names:
                # make sure we have the full device paths
                if not pv.startswith("/dev/"):
                    fast_pvs.append("/dev/%s" % pv)
                else:
                    fast_pvs.append(pv)

            # get the list of all fast PV devices used in the VG so that we can
            # consider the rest to be slow PVs and generate a list of them
            all_fast_pvs_names = set()
            for lv in self.vg.lvs:
                if lv.cached and lv.cache.fast_pv_names:
                    all_fast_pvs_names |= set(lv.cache.fast_pv_names)
            slow_pvs = [pv.path for pv in self.vg.pvs if pv.name not in all_fast_pvs_names]

            # TODO: allow specification of metadata size
            # for now, we just make the metadata+data parts take the requested cache space together
            md_size = lvm.cachepool_default_md_size(self.cache.size)
            data_size = self.cache.size - md_size

            lvm.lvcreate_cached(self.vg.name, self._name, self.size,
                                data_size, md_size, self.cache.mode,
                                slow_pvs, fast_pvs)
        else:
            lvm.lvcreate(self.vg.name, self._name, self.size)

    def _preDestroy(self):
        StorageDevice._preDestroy(self)
        # set up the vg's pvs so lvm can remove the lv
        self.vg.setupParents(orig=True)

        # setting up VG's PVs may have caused this LV was automatically
        # activated, make sure it is deactivated before removal
        self.teardown()

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        lvm.lvremove(self.vg.name, self._name)

    def resize(self):
        log_method_call(self, self.name, status=self.status)

        # Setup VG parents (in case they are dmraid partitions for example)
        self.vg.setupParents(orig=True)

        if self.originalFormat.exists:
            self.originalFormat.teardown()
        if self.format.exists:
            self.format.teardown()

        udev.settle()
        lvm.lvresize(self.vg.name, self._name, self.size)

    @property
    def isleaf(self):
        # Thin snapshots do not need to be removed prior to removal of the
        # origin, but the old snapshots do.
        non_thin_snapshots = any(s for s in self.snapshots
                                    if not isinstance(s, LVMThinSnapShotDevice))
        return (super(LVMLogicalVolumeDevice, self).isleaf and
                not non_thin_snapshots)

    @property
    def direct(self):
        """ Is this device directly accessible? """
        # an LV can contain a direct filesystem if it is a leaf device or if
        # its only dependent devices are snapshots
        return super(LVMLogicalVolumeDevice, self).isleaf

    def dracutSetupArgs(self):
        # Note no mapName usage here, this is a lvm cmdline name, which
        # is different (ofcourse)
        return set(["rd.lvm.lv=%s/%s" % (self.vg.name, self._name)])

    def checkSize(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.maxSize and self.size > self.format.maxSize:
            return 1
        elif (self.format.minSize and
              (not self.req_grow and
               self.size < self.format.minSize) or
              (self.req_grow and self.req_max_size and
               self.req_max_size < self.format.minSize)):
            return -1
        return 0

    def removeHook(self, modparent=True):
        if modparent:
            self.vg._removeLogVol(self)

        super(LVMLogicalVolumeDevice, self).removeHook(modparent=modparent)

    def addHook(self, new=True):
        super(LVMLogicalVolumeDevice, self).addHook(new=new)
        if new:
            return

        if self not in self.vg.lvs:
            self.vg._addLogVol(self)

    def populateKSData(self, data):
        super(LVMLogicalVolumeDevice, self).populateKSData(data)
        data.vgname = self.vg.name
        data.name = self.lvname
        data.preexist = self.exists
        data.resize = (self.exists and self.targetSize and
                       self.targetSize != self.currentSize)
        if not self.exists:
            data.grow = self.req_grow
            if self.req_percent:
                data.percent = self.req_percent

            if self.req_grow:
                if not self.req_percent:
                    data.size = self.req_size.convertTo(spec="MiB")
                data.maxSizeMB = self.req_max_size.convertTo(spec="MiB")
            else:
                if not self.req_percent:
                    data.size = self.size.convertTo(spec="MiB")
        elif data.resize:
            data.size = self.targetSize.convertTo(spec="MiB")

    @classmethod
    def isNameValid(cls, name):
        # Check that the LV name is valid

        # Start with the checks shared with volume groups
        if not LVMVolumeGroupDevice.isNameValid(name):
            return False

        # And now the ridiculous ones
        # These strings are taken from apply_lvname_restrictions in lib/misc/lvm-string.c
        reserved_prefixes = set(['pvmove', 'snapshot'])
        reserved_substrings = set(['_cdata', '_cmeta', '_mimage', '_mlog', '_pmspare', '_rimage',
                                   '_rmeta', '_tdata', '_tmeta', '_vorigin'])

        for prefix in reserved_prefixes:
            if name.startswith(prefix):
                return False

        for substring in reserved_substrings:
            if substring in name:
                return False

        return True

    @property
    def cached(self):
        return bool(self._cache)

    @property
    def cache(self):
        return self._cache

    @cache.setter
    def cache(self, val):
        self._cache = val

class LVMSnapShotBase(object):
    """ Abstract base class for lvm snapshots

        This class is intended to be used with multiple inheritance in addition
        to some subclass of :class:`~.StorageDevice`.

        Snapshots do not have their origin/source volume as parent. They are
        like other LVs except that they have an origin attribute and are in that
        instance's snapshots list.

        Normal/old snapshots must be removed with their origin, while thin
        snapshots can remain after their origin is removed.

        It is also impossible to set the format for a non-existent snapshot
        explicitly as it always has the same format as its origin.
    """
    __metaclass__ = abc.ABCMeta
    _type = "lvmsnapshotbase"

    def __init__(self, origin=None, vorigin=False, exists=False):
        """
            :keyword :class:`~.LVMLogicalVolumeDevice` origin: source volume
            :keyword bool vorigin: is this a vorigin snapshot?
            :keyword bool exists: is this an existing snapshot?

            vorigin is a special type of device that makes use of snapshots to
            create a sparse device. These snapshots have no origin lv, instead
            using space in the vg directly. Only preexisting vorigin snapshots
            are supported here.
        """
        self._originSpecifiedCheck(origin, vorigin, exists)
        self._originTypeCheck(origin)
        self._voriginExistenceCheck(vorigin, exists)

        self.origin = origin
        """ the snapshot's source volume """

        self.vorigin = vorigin
        """ a boolean flag indicating a vorigin snapshot """

    def _originSpecifiedCheck(self, origin, vorigin, exists):
        # pylint: disable=unused-argument
        if not origin and not vorigin:
            raise ValueError("lvm snapshot devices require an origin lv")

    def _originTypeCheck(self, origin):
        if origin and not isinstance(origin, LVMLogicalVolumeDevice):
            raise ValueError("lvm snapshot origin must be a logical volume")

    def _voriginExistenceCheck(self, vorigin, exists):
        if vorigin and not exists:
            raise ValueError("only existing vorigin snapshots are supported")

    def _updateFormatFromOrigin(self):
        """ Update the snapshot's format to reflect the origin's.

            .. note::
                This should only be called for non-existent snapshot devices.
                Once a snapshot exists its format is distinct from that of its
                origin.

        """
        fmt = copy.deepcopy(self.origin.format)
        fmt.exists = False
        if hasattr(fmt, "mountpoint"):
            fmt._mountpoint = None
            fmt._chrootedMountpoint = None
            fmt.device = self.path # pylint: disable=no-member

        super(LVMSnapShotBase, self)._setFormat(fmt)

    def _setFormat(self, fmt):
        # If a snapshot exists it can have a format that is distinct from its
        # origin's. If it does not exist its format must be a copy of its
        # origin's.
        if self.exists: # pylint: disable=no-member
            super(LVMSnapShotBase, self)._setFormat(fmt)
        else:
            log.info("copying %s origin's format", self.name) # pylint: disable=no-member
            self._updateFormatFromOrigin()

    @abc.abstractmethod
    def _create(self):
        """ Create the device. """
        raise NotImplementedError()

    def merge(self):
        """ Merge the snapshot back into its origin volume. """
        log_method_call(self, self.name, status=self.status) # pylint: disable=no-member
        self.vg.setup()    # pylint: disable=no-member
        try:
            self.origin.teardown()
        except errors.FSError:
            # the merge will begin based on conditions described in the --merge
            # section of lvconvert(8)
            pass

        try:
            self.teardown() # pylint: disable=no-member
        except errors.FSError:
            pass

        udev.settle()
        lvm.lvsnapshotmerge(self.vg.name, self.lvname) # pylint: disable=no-member


class LVMSnapShotDevice(LVMSnapShotBase, LVMLogicalVolumeDevice):
    """ An LVM snapshot """
    _type = "lvmsnapshot"
    _formatImmutable = True

    def __init__(self, name, parents=None, size=None, uuid=None,
                 copies=1, logSize=0, segType=None,
                 fmt=None, exists=False, sysfsPath='',
                 grow=None, maxsize=None, percent=None,
                 origin=None, vorigin=False):
        """ Create an LVMSnapShotDevice instance.

            This class is for the old-style (not thin) lvm snapshots. The origin
            volume cannot be removed without also removing all snapshots (not so
            for thin snapshots). Also, the snapshot is automatically activated
            or deactivated with its origin.

            :param str name: the device name (generally a device node basename)
            :keyword bool exists: does this device exist?
            :keyword :class:`~.size.Size` size: the device's size
            :keyword :class:`~.ParentList` parents: list of parent devices
            :keyword fmt: this device's formatting
            :type fmt: :class:`~.formats.DeviceFormat`
            :keyword str sysfsPath: sysfs device path
            :keyword str uuid: the device UUID
            :keyword str segType: segment type

            :keyword :class:`~.StorageDevice` origin: the origin/source volume
            :keyword bool vorigin: is this a vorigin snapshot?

            For non-existent devices only:

            :keyword bool grow: whether to grow this LV
            :keyword :class:`~.size.Size` maxsize: maximum size for growable LV
            :keyword int percent: percent of VG space to take
        """
        # pylint: disable=unused-argument

        if isinstance(origin, LVMLogicalVolumeDevice) and \
           isinstance(parents[0], LVMVolumeGroupDevice) and \
           origin.vg != parents[0]:
            raise ValueError("lvm snapshot and origin must be in the same vg")

        LVMSnapShotBase.__init__(self, origin=origin, vorigin=vorigin,
                                 exists=exists)

        LVMLogicalVolumeDevice.__init__(self, name, parents=parents, size=size,
                                        uuid=uuid, fmt=None, exists=exists,
                                        copies=copies, logSize=logSize,
                                        segType=segType,
                                        sysfsPath=sysfsPath, grow=grow,
                                        maxsize=maxsize, percent=percent)

    def setup(self, orig=False):
        pass

    def teardown(self, recursive=False):
        pass

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        lvm.lvsnapshotcreate(self.vg.name, self._name, self.size,
                             self.origin.lvname)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        # old-style snapshots' status is tied to the origin's so we never
        # explicitly activate or deactivate them and we have to tell lvremove
        # that it is okay to remove the active snapshot
        lvm.lvremove(self.vg.name, self._name, force=True)

    def _getPartedDevicePath(self):
        return "%s-cow" % self.path

    def dependsOn(self, dep):
        # pylint: disable=bad-super-call
        return (self.origin == dep or
                super(LVMSnapShotBase, self).dependsOn(dep))

    def _postCreate(self):
        LVMLogicalVolumeDevice._postCreate(self)
        # the snapshot's format exists if the origin's format exists
        self.format.exists = self.origin.format.exists


class LVMThinPoolDevice(LVMLogicalVolumeDevice):
    """ An LVM Thin Pool """
    _type = "lvmthinpool"
    _resizable = False

    def __init__(self, name, parents=None, size=None, uuid=None,
                 fmt=None, exists=False, sysfsPath='',
                 grow=None, maxsize=None, percent=None,
                 metadatasize=None, chunksize=None, segType=None, profile=None):
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
            :keyword segType: segment type
            :type segType: str

            For non-existent pools only:

            :keyword grow: whether to grow this LV
            :type grow: bool
            :keyword maxsize: maximum size for growable LV
            :type maxsize: :class:`~.size.Size`
            :keyword percent: percent of VG space to take
            :type percent: int
            :keyword metadatasize: the size of the metadata LV
            :type metadatasize: :class:`~.size.Size`
            :keyword chunksize: chunk size for the pool
            :type chunksize: :class:`~.size.Size`
            :keyword profile: (allocation) profile for the pool or None (unspecified)
            :type profile: :class:`~.devicelibs.lvm.ThPoolProfile` or NoneType

        """
        if metadatasize is not None and \
           not lvm.is_valid_thin_pool_metadata_size(metadatasize):
            raise ValueError("invalid metadatasize value")

        if chunksize is not None and \
           not lvm.is_valid_thin_pool_chunk_size(chunksize):
            raise ValueError("invalid chunksize value")

        super(LVMThinPoolDevice, self).__init__(name, parents=parents,
                                                size=size, uuid=uuid,
                                                fmt=fmt, exists=exists,
                                                sysfsPath=sysfsPath, grow=grow,
                                                maxsize=maxsize,
                                                percent=percent,
                                                segType=segType)

        self.chunkSize = chunksize or 0
        self.profile = profile
        self._lvs = []

        self.metaDataSize = Size(0)
        if metadatasize:
            self.metaDataSize = metadatasize
        elif not self.exists and not grow:
            # a thin pool we are not going to grow -> lets calculate metadata
            # size now if not given explicitly
            self.autoset_md_size()

    def _addLogVol(self, lv):
        """ Add an LV to this pool. """
        if lv in self._lvs:
            raise ValueError("lv is already part of this vg")

        # TODO: add some checking to prevent overcommit for preexisting
        self.vg._addLogVol(lv)
        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

    def _removeLogVol(self, lv):
        """ Remove an LV from this pool. """
        if lv not in self._lvs:
            raise ValueError("specified lv is not part of this vg")

        self._lvs.remove(lv)
        self.vg._removeLogVol(lv)

    @property
    def lvs(self):
        """ A list of this pool's LVs """
        return self._lvs[:]     # we don't want folks changing our list

    @property
    def usedSpace(self):
        return sum(l.poolSpaceUsed for l in self.lvs)

    @property
    def freeSpace(self):
        return self.size - self.usedSpace

    def autoset_md_size(self):
        """ If self._metadata_size not set already, it calculates the recommended value
        and sets it while subtracting the size from self.size.

        """
        if self.metaDataSize != 0:
            return  # Metadata size already set

        if self.size == 0:
            return  # no size (yet) to derive MD size from

        log.debug("Auto-setting thin pool metadata size")

        # we need to know chunk size to calculate recommended metadata size
        if self.chunkSize == 0:
            self.chunkSize = lvm.LVM_THINP_DEFAULT_CHUNK_SIZE
            log.debug("Using default chunk size: %s", self.chunkSize)

        self.metaDataSize = lvm.get_pool_metadata_size(self._size,
                                                       self.chunkSize,
                                                       100)  # snapshots
        log.debug("Recommended metadata size: %s", self.metaDataSize)

        self.metaDataSize = self.vg.align(self.metaDataSize, roundup=True)
        log.debug("Rounded metadata size to extents: %s", self.metaDataSize)

        # we also need space for the (potential) pmspare LV (of the same size as
        # the metaDataSize)
        log.debug("Adjusting size from %s to %s", self.size, self.size - 2 * self.metaDataSize)
        self._size = self.size - 2 * self.metaDataSize

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        # TODO: chunk size, data/metadata split --> profile
        if self.profile:
            profile_name = self.profile.name
        else:
            profile_name = ""

        lvm.thinpoolcreate(self.vg.name, self.lvname, self.size,
                           metadatasize=self.metaDataSize,
                           chunksize=self.chunkSize,
                           profile=profile_name)

    def dracutSetupArgs(self):
        return set()

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return False

    def populateKSData(self, data):
        super(LVMThinPoolDevice, self).populateKSData(data)
        data.mountpoint = "none"
        data.thin_pool = True
        data.metadata_size = self.metaDataSize
        data.chunk_size = self.chunkSize
        if self.profile:
            data.profile = self.profile.name

class LVMThinLogicalVolumeDevice(LVMLogicalVolumeDevice):
    """ An LVM Thin Logical Volume """
    _type = "lvmthinlv"

    @property
    def pool(self):
        return self.parents[0]

    @property
    def vg(self):
        return self.pool.vg

    @property
    def poolSpaceUsed(self):
        """ The total space used within the thin pool by this volume.

            This should probably align to the greater of vg extent size and
            pool chunk size. If it ends up causing overcommit in the amount of
            less than one chunk per thin lv, so be it.
        """
        return self.vg.align(self.size, roundup=True)

    @property
    def vgSpaceUsed(self):
        return 0    # the pool's size is already accounted for in the vg

    def _setSize(self, size):
        if not isinstance(size, Size):
            raise ValueError("new size must of type Size")

        size = self.vg.align(size)
        size = self.vg.align(util.numeric_type(size))
        self._size = size
        self.targetSize = size

    size = property(StorageDevice._getSize, _setSize)

    def _preCreate(self):
        # skip LVMLogicalVolumeDevice's _preCreate() method as it checks for a
        # free space in a VG which doesn't make sense for a ThinLV and causes a
        # bug by limitting the ThinLV's size to VG free space which is nonsense
        super(LVMLogicalVolumeDevice, self)._preCreate() # pylint: disable=bad-super-call

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        lvm.thinlvcreate(self.vg.name, self.pool.lvname, self.lvname,
                         self.size)

    def removeHook(self, modparent=True):
        if modparent:
            self.pool._removeLogVol(self)

        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeDevice, self).removeHook(modparent=modparent)

    def addHook(self, new=True):
        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeDevice, self).addHook(new=new)
        if new:
            return

        if self not in self.pool.lvs:
            self.pool._addLogVol(self)

    def populateKSData(self, data):
        super(LVMThinLogicalVolumeDevice, self).populateKSData(data)
        data.thin_volume = True
        data.pool_name = self.pool.lvname

class LVMThinSnapShotDevice(LVMSnapShotBase, LVMThinLogicalVolumeDevice):
    """ An LVM Thin Snapshot """
    _type = "lvmthinsnapshot"
    _resizable = False
    _formatImmutable = True

    def __init__(self, name, parents=None, sysfsPath='', origin=None,
                 fmt=None, uuid=None, size=None, exists=False, segType=None):
        """
            :param str name: the name of the device
            :param :class:`~.ParentList` parents: parent devices
            :param str sysfsPath: path to this device's /sys directory
            :keyword origin: the origin(source) volume for the snapshot
            :type origin: :class:`~.LVMLogicalVolumeDevice` or None
            :keyword str segType: segment type
            :keyword :class:`~.formats.DeviceFormat` fmt: this device's format
            :keyword str uuid: the device UUID
            :keyword :class:`~.size.Size` size: the device's size
            :keyword bool exists: is this an existing device?

            LVM thin snapshots can remain after their origin volume is removed,
            unlike the older-style snapshots.
        """
        # pylint: disable=unused-argument

        if isinstance(origin, LVMLogicalVolumeDevice) and \
           isinstance(parents[0], LVMThinPoolDevice) and \
           origin.vg != parents[0].vg:
            raise ValueError("lvm snapshot and origin must be in the same vg")

        if size and not exists:
            raise ValueError("thin snapshot size is determined automatically")

        LVMSnapShotBase.__init__(self, origin=origin, exists=exists)
        LVMThinLogicalVolumeDevice.__init__(self, name, parents=parents,
                                            sysfsPath=sysfsPath,fmt=fmt,
                                            segType=segType,
                                            uuid=uuid, size=size, exists=exists)

    def _originSpecifiedCheck(self, origin, vorigin, exists):
        if not exists and not origin:
            raise ValueError("non-existent lvm thin snapshots require an origin")

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        lvm.lvactivate(self.vg.name, self._name, ignore_skip=True)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        pool_name = None
        if not isinstance(self.origin, LVMThinLogicalVolumeDevice):
            # if the origin is not a thin volume we need to tell lvm which pool
            # to use
            pool_name = self.pool.lvname

        lvm.thinsnapshotcreate(self.vg.name, self._name, self.origin.lvname,
                               pool_name=pool_name)


    def _postCreate(self):
        LVMThinLogicalVolumeDevice._postCreate(self)
        # the snapshot's format exists if the origin's format exists
        self.format.exists = self.origin.format.exists

    def dependsOn(self, dep):
        # once a thin snapshot exists it no longer depends on its origin
        return ((self.origin == dep and not self.exists) or
                super(LVMThinSnapShotDevice, self).dependsOn(dep))

class LVMCache(object):
    """Class providing the cache-related functionality of a cached LV"""

    def __init__(self, cached_lv, size=None, exists=False, fast_pv_names=None, mode=None):
        """
        :param cached_lv: the LV the cache functionality of which to provide
        :type cached_lv: :class:`LVMLogicalVolumeDevice`
        :param size: size of the cache (useful mainly for non-existing caches
                     that cannot determine their size dynamically)
        :type size: :class:`~.size.Size`
        :param bool exists: whether the cache exists or not
        :param fast_pv_names: PVs to allocate the cache on/from (ignored for existing)
        :type fast_pv_names: list of str
        :param str mode: desired mode for non-existing cache (ignored for existing)

        """
        self._cached_lv = cached_lv
        self._size = size
        self._exists = exists
        self._fast_pvs = fast_pv_names
        self._mode = mode

    @property
    def size(self):
        return self._size

    @property
    def exists(self):
        return self._exists

    @property
    def fast_pv_names(self):
        return self._fast_pvs

    @property
    def mode(self):
        return self._mode

class LVMCacheRequest(object):
    """Class representing the LVM cache creation request"""
    def __init__(self, size, fast_pv_names, mode=None):
        """
        :param size: requested size of the cache
        :type size: :class:`~.size.Size`
        :param fast_pv_names: PVs to allocate the cache on/from
        :type fast_pv_names: list of str
        :param str mode: requested mode for the cache (``None`` means the default is used)

        """
        self._size = size
        self._fast_pvs = fast_pv_names
        self._mode = mode or "writethrough"

    @property
    def size(self):
        return self._size

    @property
    def fast_devs_names(self):
        return self._fast_pvs

    @property
    def mode(self):
        return self._mode
