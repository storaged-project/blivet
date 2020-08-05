# lvmpv.py
# Device format classes for anaconda's storage configuration module.
#
# Copyright (C) 2009  Red Hat, Inc.
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
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import os

from ..storage_log import log_method_call
from parted import PARTITION_LVM
from ..devicelibs import lvm
from ..tasks import availability, pvtask
from ..i18n import N_
from ..size import Size
from ..errors import PhysicalVolumeError
from . import DeviceFormat, register_device_format
from .. import udev
from ..static_data.lvm_info import pvs_info

import logging
log = logging.getLogger("blivet")


class LVMPhysicalVolume(DeviceFormat):

    """ An LVM physical volume. """
    _type = "lvmpv"
    _name = N_("physical volume (LVM)")
    _udev_types = ["LVM2_member"]
    parted_flag = PARTITION_LVM
    _formattable = True                 # can be formatted
    _supported = True                   # is supported
    _linux_native = True                 # for clearpart
    _min_size = lvm.LVM_PE_SIZE * 2      # one for metadata and one for data
    _packages = ["lvm2"]                # required packages
    _ks_mountpoint = "pv."
    _plugin = availability.BLOCKDEV_LVM_PLUGIN
    _resizable = True

    _size_info_class = pvtask.PVSize
    _resize_class = pvtask.PVResize

    def __init__(self, **kwargs):
        """
            :keyword device: path to the block device node
            :keyword uuid: this PV's uuid (not the VG uuid)
            :keyword exists: indicates whether this is an existing format
            :type exists: bool
            :keyword vg_name: the name of the VG this PV belongs to
            :keyword vg_uuid: the UUID of the VG this PV belongs to
            :keyword pe_start: offset of first physical extent
            :type pe_start: :class:`~.size.Size`
            :keyword data_alignment: data alignment (for non-existent PVs)
            :type data_alignment: :class:`~.size.Size`
            :keyword free: free space in the PV
            :type free: :class:`~.size.Size`

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        self._size_info = self._size_info_class(self)
        self._resize = self._resize_class(self)

        self.vg_name = kwargs.get("vg_name")
        self.vg_uuid = kwargs.get("vg_uuid")
        self.pe_start = kwargs.get("pe_start", lvm.LVM_PE_START)
        self.data_alignment = kwargs.get("data_alignment", Size(0))
        self._free = kwargs.get("free")  # None means unknown

        self.inconsistent_vg = False

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  vg_name = %(vg_name)s  vg_uuid = %(vg_uuid)s"
              "  pe_start = %(pe_start)s  data_alignment = %(data_alignment)s" %
              {"vg_name": self.vg_name, "vg_uuid": self.vg_uuid,
               "pe_start": self.pe_start, "data_alignment": self.data_alignment})
        return s

    @property
    def dict(self):
        d = super(LVMPhysicalVolume, self).dict
        d.update({"vg_name": self.vg_name, "vg_uuid": self.vg_uuid,
                  "pe_start": self.pe_start, "data_alignment": self.data_alignment})
        return d

    @property
    def formattable(self):
        return super(LVMPhysicalVolume, self).formattable and self._plugin.available

    @property
    def supported(self):
        return super(LVMPhysicalVolume, self).supported and self._plugin.available

    def _create(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)

        ea_yes = blockdev.ExtraArg.new("-y", "")
        blockdev.lvm.pvcreate(self.device, data_alignment=self.data_alignment, extra=[ea_yes])

    def _destroy(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        try:
            blockdev.lvm.pvremove(self.device)
        except blockdev.LVMError:
            DeviceFormat._destroy(self, **kwargs)
        finally:
            udev.settle()

    @property
    def destroyable(self):
        return self._plugin.available

    @property
    def status(self):
        # XXX hack
        return (self.exists and self.vg_name and
                os.path.isdir("/dev/%s" % self.vg_name))

    def update_size_info(self):
        """ Update this format's current size. """

        self._resizable = False

        if not self.exists:
            return

        try:
            self._size = self._size_info.do_task()
        except PhysicalVolumeError as e:
            log.warning("Failed to obtain current size for device %s: %s", self.device, e)
        else:
            self._resizable = True

    @property
    def free(self):
        """ Information about the free space in this PV """
        if self._free is None:
            if self.exists:
                # we don't have any actual value, but the PV exists and is
                # active, we should try to determine it
                pv_info = pvs_info.cache.get(self.device.path)
                if pv_info is None:
                    log.error("Failed to get free space information for the PV '%s'", self.device)
                    self._free = Size(0)
                else:
                    self._free = Size(pv_info.pv_free)
            else:
                raise PhysicalVolumeError("Unknown free space information for the PV '%s'" % self.device)

        return self._free

    @free.setter
    def free(self, value):
        self._free = value

    @property
    def container_uuid(self):
        return self.vg_uuid

    @container_uuid.setter
    def container_uuid(self, uuid):
        self.vg_uuid = uuid


register_device_format(LVMPhysicalVolume)
