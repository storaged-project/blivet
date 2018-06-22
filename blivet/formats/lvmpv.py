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

import os

from ..storage_log import log_method_call
from parted import PARTITION_LVM
from ..errors import LVMError, PhysicalVolumeError
from ..devicelibs import lvm
from ..i18n import N_
from . import DeviceFormat, register_device_format
from .. import udev

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
        # liblvm may be able to tell us this at some point, even
        # for not-yet-created devices
        self.peStart = kwargs.get("peStart", lvm.LVM_PE_START)
        self.dataAlignment = kwargs.get("dataAlignment")

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

    def probe(self):
        """ Probe for any missing information about this device. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self.exists:
            raise PhysicalVolumeError("format has not been created")

        #info = lvm.pvinfo(self.device)
        #self.vgName = info['vg_name']
        #self.vgUuid = info['vg_uuid']

    def create(self, **kwargs):
        """ Write the formatting to the specified block device.

            :keyword device: path to device node
            :type device: str
            :raises: FormatCreateError
            :returns: None.

            .. :note::

                If a device node path is passed to this method it will overwrite
                any previously set value of this instance's "device" attribute.
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)

        try:
            DeviceFormat.create(self, **kwargs)
            # Consider use of -Z|--zero
            # -f|--force or -y|--yes may be required

            # lvm has issues with persistence of metadata, so here comes the
            # hammer...
            DeviceFormat.destroy(self, **kwargs)
            lvm.pvscan(self.device)
            lvm.pvcreate(self.device, data_alignment=self.dataAlignment)
        except Exception:
            raise
        finally:
            udev.settle()
            lvm.pvscan(self.device)

        self.exists = True
        self.notifyKernel()

    def destroy(self, **kwargs):
        """ Remove the formatting from the associated block device.

            :raises: FormatDestroyError
            :returns: None.
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self.exists:
            raise PhysicalVolumeError("format has not been created")

        if self.status:
            raise PhysicalVolumeError("device is active")

        # FIXME: verify path exists?
        try:
            lvm.pvremove(self.device)
        except LVMError:
            DeviceFormat.destroy(self, **kwargs)
        finally:
            udev.settle()
            lvm.pvscan(self.device)

        self.exists = False
        self.notifyKernel()

    @property
    def status(self):
        # XXX hack
        return (self.exists and self.vgName and
                os.path.isdir("/dev/mapper/%s" % self.vgName))

register_device_format(LVMPhysicalVolume)

