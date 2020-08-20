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
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from ...callbacks import callbacks
from ... import udev
from ...devicelibs import lvm
from ...devices.lvm import LVMVolumeGroupDevice, LVMLogicalVolumeDevice, LVMInternalLVtype
from ...errors import DeviceTreeError, DuplicateVGError
from ...flags import flags
from ...size import Size
from ...storage_log import log_method_call
from .devicepopulator import DevicePopulator
from .formatpopulator import FormatPopulator

from ...static_data import lvs_info, pvs_info, vgs_info

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

        self._devicetree._add_parent_devices(self.data)

        # LVM provides no means to resolve conflicts caused by duplicated VG
        # names, so we're just being optimistic here. Woo!
        vg_name = udev.device_get_lv_vg_name(self.data)
        vg_device = self._devicetree.get_device_by_name(vg_name)
        if not vg_device:
            log.error("failed to find vg '%s' after scanning pvs", vg_name)

        return self._devicetree.get_device_by_name(name)

    def _handle_rename(self):
        name = self.data.get("DM_LV_NAME")
        if not name:
            return

        # device.name is of the form "%s-%s" % (vg_name, lv_name), while
        # device.lvname is the name of the lv without the vg name.
        if self.device.lvname != name:
            self.device.name = name
        # TODO: update name registry


class LVMFormatPopulator(FormatPopulator):
    priority = 100
    _type_specifier = "lvmpv"

    def _get_kwargs(self):
        kwargs = super(LVMFormatPopulator, self)._get_kwargs()

        pv_info = pvs_info.cache.get(self.device.path, None)

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

    def _get_vg_device(self):
        return self._devicetree.get_device_by_uuid(self.device.format.container_uuid, incomplete=True)

    def _update_lvs(self):
        """ Handle setup of the LVs in the vg_device. """
        log_method_call(self, pv=self.device.name)
        vg_device = self._get_vg_device()
        if vg_device is None:
            # orphan pv
            return

        vg_name = vg_device.name
        lv_info = dict((k, v) for (k, v) in iter(lvs_info.cache.items())
                       if v.vg_name == vg_name)

        for lv_device in vg_device.lvs[:]:
            if lv_device.name not in lv_info:
                log.info("lv %s was removed", lv_device.name)
                self._devicetree.cancel_disk_actions(vg_device.disks)
                self._devicetree.recursive_remove(lv_device, actions=False)

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

            lv_device = self._devicetree.get_device_by_name(name)
            if lv_device is not None:
                # some lvs may have been added on demand below
                log.debug("already added %s", name)
                if lv_size != lv_device.current_size:
                    # lvresize can operate on an inactive lv, in which case
                    # the only notification we will receive is a change uevent
                    # for the pv(s)
                    old_size = lv_device._size
                    lv_device.update_size(newsize=lv_size)
                    callbacks.attribute_changed(device=lv_device, attr="size",
                                                old=old_size, new=lv_size)
                    self._devicetree.cancel_disk_actions(vg_device.disks)

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
            elif lv_attr[0] in 'IrielTCo' and lv_name.endswith(']'):
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
            elif lv_attr[0] == 'd':
                # vdo pool
                # nothing to do here
                pass
            elif lv_attr[0] == 'v':
                if lv_type != "vdo":
                    # skip vorigins
                    return
                pool_name = blockdev.lvm.vdolvpoolname(vg_name, lv_name)
                pool_device_name = "%s-%s" % (vg_name, pool_name)
                add_required_lv(pool_device_name, "failed to look up VDO pool")

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
                if flags.auto_dev_updates:
                    try:
                        lv_device.setup()
                    except blockdev.LVMError:
                        log.warning("failed to activate lv %s", lv_device.name)
                        lv_device.controllable = False

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
            parent_lv = lvm.determine_parent_lv(lv, all_lvs, lv_info)
            if parent_lv:
                lv.parent_lv = parent_lv
            else:
                log.warning("Failed to determine parent LV for an internal LV '%s'", lv.name)

    def _add_vg_device(self):
        pv_info = pvs_info.cache.get(self.device.path, None)
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
        if vg_device and self.device not in vg_device.parents:
            vg_device.parents.append(self.device)
            callbacks.parent_added(device=vg_device, parent=self.device)
        elif vg_device is None:
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

            vg_info = vgs_info.cache.get(pv_info.vg_uuid)
            if vg_info is None:
                log.warning("Failed to get information about LVM volume group %s (%s)", vg_name, pv_info.vg_uuid)
                return

            if not hasattr(vg_info, "exported"):
                log.info("Can't get exported information from VG info, assuming VG is not exported.")
                exported = False
            else:
                exported = vg_info.exported

            vg_device = LVMVolumeGroupDevice(vg_name,
                                             parents=[self.device],
                                             uuid=vg_uuid,
                                             size=vg_size,
                                             free=vg_free,
                                             pe_size=pe_size,
                                             pe_count=pe_count,
                                             pe_free=pe_free,
                                             pv_count=pv_count,
                                             exists=True,
                                             exported=exported)
            self._devicetree._add_device(vg_device)

    def run(self):
        log_method_call(self, pv=self.device.name)
        super(LVMFormatPopulator, self).run()
        self._add_vg_device()
        self._update_lvs()

    def _handle_vg_rename(self):
        vg_device = self._get_vg_device()
        if vg_device is None:
            return

        pv_info = pvs_info.cache.get(self.device.path, None)
        if not pv_info or not pv_info.vg_name:
            return

        vg_name = pv_info.vg_name
        if vg_device.name != vg_name:
            vg_device.name = vg_name
        # TODO: update name registry

    def _update_pv_format(self):
        pv_info = pvs_info.cache.get(self.device.path, None)
        if not pv_info:
            return

        self.device.format.vg_name = pv_info.vg_name
        self.device.format.vg_uuid = pv_info.vg_uuid
        self.device.format.pe_start = Size(pv_info.pe_start)
        self.device.format.pe_free = Size(pv_info.pv_free)

    def update(self):
        self._devicetree.drop_lvm_cache()
        self._update_pv_format()
        pv_info = pvs_info.cache.get(self.device.path, None)
        vg_device = self._get_vg_device()
        if vg_device is None:
            # The VG device isn't in the tree. The PV might have just been
            # added to a VG.
            if pv_info and pv_info.vg_name:
                # Handle adding orphan pv to a vg.
                self._add_vg_device()
            elif self.device.children:
                # The PV was removed from its VG or the VG was removed.
                vg_device = self.device.children[0]
                if len(vg_device.parents) > 1:
                    vg_device.parents.remove(self.device)
                    callbacks.parent_removed(device=vg_device, parent=self.device)
                else:
                    self._devicetree.recursive_remove(vg_device, actions=False)
                return
        else:
            # The VG device is in the tree. Check if the PV still belongs to it.
            if pv_info and pv_info.vg_name:
                # This is the "normal" case: the pv is still part of the
                # vg it was part of last time we looked.
                self._handle_vg_rename()

        # handles vg rename, lv add, lv remove, lv resize (inactive lv)
        self._update_lvs()
