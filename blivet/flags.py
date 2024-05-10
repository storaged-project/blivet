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
        try:
            import selinux
        except ImportError:
            self.selinux = False
        else:
            self.selinux = selinux.is_selinux_enabled()

        self.ibft = True

        self.gfs2 = True

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

        # set to False to not write new LVM PVs to /etc/lvm/devices/system.devices
        self.lvm_devices_file = True

        # whether to include nodev filesystems in the devicetree
        self.include_nodev = False

        # whether to enable discard for newly created devices
        # (so far only for LUKS)
        self.discard_new = False

        self.allow_imperfect_devices = True

        # compression option for btrfs filesystems
        self.btrfs_compression = None

        self.debug_threads = False

        # Assign GPT partition type UUIDs to allow partition
        # auto-discovery according to:
        # https://uapi-group.org/specifications/specs/discoverable_partitions_specification/
        self.gpt_discoverable_partitions = False

        # Allow online filesystem resizes
        self.allow_online_fs_resize = False


flags = Flags()
