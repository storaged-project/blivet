# flags.py
#
# Copyright (C) 2013  Red Hat, Inc.
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

import shlex
import selinux


class Flags(object):

    def __init__(self):
        #
        # mode of operation
        #
        self.testing = False
        self.debug = False

        #
        # minor modes
        #
        self.uevents = False

        #
        # enable/disable functionality
        #
        self.selinux = selinux.is_selinux_enabled()
        self.multipath = True
        self.dmraid = True
        self.ibft = True
        self.noiswmd = False

        self.gfs2 = True
        self.jfs = True
        self.reiserfs = True

        # for this flag to take effect,
        # blockdev.mpath.set_friendly_names(flags.multipath_friendly_names) must
        # be called prior to calling Blivet.reset() or DeviceTree.populate()
        self.multipath_friendly_names = True

        # set to False since automatic updates of a device's information
        # or state should not be necessary by default
        self.auto_dev_updates = False

        # set to False by default since a forced reset for file contexts
        # is ordinary not necessary
        self.selinux_reset_fcon = False

        # set to True since we want to keep these around by default
        self.keep_empty_ext_partitions = True

        # set to False to suppress the default LVM behavior of saving
        # backup metadata in /etc/lvm/{archive,backup}
        self.lvm_metadata_backup = True

        # whether to include nodev filesystems in the devicetree
        self.include_nodev = False

        # whether to enable discard for newly created devices
        # (so far only for LUKS)
        self.discard_new = False

        self.boot_cmdline = {}

        self.update_from_boot_cmdline()
        self.allow_imperfect_devices = True
        self.debug_threads = False

    def get_boot_cmdline(self):
        buf = open("/proc/cmdline").read().strip()
        args = shlex.split(buf)
        for arg in args:
            (opt, _equals, val) = arg.partition("=")
            if val:
                self.boot_cmdline[opt] = val

    def update_from_boot_cmdline(self):
        self.get_boot_cmdline()
        self.multipath = "nompath" not in self.boot_cmdline
        self.dmraid = "nodmraid" not in self.boot_cmdline
        self.noiswmd = "noiswmd" in self.boot_cmdline
        self.gfs2 = "gfs2" in self.boot_cmdline
        self.jfs = "jfs" in self.boot_cmdline
        self.reiserfs = "reiserfs" in self.boot_cmdline


flags = Flags()
