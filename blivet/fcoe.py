#
# fcoe.py - fcoe class
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

import os
from . import udev
from . import util
#from pyanaconda import isys
import logging
import time
import shutil
from .i18n import _
log = logging.getLogger("blivet")

_fcoe_module_loaded = False

def has_fcoe():
    global _fcoe_module_loaded
    if not _fcoe_module_loaded:
        util.run_program(["modprobe", "fcoe"])
        _fcoe_module_loaded = True
        if "bnx2x" in util.lsmod():
            log.info("fcoe: loading bnx2fc")
            util.run_program(["modprobe", "bnx2fc"])

    return os.access("/sys/module/fcoe", os.X_OK)

class fcoe(object):
    """ FCoE utility class.

        This class will automatically discover and connect to EDD configured
        FCoE SAN's when the startup() method gets called. It can also be
        used to manually configure FCoE SAN's through the addSan() method.

        As this class needs to make sure certain things like starting fcoe
        daemons and connecting to firmware discovered SAN's only happens once
        and as it keeps a global list of all FCoE devices it is
        implemented as a Singleton.
    """

    def __init__(self):
        self.started = False
        self.lldpadStarted = False
        self.nics = []
        self.added_nics = []

    # So that users can write fcoe() to get the singleton instance
    def __call__(self):
        return self

    def _stabilize(self):
        # I have no clue how long we need to wait, this ought to do the trick
        time.sleep(10)
        udev.settle()

    def _startEDD(self):
        try:
            buf = util.capture_output(["/usr/libexec/fcoe/fcoe_edd.sh", "-i"])
        except OSError as e:
            log.info("Failed to read FCoE EDD info: %s", e.strerror)
            return

        (key, _equals, val) = buf.strip().partition("=")
        if not val or key != "NIC":
            log.info("No FCoE EDD info found: %s", buf.rstrip())
            return

        log.info("FCoE NIC found in EDD: %s", val)
        self.addSan(val, dcb=True, auto_vlan=True)

    def startup(self):
        if self.started:
            return

        if not has_fcoe():
            return

        self._startEDD()
        self.started = True

    def _startLldpad(self):
        if self.lldpadStarted:
            return

        util.run_program(["systemctl", "start", "lldpad.service"])
        self.lldpadStarted = True

    def addSan(self, nic, dcb=False, auto_vlan=True):
        """Activates FCoE SANs attached to interface specified by nic.

           Returns error message, or empty string if succeeded.
        """
        if not has_fcoe():
            raise IOError(_("FCoE not available"))

        log.info("Activating FCoE SAN attached to %s, dcb: %s autovlan: %s",
                 nic, dcb, auto_vlan)

        rc = 0
        out = ""
        timeout = 60
        error_msg = ""
        if dcb:

            self._startLldpad()

            timeout_msg = "waiting for lldpad to be ready"
            while timeout > 0:
                rc, out = util.run_program_and_capture_output(
                    ["lldptool", "-p"])
                if rc == 0:
                    break
                timeout -= 1
                time.sleep(1)

            timeout_msg = "retrying to turn dcb on"
            while timeout > 0:
                rc, out = util.run_program_and_capture_output(
                    ["dcbtool", "sc", nic, "dcb", "on"])
                if rc == 0:
                    break
                timeout -= 1
                time.sleep(1)

            timeout_msg = "retrying to set up dcb with pfc"
            while timeout > 0:
                rc, out = util.run_program_and_capture_output(
                    ["dcbtool", "sc", nic, "pfc", "e:1", "a:1", "w:1"])
                if rc == 0:
                    break
                timeout -= 1
                time.sleep(1)

            timeout_msg = "retrying to set up dcb for fcoe"
            while timeout > 0:
                rc, out = util.run_program_and_capture_output(
                    ["dcbtool", "sc", nic, "app:fcoe", "e:1", "a:1", "w:1"])
                if rc == 0:
                    break
                timeout -= 1
                time.sleep(1)

            time.sleep(1)

            if rc == 0:
                self.write_nic_fcoe_cfg(nic, dcb=dcb, auto_vlan=auto_vlan)
                rc, out = util.run_program_and_capture_output(
                    ["systemctl", "restart", "fcoe.service"])
            else:
                log.info("Timed out when %s", timeout_msg)

        else:
            dpath = os.readlink("/sys/class/net/%s/device/driver" % nic)
            driver = os.path.basename(dpath)
            if driver == "bnx2x":
                util.run_program(["ip", "link", "set", nic, "up"])
                util.run_program(["modprobe", "8021q"])
                udev.settle()
                # Sleep for 3 s to allow dcb negotiation (#813057)
                time.sleep(3)
                rc, out = util.run_program_and_capture_output(
                    ["fipvlan", '-c', '-s', '-f', 'fcoe', nic])
            else:
                self.write_nic_fcoe_cfg(nic, dcb=dcb, auto_vlan=auto_vlan)
                rc, out = util.run_program_and_capture_output(
                    ["systemctl", "restart", "fcoe.service"])

        if rc == 0:
            self._stabilize()
            self.nics.append((nic, dcb, auto_vlan))
        else:
            log.debug("Activating FCoE SAN failed: %s %s", rc, out)
            error_msg = out

        return error_msg

    def write(self, root):
        if not self.nics:
            return

        # Done before packages are installed so don't call
        # write_nic_fcoe_cfg in target root but just copy the cfgs
        shutil.copytree("/etc/fcoe", root + "/etc/fcoe")

    def write_nic_fcoe_cfg(self, nic, dcb=True, auto_vlan=True, enable=True, mode=None, root=""):
        cfg_dir = root + "/etc/fcoe"
        example_cfg = os.path.join(cfg_dir, "cfg-ethx")
        if os.access(example_cfg, os.R_OK):
            lines = open(example_cfg, "r").readlines()
        else:
            anaconda_cfg = """FCOE_ENABLE="yes"\n
DCB_REQUIRED="yes"\n
AUTO_VLAN="yes"\n
MODE="fabric"\n
"""
            lines = anaconda_cfg.splitlines(True)

        new_cfg = open(os.path.join(cfg_dir, "cfg-%s" % nic), "w")
        new_cfg.write("# Generated by Anaconda installer\n")
        for line in lines:
            if not line.strip().startswith("#"):
                if line.startswith("FCOE_ENABLE"):
                    if enable:
                        line = 'FCOE_ENABLE="yes"'
                    else:
                        line = 'FCOE_ENABLE="no"'
                elif line.startswith("DCB_REQUIRED"):
                    if dcb:
                        line = 'DCB_REQUIRED="yes"'
                    else:
                        line = 'DCB_REQUIRED="no"'
                elif line.startswith("AUTO_VLAN"):
                    if auto_vlan:
                        line = 'AUTO_VLAN="yes"'
                    else:
                        line = 'AUTO_VLAN="no"'
                elif line.startswith("MODE"):
                    if mode:
                        line = 'MODE="%s"' % mode
            new_cfg.write(line)

# Create FCoE singleton
fcoe = fcoe()

# vim:tw=78:ts=4:et:sw=4
