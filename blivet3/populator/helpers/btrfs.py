# populator/helpers/btrfs.py
# BTTRFS backend code for populating a DeviceTree.
#
# Copyright (C) 2009-2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from ... import formats
from ... import udev
from ...devices import BTRFSVolumeDevice, BTRFSSnapShotDevice, BTRFSSubVolumeDevice
from ...errors import DeviceTreeError
from .formatpopulator import FormatPopulator

import logging
log = logging.getLogger("blivet")


class BTRFSFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "btrfs"

    def _get_kwargs(self):
        kwargs = super(BTRFSFormatPopulator, self)._get_kwargs()
        # the format's uuid attr will contain the UUID_SUB, while the
        # overarching volume UUID will be stored as vol_uuid
        kwargs["uuid"] = self.data["ID_FS_UUID_SUB"]
        kwargs["vol_uuid"] = udev.device_get_uuid(self.data)
        return kwargs

    def run(self):
        super(BTRFSFormatPopulator, self).run()
        uuid = udev.device_get_uuid(self.data)

        btrfs_dev = None
        for d in self._devicetree.devices:
            if isinstance(d, BTRFSVolumeDevice) and d.uuid == uuid:
                btrfs_dev = d
                break

        if btrfs_dev:
            log.info("found btrfs volume %s", btrfs_dev.name)
            btrfs_dev.parents.append(self.device)
        else:
            label = udev.device_get_label(self.data)
            log.info("creating btrfs volume btrfs.%s", label)
            btrfs_dev = BTRFSVolumeDevice(label, parents=[self.device], uuid=uuid,
                                          exists=True)
            self._devicetree._add_device(btrfs_dev)

        if not btrfs_dev.subvolumes:
            snapshots = btrfs_dev.list_subvolumes(snapshots_only=True)
            snapshot_ids = [s.id for s in snapshots]
            for subvol_dict in btrfs_dev.list_subvolumes():
                vol_id = subvol_dict.id
                vol_path = subvol_dict.path
                parent_id = subvol_dict.parent_id
                if vol_path in [sv.name for sv in btrfs_dev.subvolumes]:
                    continue

                # look up the parent subvol
                parent = None
                subvols = [btrfs_dev] + btrfs_dev.subvolumes
                for sv in subvols:
                    if sv.vol_id == parent_id:
                        parent = sv
                        break

                if parent is None:
                    log.error("failed to find parent (%d) for subvol %s",
                              parent_id, vol_path)
                    raise DeviceTreeError("could not find parent for subvol")

                fmt = formats.get_format("btrfs",
                                         device=btrfs_dev.path,
                                         exists=True,
                                         vol_uuid=btrfs_dev.format.vol_uuid,
                                         subvolspec=vol_path,
                                         mountopts="subvol=%s" % vol_path)
                if vol_id in snapshot_ids:
                    device_class = BTRFSSnapShotDevice
                else:
                    device_class = BTRFSSubVolumeDevice

                subvol = device_class(vol_path,
                                      vol_id=vol_id,
                                      fmt=fmt,
                                      parents=[parent],
                                      exists=True)
                self._devicetree._add_device(subvol)
