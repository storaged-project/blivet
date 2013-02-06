#
# lvm.py
# lvm functions
#
# Copyright (C) 2009  Red Hat, Inc.  All rights reserved.
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
# Author(s): Dave Lehman <dlehman@redhat.com>
#

import os
import math
import re

import logging
log = logging.getLogger("blivet")

from .. import util
from .. import arch
from ..errors import *

import gettext
_ = lambda x: gettext.ldgettext("blivet", x)

MAX_LV_SLOTS = 256

# some of lvm's defaults that we have no way to ask it for
LVM_PE_START = 1.0      # MB
LVM_PE_SIZE = 4.0       # MB

def has_lvm():
    if util.find_program_in_path("lvm"):
        for line in open("/proc/devices").readlines():
            if "device-mapper" in line.split():
                return True

    return False

# Start config_args handling code
#
# Theoretically we can handle all that can be handled with the LVM --config
# argument.  For every time we call an lvm_cc (lvm compose config) funciton
# we regenerate the config_args with all global info.
config_args_data = { "filterRejects": [],    # regular expressions to reject.
                            "filterAccepts": [] }   # regexp to accept

def _getConfigArgs(**kwargs):
    """lvm command accepts lvm.conf type arguments preceded by --config. """
    global config_args_data
    config_args = []

    read_only_locking = kwargs.get("read_only_locking", False)

    filter_string = ""
    rejects = config_args_data["filterRejects"]
    for reject in rejects:
        filter_string += ("\"r|/%s$|\"," % reject)

    if filter_string:
        filter_string = " filter=[%s] " % filter_string.strip(",")

    # devices_string can have (inside the brackets) "dir", "scan",
    # "preferred_names", "filter", "cache_dir", "write_cache_state",
    # "types", "sysfs_scan", "md_component_detection".  see man lvm.conf.
    config_string = ""
    devices_string = " devices {%s} " % (filter_string) # strings can be added
    if filter_string:
        config_string += devices_string # more strings can be added.
    if read_only_locking:
        config_string += "global {locking_type=4} "
    if config_string:
        config_args = ["--config", config_string]
    return config_args

def lvm_cc_addFilterRejectRegexp(regexp):
    """ Add a regular expression to the --config string."""
    global config_args_data
    log.debug("lvm filter: adding %s to the reject list" % regexp)
    config_args_data["filterRejects"].append(regexp)

def lvm_cc_removeFilterRejectRegexp(regexp):
    """ Remove a regular expression from the --config string."""
    global config_args_data
    log.debug("lvm filter: removing %s from the reject list" % regexp)
    try:
        config_args_data["filterRejects"].remove(regexp)
    except ValueError:
        log.debug("%s wasn't in the reject list" % regexp)
        return

def lvm_cc_resetFilter():
    global config_args_data
    config_args_data["filterRejects"] = []
    config_args_data["filterAccepts"] = []
# End config_args handling code.

# Names that should not be used int the creation of VGs
lvm_vg_blacklist = []
def blacklistVG(name):
    global lvm_vg_blacklist
    lvm_vg_blacklist.append(name)

def getPossiblePhysicalExtents(floor=0):
    """Returns a list of integers representing the possible values for
       the physical extent of a volume group.  Value is in KB.

       floor - size (in KB) of smallest PE we care about.
    """

    possiblePE = []
    curpe = 8
    while curpe <= 16384*1024:
	if curpe >= floor:
	    possiblePE.append(curpe)
	curpe = curpe * 2

    return possiblePE

def getMaxLVSize():
    """ Return the maximum size (in MB) of a logical volume. """
    if arch.getArch() in ("x86_64", "ppc64", "alpha", "ia64", "s390", "sparc"): #64bit architectures
        return (8*1024*1024*1024*1024) #Max is 8EiB (very large number..)
    else:
        return (16*1024*1024) #Max is 16TiB

def clampSize(size, pesize, roundup=None):
    if roundup:
        round = math.ceil
    else:
        round = math.floor

    return long(round(float(size)/float(pesize)) * pesize)

def get_pv_space(size, disks, pesize=LVM_PE_SIZE,
                 striped=False, mirrored=False):
    """ Given specs for an LV, return total PV space required. """
    # XXX default extent size should be something we can ask of lvm
    # TODO: handle striped and mirrored
    # this is adding one extent for the lv's metadata
    space = clampSize(size, pesize, roundup=True) + \
            pesize
    return space

def lvm(args):
    ret = util.run_program(["lvm"] + args)
    if ret:
        raise LVMError("running lvm " + " ".join(args) + " failed")

def pvcreate(device):
    # we force dataalignment=1024k since we cannot get lvm to tell us what
    # the pe_start will be in advance
    args = ["pvcreate"] + \
            _getConfigArgs() + \
            ["--dataalignment", "1024k"] + \
            [device]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvcreate failed for %s: %s" % (device, msg))

def pvresize(device, size):
    args = ["pvresize"] + \
            ["--setphysicalvolumesize", ("%dm" % size)] + \
            _getConfigArgs() + \
            [device]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvresize failed for %s: %s" % (device, msg))

def pvremove(device):
    args = ["pvremove", "--force", "--force", "--yes"] + \
            _getConfigArgs() + \
            [device]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("pvremove failed for %s: %s" % (device, msg))

def pvinfo(device):
    """
        If the PV was created with '--metadacopies 0', lvm will do some
        scanning of devices to determine from their metadata which VG
        this PV belongs to.

        pvs -o pv_name,pv_mda_count,vg_name,vg_uuid --config \
            'devices { scan = "/dev" filter = ["a/loop0/", "r/.*/"] }'
    """
    args = ["pvs",
            "--unit=k", "--nosuffix", "--nameprefixes", "--rows",
            "--unquoted", "--noheadings",
            "-opv_uuid,pe_start,vg_name,vg_uuid,vg_size,vg_free,vg_extent_size,vg_extent_count,vg_free_count,pv_count"] + \
            _getConfigArgs(read_only_locking=True) + \
            [device]

    rc = util.capture_output(["lvm"] + args)
    _vars = rc.split()
    info = {}
    for var in _vars:
        (name, equals, value) = var.partition("=")
        if not equals:
            continue

        if "," in value:
            val = value.strip().split(",")
        else:
            val = value.strip()

        info[name] = val

    return info

def vgcreate(vg_name, pv_list, pe_size):
    argv = ["vgcreate"]
    if pe_size:
        argv.extend(["-s", "%dm" % pe_size])
    argv.extend(_getConfigArgs())
    argv.append(vg_name)
    argv.extend(pv_list)

    try:
        lvm(argv)
    except LVMError as msg:
        raise LVMError("vgcreate failed for %s: %s" % (vg_name, msg))

def vgremove(vg_name):
    args = ["vgremove", "--force"] + \
            _getConfigArgs() +\
            [vg_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgremove failed for %s: %s" % (vg_name, msg))

def vgactivate(vg_name):
    args = ["vgchange", "-a", "y"] + \
            _getConfigArgs() + \
            [vg_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgactivate failed for %s: %s" % (vg_name, msg))

def vgdeactivate(vg_name):
    args = ["vgchange", "-a", "n"] + \
            _getConfigArgs() + \
            [vg_name]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgdeactivate failed for %s: %s" % (vg_name, msg))

def vgreduce(vg_name, pv_list, rm=False):
    """ Reduce a VG.

    rm -> with RemoveMissing option.
    Use pv_list when rm=False, otherwise ignore pv_list and call vgreduce with
    the --removemissing option.
    """
    args = ["vgreduce"]
    args.extend(_getConfigArgs())
    if rm:
        args.extend(["--removemissing", "--force", vg_name])
    else:
        args.extend([vg_name] + pv_list)

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("vgreduce failed for %s: %s" % (vg_name, msg))

def vginfo(vg_name):
    args = ["vgs", "--noheadings", "--nosuffix"] + \
            ["--units", "m"] + \
            ["-o", "uuid,size,free,extent_size,extent_count,free_count,pv_count"] + \
            _getConfigArgs(read_only_locking=True) + \
            [vg_name]

    buf = util.capture_output(["lvm"] + args)
    info = buf.split()
    if len(info) != 7:
        raise LVMError(_("vginfo failed for %s" % vg_name))

    return info

def lvs(vg_name):
    args = ["lvs",
            "--unit", "m", "--nosuffix", "--nameprefixes", "--rows",
            "--unquoted", "--noheadings",
            "-olv_name,lv_uuid,lv_size,lv_attr"] + \
            _getConfigArgs(read_only_locking=True) + \
            [vg_name]

    rc = util.capture_output(["lvm"] + args)
    _vars = rc.split()
    info = {}
    for var in _vars:
        (name, equals, value) = var.partition("=")
        if not equals:
            continue

        val = value.strip()

        if name not in info:
            info[name] = []

        info[name].append(val)

    return info

def lvorigin(vg_name, lv_name):
    args = ["lvs", "--noheadings", "-o", "origin"] + \
            _getConfigArgs(read_only_locking=True) + \
            ["%s/%s" % (vg_name, lv_name)]

    buf = util.capture_output(["lvm"] + args)

    try:
        origin = buf.splitlines()[0].strip()
    except IndexError:
        origin = ''

    return origin

def lvcreate(vg_name, lv_name, size, pvs=[]):
    args = ["lvcreate"] + \
            ["-L", "%dm" % size] + \
            ["-n", lv_name] + \
            _getConfigArgs() + \
            [vg_name] + pvs

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvcreate failed for %s/%s: %s" % (vg_name, lv_name, msg))

def lvremove(vg_name, lv_name):
    args = ["lvremove"] + \
            _getConfigArgs() + \
            ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvremove failed for %s: %s" % (lv_name, msg))

def lvresize(vg_name, lv_name, size):
    args = ["lvresize"] + \
            ["--force", "-L", "%dm" % size] + \
            _getConfigArgs() + \
            ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvresize failed for %s: %s" % (lv_name, msg))

def lvactivate(vg_name, lv_name):
    # see if lvchange accepts paths of the form 'mapper/$vg-$lv'
    args = ["lvchange", "-a", "y"] + \
            _getConfigArgs() + \
            ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvactivate failed for %s: %s" % (lv_name, msg))

def lvdeactivate(vg_name, lv_name):
    args = ["lvchange", "-a", "n"] + \
            _getConfigArgs() + \
            ["%s/%s" % (vg_name, lv_name)]

    try:
        lvm(args)
    except LVMError as msg:
        raise LVMError("lvdeactivate failed for %s: %s" % (lv_name, msg))

