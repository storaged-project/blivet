#
# nvme.py - NVMe class
#
# Copyright (C) 2022  Red Hat, Inc.  All rights reserved.
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

import os
import glob

from . import errors

import gi
gi.require_version("BlockDev", "3.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")

ETC_NVME_PATH = "/etc/nvme/"
HOSTNQN_FILE = ETC_NVME_PATH + "hostnqn"
HOSTID_FILE = ETC_NVME_PATH + "hostid"


class NVMe(object):
    """ NVMe utility class.

        .. warning::
            Since this is a singleton class, calling deepcopy() on the instance
            just returns ``self`` with no copy being created.
    """

    def __init__(self):
        self.started = False
        self._hostnqn = None
        self._hostid = None

    # So that users can write nvme() to get the singleton instance
    def __call__(self):
        return self

    def __deepcopy__(self, memo_dict):  # pylint: disable=unused-argument
        return self

    def _retrieve_fabrics_hostnqn(self):
        for d in glob.glob('/sys/class/nvme-fabrics/ctl/nvme*/'):
            try:
                # invalidate old values
                self._hostnqn = None
                self._hostid = None
                # read from sysfs
                with open(os.path.join(d, 'hostnqn')) as f:
                    self._hostnqn = f.readline().strip()
                with open(os.path.join(d, 'hostid')) as f:
                    self._hostid = f.readline().strip()
                if self._hostnqn:
                    break
            except Exception:  # pylint: disable=broad-except
                pass

    def available(self):
        if not hasattr(blockdev.Plugin, "NVME"):
            return False
        if not hasattr(blockdev.NVMETech, "FABRICS"):
            return False
        try:
            blockdev.nvme.is_tech_avail(blockdev.NVMETech.FABRICS, 0)  # pylint: disable=no-member
        except (blockdev.BlockDevNotImplementedError, blockdev.NVMEError):
            return False
        return True

    def startup(self):
        if self.started:
            return

        if not self.available():
            log.info("NVMe support not available, not starting")
            return

        self._hostnqn = blockdev.nvme_get_host_nqn()
        self._hostid = blockdev.nvme_get_host_id()
        if not self._hostnqn:
            # see if there are any active fabrics connections and take their values over
            self._retrieve_fabrics_hostnqn()
        if not self._hostnqn:
            # generate new values
            self._hostnqn = blockdev.nvme_generate_host_nqn()
        if not self._hostnqn:
            raise errors.NVMeError("Failed to generate HostNQN")
        if not self._hostid:
            if 'uuid:' not in self._hostnqn:
                raise errors.NVMeError("Missing UUID part in the HostNQN string '%s'" % self._hostnqn)
            # derive HostID from HostNQN's UUID part
            self._hostid = self._hostnqn.split('uuid:')[1]

        # do not overwrite existing files, taken e.g. from initramfs
        self.write("/", overwrite=False)

        self.started = True

    def write(self, root, overwrite=True):  # pylint: disable=unused-argument
        if not self.available():
            return

        # write down the hostnqn and hostid files
        p = root + ETC_NVME_PATH
        if not os.path.isdir(p):
            os.makedirs(p, 0o755)
        p = root + HOSTNQN_FILE
        if overwrite or not os.path.isfile(p):
            with open(p, "w") as f:
                f.write(self._hostnqn)
                f.write("\n")
        p = root + HOSTID_FILE
        if overwrite or not os.path.isfile(p):
            with open(p, "w") as f:
                f.write(self._hostid)
                f.write("\n")


# Create nvme singleton
nvme = NVMe()
""" An instance of :class:`NVMe` """
