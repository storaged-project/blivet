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

import libmount
import functools

from . import util

import logging
log = logging.getLogger("blivet")


MOUNT_FILE = "/proc/self/mountinfo"


class MountsCache(object):

    """ Cache object for system mountpoints; checks
        /proc/self/mountinfo for up-to-date information.
    """

    def __init__(self):
        self.mounts_hash = 0
        self.mountpoints = None

    def get_mountpoints(self, devspec, subvolspec=None):
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
        self._cache_check()

        mountpoints = []

        if subvolspec is not None:
            subvolspec = str(subvolspec)

        # devspec might be a '/dev/dm-X' path but /proc/self/mountinfo always
        # contains the '/dev/mapper/...' path -- find_source is able to resolve
        # both paths but returns only one mountpoint -- it is neccesary to check
        # for all possible mountpoints using new/resolved path (devspec)
        try:
            fs = self.mountpoints.find_source(devspec)
        except Exception:  # pylint: disable=broad-except
            return mountpoints
        else:
            devspec = fs.source

        # iterate over all lines in the table to find all matching mountpoints
        for fs in iter(functools.partial(self.mountpoints.next_fs), None):
            if subvolspec:
                if fs.fstype != "btrfs":
                    continue
                if fs.source == devspec and (fs.match_options("subvolid=%s" % subvolspec) or
                                             fs.match_options("subvol=/%s" % subvolspec)):
                    mountpoints.append(fs.target)
            else:
                if fs.source == devspec:
                    mountpoints.append(fs.target)

        return mountpoints

    def is_mountpoint(self, path):
        """ Check to see if a path is already mounted

            :param str path: Path to check
        """
        self._cache_check()

        try:
            self.mountpoints.find_source(path)
        except Exception:  # pylint: disable=broad-except
            return False
        else:
            return True

    def _cache_check(self):
        """ Computes the MD5 hash on /proc/self/mountinfo and updates the cache on change
        """

        md5hash = util.md5_file(MOUNT_FILE)

        if md5hash != self.mounts_hash:
            self.mounts_hash = md5hash
            self.mountpoints = libmount.Table(MOUNT_FILE)

mounts_cache = MountsCache()
