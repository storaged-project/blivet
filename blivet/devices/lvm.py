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
from six import add_metaclass
import abc
import copy
import pprint
import re
import os
import time
from collections import namedtuple

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

# device backend modules
from ..devicelibs import lvm

from .. import errors
from .. import util
from ..storage_log import log_method_call
from .. import udev
from ..size import Size, KiB, MiB, ROUND_UP, ROUND_DOWN
from ..tasks import availability

import logging
log = logging.getLogger("blivet")

from .lib import LINUX_SECTOR_SIZE, ParentList
from .device import Device
from .storage import StorageDevice
from .container import ContainerDevice
from .dm import DMDevice
from .md import MDRaidArrayDevice
from .cache import Cache, CacheStats, CacheRequest

_INTERNAL_LV_CLASSES = []


def get_internal_lv_class(lv_attr):
    if lv_attr[0] == "C":
        # cache pools and internal data LV of cache pools need a more complicated check
        if lv_attr[6] == "C":
            # target type == cache -> cache pool
            return LVMCachePoolLogicalVolumeDevice
        else:
            return LVMDataLogicalVolumeDevice
    for cls in _INTERNAL_LV_CLASSES:
        if lv_attr[0] in cls.attr_letters:
            return cls

    return None


class LVPVSpec(object):
    """ Class for specifying how much space on a PV should be allocated for some LV """
    def __init__(self, pv, size):
        self.pv = pv
        self.size = size

PVFreeInfo = namedtuple("PVFreeInfo", ["pv", "size", "free"])
""" A namedtuple class holding the information about PV's (usable) size and free space """


class LVMVolumeGroupDevice(ContainerDevice):

    """ An LVM Volume Group """
    _type = "lvmvg"
    _packages = ["lvm2"]
    _format_class_name = property(lambda s: "lvmpv")
    _format_uuid_attr = property(lambda s: "vg_uuid")
    _format_immutable = True

    @staticmethod
    def get_supported_pe_sizes():
        return [Size(pe_size) for pe_size in blockdev.lvm.get_supported_pe_sizes()]

    def __init__(self, name, parents=None, size=None, free=None,
                 pe_size=None, pe_count=None, pe_free=None, pv_count=None,
                 uuid=None, exists=False, sysfs_path=''):
        """
            :param name: the device name (generally a device node's basename)
            :type name: str
            :keyword exists: does this device exist?
            :type exists: bool
            :keyword parents: a list of parent devices
            :type parents: list of :class:`StorageDevice`
            :keyword sysfs_path: sysfs device path
            :type sysfs_path: str
            :keyword pe_size: physical extent size
            :type pe_size: :class:`~.size.Size`

            For existing VG's only:

            :keyword size: the VG's size
            :type size: :class:`~.size.Size`
            :keyword free -- amount of free space in the VG
            :type free: :class:`~.size.Size`
            :keyword pe_free: number of free extents
            :type pe_free: int
            :keyword pe_count -- total number of extents
            :type pe_count: int
            :keyword pv_count: number of PVs in this VG
            :type pv_count: int
            :keyword uuid: the VG UUID
            :type uuid: str
        """
        # These attributes are used by _add_parent, so they must be initialized
        # prior to instantiating the superclass.
        self._lvs = []
        self.has_duplicate = False
        self._complete = False  # have we found all of this VG's PVs?
        self.pv_count = util.numeric_type(pv_count)
        if exists and not pv_count:
            self._complete = True
        self.pe_size = util.numeric_type(pe_size)
        self.pe_count = util.numeric_type(pe_count)
        self.pe_free = util.numeric_type(pe_free)

        # TODO: validate pe_size if given
        if not self.pe_size:
            self.pe_size = lvm.LVM_PE_SIZE

        super(LVMVolumeGroupDevice, self).__init__(name, parents=parents,
                                                   uuid=uuid, size=size,
                                                   exists=exists, sysfs_path=sysfs_path)

        self.free = util.numeric_type(free)
        self._reserved_percent = 0
        self._reserved_space = Size(0)

        if not self.exists:
            self.pv_count = len(self.parents)

        # >0 is fixed
        self.size_policy = self.size

    def __repr__(self):
        s = super(LVMVolumeGroupDevice, self).__repr__()
        s += ("  free = %(free)s  PE Size = %(pe_size)s  PE Count = %(pe_count)s\n"
              "  PE Free = %(pe_free)s  PV Count = %(pv_count)s\n"
              "  modified = %(modified)s"
              "  extents = %(extents)s  free space = %(free_space)s\n"
              "  free extents = %(free_extents)s"
              "  reserved percent = %(rpct)s  reserved space = %(res)s\n"
              "  PVs = %(pvs)s\n"
              "  LVs = %(lvs)s" %
              {"free": self.free, "pe_size": self.pe_size, "pe_count": self.pe_count,
               "pe_free": self.pe_free, "pv_count": self.pv_count,
               "modified": self.is_modified,
               "extents": self.extents, "free_space": self.free_space,
               "free_extents": self.free_extents,
               "rpct": self._reserved_percent, "res": self._reserved_space,
               "pvs": pprint.pformat([str(p) for p in self.pvs]),
               "lvs": pprint.pformat([str(l) for l in self.lvs])})
        return s

    @property
    def dict(self):
        d = super(LVMVolumeGroupDevice, self).dict
        d.update({"free": self.free, "pe_size": self.pe_size,
                  "pe_count": self.pe_count, "pe_free": self.pe_free,
                  "pv_count": self.pv_count, "extents": self.extents,
                  "free_space": self.free_space,
                  "free_extents": self.free_extents,
                  "reserved_percent": self._reserved_percent,
                  "reserved_space": self._reserved_space,
                  "lv_names": [lv.name for lv in self.lvs]})
        return d

    @property
    def map_name(self):
        """ This device's device-mapper map name """
        # Thank you lvm for this lovely hack.
        return self.name.replace("-", "--")

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._dev_dir, self.map_name)

    def update_sysfs_path(self):
        """ Update this device's sysfs path. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        self.sysfs_path = ''

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

    def _pre_setup(self, orig=False):
        if self.exists and not self.complete:
            raise errors.DeviceError("cannot activate VG with missing PV(s)", self.name)
        return StorageDevice._pre_setup(self, orig=orig)

    def _teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        blockdev.lvm.vgdeactivate(self.name)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        pv_list = [pv.path for pv in self.parents]
        blockdev.lvm.vgcreate(self.name, pv_list, self.pe_size)

    def _post_create(self):
        self._complete = True
        super(LVMVolumeGroupDevice, self)._post_create()

    def _pre_destroy(self):
        StorageDevice._pre_destroy(self)
        # set up the pvs since lvm needs access to them to do the vgremove
        self.setup_parents(orig=True)

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

        blockdev.lvm.vgreduce(self.name, None)
        blockdev.lvm.vgdeactivate(self.name)
        blockdev.lvm.vgremove(self.name)

    def _remove(self, member):
        status = []
        for lv in self.lvs:
            status.append(lv.status)
            if lv.exists:
                lv.setup()

        blockdev.lvm.pvmove(member.path)
        blockdev.lvm.vgreduce(self.name, member.path)

        for (lv, status) in zip(self.lvs, status):
            if lv.status and not status:
                lv.teardown()

    def _add(self, member):
        blockdev.lvm.vgextend(self.name, member.path)

    def _add_log_vol(self, lv):
        """ Add an LV to this VG. """
        if lv in self._lvs:
            raise ValueError("lv is already part of this vg")

        # verify we have the space, then add it
        # do not verify for growing vg (because of ks)
        # FIXME: add a "isthin" property and/or "ispool"?
        if not lv.exists and not self.growable and \
           not isinstance(lv, LVMThinLogicalVolumeDevice) and \
           lv.size > self.free_space:
            raise errors.DeviceError("new lv is too large to fit in free space", self.name)

        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.append(lv)

        # PV space accounting
        pv_sizes = lv.pv_space_used
        if not lv.exists and pv_sizes:
            for size_spec in pv_sizes:
                # check that we have enough space in the PVs for the LV and
                # account for it
                if size_spec.pv.format.free < size_spec.size:
                    msg = "not enough space in the '%s' PV for the '%s' LV's extents" % (size_spec.pv.name, lv.name)
                    raise errors.DeviceError(msg)
                size_spec.pv.format.free -= size_spec.size

    def _remove_log_vol(self, lv):
        """ Remove an LV from this VG. """
        if lv not in self.lvs:
            raise ValueError("specified lv is not part of this vg")

        self._lvs.remove(lv)

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.remove(lv)

        # PV space accounting
        pv_sizes = lv.pv_space_used
        if not lv.exists and pv_sizes:
            for size_spec in pv_sizes:
                size_spec.pv.format.free += size_spec.size

    def _add_parent(self, member):
        super(LVMVolumeGroupDevice, self)._add_parent(member)

        if (self.exists and member.format.exists and
                len(self.parents) + 1 == self.pv_count):
            self._complete = True

        # this PV object is just being added so it has all its space available
        # (adding LVs will eat that space later)
        if not member.format.exists:
            member.format.free = self._get_pv_usable_space(member)

    def _remove_parent(self, member):
        # XXX It would be nice to raise an exception if removing this member
        #     would not leave enough space, but the devicefactory relies on it
        #     being possible to _temporarily_ overcommit the VG.
        #
        #     Maybe remove_member could be a wrapper with the checks and the
        #     devicefactory could call the _ versions to bypass the checks.
        super(LVMVolumeGroupDevice, self)._remove_parent(member)
        member.format.free = None

    # We can't rely on lvm to tell us about our size, free space, &c
    # since we could have modifications queued, unless the VG and all of
    # its PVs already exist.
    @property
    def is_modified(self):
        """ Return True if the VG has changes queued that LVM is unaware of. """
        modified = True
        if self.exists and not [d for d in self.pvs if not d.exists]:
            modified = False

        return modified

    @property
    def reserved_space(self):
        """ Reserved space in this VG """
        reserved = Size(0)
        if self._reserved_percent > 0:
            reserved = self._reserved_percent * Decimal('0.01') * self.size
        elif self._reserved_space > Size(0):
            reserved = self._reserved_space

        # reserve space for the pmspare LV LVM creates behind our back
        reserved += self.pmspare_size

        return self.align(reserved, roundup=True)

    def _get_pv_usable_space(self, pv):
        if isinstance(pv, MDRaidArrayDevice):
            return self.align(pv.size - 2 * pv.format.pe_start)
        else:
            return self.align(pv.size - pv.format.pe_start)

    @property
    def lvm_metadata_space(self):
        """ The amount of the space LVM metadata cost us in this VG's PVs """
        # NOTE: we either specify data alignment in a PV or the default is used
        #       which is both handled by pv.format.pe_start, but LVM takes into
        #       account also the underlying block device which means that e.g.
        #       for an MD RAID device, it tries to align everything also to chunk
        #       size and alignment offset of such device which may result in up
        #       to a twice as big non-data area
        # TODO: move this to either LVMPhysicalVolume's pe_start property once
        #       formats know about their devices or to a new LVMPhysicalVolumeDevice
        #       class once it exists
        diff = Size(0)
        for pv in self.pvs:
            diff += pv.size - self._get_pv_usable_space(pv)

        return diff

    @property
    def size(self):
        """ The size of this VG """
        # TODO: just ask lvm if isModified returns False

        # sum up the sizes of the PVs, subtract the unusable (meta data) space
        size = sum(pv.size for pv in self.pvs)
        size -= self.lvm_metadata_space

        return size

    @property
    def extents(self):
        """ Number of extents in this VG """
        # TODO: just ask lvm if is_modified returns False

        return int(self.size / self.pe_size)

    @property
    def free_space(self):
        """ The amount of free space in this VG. """
        # TODO: just ask lvm if is_modified returns False

        # get the number of disks used by PVs on RAID (if any)
        raid_disks = 0
        for pv in self.pvs:
            if isinstance(pv, MDRaidArrayDevice):
                raid_disks = max([raid_disks, len(pv.disks)])

        # total the sizes of any LVs
        log.debug("%s size is %s", self.name, self.size)
        used = sum((lv.vg_space_used for lv in self.lvs), Size(0))
        used += self.reserved_space
        free = self.size - used
        log.debug("vg %s has %s free", self.name, free)
        return free

    @property
    def free_extents(self):
        """ The number of free extents in this VG. """
        # TODO: just ask lvm if is_modified returns False
        return int(self.free_space / self.pe_size)

    @property
    def pv_free_info(self):
        """
        :returns: information about sizes and free space in this VG's PVs
        :rtype: list of PVFreeInfo

        """
        return [PVFreeInfo(pv, self._get_pv_usable_space(pv.size), pv.format.free)
                for pv in self.pvs]

    def align(self, size, roundup=False):
        """ Align a size to a multiple of physical extent size. """
        size = util.numeric_type(size)
        return size.round_to_nearest(self.pe_size, rounding=ROUND_UP if roundup else ROUND_DOWN)

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
    def cached_lvs(self):
        return [l for l in self._lvs if l.cached]

    @property
    def pmspare_size(self):
        """Size of the pmspare LV LVM creates in every VG that contains some metadata
        (even internal) LV. The size of such LV is equal to the size of the
        biggest metadata LV in the VG.

        """
        # TODO: report correctly/better for existing VGs
        return max([lv.metadata_size for lv in self.lvs] + [Size(0)])

    @property
    def complete(self):
        """Check if the vg has all its pvs in the system
        Return True if complete.
        """
        # vgs with duplicate names are overcomplete, which is not what we want
        if self.has_duplicate:
            return False

        return self._complete or not self.exists

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return False

    def populate_ksdata(self, data):
        super(LVMVolumeGroupDevice, self).populate_ksdata(data)
        data.vgname = self.name
        data.physvols = ["pv.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        if not self.exists:
            data.pesize = self.pe_size.convert_to(KiB)

        # reserved percent/space

    @classmethod
    def is_name_valid(cls, name):
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
    _container_class = LVMVolumeGroupDevice
    _external_dependencies = [availability.BLOCKDEV_LVM_PLUGIN]

    def __init__(self, name, parents=None, size=None, uuid=None, seg_type=None,
                 fmt=None, exists=False, sysfs_path='', grow=None, maxsize=None,
                 percent=None, cache_request=None, pvs=None):
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
            :keyword uuid: the device UUID
            :type uuid: str

            For existing LVs only:

            :keyword seg_type: segment type (eg: "linear", "raid1")
            :type seg_type: str

            For non-existent LVs only:

            :keyword grow: whether to grow this LV
            :type grow: bool
            :keyword maxsize: maximum size for growable LV
            :type maxsize: :class:`~.size.Size`
            :keyword percent: percent of VG space to take
            :type percent: int
            :keyword cache_request: parameters of requested cache (if any)
            :type cache_request: :class:`~.devices.lvm.LVMCacheRequest`
            :keyword pvs: list of PVs to allocate extents from (size could be specified for each PV)
            :type pvs: list of :class:`~.devices.StorageDevice` or :class:`LVPVSpec` objects (tuples)

        """

        if not exists:
            if seg_type and seg_type != "linear" and not pvs:
                raise ValueError("List of PVs has to be given for every non-linear LV")
            elif (not seg_type or seg_type == "linear") and pvs:
                if not all(isinstance(pv, LVPVSpec) for pv in pvs):
                    raise ValueError("Invalid specification of PVs for a linear LV: either no or complete "
                                     "specification (with all space split into PVs has to be given")
                elif sum(spec.size for spec in pvs) != size:
                    raise ValueError("Invalid specification of PVs for a linear LV: the sum of space "
                                     "assigned to PVs is not equal to the size of the LV")

        # When this device's format is set in the superclass constructor it will
        # try to access self.snapshots.
        self.snapshots = []
        DMDevice.__init__(self, name, size=size, fmt=fmt,
                          sysfs_path=sysfs_path, parents=parents,
                          exists=exists)

        self.uuid = uuid
        self.seg_type = seg_type or "linear"
        self._raid_level = None
        if self.seg_type in (level.name for level in lvm.raid_levels):
            self._raid_level = lvm.raid_levels.raid_level(self.seg_type)

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

        if not self.exists and self.seg_type.startswith("raid"):
            # RAID LVs create one extent big internal metadata LVs
            self._metadata_size = self.vg.pe_size
        else:
            self._metadata_size = Size(0)
        self._internal_lvs = []
        self._cache = None

        if cache_request and not self.exists:
            self._cache = LVMCache(self, size=cache_request.size, exists=False,
                                   fast_pvs=cache_request.fast_devs, mode=cache_request.mode)

        self._pv_specs = []
        pvs = pvs or []
        for pv_spec in pvs:
            if isinstance(pv_spec, LVPVSpec):
                self._pv_specs.append(pv_spec)
            elif isinstance(pv_spec, StorageDevice):
                self._pv_specs.append(LVPVSpec(pv_spec, Size(0)))
            else:
                raise ValueError("Invalid PV spec '%s' for the '%s' LV" % (pv_spec, self.name))
        # Make sure any destination PVs are actually PVs in this VG
        if not set(spec.pv for spec in self._pv_specs).issubset(set(self.vg.parents)):
            missing = [r.name for r in
                        set(spec.pv for spec in self._pv_specs).difference(set(self.vg.parents))]
            msg = "invalid destination PV(s) %s for LV %s" % (missing, self.name)
            raise ValueError(msg)
        if self._pv_specs:
            self._assign_pv_space()

        # check that we got parents as expected and add this device to them now
        # that it is fully-initialized
        self._check_parents()
        self._add_to_parents()

    def _assign_pv_space(self):
        if not self.is_raid_lv:
            # nothing to do for non-RAID (and thus non-striped) LVs here
            return
        for spec in self._pv_specs:
            spec.size = self._raid_level.get_base_member_size(self.size + self._metadata_size, len(self._pv_specs))

    def _check_parents(self):
        """Check that this device has parents as expected"""

        if isinstance(self.parents, (list, ParentList)):
            if len(self.parents) != 1:
                raise ValueError("constructor requires a single %s instance" % self._container_class.__name__)

            container = self.parents[0]
        else:
            container = self.parents

        if not isinstance(container, self._container_class):
            raise ValueError("constructor requires a %s instance" % self._container_class.__name__)

    def _add_to_parents(self):
        """Add this device to its parents"""

        # a normal LV has only exactly parent -- the VG it belongs to
        self._parents[0]._add_log_vol(self)

    @property
    def is_raid_lv(self):
        return self.seg_type != "linear" and self._raid_level

    @property
    def _num_raid_pvs(self):
        if self.exists:
            image_lvs = [int_lv for int_lv in self._internal_lvs if isinstance(int_lv, LVMImageLogicalVolumeDevice)]
            return len(image_lvs) or 1
        else:
            return len(self._pv_specs)

    @property
    def log_size(self):
        log_lvs = (int_lv for int_lv in self._internal_lvs if isinstance(int_lv, LVMLogLogicalVolumeDevice))
        return Size(sum(lv.size for lv in log_lvs))

    @property
    def metadata_size(self):
        if self._metadata_size:
            if self.is_raid_lv:
                zero_superblock = lambda x: Size(0)
                return self._raid_level.get_space(self._metadata_size, self._num_raid_pvs,
                                                  superblock_size_func=zero_superblock)
            else:
                return self._metadata_size
        elif self.cached:
            return self.cache.md_size

        md_lvs = (int_lv for int_lv in self._internal_lvs if isinstance(int_lv, LVMMetadataLogicalVolumeDevice))
        return Size(sum(lv.size for lv in md_lvs))

    def __repr__(self):
        s = DMDevice.__repr__(self)
        s += ("  VG device = %(vgdev)r\n"
              "  segment type = %(type)s percent = %(percent)s\n"
              "  VG space used = %(vgspace)s" %
              {"vgdev": self.vg, "percent": self.req_percent,
               "type": self.seg_type,
               "vgspace": self.vg_space_used})
        return s

    @property
    def dict(self):
        d = super(LVMLogicalVolumeDevice, self).dict
        if self.exists:
            d.update({"vgspace": self.vg_space_used})
        else:
            d.update({"percent": self.req_percent})

        return d

    @property
    def mirrored(self):
        return self._raid_level and self._raid_level.has_redundancy()

    def _set_size(self, size):
        if not isinstance(size, Size):
            raise ValueError("new size must of type Size")

        size = self.vg.align(size)
        log.debug("trying to set lv %s size to %s", self.name, size)
        # Don't refuse to set size if we think there's not enough space in the
        # VG for an existing LV, since it's existence proves there is enough
        # space for it. A similar reasoning applies to shrinking the LV.
        if not self.exists and \
           not isinstance(self, LVMThinLogicalVolumeDevice) and \
           size > self.size and size > self.vg.free_space + self.vg_space_used:
            log.error("failed to set size: %s short", size - (self.vg.free_space + self.vg_space_used))
            raise ValueError("not enough free space in volume group")

        super(LVMLogicalVolumeDevice, self)._set_size(size)

    size = property(StorageDevice._get_size, _set_size)

    @property
    def max_size(self):
        """ The maximum size this lv can be. """
        max_lv = self.size + self.vg.free_space
        max_format = self.format.max_size
        return min(max_lv, max_format) if max_format else max_lv

    @property
    def data_vg_space_used(self):
        """ Space occupied by the data part of this LV, not including snapshots """
        rounded_size = self.vg.align(self.size, roundup=True)
        if self.is_raid_lv:
            zero_superblock = lambda x: Size(0)
            try:
                return self._raid_level.get_space(rounded_size, self._num_raid_pvs,
                                                  superblock_size_func=zero_superblock)
            except errors.RaidError:
                # Too few PVs for the segment type (RAID level), we must have
                # incomplete information about the current LVM
                # configuration. Let's just default to the basic size for
                # now. Later calls to this property will provide better results.
                # TODO: add pv_count field to blockdev.LVInfo and this class
                return rounded_size
        else:
            return rounded_size

    @property
    def metadata_vg_space_used(self):
        """ Space occupied by the metadata part of this LV, not including snapshots """
        return self.log_size + self.metadata_size

    @property
    def vg_space_used(self):
        """ Space occupied by this LV, not including snapshots. """
        if self.cached:
            cache_size = self.cache.size
        else:
            cache_size = Size(0)

        return self.data_vg_space_used + self.metadata_vg_space_used + cache_size

    @property
    def pv_space_used(self):
        """
        :returns: space occupied by this LV on its VG's PVs (if we have and idea)
        :rtype: list of LVPVSpec

        """
        return self._pv_specs

    def _set_format(self, fmt):
        super(LVMLogicalVolumeDevice, self)._set_format(fmt)
        for snapshot in (s for s in self.snapshots if not s.exists):
            snapshot._update_format_from_origin()

    @property
    def vg(self):
        """ This Logical Volume's Volume Group. """
        return self.parents[0]

    @property
    def container(self):
        return self.vg

    @property
    def map_name(self):
        """ This device's device-mapper map name """
        # Thank you lvm for this lovely hack.
        return "%s-%s" % (self.vg.map_name, self._name.replace("-", "--"))

    @property
    def path(self):
        """ Device node representing this device. """
        return "%s/%s" % (self._dev_dir, self.map_name)

    def get_dm_node(self):
        """ Return the dm-X (eg: dm-0) device node for this device. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        return blockdev.dm.node_from_name(self.map_name)

    def _get_name(self):
        """ This device's name. """
        if self.vg is not None:
            return "%s-%s" % (self.vg.name, self._name)
        else:
            return super()._get_name()

    @property
    def lvname(self):
        """ The LV's name (not including VG name). """
        return self._name

    @property
    def complete(self):
        """ Test if vg exits and if it has all pvs. """
        return self.vg.complete

    def setup_parents(self, orig=False):
        # parent is a vg, which has no formatting (or device for that matter)
        Device.setup_parents(self, orig=orig)

    def _pre_setup(self, orig=False):
        # If the lvmetad socket exists and any PV is inactive before we call
        # setup_parents (via _pre_setup, below), we should wait for auto-
        # activation before trying to manually activate this LV.
        auto_activate = (lvm.lvmetad_socket_exists() and
                         any(not pv.status for pv in self.vg.pvs))
        if not super(LVMLogicalVolumeDevice, self)._pre_setup(orig=orig):
            return False

        if auto_activate:
            log.debug("waiting for lvm auto-activation of %s", self.name)
            # Wait for auto-activation for up to 30 seconds. If this LV hasn't
            # been activated when the timeout is reached, there may be some
            # lvm.conf content preventing auto-activation of this LV, so we
            # have to do it ourselves.
            # The timeout value of 30 seconds was suggested by prajnoha. He
            # noted that udev uses the same value, for whatever that's worth.
            timeout = 30  # seconds
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
        blockdev.lvm.lvactivate(self.vg.name, self._name)

    def _teardown(self, recursive=None):
        """ Close, or tear down, a device. """
        log_method_call(self, self.name, status=self.status,
                        controllable=self.controllable)
        blockdev.lvm.lvdeactivate(self.vg.name, self._name)

    def _post_teardown(self, recursive=False):
        try:
            # It's likely that teardown of a VG will fail due to other
            # LVs being active (filesystems mounted, &c), so don't let
            # it bring everything down.
            StorageDevice._post_teardown(self, recursive=recursive)
        except errors.StorageError:
            if recursive:
                log.debug("vg %s teardown failed; continuing", self.vg.name)
            else:
                raise

    def _pre_create(self):
        super(LVMLogicalVolumeDevice, self)._pre_create()

        try:
            vg_info = blockdev.lvm.vginfo(self.vg.name)
        except blockdev.LVMError as lvmerr:
            log.error("Failed to get free space for the %s VG: %s", self.vg.name, lvmerr)
            # nothing more can be done, we don't know the VG's free space
            return

        extent_size = Size(vg_info.extent_size)
        extents_free = vg_info.free_count
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
        if not self.cache:
            # just a plain LV
            # TODO: specify sizes together with PVs once LVM and libblockdev support it
            pvs = [spec.pv.path for spec in self._pv_specs]
            pvs = pvs or None

            blockdev.lvm.lvcreate(self.vg.name, self._name, self.size,
                                  type=self.seg_type, pv_list=pvs)
        else:
            mode = blockdev.lvm.cache_get_mode_from_str(self.cache.mode)
            # prepare the list of fast PV devices
            fast_pvs = []
            for pv_name in (pv.name for pv in self.cache.fast_pvs):
                # make sure we have the full device paths
                if not pv_name.startswith("/dev/"):
                    fast_pvs.append("/dev/%s" % pv_name)
                else:
                    fast_pvs.append(pv_name)

            if self._pv_specs:
                # (slow) PVs specified for this LV
                slow_pvs = [spec.pv.path for spec in self._pv_specs]
            else:
                # get the list of all fast PV devices used in the VG so that we can
                # consider the rest to be slow PVs and generate a list of them
                all_fast_pvs_names = set()
                for lv in self.vg.lvs:
                    if lv.cached and lv.cache.fast_pvs:
                        all_fast_pvs_names |= set(pv.name for pv in lv.cache.fast_pvs)
                slow_pvs = [pv.path for pv in self.vg.pvs if pv.name not in all_fast_pvs_names]

            # VG name, LV name, data size, cache size, metadata size, mode, flags, slow PVs, fast PVs
            # XXX: we need to pass slow_pvs+fast_pvs as slow PVs because parts
            # of the fast PVs may be required for allocation of the LV (it may
            # span over the slow PVs and parts of fast PVs)
            blockdev.lvm.cache_create_cached_lv(self.vg.name, self._name, self.size, self.cache.size, self.cache.md_size,
                                                mode, 0, slow_pvs + fast_pvs, fast_pvs)

    def _pre_destroy(self):
        StorageDevice._pre_destroy(self)
        # set up the vg's pvs so lvm can remove the lv
        self.vg.setup_parents(orig=True)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        blockdev.lvm.lvremove(self.vg.name, self._name)

    def resize(self):
        log_method_call(self, self.name, status=self.status)

        # Setup VG parents (in case they are dmraid partitions for example)
        self.vg.setup_parents(orig=True)

        if self.original_format.exists:
            self.original_format.teardown()
        if self.format.exists:
            self.format.teardown()

        udev.settle()
        blockdev.lvm.lvresize(self.vg.name, self._name, self.size)

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

    def dracut_setup_args(self):
        # Note no map_name usage here, this is a lvm cmdline name, which
        # is different (ofcourse)
        return set(["rd.lvm.lv=%s/%s" % (self.vg.name, self._name)])

    def check_size(self):
        """ Check to make sure the size of the device is allowed by the
            format used.

            Returns:
            0  - ok
            1  - Too large
            -1 - Too small
        """
        if self.format.max_size and self.size > self.format.max_size:
            return 1
        elif (self.format.min_size and
              (not self.req_grow and
               self.size < self.format.min_size) or
              (self.req_grow and self.req_max_size and
               self.req_max_size < self.format.min_size)):
            return -1
        return 0

    def remove_hook(self, modparent=True):
        if modparent:
            self.vg._remove_log_vol(self)

        super(LVMLogicalVolumeDevice, self).remove_hook(modparent=modparent)

    def add_hook(self, new=True):
        super(LVMLogicalVolumeDevice, self).add_hook(new=new)
        if new:
            return

        if self not in self.vg.lvs:
            self.vg._add_log_vol(self)

    def populate_ksdata(self, data):
        super(LVMLogicalVolumeDevice, self).populate_ksdata(data)
        data.vgname = self.vg.name
        data.name = self.lvname
        data.preexist = self.exists
        data.resize = (self.exists and self.target_size and
                       self.target_size != self.current_size)
        if not self.exists:
            data.grow = self.req_grow
            if self.req_grow:
                data.size = self.req_size.convert_to(MiB)
                data.max_size_mb = self.req_max_size.convert_to(MiB)
            else:
                data.size = self.size.convert_to(MiB)

            data.percent = self.req_percent
        elif data.resize:
            data.size = self.target_size.convert_to(MiB)

    @classmethod
    def is_name_valid(cls, name):
        # Check that the LV name is valid

        # Start with the checks shared with volume groups
        if not LVMVolumeGroupDevice.is_name_valid(name):
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

    def add_internal_lv(self, int_lv):
        if int_lv not in self._internal_lvs:
            self._internal_lvs.append(int_lv)

    def remove_internal_lv(self, int_lv):
        if int_lv in self._internal_lvs:
            self._internal_lvs.remove(int_lv)
        else:
            msg = "the specified internal LV '%s' doesn't belong to this LV ('%s')" % (int_lv.lv_name,
                                                                                       self.name)
            raise ValueError(msg)

    @property
    def cached(self):
        return bool(self.cache)

    @property
    def cache(self):
        if self.exists and not self._cache:
            # check if we have a cache pool internal LV
            pool = None
            for lv in self._internal_lvs:
                if isinstance(lv, LVMCachePoolLogicalVolumeDevice):
                    pool = lv

            if pool is not None:
                self._cache = LVMCache(self, size=pool.size, exists=True)

        return self._cache

    def attach_cache(self, cache_pool_lv):
        blockdev.lvm.cache_attach(self.vg.name, self.lvname, cache_pool_lv.lvname)
        self._cache = LVMCache(self, size=cache_pool_lv.size, exists=True)


@add_metaclass(abc.ABCMeta)
class LVMInternalLogicalVolumeDevice(LVMLogicalVolumeDevice):

    """Abstract base class for internal LVs

    A common class for all classes representing internal Logical Volumes like
    data and metadata parts of pools, RAID images, etc.

    Internal LVs are only referenced by their "parent" LVs (normal LVs they
    back) as all queries and manipulations with them should be done via their
    parent LVs.

    """

    _type = "lvminternallv"

    # generally changes should be done on the parent LV (exceptions should
    # override these)
    _resizable = False
    _readonly = True

    attr_letters = abc.abstractproperty(doc="letters representing the type of the internal LV in the attrs")
    name_suffix = abc.abstractproperty(doc="pattern matching typical/default suffices for internal LVs of this type")
    takes_extra_space = abc.abstractproperty(doc="whether LVs of this type take space in a VG or are part of their parent LVs")

    @classmethod
    def is_name_valid(cls, name):
        # override checks for normal LVs, internal LVs typically have names that
        # are forbidden for normal LVs
        return True

    def __init__(self, name, vg, parent_lv=None, size=None, uuid=None,
                 exists=False, seg_type=None, sysfs_path=''):
        """
        :param vg: the VG this internal LV belongs to
        :type vg: :class:`LVMVolumeGroupDevice`
        :param parent_lv: the parent LV of this internal LV
        :type parent_lv: :class:`LVMLogicalVolumeDevice`

        See :method:`LVMLogicalVolumeDevice.__init__` for details about the
        rest of the parameters.
        """

        # VG name has to be set for parent class' constructors
        self._vg = vg

        # so does the parent LV
        self._parent_lv = parent_lv

        # construct the internal LV just like a normal one just with no parents
        # and some parameters set to values reflecting the fact that this is an
        # internal LV
        super(LVMInternalLogicalVolumeDevice, self).__init__(name, parents=None,
                                                             size=size, uuid=uuid, seg_type=seg_type, fmt=None, exists=exists,
                                                             sysfs_path=sysfs_path, grow=None, maxsize=None, percent=None)

        if parent_lv:
            self._parent_lv.add_internal_lv(self)

    def _check_parents(self):
        # an internal LV should have no parents
        if self._parents:
            raise ValueError("an internal LV should have no parents")

    def _add_to_parents(self):
        # nothing to do here, an internal LV has no parents (in the DeviceTree's
        # meaning of 'parents')
        pass

    @property
    def vg(self):
        return self._vg

    @vg.setter
    def vg(self, vg):
        # pylint: disable=arguments-differ
        self._vg = vg

    @property
    def parent_lv(self):
        return self._parent_lv

    @parent_lv.setter
    def parent_lv(self, parent_lv):
        if self._parent_lv:
            self._parent_lv.remove_internal_lv(self)
        self._parent_lv = parent_lv
        if self._parent_lv:
            self._parent_lv.add_internal_lv(self)

    # internal LVs follow different rules limitting size
    def _set_size(self, size):
        if not isinstance(size, Size):
            raise ValueError("new size must of type Size")

        if not self.takes_extra_space:
            if size <= self.parent_lv.size:
                self._size = size
            else:
                raise ValueError("Internal LV cannot be bigger than its parent LV")
        else:
            # same rules apply as for any other LV
            super(LVMInternalLogicalVolumeDevice, self)._set_size(size)

    @property
    def max_size(self):
        # no format, so maximum size is only limitted by either the parent LV or the VG
        if not self.takes_extra_space:
            return self._parent_lv.max_size
        else:
            return self.size + self.vg.free_space

    def __repr__(self):
        s = "%s:\n" % self.__class__.__name__
        s += ("  name = %s, status = %s exists = %s\n" % (self.lvname, self.status, self.exists))
        s += ("  uuid = %s, size = %s\n" % (self.uuid, self.size))
        s += ("  parent LV = %r\n" % self.parent_lv)
        s += ("  VG device = %(vgdev)r\n"
              "  segment type = %(type)s percent = %(percent)s\n"
              "  VG space used = %(vgspace)s" %
              {"vgdev": self.vg, "percent": self.req_percent,
               "type": self.seg_type,
               "vgspace": self.vg_space_used})
        return s

    # generally changes should be done on the parent LV (exceptions should
    # override these)
    def setup(self, orig=False):
        raise errors.DeviceError("An internal LV cannot be set up separately")

    def teardown(self, recursive=None):
        raise errors.DeviceError("An internal LV cannot be torn down separately")

    def destroy(self):
        raise errors.DeviceError("An internal LV cannot be destroyed separately")

    def resize(self):
        raise errors.DeviceError("An internal LV cannot be resized")

    @property
    def growable(self):
        return False

    @property
    def display_lvname(self):
        """Name of the internal LV as displayed by the lvm utilities"""
        return "[%s]" % self.lvname

    # these two methods are not needed right now, because they are only called
    # when devices are added/removed to/from the DeviceTree, but they may come
    # handy in the future
    def add_hook(self, new=True):
        # skip LVMLogicalVolumeDevice in the class hierarchy -- we don't want to
        # add an internal LV to the VG (it's only referenced by the parent LV)
        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeDevice, self).add_hook(new=new)
        self._parent_lv.add_internal_lv(self)

    def remove_hook(self, modparent=True):
        if modparent:
            self._parent_lv.remove_internal_lv(self)

        # skip LVMLogicalVolumeDevice in the class hierarchy -- we cannot remove
        # an internal LV from the VG (it's only referenced by the parent LV)
        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeDevice, self).remove_hook(modparent=modparent)

    @property
    def direct(self):
        # internal LVs are not directly accessible
        return False


class LVMDataLogicalVolumeDevice(LVMInternalLogicalVolumeDevice):

    """Internal data LV (used by thin/cache pools)"""

    attr_letters = ["T", "C"]
    name_suffix = r"_[tc]data"
    takes_extra_space = False
_INTERNAL_LV_CLASSES.append(LVMDataLogicalVolumeDevice)


class LVMMetadataLogicalVolumeDevice(LVMInternalLogicalVolumeDevice):

    """Internal metadata LV (used by thin/cache pools, RAIDs, etc.)"""

    # thin pool metadata LVs can be resized directly
    _resizable = True

    attr_letters = ["e"]
    # RAIDs can have multiple (numbered) metadata LVs
    name_suffix = r"_[trc]meta(_[0-9]+)?"
    takes_extra_space = True

    # (only) thin pool metadata LVs can be resized directly
    @property
    def resizable(self):
        if self._parent_lv:
            return isinstance(self._parent_lv, LVMThinPoolDevice)
        else:
            # hard to say at this point, just use the name
            return not re.search(r'_[rc]meta', self.lvname)

    # (only) thin pool metadata LVs can be resized directly
    def resize(self):
        if ((self._parent_lv and not isinstance(self._parent_lv, LVMThinPoolDevice)) or
                re.search(r'_[rc]meta', self.lvname)):
            raise errors.DeviceError("RAID and cache pool metadata LVs cannot be resized directly")

        # skip the generic LVMInternalLogicalVolumeDevice class and call the
        # resize() method of the LVMLogicalVolumeDevice
        # pylint: disable=bad-super-call
        super(LVMInternalLogicalVolumeDevice, self).resize()

_INTERNAL_LV_CLASSES.append(LVMMetadataLogicalVolumeDevice)


class LVMLogLogicalVolumeDevice(LVMInternalLogicalVolumeDevice):

    """Internal log LV (used by mirrored LVs)"""

    attr_letters = ["l", "L"]
    name_suffix = "_mlog"
    takes_extra_space = True
_INTERNAL_LV_CLASSES.append(LVMLogLogicalVolumeDevice)


class LVMImageLogicalVolumeDevice(LVMInternalLogicalVolumeDevice):

    """Internal image LV (used by mirror/RAID LVs)"""

    attr_letters = ["i"]
    # RAIDs have multiple (numbered) image LVs
    name_suffix = r"_[rm]image(_[0-9]+)?"
    takes_extra_space = False
_INTERNAL_LV_CLASSES.append(LVMImageLogicalVolumeDevice)


class LVMOriginLogicalVolumeDevice(LVMInternalLogicalVolumeDevice):

    """Internal origin LV (e.g. the raw/uncached part of a cached LV)"""

    attr_letters = ["o"]
    name_suffix = r"_c?orig"
    takes_extra_space = False
_INTERNAL_LV_CLASSES.append(LVMOriginLogicalVolumeDevice)


class LVMCachePoolLogicalVolumeDevice(LVMInternalLogicalVolumeDevice):

    """Internal cache pool logical volume"""

    attr_letters = ["C"]
    name_suffix = r"_cache(_?pool)?"
    takes_extra_space = True
_INTERNAL_LV_CLASSES.append(LVMCachePoolLogicalVolumeDevice)


@add_metaclass(abc.ABCMeta)
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
        self._origin_specified_check(origin, vorigin, exists)
        self._origin_type_check(origin)
        self._origin_existence_check(origin)
        self._vorigin_existence_check(vorigin, exists)

        self.origin = origin
        """ the snapshot's source volume """

        self.vorigin = vorigin
        """ a boolean flag indicating a vorigin snapshot """

    def _origin_specified_check(self, origin, vorigin, exists):
        # pylint: disable=unused-argument
        if not origin and not vorigin:
            raise ValueError("lvm snapshot devices require an origin lv")

    def _origin_type_check(self, origin):
        if origin and not isinstance(origin, LVMLogicalVolumeDevice):
            raise ValueError("lvm snapshot origin must be a logical volume")

    def _origin_existence_check(self, origin):
        if origin and not origin.exists:
            raise ValueError("lvm snapshot origin volume must already exist")

    def _vorigin_existence_check(self, vorigin, exists):
        if vorigin and not exists:
            raise ValueError("only existing vorigin snapshots are supported")

    def _update_format_from_origin(self):
        """ Update the snapshot's format to reflect the origin's.

            .. note::
                This should only be called for non-existent snapshot devices.
                Once a snapshot exists its format is distinct from that of its
                origin.

        """
        fmt = copy.deepcopy(self.origin.format)
        fmt.exists = False
        if hasattr(fmt, "mountpoint"):
            fmt.mountpoint = ""
            fmt._chrooted_mountpoint = None
            fmt.device = self.path  # pylint: disable=no-member

        super(LVMSnapShotBase, self)._set_format(fmt)

    def _set_format(self, fmt):
        # If a snapshot exists it can have a format that is distinct from its
        # origin's. If it does not exist its format must be a copy of its
        # origin's.
        if self.exists:  # pylint: disable=no-member
            super(LVMSnapShotBase, self)._set_format(fmt)
        else:
            log.info("copying %s origin's format", self.name)  # pylint: disable=no-member
            self._update_format_from_origin()

    @abc.abstractmethod
    def _create(self):
        """ Create the device. """
        raise NotImplementedError()

    def merge(self):
        """ Merge the snapshot back into its origin volume. """
        log_method_call(self, self.name, status=self.status)  # pylint: disable=no-member
        self.vg.setup()    # pylint: disable=no-member
        try:
            self.origin.teardown()
        except errors.FSError:
            # the merge will begin based on conditions described in the --merge
            # section of lvconvert(8)
            pass

        try:
            self.teardown()  # pylint: disable=no-member
        except errors.FSError:
            pass

        udev.settle()
        blockdev.lvm.lvsnapshotmerge(self.vg.name, self.lvname)  # pylint: disable=no-member


class LVMSnapShotDevice(LVMSnapShotBase, LVMLogicalVolumeDevice):

    """ An LVM snapshot """
    _type = "lvmsnapshot"
    _format_immutable = True

    def __init__(self, name, parents=None, size=None, uuid=None, seg_type=None,
                 fmt=None, exists=False, sysfs_path='', grow=None, maxsize=None,
                 percent=None, origin=None, vorigin=False):
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
            :keyword str sysfs_path: sysfs device path
            :keyword str uuid: the device UUID
            :keyword str seg_type: segment type

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
                                        seg_type=seg_type,
                                        sysfs_path=sysfs_path, grow=grow,
                                        maxsize=maxsize, percent=percent)

    def setup(self, orig=False):
        pass

    def teardown(self, recursive=False):
        pass

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        blockdev.lvm.lvsnapshotcreate(self.vg.name, self.origin.lvname, self._name, self.size)

    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        # old-style snapshots' status is tied to the origin's so we never
        # explicitly activate or deactivate them and we have to tell lvremove
        # that it is okay to remove the active snapshot
        blockdev.lvm.lvremove(self.vg.name, self._name, force=True)

    def _get_parted_device_path(self):
        return "%s-cow" % self.path

    def depends_on(self, dep):
        # pylint: disable=bad-super-call
        return (self.origin == dep or
                super(LVMSnapShotBase, self).depends_on(dep))

    def read_current_size(self):
        log_method_call(self, exists=self.exists, path=self.path,
                        sysfs_path=self.sysfs_path)
        size = Size(0)
        if self.exists and os.path.isdir(self.sysfs_path):
            cow_sysfs_path = util.get_cow_sysfs_path(self.path, self.sysfs_path)

            if os.path.exists(cow_sysfs_path) and os.path.isdir(cow_sysfs_path):
                blocks = int(util.get_sysfs_attr(cow_sysfs_path, "size"))
                size = Size(blocks * LINUX_SECTOR_SIZE)

        return size


class LVMThinPoolDevice(LVMLogicalVolumeDevice):

    """ An LVM Thin Pool """
    _type = "lvmthinpool"
    _resizable = False

    def __init__(self, name, parents=None, size=None, uuid=None,
                 fmt=None, exists=False, sysfs_path='',
                 grow=None, maxsize=None, percent=None,
                 metadatasize=None, chunksize=None, seg_type=None, profile=None):
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
            :keyword uuid: the device UUID
            :type uuid: str
            :keyword seg_type: segment type (only "linear" supported for non-existing ThinPool LVs)
            :type seg_type: str

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
           not blockdev.lvm.is_valid_thpool_md_size(metadatasize):
            raise ValueError("invalid metadatasize value")

        if chunksize is not None and \
           not blockdev.lvm.is_valid_thpool_chunk_size(chunksize):
            raise ValueError("invalid chunksize value")

        if not exists and seg_type and seg_type != "linear":
            raise ValueError("creation of non-linear thin pool LVs is not supported (yet)")

        super(LVMThinPoolDevice, self).__init__(name, parents=parents,
                                                size=size, uuid=uuid,
                                                fmt=fmt, exists=exists,
                                                sysfs_path=sysfs_path, grow=grow,
                                                maxsize=maxsize,
                                                percent=percent,
                                                seg_type=seg_type)

        self._metadata_size = metadatasize or Size(0)
        self.chunk_size = chunksize or Size(0)
        self.profile = profile
        self._lvs = []

    def _add_log_vol(self, lv):
        """ Add an LV to this pool. """
        if lv in self._lvs:
            raise ValueError("lv is already part of this vg")

        # TODO: add some checking to prevent overcommit for preexisting
        self.vg._add_log_vol(lv)
        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

    def _remove_log_vol(self, lv):
        """ Remove an LV from this pool. """
        if lv not in self._lvs:
            raise ValueError("specified lv is not part of this vg")

        self._lvs.remove(lv)
        self.vg._remove_log_vol(lv)

    @property
    def lvs(self):
        """ A list of this pool's LVs """
        return self._lvs[:]     # we don't want folks changing our list

    @property
    def vg_space_used(self):
        space = super(LVMThinPoolDevice, self).vg_space_used
        space += Size(blockdev.lvm.get_thpool_padding(space, self.vg.pe_size))
        return space

    @property
    def used_space(self):
        return sum((l.pool_space_used for l in self.lvs), Size(0))

    @property
    def free_space(self):
        return self.size - self.used_space

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        if self.profile:
            profile_name = self.profile.name
        else:
            profile_name = None
        # TODO: chunk size, data/metadata split --> profile
        # TODO: allow for specification of PVs
        blockdev.lvm.thpoolcreate(self.vg.name, self.lvname, self.size,
                                  md_size=self.metadata_size,
                                  chunk_size=self.chunk_size,
                                  profile=profile_name)

    def dracut_setup_args(self):
        return set()

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return False

    def populate_ksdata(self, data):
        super(LVMThinPoolDevice, self).populate_ksdata(data)
        data.mountpoint = "none"
        data.thin_pool = True
        data.metadata_size = self.metadata_size.convert_to(MiB)
        data.chunk_size = self.chunk_size.convert_to(KiB)
        if self.profile:
            data.profile = self.profile.name


class LVMThinLogicalVolumeDevice(LVMLogicalVolumeDevice):

    """ An LVM Thin Logical Volume """
    _type = "lvmthinlv"
    _container_class = LVMThinPoolDevice

    @property
    def pool(self):
        return self.parents[0]

    @property
    def vg(self):
        return self.pool.vg

    @property
    def pool_space_used(self):
        """ The total space used within the thin pool by this volume.

            This should probably align to the greater of vg extent size and
            pool chunk size. If it ends up causing overcommit in the amount of
            less than one chunk per thin lv, so be it.
        """
        return self.vg.align(self.size, roundup=True)

    @property
    def vg_space_used(self):
        return Size(0)    # the pool's size is already accounted for in the vg

    def _set_size(self, size):
        if not isinstance(size, Size):
            raise ValueError("new size must of type Size")

        size = self.vg.align(size)
        size = self.vg.align(util.numeric_type(size))
        super(LVMThinLogicalVolumeDevice, self)._set_size(size)

    size = property(StorageDevice._get_size, _set_size)

    def _pre_create(self):
        # skip LVMLogicalVolumeDevice's _pre_create() method as it checks for a
        # free space in a VG which doesn't make sense for a ThinLV and causes a
        # bug by limitting the ThinLV's size to VG free space which is nonsense
        super(LVMLogicalVolumeDevice, self)._pre_create()  # pylint: disable=bad-super-call

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        blockdev.lvm.thlvcreate(self.vg.name, self.pool.lvname, self.lvname,
                                self.size)

    def remove_hook(self, modparent=True):
        if modparent:
            self.pool._remove_log_vol(self)

        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeDevice, self).remove_hook(modparent=modparent)

    def add_hook(self, new=True):
        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeDevice, self).add_hook(new=new)
        if new:
            return

        if self not in self.pool.lvs:
            self.pool._add_log_vol(self)

    def populate_ksdata(self, data):
        super(LVMThinLogicalVolumeDevice, self).populate_ksdata(data)
        data.thin_volume = True
        data.pool_name = self.pool.lvname


class LVMThinSnapShotDevice(LVMSnapShotBase, LVMThinLogicalVolumeDevice):

    """ An LVM Thin Snapshot """
    _type = "lvmthinsnapshot"
    _resizable = False
    _format_immutable = True

    def __init__(self, name, parents=None, sysfs_path='', origin=None,
                 fmt=None, uuid=None, size=None, exists=False, seg_type=None):
        """
            :param str name: the name of the device
            :param :class:`~.ParentList` parents: parent devices
            :param str sysfs_path: path to this device's /sys directory
            :keyword origin: the origin(source) volume for the snapshot
            :type origin: :class:`~.LVMLogicalVolumeDevice` or None
            :keyword str seg_type: segment type
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
                                            sysfs_path=sysfs_path, fmt=fmt,
                                            seg_type=seg_type,
                                            uuid=uuid, size=size, exists=exists)

    def _origin_specified_check(self, origin, vorigin, exists):
        if not exists and not origin:
            raise ValueError("non-existent lvm thin snapshots require an origin")

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        blockdev.lvm.lvactivate(self.vg.name, self._name, ignore_skip=True)

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        pool_name = None
        if not isinstance(self.origin, LVMThinLogicalVolumeDevice):
            # if the origin is not a thin volume we need to tell lvm which pool
            # to use
            pool_name = self.pool.lvname

        blockdev.lvm.thsnapshotcreate(self.vg.name, self.origin.lvname, self._name,
                                      pool_name=pool_name)

    def _post_create(self):
        super(LVMThinSnapShotDevice, self)._post_create()
        # A snapshot's format exists as soon as the snapshot has been created.
        self.format.exists = True

    def depends_on(self, dep):
        # once a thin snapshot exists it no longer depends on its origin
        return ((self.origin == dep and not self.exists) or
                super(LVMThinSnapShotDevice, self).depends_on(dep))


class LVMCache(Cache):

    """Class providing the cache-related functionality of a cached LV"""

    def __init__(self, cached_lv, size=None, md_size=None, exists=False, fast_pvs=None, mode=None):
        """
        :param cached_lv: the LV the cache functionality of which to provide
        :type cached_lv: :class:`LVMLogicalVolumeDevice`
        :param size: size of the cache (useful mainly for non-existing caches
                     that cannot determine their size dynamically)
        :type size: :class:`~.size.Size`
        :param md_size: size of the metadata part (LV) of the cache (for
                        non-existing caches that cannot determine their metadata
                        size dynamically) or None to use the default (see note below)
        :type md_size: :class:`~.size.Size` or NoneType
        :param bool exists: whether the cache exists or not
        :param fast_pvs: PVs to allocate the cache on/from (ignored for existing)
        :type fast_pvs: list of :class:`~.devices.storage.StorageDevice`
        :param str mode: desired mode for non-existing cache (ignored for existing)

        .. note::
            If :param:`md_size` is None for a an unexisting cache, the default
            is used and it is subtracted from the requested :param:`size` so
            that the whole cache (data+metadata) fits in the space of size
            :param:`size`.

        """
        self._cached_lv = cached_lv
        if not exists and not md_size:
            default_md_size = Size(blockdev.lvm.cache_get_default_md_size(size))
            self._size = size - default_md_size
            self._md_size = default_md_size
        else:
            self._size = size
            self._md_size = md_size
        self._exists = exists
        if not exists:
            self._mode = mode or "writethrough"
            self._fast_pvs = fast_pvs
        else:
            self._mode = None
            self._fast_pvs = None

    @property
    def size(self):
        # self.stats is always dynamically fetched so store and reuse the value here
        stats = self.stats
        if stats:
            return stats.size
        else:
            return self._size

    @property
    def md_size(self):
        if self.exists:
            return self.stats.md_size
        else:
            return self._md_size

    @property
    def vg_space_used(self):
        return self.size + self.md_size

    @property
    def exists(self):
        return self._exists

    @property
    def stats(self):
        # to get the stats we need the cached LV to exist and be activated
        if self._exists and self._cached_lv.status:
            return LVMCacheStats(blockdev.lvm.cache_stats(self._cached_lv.vg.name, self._cached_lv.lvname))
        else:
            return None

    @property
    def mode(self):
        if not self._exists:
            return self._mode
        else:
            stats = blockdev.lvm.cache_stats(self._cached_lv.vg.name, self._cached_lv.lvname)
            return blockdev.lvm.cache_get_mode_str(stats.mode)

    @property
    def backing_device_name(self):
        if self._exists:
            return self._cached_lv.name
        else:
            return None

    @property
    def cache_device_name(self):
        if self._exists:
            vg_name = self._cached_lv.vg.name
            return "%s-%s" % (vg_name, blockdev.lvm.cache_pool_name(vg_name, self._cached_lv.lvname))
        else:
            return None

    @property
    def fast_pvs(self):
        return self._fast_pvs

    def detach(self):
        vg_name = self._cached_lv.vg.name
        ret = blockdev.lvm.cache_pool_name(vg_name, self._cached_lv.lvname)
        blockdev.lvm.cache_detach(vg_name, self._cached_lv.lvname, False)
        return ret


class LVMCacheStats(CacheStats):

    def __init__(self, stats_data):
        """
        :param stats_data: cache stats data
        :type stats_data: :class:`blockdev.LVMCacheStats`

        """
        self._block_size = Size(stats_data.block_size)
        self._cache_size = Size(stats_data.cache_size)
        self._cache_used = stats_data.cache_used
        self._md_block_size = Size(stats_data.md_block_size)
        self._md_size = Size(stats_data.md_size)
        self._md_used = stats_data.md_used
        self._read_hits = stats_data.read_hits
        self._read_misses = stats_data.read_misses
        self._write_hits = stats_data.write_hits
        self._write_misses = stats_data.write_misses

    # common properties for all caches
    @property
    def block_size(self):
        return self._block_size

    @property
    def size(self):
        return self._cache_size

    @property
    def used(self):
        return self._cache_used

    @property
    def hits(self):
        return self._read_hits + self._write_hits

    @property
    def misses(self):
        return self._read_misses + self._write_misses

    # LVM cache specific properties
    @property
    def md_block_size(self):
        return self._md_block_size

    @property
    def md_size(self):
        return self._md_size

    @property
    def md_used(self):
        return self._md_used

    @property
    def read_hits(self):
        return self._read_hits

    @property
    def read_misses(self):
        return self._read_misses

    @property
    def write_hits(self):
        return self._write_hits

    @property
    def write_misses(self):
        return self._write_misses


class LVMCacheRequest(CacheRequest):

    """Class representing the LVM cache creation request"""

    def __init__(self, size, fast_pvs, mode=None):
        """
        :param size: requested size of the cache
        :type size: :class:`~.size.Size`
        :param fast_pvs: PVs to allocate the cache on/from
        :type fast_pvs: list of :class:`~.devices.storage.StorageDevice`
        :param str mode: requested mode for the cache (``None`` means the default is used)

        """
        self._size = size
        self._fast_pvs = fast_pvs
        self._mode = mode or "writethrough"

    @property
    def size(self):
        return self._size

    @property
    def fast_devs(self):
        return self._fast_pvs

    @property
    def mode(self):
        return self._mode
