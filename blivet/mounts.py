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

from . import util

import logging
log = logging.getLogger("blivet")

class MountsCache(object):

    def __init__(self):
        self.mountsHash = 0
        self.mountpoints = {}

        # new device manually added to cache since last check
        self.newDevice = False

    def add(self, devspec, subvolspec=None):
        """ Add device to cache

            :param devscpec: device specification, eg. "/dev/vda1"
            :type devspec: str
            :param subvolspec: btrfs subvolume specification, eg. ID or name
            :type subvolspec: str

        """

        self.mountpoints[(devspec, subvolspec)] = None
        self.newDevice = True

    def remove(self, devspec, subvolspec=None):
        """ Remove device from cache

            :param devscpec: device specification, eg. "/dev/vda1"
            :type devspec: str
            :param subvolspec: btrfs subvolume specification, eg. ID or name
            :type subvolspec: str

        """

        if (devspec, subvolspec) in self.mountpoints:
            del self.mountpoints[(devspec, subvolspec)]

    def clear(self):
        """ Clear cache
        """

        for key in self.mountpoints.keys():
            self.mountpoints[key] = None

        self._getActiveMounts()

    def getMountpoint(self, devspec, subvolspec=None):
        """ Get mountpoint for selected device

            :param devscpec: device specification, eg. "/dev/vda1"
            :type devspec: str
            :param subvolspec: btrfs subvolume specification, eg. ID or name
            :type subvolspec: str
            :returns: mountpoint (path)
            :rtype: str

        """

        self._cacheCheck()

        if (devspec, subvolspec) not in self.mountpoints.keys():
            return None

        else:
            return self.mountpoints[(devspec, subvolspec)]

    def _getActiveMounts(self):

        for line in open("/proc/mounts").readlines():
            try:
                (devspec, mountpoint, fstype, options, _rest) = line.split(None, 4)
            except ValueError:
                log.error("failed to parse /proc/mounts line: %s", line)
                continue

            if fstype == "btrfs":
                # get the subvol name from /proc/self/mountinfo
                for line in open("/proc/self/mountinfo").readlines():
                    fields = line.split()
                    _subvol = fields[3]
                    _mountpoint = fields[4]
                    _devspec = fields[9]
                    if _mountpoint == mountpoint and _devspec == devspec:
                        # empty _subvol[1:] means it is a top-level volume
                        subvolspec = _subvol[1:] or 5

                        fmt = self._resolveFormat(devspec, subvolspec)

            else:
                fmt = self._resolveFormat(devspec)

            if fmt:
                self.mountpoints[fmt] = mountpoint

    def _resolveFormat(self, devspec, subvolspec=None):

        for fmt in self.mountpoints.keys():
            if fmt[0] == devspec:
                if not fmt[1]:
                    return fmt

                elif fmt[1] == subvolspec:
                    return fmt

    def _cacheCheck(self):

        md5hash = util.md5_file("/proc/mounts")

        if md5hash != self.mountsHash or self.newDevice:
            self.newDevice = False
            self.mountsHash = md5hash
            self.clear()
