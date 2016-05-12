# volume_info.py
# Backend code for populating a DeviceTree.
#
# Copyright (C) 2009-2016  Red Hat, Inc.
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
# Red Hat Author(s): Jan Pokorny <japokorn@redhat.com>
#

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")


class LVsInfo(object):
    """ Class to be used as a singleton.
        Maintains the LVs cache.
    """

    @property
    def cache(self):
        if self._lvs_cache is None:
            lvs = blockdev.lvm.lvs()
            self._lvs_cache = dict(("%s-%s" % (lv.vg_name, lv.lv_name), lv) for lv in lvs)  # pylint: disable=attribute-defined-outside-init

        return self._lvs_cache

    def drop_cache(self):
        self._lvs_cache = None  # pylint: disable=attribute-defined-outside-init

lvs_info = LVsInfo()


class PVsInfo(object):
    """ Class to be used as a singleton.
        Maintains the PVs cache.
    """

    @property
    def cache(self):
        if self._pvs_cache is None:
            pvs = blockdev.lvm.pvs()
            self._pvs_cache = dict((pv.pv_name, pv) for pv in pvs)  # pylint: disable=attribute-defined-outside-init

        return self._pvs_cache

    def drop_cache(self):
        self._pvs_cache = None  # pylint: disable=attribute-defined-outside-init

pvs_info = PVsInfo()
