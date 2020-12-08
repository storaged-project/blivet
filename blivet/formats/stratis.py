# stratis.py
# Device format classes for anaconda's storage configuration module.
#
# Copyright (C) 2020  Red Hat, Inc.
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
# Red Hat Author(s): Vojtech Trefny <vtrefny@redhat.com>
#

from ..storage_log import log_method_call
from ..i18n import N_
from ..size import Size
from . import DeviceFormat, register_device_format

import logging
log = logging.getLogger("blivet")


class StratisBlockdev(DeviceFormat):
    """ A Stratis block device """

    _type = "stratis"
    _name = N_("Stratis block device")
    _udev_types = ["stratis"]
    _formattable = False                 # can be formatted
    _supported = True                    # is supported
    _linux_native = True                 # for clearpart
    _min_size = Size("1 GiB")
    _packages = ["stratisd"]             # required packages
    _resizable = False

    def __init__(self, **kwargs):
        """
            :keyword device: path to the block device node
            :keyword uuid: this Stratis block device UUID (not the pool UUID)
            :keyword exists: indicates whether this is an existing format
            :type exists: bool
            :keyword pool_name: the name of the pool this block device belongs to
            :keyword pool_uuid: the UUID of the pool this block device belongs to

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        self.pool_name = kwargs.get("pool_name")
        self.pool_uuid = kwargs.get("pool_uuid")

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        s += ("  pool_name = %(pool_name)s  pool_uuid = %(pool_uuid)s" %
              {"pool_name": self.pool_name, "pool_uuid": self.pool_uuid})
        return s

    @property
    def dict(self):
        d = super(StratisBlockdev, self).dict
        d.update({"pool_name": self.pool_name, "pool_uuid": self.pool_uuid})
        return d


register_device_format(StratisBlockdev)
