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
from ..tasks import availability
from ..i18n import N_
from ..size import Size
from . import DeviceFormat, register_device_format

import logging
log = logging.getLogger("blivet")


class LVMPhysicalVolume(DeviceFormat):
    """ An LVM physical volume. """
    _type = "lvmpv"
    _name = N_("physical volume (LVM)")
    _udevTypes = ["LVM2_member"]
    partedFlag = PARTITION_LVM
    _formattable = True                 # can be formatted
    _supported = True                   # is supported
    _linuxNative = True                 # for clearpart
    _minSize = lvm.LVM_PE_SIZE * 2      # one for metadata and one for data
    _packages = ["lvm2"]                # required packages
    _ksMountpoint = "pv."
    _plugin = availability.BLOCKDEV_LVM_PLUGIN

    def __init__(self, **kwargs):
        """
            :keyword device: path to the block device node
            :keyword uuid: this PV's uuid (not the VG uuid)
            :keyword exists: indicates whether this is an existing format
            :type exists: bool
            :keyword vgName: the name of the VG this PV belongs to
            :keyword vgUuid: the UUID of the VG this PV belongs to
            :keyword peStart: offset of first physical extent
            :type peStart: :class:`~.size.Size`
            :keyword dataAlignment: data alignment (for non-existent PVs)
            :type dataAlignment: :class:`~.size.Size`

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)
        self.vgName = kwargs.get("vgName")
        self.vgUuid = kwargs.get("vgUuid")
        self.peStart = kwargs.get("peStart", lvm.LVM_PE_START)
        self.dataAlignment = kwargs.get("dataAlignment", Size(0))

        self.inconsistentVG = False

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  vgName = %(vgName)s  vgUUID = %(vgUUID)s"
              "  peStart = %(peStart)s  dataAlignment = %(dataAlignment)s" %
              {"vgName": self.vgName, "vgUUID": self.vgUuid,
               "peStart": self.peStart, "dataAlignment": self.dataAlignment})
        return s

    @property
    def dict(self):
        d = super(LVMPhysicalVolume, self).dict
        d.update({"vgName": self.vgName, "vgUUID": self.vgUuid,
                  "peStart": self.peStart, "dataAlignment": self.dataAlignment})
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

        # Consider use of -Z|--zero
        # -f|--force or -y|--yes may be required

        # lvm has issues with persistence of metadata, so here comes the
        # hammer...
        # XXX This format doesn't exist yet, so bypass the precondition checking
        #     for destroy by calling _destroy directly.
        DeviceFormat._destroy(self, **kwargs)
        blockdev.lvm.pvscan(self.device)
        blockdev.lvm.pvcreate(self.device, data_alignment=self.dataAlignment)
        blockdev.lvm.pvscan(self.device)

    def _destroy(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        try:
            blockdev.lvm.pvremove(self.device)
        except blockdev.LVMError:
            DeviceFormat._destroy(self, **kwargs)
        finally:
            blockdev.lvm.pvscan(self.device)

    @property
    def destroyable(self):
        return self._plugin.available

    @property
    def status(self):
        # XXX hack
        return (self.exists and self.vgName and
                os.path.isdir("/dev/%s" % self.vgName))

register_device_format(LVMPhysicalVolume)

