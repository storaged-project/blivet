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
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")


class LVsInfo(object):
    """ Class to be used as a singleton.
        Maintains the LVs cache.
    """

    def __init__(self):
        self._lvs_cache = None

    @property
    def cache(self):
        if self._lvs_cache is None:
            try:
                lvs = blockdev.lvm.lvs()
            except NotImplementedError:
                log.error("libblockdev lvm plugin is missing")
                self._lvs_cache = dict()
                return self._lvs_cache

            self._lvs_cache = dict(("%s-%s" % (lv.vg_name, lv.lv_name), lv) for lv in lvs)

        return self._lvs_cache

    def drop_cache(self):
        self._lvs_cache = None


lvs_info = LVsInfo()


class PVsInfo(object):
    """ Class to be used as a singleton.
        Maintains the PVs cache.
    """

    def __init__(self):
        self._pvs_cache = None

    @property
    def cache(self):
        if self._pvs_cache is None:
            self._pvs_cache = dict()

            try:
                pvs = blockdev.lvm.pvs()
            except NotImplementedError:
                log.error("libblockdev lvm plugin is missing")
                return self._pvs_cache

            for pv in pvs:
                self._pvs_cache[pv.pv_name] = pv
                # TODO: add get_all_device_symlinks() and resolve_device_symlink() functions to
                #       libblockdev and use them here
                if pv.pv_name.startswith("/dev/md/"):
                    try:
                        md_node = blockdev.md.node_from_name(pv.pv_name[len("/dev/md/"):])
                        self._pvs_cache["/dev/" + md_node] = pv
                    except blockdev.MDRaidError:
                        pass
                elif pv.pv_name.startswith("/dev/md"):
                    try:
                        md_named_dev = blockdev.md.name_from_node(pv.pv_name[len("/dev/"):])
                        self._pvs_cache["/dev/md/" + md_named_dev] = pv
                    except blockdev.MDRaidError:
                        pass

        return self._pvs_cache

    def drop_cache(self):
        self._pvs_cache = None


pvs_info = PVsInfo()


class VGsInfo(object):
    """ Class to be used as a singleton.
        Maintains the VGs cache.
    """

    def __init__(self):
        self._vgs_cache = None

    @property
    def cache(self):
        if self._vgs_cache is None:
            try:
                vgs = blockdev.lvm.vgs()
            except NotImplementedError:
                log.error("libblockdev lvm plugin is missing")
                self._vgs_cache = dict()
                return self._vgs_cache

            self._vgs_cache = dict(("%s" % (vg.uuid), vg) for vg in vgs)

        return self._vgs_cache

    def drop_cache(self):
        self._vgs_cache = None


vgs_info = VGsInfo()
