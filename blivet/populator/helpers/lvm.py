# populator/helpers/lvm.py
# LVM backend code for populating a DeviceTree.
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

import gi
gi.require_version("BlockDev", "1.0")

from gi.repository import BlockDev as blockdev

from ... import udev
from ...devicelibs import lvm
from ...devices.lvm import LVMVolumeGroupDevice, LVMLogicalVolumeDevice, LVMInternalLVtype
from ...errors import DeviceTreeError, DuplicateVGError
from ...flags import flags
from ...size import Size
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator
from .formatpopulator import FormatPopulator

import logging
log = logging.getLogger("blivet")


class LVMDevicePopulator(DevicePopulator):
    @classmethod
    def match(cls, data):
        return udev.device_is_dm_lvm(data)

    def run(self):
        name = udev.device_get_name(self.data)
        log_method_call(self, name=name)

        vg_name = udev.device_get_lv_vg_name(self.data)
        device = self._devicetree.get_device_by_name(vg_name, hidden=True)
        if device and not isinstance(device, LVMVolumeGroupDevice):
            log.warning("found non-vg device with name %s", vg_name)
            device = None

        self._devicetree._add_slave_devices(self.data)

        # LVM provides no means to resolve conflicts caused by duplicated VG
        # names, so we're just being optimistic here. Woo!
        vg_name = udev.device_get_lv_vg_name(self.data)
        vg_device = self._devicetree.get_device_by_name(vg_name)
        if not vg_device:
            log.error("failed to find vg '%s' after scanning pvs", vg_name)

        return self._devicetree.get_device_by_name(name)


class LVMFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "lvmpv"

    def _get_kwargs(self):
        kwargs = super()._get_kwargs()

        pv_info = self._devicetree.pv_info.get(self.device.path, None)
        name = udev.device_get_name(self.data)
        if pv_info:
            if pv_info.vg_name:
                kwargs["vg_name"] = pv_info.vg_name
            else:
                log.warning("PV %s has no vg_name", name)
            if pv_info.vg_uuid:
                kwargs["vg_uuid"] = pv_info.vg_uuid
            else:
                log.warning("PV %s has no vg_uuid", name)
            if pv_info.pe_start:
                kwargs["pe_start"] = Size(pv_info.pe_start)
            else:
                log.warning("PV %s has no pe_start", name)
            if pv_info.pv_free:
                kwargs["free"] = Size(pv_info.pv_free)

        return kwargs

    def _handle_vg_lvs(self, vg_device):
        """ Handle setup of the LV's in the vg_device. """
        vg_name = vg_device.name
        lv_info = dict((k, v) for (k, v) in iter(self._devicetree.lv_info.items())
                       if v.vg_name == vg_name)

        self._devicetree.names.extend(n for n in lv_info.keys() if n not in self._devicetree.names)

        if not vg_device.complete:
            log.warning("Skipping LVs for incomplete VG %s", vg_name)
            return

        if not lv_info:
            log.debug("no LVs listed for VG %s", vg_name)
            return

        all_lvs = []
        internal_lvs = []

        def add_required_lv(name, msg):
            """ Add a prerequisite/parent LV.

                The parent is strictly required in order to be able to add
                some other LV that depends on it. For this reason, failure to
                add the specified LV results in a DeviceTreeError with the
                message string specified in the msg parameter.

                :param str name: the full name of the LV (including vgname)
                :param str msg: message to pass DeviceTreeError ctor on error
                :returns: None
                :raises: :class:`~.errors.DeviceTreeError` on failure

            """
            vol = self._devicetree.get_device_by_name(name)
            if vol is None:
                new_lv = add_lv(lv_info[name])
                if new_lv:
                    all_lvs.append(new_lv)
                vol = self._devicetree.get_device_by_name(name)

                if vol is None:
                    log.error("%s: %s", msg, name)
                    raise DeviceTreeError(msg)

        def add_lv(lv):
            """ Instantiate and add an LV based on data from the VG. """
            lv_name = lv.lv_name
            lv_uuid = lv.uuid
            lv_attr = lv.attr
            lv_size = Size(lv.size)
            lv_type = lv.segtype

            lv_parents = [vg_device]
            lv_kwargs = {}
            name = "%s-%s" % (vg_name, lv_name)

            if self._devicetree.get_device_by_name(name):
                # some lvs may have been added on demand below
                log.debug("already added %s", name)
                return

            if lv_attr[0] in 'Ss':
                log.info("found lvm snapshot volume '%s'", name)
                origin_name = blockdev.lvm.lvorigin(vg_name, lv_name)
                if not origin_name:
                    log.error("lvm snapshot '%s-%s' has unknown origin",
                              vg_name, lv_name)
                    return

                if origin_name.endswith("_vorigin]"):
                    lv_kwargs["vorigin"] = True
                    origin = None
                else:
                    origin_device_name = "%s-%s" % (vg_name, origin_name)
                    add_required_lv(origin_device_name,
                                    "failed to locate origin lv")
                    origin = self._devicetree.get_device_by_name(origin_device_name)

                lv_kwargs["origin"] = origin
            elif lv_attr[0] == 'v':
                # skip vorigins
                return
            elif lv_attr[0] in 'IielTCo' and lv_name.endswith(']'):
                # an internal LV, add the an instance of the appropriate class
                # to internal_lvs for later processing when non-internal LVs are
                # processed
                internal_lvs.append(lv_name)
                return
            elif lv_attr[0] == 't':
                # thin pool
                # nothing to do here
                pass
            elif lv_attr[0] == 'V':
                # thin volume
                pool_name = blockdev.lvm.thlvpoolname(vg_name, lv_name)
                pool_device_name = "%s-%s" % (vg_name, pool_name)
                add_required_lv(pool_device_name, "failed to look up thin pool")

                origin_name = blockdev.lvm.lvorigin(vg_name, lv_name)
                if origin_name:
                    origin_device_name = "%s-%s" % (vg_name, origin_name)
                    add_required_lv(origin_device_name, "failed to locate origin lv")
                    origin = self._devicetree.get_device_by_name(origin_device_name)
                    lv_kwargs["origin"] = origin

                lv_parents = [self._devicetree.get_device_by_name(pool_device_name)]
            elif lv_name.endswith(']'):
                # unrecognized Internal LVM2 device
                return
            elif lv_attr[0] not in '-mMrRoOC':
                # Ignore anything else except for the following:
                #   - normal lv
                #   m mirrored
                #   M mirrored without initial sync
                #   r raid
                #   R raid without initial sync
                #   o origin
                #   O origin with merging snapshot
                #   C cached LV
                return

            lv_dev = self._devicetree.get_device_by_uuid(lv_uuid)
            if lv_dev is None:
                lv_device = LVMLogicalVolumeDevice(lv_name, parents=lv_parents,
                                                   uuid=lv_uuid, size=lv_size, seg_type=lv_type,
                                                   exists=True, **lv_kwargs)
                self._devicetree._add_device(lv_device)
                if flags.installer_mode:
                    lv_device.setup()

                if lv_device.status:
                    lv_device.update_sysfs_path()
                    lv_device.update_size()
                    lv_info = udev.get_device(lv_device.sysfs_path)
                    if not lv_info:
                        log.error("failed to get udev data for lv %s", lv_device.name)
                        return lv_device

                    # do format handling now
                    self._devicetree.handle_device(lv_info, update_orig_fmt=True)

                return lv_device

            return None

        def create_internal_lv(lv):
            lv_name = lv.lv_name
            lv_uuid = lv.uuid
            lv_attr = lv.attr
            lv_size = Size(lv.size)
            seg_type = lv.segtype

            lv_type = LVMInternalLVtype.get_type(lv_attr, lv_name)
            if lv_type is LVMInternalLVtype.unknown:
                raise DeviceTreeError("Internal LVs of type '%s' are not supported" % lv_attr[0])

            # strip the "[]"s marking the LV as internal
            lv_name = lv_name.strip("[]")

            # don't know the parent LV yet, will be set later
            new_lv = LVMLogicalVolumeDevice(lv_name, vg_device, parent_lv=None, int_type=lv_type,
                                            size=lv_size, uuid=lv_uuid, exists=True, seg_type=seg_type)
            if new_lv.status:
                new_lv.update_sysfs_path()
                new_lv.update_size()

                lv_info = udev.get_device(new_lv.sysfs_path)
                if not lv_info:
                    log.error("failed to get udev data for lv %s", new_lv.name)
                    return new_lv

            return new_lv

        # add LVs
        for lv in lv_info.values():
            # add the LV to the DeviceTree
            new_lv = add_lv(lv)

            if new_lv:
                # save the reference for later use
                all_lvs.append(new_lv)

        # Instead of doing a topological sort on internal LVs to make sure the
        # parent LV is always created before its internal LVs (an internal LV
        # can have internal LVs), we just create all the instances here and
        # assign their parents later. Those who are not assinged a parent (which
        # would hold a reference to them) will get eaten by the garbage
        # collector.

        # create device instances for the internal LVs
        orphan_lvs = dict()
        for lv_name in internal_lvs:
            full_name = "%s-%s" % (vg_name, lv_name)
            try:
                new_lv = create_internal_lv(lv_info[full_name])
            except DeviceTreeError as e:
                log.warning("Failed to process an internal LV '%s': %s", full_name, e)
            else:
                orphan_lvs[full_name] = new_lv
                all_lvs.append(new_lv)

        # assign parents to internal LVs (and vice versa)
        for lv in orphan_lvs.values():
            parent_lv = lvm.determine_parent_lv(vg_name, lv, all_lvs)
            if parent_lv:
                lv.parent_lv = parent_lv
            else:
                log.warning("Failed to determine parent LV for an internal LV '%s'", lv.name)

    def run(self):
        super().run()
        pv_info = self._devicetree.pv_info.get(self.device.path, None)
        if pv_info:
            vg_name = pv_info.vg_name
            vg_uuid = pv_info.vg_uuid
        else:
            # no info about the PV -> we're done
            return

        if not vg_name:
            log.info("lvm pv %s has no vg", self.device.name)
            return

        vg_device = self._devicetree.get_device_by_uuid(vg_uuid, incomplete=True)
        if vg_device:
            vg_device.parents.append(self.device)
        else:
            same_name = self._devicetree.get_device_by_name(vg_name)
            if isinstance(same_name, LVMVolumeGroupDevice):
                raise DuplicateVGError("multiple LVM volume groups with the same name (%s)" % vg_name)

            try:
                vg_size = Size(pv_info.vg_size)
                vg_free = Size(pv_info.vg_free)
                pe_size = Size(pv_info.vg_extent_size)
                pe_count = pv_info.vg_extent_count
                pe_free = pv_info.vg_free_count
                pv_count = pv_info.vg_pv_count
            except (KeyError, ValueError) as e:
                log.warning("invalid data for %s: %s", self.device.name, e)
                return

            vg_device = LVMVolumeGroupDevice(vg_name,
                                             parents=[self.device],
                                             uuid=vg_uuid,
                                             size=vg_size,
                                             free=vg_free,
                                             pe_size=pe_size,
                                             pe_count=pe_count,
                                             pe_free=pe_free,
                                             pv_count=pv_count,
                                             exists=True)
            self._devicetree._add_device(vg_device)

        self._handle_vg_lvs(vg_device)
