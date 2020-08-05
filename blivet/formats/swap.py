# swap.py
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

from parted import PARTITION_SWAP, fileSystemType
from ..errors import FSWriteUUIDError, SwapSpaceError
from ..storage_log import log_method_call
from ..tasks import availability
from ..tasks import fsuuid
from . import DeviceFormat, register_device_format
from ..size import Size

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")


class SwapSpace(DeviceFormat):

    """ Swap space """
    _type = "swap"
    _name = None
    _udev_types = ["swap"]
    parted_flag = PARTITION_SWAP
    parted_system = fileSystemType["linux-swap(v1)"]
    _formattable = True                # can be formatted
    _supported = True                  # is supported
    _linux_native = True                # for clearpart
    _plugin = availability.BLOCKDEV_SWAP_PLUGIN

    _max_size = Size("16 TiB")

    config_actions_map = {"label": "write_label"}

    def __init__(self, **kwargs):
        """
            :keyword device: path to the block device node
            :keyword uuid: this swap space's uuid
            :keyword exists: whether this is an existing format
            :type exists: bool
            :keyword label: this swap space's label
            :keyword priority: this swap space's priority
            :type priority: int

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the 'device'
                attribute be set before the :meth:`~.SwapSpace.create` method
                runs. You can specify the device at the last moment by via the
                'device' kwarg to the :meth:`~.SwapSpace.create` method.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        self.priority = kwargs.get("priority", -1)
        self.label = kwargs.get("label")

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  priority = %(priority)s  label = %(label)s" %
              {"priority": self.priority, "label": self.label})
        return s

    @property
    def dict(self):
        d = super(SwapSpace, self).dict
        d.update({"priority": self.priority, "label": self.label})
        return d

    @property
    def formattable(self):
        return super(SwapSpace, self).formattable and self._plugin.available

    @property
    def supported(self):
        return super(SwapSpace, self).supported and self._plugin.available

    @property
    def controllable(self):
        return super(SwapSpace, self).controllable and self._plugin.available

    def labeling(self):
        """Returns True as mkswap can write a label to the swap space."""
        return True

    def relabels(self):
        """Returns True as mkswap can write a label to the swap space."""
        return True and self._plugin.available

    def label_format_ok(self, label):
        """Returns True since no known restrictions on the label."""
        return True

    def write_label(self, dry_run=False):
        """ Create a label for this format.

            :raises: SwapSpaceError

            If self.label is None, this means accept the default, so raise
            an SwapSpaceError in this case.

            Raises a SwapSpaceError if the label can not be set.
        """

        if not self._plugin.available:
            raise SwapSpaceError("application to set label on swap format is not available")

        if not dry_run:
            if not self.exists:
                raise SwapSpaceError("swap has not been created")

            if not os.path.exists(self.device):
                raise SwapSpaceError("device does not exist")

            if self.label is None:
                raise SwapSpaceError("makes no sense to write a label when accepting default label")

            if not self.label_format_ok(self.label):
                raise SwapSpaceError("bad label format")

            blockdev.swap.mkswap(self.device, self.label)

    label = property(lambda s: s._get_label(), lambda s, l: s._set_label(l),
                     doc="the label for this swap space")

    def uuid_format_ok(self, uuid):
        """Check whether the given UUID is correct according to RFC 4122."""
        return fsuuid.FSUUID._check_rfc4122_uuid(uuid)

    def _set_priority(self, priority):
        # pylint: disable=attribute-defined-outside-init
        if priority is None:
            self._priority = -1
            return

        if not isinstance(priority, int) or not -1 <= priority <= 32767:
            # -1 means "unspecified"
            raise ValueError("swap priority must be an integer between -1 and 32767")

        self._priority = priority

    def _get_priority(self):
        return self._priority

    priority = property(_get_priority, _set_priority,
                        doc="The priority of the swap device")

    def _get_options(self):
        opts = ""
        if self.priority is not None and self.priority != -1:
            opts += "pri=%d" % self.priority

        return opts

    def _set_options(self, options):
        if not options:
            self.priority = None
            return

        for option in options.split(","):
            (opt, equals, arg) = option.partition("=")
            if equals and opt == "pri":
                try:
                    self.priority = int(arg)
                except ValueError:
                    log.info("invalid value for swap priority: %s", arg)

    @property
    def status(self):
        """ Device status. """
        return self.exists and blockdev.swap.swapstatus(self.device)

    def _setup(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        blockdev.swap.swapon(self.device, priority=self.priority)

    def _teardown(self, **kwargs):
        """ Close, or tear down, a device. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        blockdev.swap.swapoff(self.device)

    def _create(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if self.uuid is None:
            blockdev.swap.mkswap(self.device, label=self.label)
        else:
            if not self.uuid_format_ok(self.uuid):
                raise FSWriteUUIDError("bad UUID format for swap filesystem")
            blockdev.swap.mkswap(self.device, label=self.label,
                                 extra={"-U": self.uuid})


register_device_format(SwapSpace)
