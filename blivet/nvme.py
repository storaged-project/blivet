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
import shutil

from . import errors
from . import util

import logging
log = logging.getLogger("blivet")

HOSTNQN_FILE = "/etc/nvme/hostnqn"
HOSTID_FILE = "/etc/nvme/hostid"


class NVMe(object):
    """ NVMe utility class.

        .. warning::
            Since this is a singleton class, calling deepcopy() on the instance
            just returns ``self`` with no copy being created.
    """

    def __init__(self):
        self.started = False

    # So that users can write nvme() to get the singleton instance
    def __call__(self):
        return self

    def __deepcopy__(self, memo_dict):  # pylint: disable=unused-argument
        return self

    def startup(self):
        if self.started:
            return

        rc, nqn = util.run_program_and_capture_output(["nvme", "gen-hostnqn"])
        if rc != 0:
            raise errors.NVMeError("Failed to generate hostnqn")

        with open(HOSTNQN_FILE, "w") as f:
            f.write(nqn)

        rc, hid = util.run_program_and_capture_output(["dmidecode", "-s", "system-uuid"])
        if rc != 0:
            raise errors.NVMeError("Failed to generate host ID")

        with open(HOSTID_FILE, "w") as f:
            f.write(hid)

        self.started = True

    def write(self, root):  # pylint: disable=unused-argument
        # copy the hostnqn and hostid files
        if not os.path.isdir(root + "/etc/nvme"):
            os.makedirs(root + "/etc/nvme", 0o755)
        shutil.copyfile(HOSTNQN_FILE, root + HOSTNQN_FILE)
        shutil.copyfile(HOSTID_FILE, root + HOSTID_FILE)


# Create nvme singleton
nvme = NVMe()
""" An instance of :class:`NVMe` """
