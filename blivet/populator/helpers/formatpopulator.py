# populator/helpers/formatpopulator.py
# Base classes for type-specific helpers for populating a DeviceTree.
#
# Copyright (C) 2009-2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from ...callbacks import callbacks
from ... import formats
from ... import udev
from ...errors import FSError

from .populatorhelper import PopulatorHelper

import logging
log = logging.getLogger("blivet")


class FormatPopulator(PopulatorHelper):
    priority = 0
    _type_specifier = None

    @classmethod
    def match(cls, data, device):  # pylint: disable=arguments-differ,unused-argument
        """ Return True if this helper is appropriate for the given device.

            :param :class:`pyudev.Device` data: udev data describing a device
            :param device: device instance corresponding to the udev data
            :type device: :class:`~.devices.StorageDevice`
            :returns: whether this class is appropriate for the specified device
            :rtype: bool
        """
        ret = False
        if cls is FormatPopulator:
            ret = True
        else:
            format_class = formats.get_device_format_class(cls._type_specifier)
            fmt_types = []
            if format_class is not None:
                fmt_types = format_class._udev_types[:]
                if cls._type_specifier and cls._type_specifier not in fmt_types:
                    fmt_types.append(cls._type_specifier)

            ret = (udev.device_get_format(data) in fmt_types)

        return ret

    def _get_kwargs(self):
        """ Return a kwargs dict to pass to DeviceFormat constructor. """
        kwargs = {"uuid": udev.device_get_uuid(self.data),
                  "label": udev.device_get_label(self.data),
                  "device": self.device.path,
                  "serial": udev.device_get_serial(self.data),
                  "exists": True}
        return kwargs

    @property
    def type_spec(self):
        if self._type_specifier is not None:
            type_spec = self._type_specifier
        else:
            type_spec = udev.device_get_format(self.data) or None

        return type_spec

    def run(self):
        """ Create a format instance and associate it with the device instance. """
        kwargs = self._get_kwargs()
        type_spec = self.type_spec
        try:
            log.info("type detected on '%s' is '%s'", self.device.name, type_spec)
            self.device.format = formats.get_format(type_spec, **kwargs)
        except FSError:
            log.warning("type '%s' on '%s' invalid, assuming no format",
                        type_spec, self.device.name)
            self.device.format = formats.DeviceFormat(device=self.device.path, exists=True)

    def update(self):
        label = udev.device_get_label(self.data)
        if hasattr(self.device.format, "label") and self.device.format.label != label:
            old_label = self.device.format.label
            self.device.format.label = label
            callbacks.attribute_changed(device=self.device, fmt=self.device.format,
                                        attr="label", old=old_label, new=label)
