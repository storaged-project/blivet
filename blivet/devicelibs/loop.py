#
# loop.py
# loop device functions
#
# Copyright (C) 2010  Red Hat, Inc.  All rights reserved.
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
# Author(s): David Lehman <dlehman@redhat.com>
#

import os

from .. import util
from ..errors import DeviceError, LoopError

import logging
log = logging.getLogger("blivet")


def losetup(args, capture=False):
    if capture:
        exec_func = util.capture_output
    else:
        exec_func = util.run_program

    try:
        # ask losetup what this loop device's backing device is
        ret = exec_func(["losetup"] + args)
    except OSError as e:
        raise LoopError(e.strerror)

    return ret

def get_backing_file(name):
    path = ""
    sys_path  = "/sys/class/block/%s/loop/backing_file" % name
    if os.access(sys_path, os.R_OK):
        path = open(sys_path).read().strip()

    return path

def get_loop_name(path):
    args = ["-j", path]
    buf = losetup(args, capture=True)

    entries = buf.splitlines()
    if not entries:
        return ""

    first_entry = entries[0]
    if len(entries) > 1:
        # If there are multiple loop devices use the first one
        log.warning("multiple loops associated with %s. Using %s", path, first_entry)

    name = os.path.basename(first_entry.split(":")[0])
    return name

def loop_setup(path):
    args = ["-f", path]
    msg = None
    try:
        msg = losetup(args)
    except LoopError as e:
        msg = str(e)

    if msg:
        raise LoopError("failed to set up loop for %s: %s" % (path, msg))

def loop_teardown(path):
    args = ["-d", path]
    msg = None
    try:
        msg = losetup(args)
    except LoopError as e:
        msg = str(e)

    if msg:
        raise DeviceError("failed to tear down loop %s: %s" % (path, msg))


