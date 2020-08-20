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
import copy
import pprint
import re
import os
import time
from collections import namedtuple
from functools import wraps
from enum import Enum
import six

import gi
gi.require_version("BlockDev", "2.0")

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
from .raid import RaidDevice
from .dm import DMDevice
from .md import MDRaidArrayDevice
from .cache import Cache, CacheStats, CacheRequest


class LVPVSpec(object):
    """ Class for specifying how much space on a PV should be allocated for some LV """
    def __init__(self, pv, size):
        self.pv = pv
        self.size = size


PVFreeInfo = namedtuple("PVFreeInfo", ["pv", "size", "free"])
""" A namedtuple class holding the information about PV's (usable) size and free space """


ThPoolReserveSpec = namedtuple("ThPoolReserveSpec", ["percent", "min", "max"])
""" A namedtuple class for specifying restrictions of space reserved for a thin pool to grow """

DEFAULT_THPOOL_RESERVE = ThPoolReserveSpec(20, Size("1 GiB"), Size("100 GiB"))


class NotTypeSpecific(Exception):
    """Exception class for invalid type-specific calls"""


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
                 uuid=None, exists=False, sysfs_path='', exported=False):
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
        self.exported = exported

        # TODO: validate pe_size if given
        if not self.pe_size:
            self.pe_size = lvm.LVM_PE_SIZE

        super(LVMVolumeGroupDevice, self).__init__(name, parents=parents,
                                                   uuid=uuid, size=size,
                                                   exists=exists, sysfs_path=sysfs_path)

        self.free = util.numeric_type(free)
        self._reserved_percent = 0
        self._reserved_space = Size(0)
        self._thpool_reserve = None

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

        # special handling for incomplete VGs
        if not self.complete:
            try:
                lvs_info = blockdev.lvm.lvs(vg_name=self.name)
            except blockdev.LVMError:
                lvs_info = []

            for lv_info in lvs_info:
                if lv_info.attr and lv_info.attr[4] == 'a':
                    return True

            return False

        # if any of our PVs are not active then we cannot be
        for pv in self.pvs:
            if not pv.format.status:
                return False

        return True

    @property
    def is_empty(self):
        return len(self.lvs) == 0

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
        self.format.exists = True

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

        # do not run pvmove on empty PVs
        member.format.update_size_info()
        if member.format.free < member.format.size:
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
            raise errors.DeviceError("lv is already part of this vg")

        # verify we have the space, then add it
        # do not verify for growing vg (because of ks)
        if not lv.exists and not self.growable and not lv.is_thin_lv and lv.size > self.free_space:
            raise errors.DeviceError("new lv is too large to fit in free space", self.name)

        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.append(lv)

        # PV space accounting
        if not lv.exists:
            # create a copy of the list so that we don't modify the origin below
            pv_sizes = lv.pv_space_used[:]
            if lv.cached:
                pv_sizes.extend(lv.cache.pv_space_used)
            if pv_sizes:
                # check that we have enough space in the PVs for the LV and
                # account for it
                for size_spec in pv_sizes:
                    if size_spec.pv.format.free < size_spec.size:
                        msg = "not enough space in the '%s' PV for the '%s' LV's extents" % (size_spec.pv.name, lv.name)
                        raise errors.DeviceError(msg)
                    size_spec.pv.format.free -= size_spec.size

    def _remove_log_vol(self, lv):
        """ Remove an LV from this VG. """
        if lv not in self.lvs:
            raise errors.DeviceError("specified lv is not part of this vg")

        self._lvs.remove(lv)

        # snapshot accounting
        origin = getattr(lv, "origin", None)
        if origin:
            origin.snapshots.remove(lv)

        # PV space accounting
        pv_sizes = lv.pv_space_used[:]
        if lv.cached:
            pv_sizes.extend(lv.cache.pv_space_used)
        if not lv.exists and pv_sizes:
            for size_spec in pv_sizes:
                size_spec.pv.format.free += size_spec.size

    def _add_parent(self, parent):
        super(LVMVolumeGroupDevice, self)._add_parent(parent)

        # we are creating new VG or adding a new PV to an existing (complete) one
        if not self.exists or (self.exists and self._complete):
            parent_sectors = set([p.sector_size for p in self.pvs] + [parent.sector_size])
            if len(parent_sectors) != 1:
                if not self.exists:
                    msg = "The volume group %s cannot be created. Selected disks have " \
                          "inconsistent sector sizes (%s)." % (self.name, parent_sectors)
                else:
                    msg = "Disk %s cannot be added to this volume group. LVM doesn't " \
                          "allow using physical volumes with inconsistent (logical) sector sizes." % parent.name
                raise ValueError(msg)

        if (self.exists and parent.format.exists and
                len(self.parents) + 1 == self.pv_count):
            self._complete = True

        # this PV object is just being added so it has all its space available
        # (adding LVs will eat that space later)
        if not parent.format.exists:
            parent.format.free = self._get_pv_usable_space(parent)

    def _remove_parent(self, parent):
        # XXX It would be nice to raise an exception if removing this member
        #     would not leave enough space, but the devicefactory relies on it
        #     being possible to _temporarily_ overcommit the VG.
        #
        #     Maybe remove_member could be a wrapper with the checks and the
        #     devicefactory could call the _ versions to bypass the checks.
        super(LVMVolumeGroupDevice, self)._remove_parent(parent)
        parent.format.free = None
        parent.format.container_uuid = None

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
    def thpool_reserve(self):
        return self._thpool_reserve

    @thpool_reserve.setter
    def thpool_reserve(self, value):
        if value is not None and not isinstance(value, ThPoolReserveSpec):
            raise AttributeError("Invalid thpool_reserve given, must be of type ThPoolReserveSpec")
        self._thpool_reserve = value

    @property
    def reserved_space(self):
        """ Reserved space in this VG """
        reserved = Size(0)
        if self._reserved_percent > 0:
            reserved = self._reserved_percent * Decimal('0.01') * self.size
        elif self._reserved_space > Size(0):
            reserved = self._reserved_space

        if self._thpool_reserve and any(lv.is_thin_pool for lv in self._lvs):
            reserved += min(max(self._thpool_reserve.percent * Decimal(0.01) * self.size,
                                self._thpool_reserve.min),
                            self._thpool_reserve.max)

        # reserve space for the pmspare LV LVM creates behind our back
        reserved += self.pmspare_size

        return self.align(reserved, roundup=True)

    @reserved_space.setter
    def reserved_space(self, value):
        if self.exists:
            raise ValueError("Can't set reserved space for an existing VG")

        self._reserved_space = value

    @property
    def reserved_percent(self):
        """ Reserved space in this VG in percent """
        return self._reserved_percent

    @reserved_percent.setter
    def reserved_percent(self, value):
        if self.exists:
            raise ValueError("Can't set reserved percent for an existing VG")

        self._reserved_percent = value

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
        return [PVFreeInfo(pv, self._get_pv_usable_space(pv), pv.format.free)
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
        return [l for l in self._lvs if l.is_thin_pool]

    @property
    def thinlvs(self):
        return [l for l in self._lvs if l.is_thin_lv]

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
        # gather metadata sizes for all LVs including their potential caches
        md_sizes = set((Size(0),))
        for lv in self.lvs:
            md_sizes.add(lv.metadata_size)
            if lv.cached:
                md_sizes.add(lv.cache.md_size)
        return max(md_sizes)

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

    @property
    def protected(self):
        if self.exported:
            return True

        return super(LVMVolumeGroupDevice, self).protected

    @protected.setter
    def protected(self, value):
        self._protected = value

    def remove_hook(self, modparent=True):
        if modparent:
            for pv in self.pvs:
                pv.format.vg_name = None

        super(LVMVolumeGroupDevice, self).remove_hook(modparent=modparent)

    def add_hook(self, new=True):
        super(LVMVolumeGroupDevice, self).add_hook(new=new)
        if new:
            return

        for pv in self.pvs:
            pv.format.vg_name = self.name

    def populate_ksdata(self, data):
        super(LVMVolumeGroupDevice, self).populate_ksdata(data)
        data.vgname = self.name
        data.physvols = ["pv.%d" % p.id for p in self.parents]
        data.preexist = self.exists
        if not self.exists:
            data.pesize = self.pe_size.convert_to(KiB)

        # reserved percent/space

    def is_name_valid(self, name):
        return lvm.is_lvm_name_valid(name)


class LVMLogicalVolumeBase(DMDevice, RaidDevice):
    """Abstract base class for LVM LVs

    Attributes, properties and methods defined in this class are common too all
    LVs.

    """

    _type = "lvmlv"
    _packages = ["lvm2"]
    _external_dependencies = [availability.BLOCKDEV_LVM_PLUGIN]

    def __init__(self, name, parents=None, size=None, uuid=None, seg_type=None,
                 fmt=None, exists=False, sysfs_path='', grow=None, maxsize=None,
                 percent=None, cache_request=None, pvs=None, from_lvs=None):

        if not exists:
            if seg_type not in [None, "linear", "thin", "thin-pool", "cache"] + lvm.raid_seg_types:
                raise ValueError("Invalid or unsupported segment type: %s" % seg_type)
            if seg_type and seg_type in lvm.raid_seg_types and not pvs:
                raise errors.DeviceError("List of PVs has to be given for every non-linear LV")
            elif (not seg_type or seg_type == "linear") and pvs:
                if not all(isinstance(pv, LVPVSpec) for pv in pvs):
                    raise errors.DeviceError("Invalid specification of PVs for a linear LV: either no or complete "
                                             "specification (with all space split into PVs has to be given")
                elif sum(spec.size for spec in pvs) != size:
                    raise errors.DeviceError("Invalid specification of PVs for a linear LV: the sum of space "
                                             "assigned to PVs is not equal to the size of the LV")

        # When this device's format is set in the superclass constructor it will
        # try to access self.snapshots.
        self.snapshots = []
        DMDevice.__init__(self, name, size=size, fmt=fmt,
                          sysfs_path=sysfs_path, parents=parents,
                          exists=exists)
        RaidDevice.__init__(self, name, size=size, fmt=fmt,
                            sysfs_path=sysfs_path, parents=parents,
                            exists=exists)

        self.uuid = uuid
        self.seg_type = seg_type or "linear"
        self._raid_level = None
        self.ignore_skip_activation = 0

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

        if not self.exists and self.seg_type.startswith(("raid", "mirror")):
            # RAID LVs create one extent big internal metadata LVs so make sure
            # we reserve space for it
            self._metadata_size = self.vg.pe_size
            self._size -= self._metadata_size
        elif self.seg_type == "thin-pool":
            # LVMThinPoolMixin sets self._metadata_size on its own
            if not self.exists and not from_lvs and not grow:
                # a thin pool we are not going to grow -> lets calculate metadata
                # size now if not given explicitly
                # pylint: disable=no-member
                self.autoset_md_size()
        else:
            self._metadata_size = Size(0)

        self._internal_lvs = []

        self._from_lvs = from_lvs
        if self._from_lvs:
            if exists:
                raise errors.DeviceError("Only new LVs can be created from other LVs")
            if size or maxsize or percent:
                raise errors.DeviceError("Cannot specify size for a converted LV")
            if fmt:
                raise errors.DeviceError("Cannot specify format for a converted LV")
            if any(lv.vg != self.vg for lv in self._from_lvs):
                raise errors.DeviceError("Conversion of LVs only possible inside a VG")

        self._cache = None
        if cache_request and not self.exists:
            self._cache = LVMCache(self, size=cache_request.size, exists=False,
                                   pvs=cache_request.fast_devs, mode=cache_request.mode)

        self._pv_specs = []
        pvs = pvs or []
        for pv_spec in pvs:
            if isinstance(pv_spec, LVPVSpec):
                self._pv_specs.append(pv_spec)
            elif isinstance(pv_spec, StorageDevice):
                self._pv_specs.append(LVPVSpec(pv_spec, Size(0)))
            else:
                raise AttributeError("Invalid PV spec '%s' for the '%s' LV" % (pv_spec, self.name))
        # Make sure any destination PVs are actually PVs in this VG
        if not set(spec.pv for spec in self._pv_specs).issubset(set(self.vg.parents)):
            missing = [r.name for r in
                       set(spec.pv for spec in self._pv_specs).difference(set(self.vg.parents))]
            msg = "invalid destination PV(s) %s for LV %s" % (missing, self.name)
            raise errors.DeviceError(msg)
        if self._pv_specs:
            self._assign_pv_space()

    def _assign_pv_space(self):
        if not self.is_raid_lv:
            # nothing to do for non-RAID (and thus non-striped) LVs here
            return
        for spec in self._pv_specs:
            spec.size = self.raid_level.get_base_member_size(self.size + self._metadata_size, len(self._pv_specs))

    @property
    def members(self):
        return self.vg.pvs

    @property
    def from_lvs(self):
        # this needs to be read-only
        return self._from_lvs

    @property
    def is_raid_lv(self):
        seg_type = self.seg_type
        if self.seg_type == "cache":
            # for a cached LV we are interested in the segment type of its
            # origin LV (the original non-cached LV)
            for lv in self._internal_lvs:
                if lv.int_lv_type == LVMInternalLVtype.origin:
                    seg_type = lv.seg_type
        return seg_type in lvm.raid_seg_types

    @property
    def raid_level(self):
        if self._raid_level is not None:
            return self._raid_level

        seg_type = self.seg_type
        if self.cached:
            # for a cached LV we are interested in the segment type of its
            # origin LV (the original non-cached LV)
            for lv in self._internal_lvs:
                if lv.int_lv_type == LVMInternalLVtype.origin:
                    seg_type = lv.seg_type
                    break

        if seg_type in lvm.raid_seg_types:
            self._raid_level = lvm.raid_levels.raid_level(seg_type)
        else:
            self._raid_level = lvm.raid_levels.raid_level("linear")

        return self._raid_level

    @property
    def vg(self):
        """This Logical Volume's Volume Group."""
        if self._parents:
            return self._parents[0]
        else:
            return None

    @property
    def num_raid_pvs(self):
        if self.exists:
            if self.cached:
                # for a cached LV we are interested in the number of image LVs of its
                # origin LV (the original non-cached LV)
                for lv in self._internal_lvs:
                    if lv.int_lv_type == LVMInternalLVtype.origin:
                        return lv.num_raid_pvs

                # this should never be reached, every existing cached LV should
                # have an origin internal LV
                log.warning("An existing cached LV '%s' has no internal LV of type origin",
                            self.name)
                return 1
            else:
                image_lvs = [int_lv for int_lv in self._internal_lvs
                             if int_lv.is_internal_lv and int_lv.int_lv_type == LVMInternalLVtype.image]
                return len(image_lvs) or 1
        else:
            return len(self._pv_specs)

    @property
    def log_size(self):
        log_lvs = (int_lv for int_lv in self._internal_lvs
                   if int_lv.is_internal_lv and int_lv.int_lv_type == LVMInternalLVtype.log)
        return Size(sum(lv.size for lv in log_lvs))

    @property
    def metadata_size(self):
        """ Size of the meta data space this LV has available (see also :property:`metadata_vg_space_used`) """
        if self._internal_lvs:
            md_lvs = (int_lv for int_lv in self._internal_lvs
                      if int_lv.is_internal_lv and int_lv.int_lv_type == LVMInternalLVtype.meta)
            return Size(sum(lv.size for lv in md_lvs))

        return self._metadata_size

    @property
    def dict(self):
        d = super(LVMLogicalVolumeBase, self).dict
        if self.exists:
            d.update({"vgspace": self.vg_space_used})
        else:
            d.update({"percent": self.req_percent})

        return d

    @property
    def mirrored(self):
        return self.raid_level and self.raid_level.has_redundancy()

    @property
    def vg_space_used(self):
        """ Space occupied by this LV, not including snapshots. """
        return self.data_vg_space_used + self.metadata_vg_space_used

    @property
    def data_vg_space_used(self):
        """ Space occupied by the data part of this LV, not including snapshots """
        if self.exists and self._internal_lvs:
            image_lvs_sum = Size(0)
            complex_int_lvs = []
            for lv in self._internal_lvs:
                if lv.int_lv_type == LVMInternalLVtype.image:
                    # image LV (RAID leg)
                    image_lvs_sum += lv.vg_space_used
                elif lv.int_lv_type in (LVMInternalLVtype.meta, LVMInternalLVtype.log):
                    # metadata LVs
                    continue
                else:
                    complex_int_lvs.append(lv)

            return image_lvs_sum + sum(lv.data_vg_space_used for lv in complex_int_lvs)

        if self.cached:
            cache_size = self.cache.size
        else:
            cache_size = Size(0)

        rounded_size = self.vg.align(self.size, roundup=True)
        if self.is_raid_lv:
            zero_superblock = lambda x: Size(0)
            try:
                raided_size = self.raid_level.get_space(rounded_size, self.num_raid_pvs,
                                                        superblock_size_func=zero_superblock)
                return raided_size + cache_size
            except errors.RaidError:
                # Too few PVs for the segment type (RAID level), we must have
                # incomplete information about the current LVM
                # configuration. Let's just default to the basic size for
                # now. Later calls to this property will provide better results.
                # TODO: add pv_count field to blockdev.LVInfo and this class
                return rounded_size + cache_size
        else:
            return rounded_size + cache_size

    @property
    def metadata_vg_space_used(self):
        """ Space occupied by the metadata part(s) of this LV, not including snapshots """
        if self.exists and self._internal_lvs:
            meta_lvs_sum = Size(0)
            complex_int_lvs = []
            for lv in self._internal_lvs:
                if lv.int_lv_type == LVMInternalLVtype.image:
                    # image LV (RAID leg)
                    continue
                elif lv.int_lv_type in (LVMInternalLVtype.meta, LVMInternalLVtype.log):
                    # metadata LVs
                    meta_lvs_sum += lv.vg_space_used
                else:
                    complex_int_lvs.append(lv)

            return meta_lvs_sum + sum(lv.metadata_vg_space_used for lv in complex_int_lvs)

        # otherwise we need to do the calculations
        if self.cached:
            cache_md = self.cache.md_size
        else:
            cache_md = Size(0)

        non_raid_base = self.metadata_size + self.log_size
        if non_raid_base and self.is_raid_lv:
            zero_superblock = lambda x: Size(0)
            try:
                raided_space = self.raid_level.get_space(non_raid_base, self.num_raid_pvs,
                                                         superblock_size_func=zero_superblock)
                return raided_space + cache_md
            except errors.RaidError:
                # Too few PVs for the segment type (RAID level), we must have
                # incomplete information about the current LVM
                # configuration. Let's just default to the basic size for
                # now. Later calls to this property will provide better results.
                # TODO: add pv_count field to blockdev.LVInfo and this class
                return non_raid_base + cache_md

        return non_raid_base + cache_md

    @property
    def pv_space_used(self):
        """
        :returns: space occupied by this LV on its VG's PVs (if we have and idea)
        :rtype: list of LVPVSpec

        """
        return self._pv_specs

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
            return super(LVMLogicalVolumeBase, self)._get_name()

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

    def _pre_setup(self, orig=False):
        # If the lvmetad socket exists and any PV is inactive before we call
        # setup_parents (via _pre_setup, below), we should wait for auto-
        # activation before trying to manually activate this LV.
        auto_activate = (lvm.lvmetad_socket_exists() and
                         any(not pv.format.status for pv in self.vg.pvs))
        if not super(LVMLogicalVolumeBase, self)._pre_setup(orig=orig):
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

    def _pre_destroy(self):
        StorageDevice._pre_destroy(self)
        # set up the vg's pvs so lvm can remove the lv
        self.vg.setup_parents(orig=True)

    def set_rw(self):
        """ Run lvchange as needed to ensure the lv is not read-only. """
        lvm.ensure_lv_is_writable(self.vg.name, self.lvname)

    @property
    def lvname(self):
        """ The LV's name (not including VG name). """
        return self._name

    @property
    def complete(self):
        """ Test if vg exits and if it has all pvs. """
        return self.vg.complete

    @property
    def isleaf(self):
        # Thin snapshots do not need to be removed prior to removal of the
        # origin, but the old snapshots do.
        non_thin_snapshots = any(s for s in self.snapshots
                                 if not s.is_thin_lv)
        return super(LVMLogicalVolumeBase, self).isleaf and not non_thin_snapshots

    def add_internal_lv(self, int_lv):
        if int_lv not in self._internal_lvs:
            self._internal_lvs.append(int_lv)

    def remove_internal_lv(self, int_lv):
        if int_lv in self._internal_lvs:
            self._internal_lvs.remove(int_lv)
        else:
            msg = "the specified internal LV '%s' doesn't belong to this LV ('%s')" % (int_lv.lv_name,
                                                                                       self.name)
            raise errors.DeviceError(msg)

    def populate_ksdata(self, data):
        super(LVMLogicalVolumeBase, self).populate_ksdata(data)
        data.vgname = self.vg.name
        data.name = self.lvname
        data.preexist = self.exists
        data.resize = (self.exists and self.target_size and
                       self.target_size != self.current_size)
        if not self.exists:
            data.grow = self.req_grow
            if self.req_percent:
                data.percent = self.req_percent
            elif self.req_grow:
                # use the base size for growable lvs
                data.size = self.req_size.convert_to(MiB)
            else:
                data.size = self.size.convert_to(MiB)

            if self.req_grow:
                # base size could be literal or percentage
                data.max_size_mb = self.req_max_size.convert_to(MiB)
        elif data.resize:
            data.size = self.target_size.convert_to(MiB)

    @property
    def cached(self):
        return bool(self.cache)

    @property
    def cache(self):
        if self.exists and not self._cache:
            # check if we have a cache pool internal LV
            for lv in self._internal_lvs:
                if lv.int_lv_type == LVMInternalLVtype.cache_pool:
                    if self.seg_type == "cache":
                        self._cache = LVMCache(self, size=lv.size, exists=True)
                    elif self.seg_type == "writecache":
                        self._cache = LVMWriteCache(self, size=lv.size, exists=True)

        return self._cache


class LVMInternalLVtype(Enum):
    data = 1
    meta = 2
    log = 3
    image = 4
    origin = 5
    cache_pool = 6
    unknown = 99

    @classmethod
    def get_type(cls, lv_attr, lv_name):  # pylint: disable=unused-argument
        attr_letters = {cls.data: ("T", "C"),
                        cls.meta: ("e",),
                        cls.log: ("l", "L"),
                        cls.image: ("i", "I"),
                        cls.origin: ("o",),
                        cls.cache_pool: ("C",)}

        if lv_attr[0] == "C":
            # cache pools and internal data LV of cache pools need a more complicated check
            if lv_attr[6] == "C":
                # target type == cache -> cache pool
                return cls.cache_pool
            else:
                return cls.data

        if lv_attr[0] == "r":
            # internal LV which is at the same time a RAID LV
            if lv_attr[6] == "C":
                # part of the cache -> cache origin
                # (cache pool cannot be a RAID LV, cache pool's data LV would
                # have lv_attr[0] == "C", metadata LV would have
                # lv_attr[0] == "e" even if they were RAID LVs)
                return cls.origin
            elif lv_attr[6] == "r":
                # a data LV (metadata LV would have lv_attr[0] == "e")
                return cls.data

        for lv_type, letters in attr_letters.items():
            if lv_attr[0] in letters:
                return lv_type

        return cls.unknown


class LVMInternalLogicalVolumeMixin(object):
    def __init__(self, vg, parent_lv, lv_type):
        self._vg = vg
        self._parent_lv = parent_lv
        self._lv_type = lv_type
        if parent_lv:
            self._parent_lv.add_internal_lv(self)

    def _init_check(self):
        # an internal LV should have no parents
        if self._parent_lv and self._parents:
            raise errors.DeviceError("an internal LV should have no parents")

    @property
    def is_internal_lv(self):
        return bool(self._parent_lv or self._lv_type)

    @property
    def vg(self):
        if self._parent_lv:
            return self._parent_lv.vg
        else:
            return self._vg

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
            self._vg = self._parent_lv.vg

    @property
    @util.requires_property("is_internal_lv")
    def int_lv_type(self):
        return self._lv_type

    @int_lv_type.setter
    @util.requires_property("is_internal_lv")
    def int_lv_type(self, lv_type):
        self._lv_type = lv_type

    @property
    @util.requires_property("is_internal_lv")
    def takes_extra_space(self):
        return self._lv_type in (LVMInternalLVtype.meta,
                                 LVMInternalLVtype.log,
                                 LVMInternalLVtype.cache_pool)

    @property
    @util.requires_property("is_internal_lv")
    def name_suffix(self):
        suffixes = {LVMInternalLVtype.data: r"_[tc]data",
                    LVMInternalLVtype.meta: r"_[trc]meta(_[0-9]+)?",
                    LVMInternalLVtype.log: r"_mlog",
                    LVMInternalLVtype.image: r"_[rm]image(_[0-9]+)?",
                    LVMInternalLVtype.origin: r"_c?orig",
                    LVMInternalLVtype.cache_pool: r"_cache(_?pool)?"}
        return suffixes.get(self._lv_type)

    @property
    def readonly(self):
        return True

    @readonly.setter
    def readonly(self, value):  # pylint: disable=unused-argument
        raise errors.DeviceError("Cannot make an internal LV read-write")

    @property
    def type(self):
        return "lvminternallv"

    @property
    def resizable(self):
        if DMDevice.resizable.__get__(self) and self._lv_type is LVMInternalLVtype.meta:  # pylint: disable=no-member,too-many-function-args,no-value-for-parameter
            if self._parent_lv:
                return self._parent_lv.is_thin_pool
            else:
                # hard to say at this point, just use the name
                return not re.search(r'_[rc]meta', self.lvname)
        else:
            return False

    def resize(self):
        if self._lv_type is not LVMInternalLVtype.meta:
            errors.DeviceError("The internal LV %s cannot be resized" % self.lvname)
        if ((self._parent_lv and not self._parent_lv.is_thin_pool) or
                re.search(r'_[rc]meta', self.lvname)):
            raise errors.DeviceError("RAID and cache pool metadata LVs cannot be resized directly")

        # skip the generic LVMInternalLogicalVolumeDevice class and call the
        # resize() method of the LVMLogicalVolumeDevice
        raise NotTypeSpecific()

    def is_name_valid(self, name):  # pylint: disable=unused-argument
        # override checks for normal LVs, internal LVs typically have names that
        # are forbidden for normal LVs
        return True

    def _check_parents(self):
        # an internal LV should have no parents
        if self._parents:
            raise errors.DeviceError("an internal LV should have no parents")

    def _add_to_parents(self):
        # nothing to do here, an internal LV has no parents (in the DeviceTree's
        # meaning of 'parents')
        pass

    # internal LVs follow different rules limitting size
    def _set_size(self, newsize):
        if not isinstance(newsize, Size):
            raise AttributeError("new size must of type Size")

        if not self.takes_extra_space:
            if newsize <= self.parent_lv.size:  # pylint: disable=no-member
                self._size = newsize  # pylint: disable=attribute-defined-outside-init
            else:
                raise errors.DeviceError("Internal LV cannot be bigger than its parent LV")
        else:
            # same rules apply as for any other LV
            raise NotTypeSpecific()

    @property
    def max_size(self):
        # no format, so maximum size is only limitted by either the parent LV or the VG
        if not self.takes_extra_space:
            return self._parent_lv.max_size
        else:
            return self.size + self.vg.free_space

    # generally changes should be done on the parent LV (exceptions should
    # override these)
    def setup(self, orig=False):  # pylint: disable=unused-argument
        if self._parent_lv.exists:
            # unless this LV is yet to be used by the parent LV...
            raise errors.DeviceError("An internal LV cannot be set up separately")

    def teardown(self, recursive=None):  # pylint: disable=unused-argument
        if self._parent_lv.exists:
            # unless this LV is yet to be used by the parent LV...
            raise errors.DeviceError("An internal LV cannot be torn down separately")

    def destroy(self):
        if self._parent_lv.exists:
            # unless this LV is yet to be used by the parent LV...
            raise errors.DeviceError("An internal LV cannot be destroyed separately")

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
        DMDevice.add_hook(self, new=new)
        self._parent_lv.add_internal_lv(self)

    def remove_hook(self, modparent=True):
        if modparent:
            self._parent_lv.remove_internal_lv(self)

        # skip LVMLogicalVolumeDevice in the class hierarchy -- we cannot remove
        # an internal LV from the VG (it's only referenced by the parent LV)
        # pylint: disable=bad-super-call
        DMDevice.remove_hook(self, modparent=modparent)

    @property
    def direct(self):
        # internal LVs are not directly accessible
        return False


class LVMSnapshotMixin(object):
    def __init__(self, origin=None, vorigin=False):
        self.origin = origin
        """ the snapshot's source volume """

        self.vorigin = vorigin
        """ a boolean flag indicating a vorigin snapshot """

    def _init_check(self):
        if not self.is_snapshot_lv:
            # not a snapshot, nothing more to be done
            return

        if self.origin and not isinstance(self.origin, LVMLogicalVolumeDevice):
            raise errors.DeviceError("lvm snapshot origin must be a logical volume")
        if self.vorigin and not self.exists:
            raise errors.DeviceError("only existing vorigin snapshots are supported")

        if isinstance(self.origin, LVMLogicalVolumeDevice) and \
           isinstance(self.parents[0], LVMVolumeGroupDevice) and \
           self.origin.vg != self.parents[0]:
            raise errors.DeviceError("lvm snapshot and origin must be in the same vg")

        if self.is_thin_lv:
            if self.origin and self.size and not self.exists:
                raise errors.DeviceError("thin snapshot size is determined automatically")

    @property
    def is_snapshot_lv(self):
        return bool(self.origin or self.vorigin)

    @property
    def type(self):
        if self.is_thin_lv:
            return "lvmthinsnapshot"
        else:
            return "lvmsnapshot"

    @property
    def resizable(self):
        if self.is_thin_lv:
            return False
        else:
            raise NotTypeSpecific()

    @property
    def format_immutable(self):
        return False

    # decorator
    def old_snapshot_specific(meth):  # pylint: disable=no-self-argument
        """Decorator for methods that are specific only to old snapshots"""
        @wraps(meth)
        def decorated(self, *args, **kwargs):
            if self.is_thin_lv:
                raise NotTypeSpecific()
            else:
                return meth(self, *args, **kwargs)  # pylint: disable=not-callable
        return decorated

    @util.requires_property("is_snapshot_lv")
    def merge(self):
        """ Merge the snapshot back into its origin volume. """
        log_method_call(self, self.name, status=self.status)
        self.vg.setup()
        try:
            self.origin.teardown()
        except errors.FSError:
            # the merge will begin based on conditions described in the --merge
            # section of lvconvert(8)
            pass

        try:
            self.teardown()
        except errors.FSError:
            pass

        udev.settle()
        blockdev.lvm.lvsnapshotmerge(self.vg.name, self.lvname)

    @util.requires_property("is_snapshot_lv")
    def _update_format_from_origin(self):
        """ Update the snapshot's format to reflect the origin's.

            .. note::
                This should only be called for non-existent snapshot devices.
                Once a snapshot exists its format is distinct from that of its
                origin.

        """
        if not self.origin and self.vorigin:
            # nothing to do for vorigin with no origin set
            return

        fmt = copy.deepcopy(self.origin.format)
        fmt.exists = False
        if hasattr(fmt, "mountpoint"):
            fmt.mountpoint = None
            fmt._chrooted_mountpoint = None
            fmt.device = self.path

        self._format = fmt  # pylint: disable=attribute-defined-outside-init

    def _set_format(self, fmt):  # pylint: disable=unused-argument
        # If a snapshot exists it can have a format that is distinct from its
        # origin's. If it does not exist its format must be a copy of its
        # origin's.
        if self.exists:
            raise NotTypeSpecific()
        else:
            log.info("copying %s origin's format", self.name)
            self._update_format_from_origin()

    @old_snapshot_specific
    def setup(self, orig=False):
        # the old snapshot cannot be setup and torn down
        pass

    @old_snapshot_specific
    def teardown(self, recursive=False):
        # the old snapshot cannot be setup and torn down
        pass

    def _create(self):
        """ Create the device. """
        if not self.is_thin_lv:
            log_method_call(self, self.name, status=self.status)
            blockdev.lvm.lvsnapshotcreate(self.vg.name, self.origin.lvname, self._name, self.size)
        else:
            pool_name = None
            if not self.origin.is_thin_lv:
                # if the origin is not a thin volume we need to tell lvm which pool
                # to use
                pool_name = self.pool.lvname

            blockdev.lvm.thsnapshotcreate(self.vg.name, self.origin.lvname, self._name,
                                          pool_name=pool_name)

    def _post_create(self):
        DMDevice._post_create(self)
        # Snapshot's format exists as soon as the snapshot has been
        # created iff the origin's format exists
        self.format.exists = self.origin.format.exists

    @old_snapshot_specific
    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        # old-style snapshots' status is tied to the origin's so we never
        # explicitly activate or deactivate them and we have to tell lvremove
        # that it is okay to remove the active snapshot
        blockdev.lvm.lvremove(self.vg.name, self._name, force=True)

    def depends_on(self, dep):
        if self.is_thin_lv:
            if self.origin == dep and not self.exists:
                return True
            else:
                raise NotTypeSpecific()
        else:
            if self.origin == dep:
                return True
            else:
                raise NotTypeSpecific()

    @old_snapshot_specific
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


class LVMThinPoolMixin(object):
    def __init__(self, metadata_size=None, chunk_size=None, profile=None):
        self._metadata_size = metadata_size or Size(0)
        self._chunk_size = chunk_size or Size(0)
        self._profile = profile
        self._lvs = []

    def _init_check(self):
        if self._metadata_size and not blockdev.lvm.is_valid_thpool_md_size(self._metadata_size):
            raise ValueError("invalid metadatasize value")

        if self._chunk_size and not blockdev.lvm.is_valid_thpool_chunk_size(self._chunk_size):
            raise ValueError("invalid chunksize value")

    def _check_from_lvs(self):
        if self._from_lvs:
            if len(self._from_lvs) != 2:
                raise errors.DeviceError("two LVs required to create a thin pool")

    def _convert_from_lvs(self):
        data_lv, metadata_lv = self._from_lvs

        data_lv.parent_lv = self  # also adds the LV to self._internal_lvs
        data_lv.int_lv_type = LVMInternalLVtype.data
        metadata_lv.parent_lv = self
        metadata_lv.int_lv_type = LVMInternalLVtype.meta

        self.size = data_lv.size

    @property
    def is_thin_pool(self):
        return self.seg_type == "thin-pool"

    @property
    def profile(self):
        return self._profile

    @property
    def chunk_size(self):
        return self._chunk_size

    @property
    def type(self):
        return "lvmthinpool"

    @property
    def resizable(self):
        return False

    @property
    @util.requires_property("is_thin_pool")
    def used_space(self):
        return sum((l.pool_space_used for l in self.lvs), Size(0))

    @property
    @util.requires_property("is_thin_pool")
    def free_space(self):
        return self.size - self.used_space

    @util.requires_property("is_thin_pool")
    def _add_log_vol(self, lv):
        """ Add an LV to this pool. """
        if lv in self._lvs:
            raise errors.DeviceError("lv is already part of this vg")

        # TODO: add some checking to prevent overcommit for preexisting
        self.vg._add_log_vol(lv)
        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

    @util.requires_property("is_thin_pool")
    def _remove_log_vol(self, lv):
        """ Remove an LV from this pool. """
        if lv not in self._lvs:
            raise errors.DeviceError("specified lv is not part of this vg")

        self._lvs.remove(lv)
        self.vg._remove_log_vol(lv)

    @property
    @util.requires_property("is_thin_pool")
    def lvs(self):
        """ A list of this pool's LVs """
        return self._lvs[:]     # we don't want folks changing our list

    @util.requires_property("is_thin_pool")
    def autoset_md_size(self, enforced=False):
        """ If self._metadata_size not set already, it calculates the recommended value
        and sets it while subtracting the size from self.size.

        """

        if self._metadata_size != 0 and not enforced:
            return  # Metadata size already set

        log.debug("Auto-setting thin pool metadata size%s", (" (enforced)" if enforced else ""))

        if self._size <= Size(0):
            log.debug("Thin pool size not bigger than 0, just setting metadata size to 0")
            self._metadata_size = 0
            return

        # we need to know chunk size to calculate recommended metadata size
        if self._chunk_size == 0:
            self._chunk_size = Size(blockdev.LVM_DEFAULT_CHUNK_SIZE)
            log.debug("Using default chunk size: %s", self._chunk_size)

        old_md_size = self._metadata_size
        old_pmspare_size = self.vg.pmspare_size
        self._metadata_size = Size(blockdev.lvm.get_thpool_meta_size(self._size,
                                                                     self._chunk_size,
                                                                     100))  # snapshots
        log.debug("Recommended metadata size: %s MiB", self._metadata_size.convert_to("MiB"))

        self._metadata_size = self.vg.align(self._metadata_size, roundup=True)
        log.debug("Rounded metadata size to extents: %s MiB", self._metadata_size.convert_to("MiB"))

        if self._metadata_size == old_md_size:
            log.debug("Rounded metadata size unchanged")
        else:
            new_size = self.size - (self._metadata_size - old_md_size) - (self.vg.pmspare_size - old_pmspare_size)
            log.debug("Adjusting size from %s MiB to %s MiB",
                      self.size.convert_to("MiB"), new_size.convert_to("MiB"))
            self.size = new_size

    def _pre_create(self):
        # make sure all the LVs this LV should be created from exist (if any)
        if self._from_lvs and any(not lv.exists for lv in self._from_lvs):
            raise errors.DeviceError("Component LVs need to be created first")

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        if self.profile:
            profile_name = self.profile.name
        else:
            profile_name = None
        # TODO: chunk size, data/metadata split --> profile
        # TODO: allow for specification of PVs
        if self._from_lvs:
            extra = dict()
            if profile_name:
                extra["profile"] = profile_name
            if self.chunk_size:
                extra["chunksize"] = str(int(self.chunk_size))
            data_lv = six.next(lv for lv in self._internal_lvs if lv.int_lv_type == LVMInternalLVtype.data)
            meta_lv = six.next(lv for lv in self._internal_lvs if lv.int_lv_type == LVMInternalLVtype.meta)
            blockdev.lvm.thpool_convert(self.vg.name, data_lv.lvname, meta_lv.lvname, self.lvname, **extra)
            # TODO: update the names of the internal LVs here
        else:
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
        LVMLogicalVolumeBase.populate_ksdata(self, data)
        data.mountpoint = "none"
        data.thin_pool = True
        data.metadata_size = self.metadata_size.convert_to(MiB)
        data.chunk_size = self.chunk_size.convert_to(KiB)
        if self.profile:
            data.profile = self.profile.name


class LVMThinLogicalVolumeMixin(object):
    def __init__(self):
        pass

    def _init_check(self):
        pass

    def _check_parents(self):
        """Check that this device has parents as expected"""
        if isinstance(self.parents, (list, ParentList)):
            if len(self.parents) != 1:
                raise errors.DeviceError("constructor requires a single thin-pool LV")

            container = self.parents[0]
        else:
            container = self.parents

        if not container or not isinstance(container, LVMLogicalVolumeDevice) or not container.is_thin_pool:
            raise errors.DeviceError("constructor requires a thin-pool LV")

    @property
    def is_thin_lv(self):
        return self.seg_type == "thin"

    @property
    def vg(self):
        # parents[0] is the pool, not the VG so set the VG here
        return self.pool.vg

    @property
    def type(self):
        return "lvmthinlv"

    @property
    @util.requires_property("is_thin_lv")
    def pool(self):
        return self.parents[0]

    @property
    @util.requires_property("is_thin_lv")
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

    def _set_size(self, newsize):
        if not isinstance(newsize, Size):
            raise AttributeError("new size must of type Size")

        newsize = self.vg.align(newsize)
        newsize = self.vg.align(util.numeric_type(newsize))
        # just make sure the size is set (no VG size/free space check needed for
        # a thin LV)
        DMDevice._set_size(self, newsize)

    def _pre_create(self):
        # skip LVMLogicalVolumeDevice's _pre_create() method as it checks for a
        # free space in a VG which doesn't make sense for a ThinLV and causes a
        # bug by limitting the ThinLV's size to VG free space which is nonsense
        super(LVMLogicalVolumeBase, self)._pre_create()  # pylint: disable=bad-super-call

    def _create(self):
        """ Create the device. """
        log_method_call(self, self.name, status=self.status)
        blockdev.lvm.thlvcreate(self.vg.name, self.pool.lvname, self.lvname,
                                self.size)

    def remove_hook(self, modparent=True):
        if modparent:
            self.pool._remove_log_vol(self)

        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeBase, self).remove_hook(modparent=modparent)

    def add_hook(self, new=True):
        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeBase, self).add_hook(new=new)
        if new:
            return

        if self not in self.pool.lvs:
            self.pool._add_log_vol(self)

    def populate_ksdata(self, data):
        LVMLogicalVolumeBase.populate_ksdata(self, data)
        data.thin_volume = True
        data.pool_name = self.pool.lvname


class LVMVDOPoolMixin(object):
    def __init__(self):
        self._lvs = []

    @property
    def is_vdo_pool(self):
        return self.seg_type == "vdo-pool"

    @property
    def type(self):
        return "lvmvdopool"

    @property
    def resizable(self):
        return False

    @util.requires_property("is_vdo_pool")
    def _add_log_vol(self, lv):
        """ Add an LV to this VDO pool. """
        if lv in self._lvs:
            raise ValueError("lv is already part of this VDO pool")

        self.vg._add_log_vol(lv)
        log.debug("Adding %s/%s to %s", lv.name, lv.size, self.name)
        self._lvs.append(lv)

    @util.requires_property("is_vdo_pool")
    def _remove_log_vol(self, lv):
        """ Remove an LV from this VDO pool. """
        if lv not in self._lvs:
            raise ValueError("specified lv is not part of this VDO pool")

        self._lvs.remove(lv)
        self.vg._remove_log_vol(lv)

    @property
    @util.requires_property("is_vdo_pool")
    def lvs(self):
        """ A list of this VDO pool's LVs """
        return self._lvs[:]     # we don't want folks changing our list

    @property
    def direct(self):
        """ Is this device directly accessible? """
        return False

    def _create(self):
        """ Create the device. """
        raise NotImplementedError


class LVMVDOLogicalVolumeMixin(object):
    def __init__(self):
        pass

    def _init_check(self):
        pass

    def _check_parents(self):
        """Check that this device has parents as expected"""
        if isinstance(self.parents, (list, ParentList)):
            if len(self.parents) != 1:
                raise ValueError("constructor requires a single vdo-pool LV")

            container = self.parents[0]
        else:
            container = self.parents

        if not container or not isinstance(container, LVMLogicalVolumeDevice) or not container.is_vdo_pool:
            raise ValueError("constructor requires a vdo-pool LV")

    @property
    def vg_space_used(self):
        return Size(0)    # the pool's size is already accounted for in the vg

    @property
    def is_vdo_lv(self):
        return self.seg_type == "vdo"

    @property
    def vg(self):
        # parents[0] is the pool, not the VG so set the VG here
        return self.pool.vg

    @property
    def type(self):
        return "vdolv"

    @property
    def resizable(self):
        return False

    @property
    @util.requires_property("is_vdo_lv")
    def pool(self):
        return self.parents[0]

    def _create(self):
        """ Create the device. """
        raise NotImplementedError

    def _destroy(self):
        # nothing to do here, VDO LV is destroyed automatically together with
        # the VDO pool
        pass

    def remove_hook(self, modparent=True):
        if modparent:
            self.pool._remove_log_vol(self)

        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeBase, self).remove_hook(modparent=modparent)

    def add_hook(self, new=True):
        # pylint: disable=bad-super-call
        super(LVMLogicalVolumeBase, self).add_hook(new=new)
        if new:
            return

        if self not in self.pool.lvs:
            self.pool._add_log_vol(self)


class LVMLogicalVolumeDevice(LVMLogicalVolumeBase, LVMInternalLogicalVolumeMixin, LVMSnapshotMixin,
                             LVMThinPoolMixin, LVMThinLogicalVolumeMixin, LVMVDOPoolMixin,
                             LVMVDOLogicalVolumeMixin):
    """ An LVM Logical Volume """

    # generally resizable, see :property:`resizable` for details
    _resizable = True

    def __init__(self, name, parents=None, size=None, uuid=None, seg_type=None,
                 fmt=None, exists=False, sysfs_path='', grow=None, maxsize=None,
                 percent=None, cache_request=None, pvs=None,
                 parent_lv=None, int_type=None, origin=None, vorigin=False,
                 metadata_size=None, chunk_size=None, profile=None, from_lvs=None):
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
            :keyword seg_type: segment type (eg: "linear", "raid1", "thin-pool", "thin",...)
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

            For internal LVs only:

            :keyword parent_lv: parent LV of this internal LV
            :type parent_lv: :class:`LVMLogicalVolumeDevice`
            :keyword int_type: type of this internal LV
            :type int_type: :class:`LVMInternalLVtype`

            For snapshots only:

            :keyword origin: origin of this snapshot
            :type origin: :class:`~.StorageDevice`
            :keyword bool vorigin: is this a vorigin snapshot?

            For thin pools (seg_type="thin-pool") only:

            :keyword metadata_size: the size of the metadata LV
            :type metadata_size: :class:`~.size.Size`
            :keyword chunk_size: chunk size for the pool
            :type chunk_size: :class:`~.size.Size`
            :keyword profile: (allocation) profile for the pool or None (unspecified)
            :type profile: :class:`~.devicelibs.lvm.ThPoolProfile` or NoneType

            For new LVs created from other LVs:

            :keyword from_lvs: LVs to create the new LV from (in the (data_lv, metadata_lv) order)
            :type from_lvs: tuple of :class:`LVMLogicalVolumeDevice`

        """

        if isinstance(parents, (list, ParentList)):
            vg = parents[0]
        else:
            vg = parents
        if parent_lv or int_type:
            # internal LVs are not in the DeviceTree and doesn't have the
            # parent<->child relation like other devices
            parents = None

        self.seg_type = seg_type

        LVMInternalLogicalVolumeMixin.__init__(self, vg, parent_lv, int_type)
        LVMSnapshotMixin.__init__(self, origin, vorigin)
        LVMThinPoolMixin.__init__(self, metadata_size, chunk_size, profile)
        LVMThinLogicalVolumeMixin.__init__(self)
        LVMLogicalVolumeBase.__init__(self, name, parents, size, uuid, seg_type,
                                      fmt, exists, sysfs_path, grow, maxsize,
                                      percent, cache_request, pvs, from_lvs)
        LVMVDOPoolMixin.__init__(self)
        LVMVDOLogicalVolumeMixin.__init__(self)

        LVMInternalLogicalVolumeMixin._init_check(self)
        LVMSnapshotMixin._init_check(self)
        LVMThinPoolMixin._init_check(self)
        LVMThinLogicalVolumeMixin._init_check(self)

        if self._from_lvs:
            self._check_from_lvs()
            self._convert_from_lvs()

        # check that we got parents as expected and add this device to them now
        # that it is fully-initialized
        self._check_parents()
        self._add_to_parents()

    def _get_type_classes(self):
        """Method to get type classes for this particular instance"""
        ret = []
        if self.is_internal_lv:
            ret.append(LVMInternalLogicalVolumeMixin)
        if self.is_snapshot_lv:
            ret.append(LVMSnapshotMixin)
        if self.is_thin_pool:
            ret.append(LVMThinPoolMixin)
        if self.is_thin_lv:
            ret.append(LVMThinLogicalVolumeMixin)
        if self.is_vdo_pool:
            ret.append(LVMVDOPoolMixin)
        if self.is_vdo_lv:
            ret.append(LVMVDOLogicalVolumeMixin)
        return ret

    def _try_specific_call(self, name, *args, **kwargs):
        """Try to call a type-specific method for this particular instance"""
        clss = self._get_type_classes()
        for cls in clss:
            if hasattr(cls, name):
                try:
                    # found, check if it is a method or property
                    if isinstance(getattr(cls, name), property):
                        if len(args) == 0 and len(kwargs.keys()) == 0:
                            # no *args nor **kwargs -> call the getter
                            ret = getattr(cls, name).__get__(self)
                        else:
                            # some args -> call the setter
                            ret = getattr(cls, name).__set__(self, *args, **kwargs)
                    else:
                        # or just call the method with all the args
                        ret = getattr(cls, name)(self, *args, **kwargs)
                except NotTypeSpecific:
                    # no type-specific steps required for this class, just
                    # continue with another one
                    continue
                else:
                    return (True, ret)
        # not found, let the caller know
        return (False, None)

    # decorator
    def type_specific(meth):  # pylint: disable=no-self-argument
        @wraps(meth)
        def decorated(self, *args, **kwargs):
            """Decorator that makes sure the type-specific code is executed if available"""
            found, ret = self._try_specific_call(meth.__name__, *args, **kwargs)  # pylint: disable=no-member
            if found:
                # nothing more to do here
                return ret
            else:
                return meth(self, *args, **kwargs)  # pylint: disable=not-callable

        return decorated

    def __repr__(self):
        s = DMDevice.__repr__(self)
        s += ("  VG device = %(vgdev)r\n"
              "  segment type = %(type)s percent = %(percent)s\n"
              "  VG space used = %(vgspace)s" %
              {"vgdev": self.vg, "percent": self.req_percent,
               "type": self.seg_type,
               "vgspace": self.vg_space_used})
        if self.parent_lv:
            s += "  parent LV = %r\n" % self.parent_lv

        return s

    @type_specific
    def _check_parents(self):
        """Check that this device has parents as expected"""
        if isinstance(self.parents, (list, ParentList)):
            if len(self.parents) != 1:
                raise ValueError("constructor requires a single LVMVolumeGroupDevice")

            container = self.parents[0]
        else:
            container = self.parents

        if not isinstance(container, LVMVolumeGroupDevice):
            raise AttributeError("constructor requires a LVMVolumeGroupDevice")

    @type_specific
    def _add_to_parents(self):
        """Add this device to its parents"""
        # a normal LV has only exactly one parent -- the VG it belongs to
        self._parents[0]._add_log_vol(self)

    @type_specific
    def _check_from_lvs(self):
        """Check the LVs to create this LV from"""
        raise errors.DeviceError("Cannot create a new LV of type '%s' from other LVs" % self.seg_type)

    @type_specific
    def _convert_from_lvs(self):
        """Convert the LVs to create this LV from into its internal LVs"""
        raise errors.DeviceError("Cannot create a new LV of type '%s' from other LVs" % self.seg_type)

    @property
    @type_specific
    def vg(self):
        """This Logical Volume's Volume Group."""
        return super(LVMLogicalVolumeDevice, self).vg

    @type_specific
    def _set_size(self, newsize):
        if not isinstance(newsize, Size):
            raise AttributeError("new size must be of type Size")

        newsize = self.vg.align(newsize)
        log.debug("trying to set lv %s size to %s", self.name, newsize)
        # Don't refuse to set size if we think there's not enough space in the
        # VG for an existing LV, since it's existence proves there is enough
        # space for it. A similar reasoning applies to shrinking the LV.
        if not self.exists and newsize > self.size and newsize > self.vg.free_space + self.vg_space_used:
            log.error("failed to set size: %s short", newsize - (self.vg.free_space + self.vg_space_used))
            raise errors.DeviceError("not enough free space in volume group")

        LVMLogicalVolumeBase._set_size(self, newsize)

    size = property(StorageDevice._get_size, _set_size)

    @property
    @type_specific
    def max_size(self):
        """ The maximum size this lv can be. """
        max_lv = (self.vg.align(self.size, roundup=True) +
                  self.vg.align(self.vg.free_space, roundup=False))
        max_format = self.format.max_size
        return min(max_lv, max_format) if max_format else max_lv

    @property
    @type_specific
    def vg_space_used(self):
        """ Space occupied by this LV, not including snapshots. """
        return super(LVMLogicalVolumeDevice, self).vg_space_used

    @type_specific
    def _set_format(self, fmt):
        LVMLogicalVolumeBase._set_format(self, fmt)
        for snapshot in (s for s in self.snapshots if not s.exists):
            snapshot._update_format_from_origin()

    def setup_parents(self, orig=False):
        # parent is a vg, which has no formatting (or device for that matter)
        Device.setup_parents(self, orig=orig)

    @type_specific
    def setup(self, orig=False):
        return DMDevice.setup(self, orig)

    @type_specific
    def teardown(self, recursive=None):
        return DMDevice.teardown(self, recursive)

    @type_specific
    def destroy(self):
        return DMDevice.destroy(self)

    @property
    @type_specific
    def growable(self):
        return super(LVMLogicalVolumeDevice, self).growable

    @property
    @type_specific
    def readonly(self):
        return super(LVMLogicalVolumeDevice, self).readonly

    @property
    @type_specific
    def display_lv_name(self):
        return self.lvname

    @property
    @type_specific
    def pool(self):
        return super(LVMLogicalVolumeDevice, self).pool

    def _setup(self, orig=False):
        """ Open, or set up, a device. """
        log_method_call(self, self.name, orig=orig, status=self.status,
                        controllable=self.controllable)
        ignore_skip_activation = self.is_snapshot_lv or self.ignore_skip_activation > 0
        blockdev.lvm.lvactivate(self.vg.name, self._name, ignore_skip=ignore_skip_activation)

    @type_specific
    def _pre_create(self):
        LVMLogicalVolumeBase._pre_create(self)

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

    @type_specific
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
            fast_pvs = [pv.path for pv in self.cache.fast_pvs]

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

            slow_pvs = util.dedup_list(slow_pvs)

            # VG name, LV name, data size, cache size, metadata size, mode, flags, slow PVs, fast PVs
            # XXX: we need to pass slow_pvs+fast_pvs (without duplicates) as slow PVs because parts of the
            # fast PVs may be required for allocation of the LV (it may span over the slow PVs and parts of
            # fast PVs)
            blockdev.lvm.cache_create_cached_lv(self.vg.name, self._name, self.size, self.cache.size, self.cache.md_size,
                                                mode, 0, util.dedup_list(slow_pvs + fast_pvs), fast_pvs)

    @type_specific
    def _post_create(self):
        LVMLogicalVolumeBase._post_create(self)
        # update the free space info of the PVs this LV could have taken space
        # from (either specified or potentially all PVs from the VG)
        if self._pv_specs:
            used_pvs = [spec.pv for spec in self._pv_specs]
        else:
            used_pvs = self.vg.pvs
        for pv in used_pvs:
            # None means "not set" and triggers a dynamic fetch of the actual
            # value when queried
            pv.format.free = None

    @type_specific
    def _destroy(self):
        """ Destroy the device. """
        log_method_call(self, self.name, status=self.status)
        blockdev.lvm.lvremove(self.vg.name, self._name)

    @type_specific
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

    @type_specific
    def _add_log_vol(self, lv):
        pass

    @type_specific
    def _remove_log_vol(self, lv):
        pass

    @property
    @type_specific
    def lvs(self):
        return []

    @property
    @type_specific
    def direct(self):
        """ Is this device directly accessible? """
        # an LV can contain a direct filesystem if it is a leaf device or if
        # its only dependent devices are snapshots
        return super(LVMLogicalVolumeBase, self).isleaf

    @property
    @type_specific
    def type(self):
        return self._type

    @property
    @type_specific
    def resizable(self):
        return super(LVMLogicalVolumeDevice, self).resizable

    @property
    @type_specific
    def format_immutable(self):
        return super(LVMLogicalVolumeDevice, self).format_immutable

    @type_specific
    def depends_on(self, dep):
        # internal LVs are not in the device tree and thus not parents nor
        # children
        return DMDevice.depends_on(self, dep) or (dep in self._internal_lvs)

    @type_specific
    def read_current_size(self):
        return DMDevice.read_current_size(self)

    @type_specific
    def dracut_setup_args(self):
        # Note no map_name usage here, this is a lvm cmdline name, which
        # is different (ofcourse)
        return set(["rd.lvm.lv=%s/%s" % (self.vg.name, self._name)])

    @type_specific
    def remove_hook(self, modparent=True):
        if modparent:
            self.vg._remove_log_vol(self)

        if self._from_lvs:
            for lv in self._from_lvs:
                # changes the LV into a non-internal one
                lv.parent_lv = None
                lv.int_lv_type = None

        LVMLogicalVolumeBase.remove_hook(self, modparent=modparent)

    @type_specific
    def add_hook(self, new=True):
        LVMLogicalVolumeBase.add_hook(self, new=new)
        if new:
            return

        if self not in self.vg.lvs:
            self.vg._add_log_vol(self)
        if self._from_lvs:
            self._check_from_lvs()
            self._convert_from_lvs()

    @type_specific
    def populate_ksdata(self, data):
        LVMLogicalVolumeBase.populate_ksdata(self, data)

    @type_specific
    def is_name_valid(self, name):
        if not lvm.is_lvm_name_valid(name):
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

    def attach_cache(self, cache_pool_lv):
        if self.is_thin_lv or self.is_snapshot_lv or self.is_internal_lv:
            raise errors.DeviceError("Cannot attach a cache pool to the '%s' LV" % self.name)
        blockdev.lvm.cache_attach(self.vg.name, self.lvname, cache_pool_lv.lvname)
        self._cache = LVMCache(self, size=cache_pool_lv.size, exists=True)


class LVMCache(Cache):

    type = "cache"

    """Class providing the cache-related functionality of a cached LV"""

    def __init__(self, cached_lv, size=None, md_size=None, exists=False, pvs=None, mode=None):
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
        :param pvs: PVs to allocate the cache on/from (ignored for existing)
        :type pvs: list of :class:`LVPVSpec`
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
            # if we are going to cause a pmspare LV allocation or growth, we
            # should account for it
            if cached_lv.vg.pmspare_size < default_md_size:
                self._size -= default_md_size - cached_lv.vg.pmspare_size
            self._size = cached_lv.vg.align(self._size)
            self._md_size = default_md_size
        else:
            self._size = size
            self._md_size = md_size
        self._exists = exists
        self._mode = None
        self._pv_specs = []
        if not exists:
            self._mode = mode or "writethrough"
            for pv_spec in pvs:
                if isinstance(pv_spec, LVPVSpec):
                    self._pv_specs.append(pv_spec)
                elif isinstance(pv_spec, StorageDevice):
                    self._pv_specs.append(LVPVSpec(pv_spec, Size(0)))
            self._assign_pv_space()

    def _assign_pv_space(self):
        # calculate the size of space that we need to place somewhere
        space_to_assign = self.size + self.md_size - sum(spec.size for spec in self._pv_specs)

        # skip the PVs that already have some chunk of the space assigned
        for spec in (spec for spec in self._pv_specs if not spec.size):
            if spec.pv.format.free >= space_to_assign:
                # enough space in this PV, put everything in there and quit
                spec.size = space_to_assign
                space_to_assign = Size(0)
                break
            elif spec.pv.format.free > 0:
                # some space, let's use it and move on to another PV (if any)
                spec.size = spec.pv.format.free
                space_to_assign -= spec.pv.format.free
        if space_to_assign > 0:
            raise errors.DeviceError("Not enough free space in the PVs for this cache: %s short" % space_to_assign)

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
        return [spec.pv for spec in self._pv_specs]

    @property
    def pv_space_used(self):
        """
        :returns: space to be occupied by the cache on its LV's VG's PVs (one has to love LVM)
        :rtype: list of LVPVSpec

        """
        return self._pv_specs

    def detach(self):
        vg_name = self._cached_lv.vg.name
        ret = blockdev.lvm.cache_pool_name(vg_name, self._cached_lv.lvname)
        blockdev.lvm.cache_detach(vg_name, self._cached_lv.lvname, False)
        return ret


class LVMWriteCache(Cache):

    type = "writecache"

    def __init__(self, cached_lv, size, exists):
        self._cached_lv = cached_lv
        self._exists = exists
        self._size = size

        if not self._exists:
            raise ValueError("Only preexisting LVM writecache devices are currently supported.")

    @property
    def size(self):
        return self._size

    @property
    def md_size(self):
        # there are no metadata for writecache
        return Size(0)

    @property
    def vg_space_used(self):
        return self.size

    @property
    def exists(self):
        return self._exists

    @property
    def stats(self):
        return None

    @property
    def backing_device_name(self):
        return self._cached_lv.name

    @property
    def cache_device_name(self):
        vg_name = self._cached_lv.vg.name
        return "%s-%s" % (vg_name, blockdev.lvm.cache_pool_name(vg_name, self._cached_lv.lvname))

    def detach(self):
        raise NotImplementedError


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

    def __init__(self, size, pvs, mode=None):
        """
        :param size: requested size of the cache
        :type size: :class:`~.size.Size`
        :param pvs: PVs to allocate the cache on/from
        :type pvs: list of (:class:`~.devices.storage.StorageDevice` or :class:`LVPVSpec`)
        :param str mode: requested mode for the cache (``None`` means the default is used)

        """
        self._size = size
        self._mode = mode or "writethrough"
        self._pv_specs = []
        for pv_spec in pvs:
            if isinstance(pv_spec, LVPVSpec):
                self._pv_specs.append(pv_spec)
            elif isinstance(pv_spec, StorageDevice):
                self._pv_specs.append(LVPVSpec(pv_spec, Size(0)))

    @property
    def size(self):
        return self._size

    @property
    def fast_devs(self):
        return [spec.pv for spec in self._pv_specs]

    @property
    def pv_space_requests(self):
        """
        :returns: space to be occupied by the cache on its LV's VG's PVs (one has to love LVM)
        :rtype: list of LVPVSpec

        """
        return self._pv_specs

    @property
    def mode(self):
        return self._mode
