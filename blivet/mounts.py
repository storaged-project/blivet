# mounts.py
# Active mountpoints cache.
#
# Copyright (C) 2015  Red Hat, Inc.
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
from collections import defaultdict
from . import util
from .devicelibs import btrfs

import logging
log = logging.getLogger("blivet")

class MountsCache(object):
    """ Cache object for system mountpoints; checks /proc/mounts and
        /proc/self/mountinfo for up-to-date information.
    """

    def __init__(self):
        self.mountsHash = 0
        self.mountpoints = defaultdict(list)

    def getMountpoints(self, devspec, subvolspec=None):
        """ Get mountpoints for selected device

            :param devscpec: device specification, eg. "/dev/vda1"
            :type devspec: str
            :param subvolspec: btrfs subvolume specification, eg. ID or name
            :type subvolspec: object (may be NoneType)
            :returns: list of mountpoints (path)
            :rtype: list of str or empty list

            .. note::
                Devices can be mounted on multiple paths, and paths can have multiple
                devices mounted to them (hiding previous mounts). Callers should take this into account.
        """
        self._cacheCheck()

        if subvolspec is not None:
            subvolspec = str(subvolspec)

        return self.mountpoints[(devspec, subvolspec)]

    def isMountpoint(self, path):
        """ Check to see if a path is already mounted

            :param str path: Path to check
        """
        self._cacheCheck()

        return any(path in p for p in self.mountpoints.values())

    def _getSubvolSpec(self, devspec, mountpoint):
        """ Get the subvolume specification for this btrfs volume.

            :param str devspec: the device specification
            :param str mountpoint: the mountpoint

            :returns: the subvolume specification, 5 for a top-level volume
            :rtype: str or NoneType
        """
        for line in open("/proc/self/mountinfo").readlines():
            fields = line.split()
            if fields[4] == mountpoint and fields[9] == devspec:
                # empty _subvol[1:] means it is a top-level volume
                subvolspec = fields[3]
                return subvolspec[1:] or str(btrfs.MAIN_VOLUME_ID)
        return None

    def _getActiveMounts(self):
        """ Get information about mounted devices from /proc/mounts and
            /proc/self/mountinfo

            Refreshes self.mountpoints with current moutpoint information
        """
        self.mountpoints = defaultdict(list)
        for line in open("/proc/mounts").readlines():
            try:
                (devspec, mountpoint, fstype, _rest) = line.split(None, 3)
            except ValueError:
                log.error("failed to parse /proc/mounts line: %s", line)
                continue

            if fstype == "btrfs":
                subvolspec = self._getSubvolSpec(devspec, mountpoint)
                if subvolspec is not None:
                    self.mountpoints[(devspec, subvolspec)].append(mountpoint)
                else:
                    log.error("failed to obtain subvolspec for btrfs device %s", devspec)
            else:
                self.mountpoints[(devspec, None)].append(mountpoint)

    def _cacheCheck(self):
        """ Computes the MD5 hash on /proc/mounts and updates the cache on change
        """

        md5hash = util.md5_file("/proc/mounts")

        if md5hash != self.mountsHash:
            self.mountsHash = md5hash
            self._getActiveMounts()

mountsCache = MountsCache()
