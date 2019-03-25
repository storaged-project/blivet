# devices/optical.py
#
# Copyright (C) 2009-2014  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

import os

from .. import errors
from .. import util
from ..storage_log import log_method_call

import logging
log = logging.getLogger("blivet")

from .storage import StorageDevice


class OpticalDevice(StorageDevice):

    """ An optical drive, eg: cdrom, dvd+r, &c.

        XXX Is this useful?
    """
    _type = "cdrom"

    def __init__(self, name, major=None, minor=None, exists=False,
                 fmt=None, parents=None, sysfs_path='', vendor="",
                 model=""):
        StorageDevice.__init__(self, name, fmt=fmt,
                               major=major, minor=minor, exists=True,
                               parents=parents, sysfs_path=sysfs_path,
                               vendor=vendor, model=model)

    @property
    def media_present(self):
        """ Return a boolean indicating whether or not the device contains
            media.
        """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        try:
            fd = os.open(self.path, os.O_RDONLY)
        except OSError as e:
            # errno 123 = No medium found
            if e.errno == 123:
                return False
            else:
                return True
        else:
            os.close(fd)
            return True

    def eject(self):
        """ Eject the drawer. """
        log_method_call(self, self.name, status=self.status)
        if not self.exists:
            raise errors.DeviceError("device has not been created", self.name)

        # try to umount and close device before ejecting
        self.teardown()

        try:
            util.run_program(["eject", self.name])
        except OSError as e:
            log.warning("error ejecting cdrom %s: %s", self.name, e)
