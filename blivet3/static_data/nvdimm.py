#
# nvdimm.py - nvdimm class
#
# Copyright (C) 2018  Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import gi
gi.require_version("BlockDev", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import BlockDev
from gi.repository import GLib

from .. import util

import logging
log = logging.getLogger("blivet")


class NVDIMMDependencyGuard(util.DependencyGuard):
    error_msg = "libblockdev NVDIMM functionality not available"

    def _check_avail(self):
        try:
            BlockDev.nvdimm_is_tech_avail(BlockDev.NVDIMMTech.NVDIMM_TECH_NAMESPACE,
                                          BlockDev.NVDIMMTechMode.RECONFIGURE |
                                          BlockDev.NVDIMMTechMode.QUERY |
                                          BlockDev.NVDIMMTechMode.ACTIVATE_DEACTIVATE)
        except GLib.GError:
            return False
        return True


blockdev_nvdimm_required = NVDIMMDependencyGuard()


class NVDIMM(object):
    """ NVDIMM utility class.

        .. warning::
            Since this is a singleton class, calling deepcopy() on the instance
            just returns ``self`` with no copy being created.
    """

    def __init__(self):
        self._namespaces = None

    # So that users can write nvdimm() to get the singleton instance
    def __call__(self):
        return self

    def __deepcopy__(self, memo_dict):
        # pylint: disable=unused-argument
        return self

    @property
    def namespaces(self):
        """ Dict of all NVDIMM namespaces, including dax and disabled namespaces
        """
        if not self._namespaces:
            self.update_namespaces_info()

        return self._namespaces

    @blockdev_nvdimm_required(critical=True, eval_mode=util.EvalMode.onetime)
    def update_namespaces_info(self):
        """ Update information about the namespaces
        """
        namespaces = BlockDev.nvdimm_list_namespaces(idle=True)

        self._namespaces = dict((namespace.dev, namespace) for namespace in namespaces)

    def get_namespace_info(self, device):
        """ Get namespace information for a device
            :param str device: device name (e.g. 'pmem0') or path
        """
        for info in self.namespaces.values():
            if info.blockdev == device or \
               (device.startswith("/dev/") and info.blockdev == device[5:]):
                return info

    @blockdev_nvdimm_required(critical=True, eval_mode=util.EvalMode.onetime)
    def enable_namespace(self, namespace):
        """ Enable a namespace
            :param str namespace: devname of the namespace (e.g. 'namespace0.0')
        """

        if namespace not in self.namespaces.keys():
            raise ValueError("Namespace '%s' doesn't exist." % namespace)

        BlockDev.nvdimm_namespace_enable(namespace)

        # and update our namespaces info "cache"
        self.update_namespaces_info()

    @blockdev_nvdimm_required(critical=True, eval_mode=util.EvalMode.onetime)
    def reconfigure_namespace(self, namespace, mode, **kwargs):
        """ Change mode of the namespace
            :param str namespace: devname of the namespace (e.g. 'namespace0.0')
            :param str mode: new mode of the namespace (one of 'sector', 'memory', 'dax')
            :keyword int sector_size: sector size when reconfiguring to the 'sector' mode
            :keyword str map_location: map location when reconfiguring to the 'memory'
                                       mode (one of 'mem', 'dev')

            .. note::
                This doesn't change state of the devicetree. It is necessary to
                run reset() or populate() to make these changes visible.
        """

        if namespace not in self.namespaces.keys():
            raise ValueError("Namespace '%s' doesn't exist." % namespace)

        info = self.namespaces[namespace]

        sector_size = kwargs.get("sector_size", None)
        map_location = kwargs.get("map_location", None)

        if sector_size and mode != "sector":
            raise ValueError("Sector size cannot be set for selected mode '%s'." % mode)

        if map_location and mode != "memory":
            raise ValueError("Map location cannot be set for selected mode '%s'." % mode)

        mode_t = BlockDev.nvdimm_namespace_get_mode_from_str(mode)

        if sector_size:
            extra = {"-l": str(sector_size)}
        elif map_location:
            extra = {"-M": map_location}
        else:
            extra = None

        BlockDev.nvdimm_namespace_reconfigure(namespace, mode_t, info.enabled, extra)

        # and update our namespaces info "cache"
        self.update_namespaces_info()


# Create nvdimm singleton
nvdimm = NVDIMM()
""" An instance of :class:`NVDIMM` """
