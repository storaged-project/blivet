# populator.py
# Backend code for populating a DeviceTree.
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

import os
import pprint
import copy
import parted
from six import add_metaclass

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

from ..errors import DeviceError, DeviceTreeError, NoParentsError
from ..devices import DMLinearDevice, DMRaidArrayDevice
from ..devices import FileDevice, LoopDevice
from ..devices import MDRaidArrayDevice
from ..devices import MultipathDevice
from ..devices import NoDevice
from ..devicelibs import disk as disklib
from ..devicelibs import lvm
from .. import formats
from .. import udev
from .. import util
from ..flags import flags
from ..storage_log import log_method_call
from ..tasks import availability
from ..threads import SynchronizedMeta
from .helpers import get_device_helper, get_format_helper
from ..static_data import lvs_info, pvs_info, vgs_info, luks_data, mpath_members
from ..callbacks import callbacks

import logging
log = logging.getLogger("blivet")


def parted_exn_handler(exn_type, exn_options, exn_msg):
    """ Answer any of parted's yes/no questions in the affirmative.

        This allows us to proceed with partially corrupt gpt disklabels.
    """
    log.info("parted exception: %s", exn_msg)
    ret = parted.EXCEPTION_RESOLVE_UNHANDLED
    if exn_type == parted.EXCEPTION_TYPE_ERROR and \
       exn_options == parted.EXCEPTION_OPT_YES_NO:
        ret = parted.EXCEPTION_RESOLVE_YES
    return ret


@add_metaclass(SynchronizedMeta)
class PopulatorMixin(object):
    def __init__(self, disk_images=None):
        """
            :keyword disk_images: dictoinary of disk images
            :type list: dict
        """
        luks_data.reset(passphrase=None, luks_dict={})
        self.reset(disk_images=disk_images)

    def reset(self, disk_images=None):
        luks_data.reset()
        self.disk_images = {}
        if disk_images:
            # this will overwrite self.exclusive_disks
            self.set_disk_images(disk_images)

        # initialize attributes that may later hold cached lvm info
        self.drop_lvm_cache()

        self._cleanup = False

    def _add_parent_devices(self, info):
        """ Add all parents of a device, raising DeviceTreeError on failure.

            :param :class:`pyudev.Device` info: the device's udev info
            :raises: :class:`~.errors.DeviceTreeError if no parents are found or
                     if we fail to add any parent
            :returns: a list of parent devices
            :rtype: list of :class:`~.StorageDevice`
        """
        name = udev.device_get_name(info)
        sysfs_path = udev.device_get_sysfs_path(info)
        parent_dir = os.path.normpath("%s/slaves" % sysfs_path)
        parent_names = os.listdir(parent_dir)
        parent_devices = []
        if not parent_names:
            log.error("no parents found for %s", name)
            raise NoParentsError("no parents found for device %s" % name)

        for parent_name in parent_names:
            path = os.path.normpath("%s/%s" % (parent_dir, parent_name))
            parent_info = udev.get_device(os.path.realpath(path))

            if not parent_info:
                msg = "unable to get udev info for %s" % parent_name
                raise DeviceTreeError(msg)

            # cciss in sysfs is "cciss!cXdYpZ" but we need "cciss/cXdYpZ"
            parent_name = udev.device_get_name(parent_info).replace("!", "/")

            parent_dev = self.get_device_by_name(parent_name)
            if not parent_dev and parent_info:
                # we haven't scanned the parent yet, so do it now
                self.handle_device(parent_info)
                parent_dev = self.get_device_by_name(parent_name)
                if parent_dev is None:
                    if udev.device_is_dm_lvm(info):
                        if parent_name not in lvs_info.cache:
                            # we do not expect hidden lvs to be in the tree
                            continue

                    # if the current parent is still not in
                    # the tree, something has gone wrong
                    log.error("failure scanning device %s: could not add parent %s", name, parent_name)
                    msg = "failed to add parent %s of device %s" % (parent_name, name)
                    raise DeviceTreeError(msg)

            parent_devices.append(parent_dev)

        return parent_devices

    def _add_name(self, name):
        if name not in self.names:
            self.names.append(name)

    def _reason_to_skip_device(self, info):
        sysfs_path = udev.device_get_sysfs_path(info)
        uuid = udev.device_get_uuid(info)

        # make sure this device was not scheduled for removal and also has not
        # been hidden
        removed = [a.device for a in self.actions.find(action_type="destroy",
                                                       object_type="device")]
        for ignored in removed + self._hidden:
            if (sysfs_path and ignored.sysfs_path == sysfs_path) or \
               (uuid and uuid in (ignored.uuid, ignored.format.uuid)):
                if ignored in removed:
                    reason = "removed"
                else:
                    reason = "hidden"

                return reason

    def _handle_degraded_md(self, info, device):
        if device is not None or not udev.device_is_md(info):
            return device

        # If the md name is None, then some udev info is missing. Likely,
        # this is because the array is degraded, and mdadm has deactivated
        # it. Try to activate it and re-get the udev info.
        if flags.allow_imperfect_devices and udev.device_get_md_name(info) is None:
            devname = udev.device_get_devname(info)
            if devname:
                try:
                    blockdev.md.run(devname)
                except blockdev.MDRaidError as e:
                    log.warning("Failed to start possibly degraded md array: %s", e)
                else:
                    udev.settle()
                    info = udev.get_device(udev.device_get_sysfs_path(info))
            else:
                log.warning("Failed to get devname for possibly degraded md array.")

        md_name = udev.device_get_md_name(info)
        if md_name is None:
            log.warning("No name for possibly degraded md array.")
        else:
            device = self.get_device_by_name(md_name, incomplete=flags.allow_imperfect_devices)

        if device and not isinstance(device, MDRaidArrayDevice):
            log.warning("Found device %s, but it turns out not be an md array device after all.", device.name)
            device = None

        return device

    def _clear_new_multipath_member(self, device):
        if device is None or not device.is_disk or not mpath_members.is_mpath_member(device.path):
            return

        # newly added device (eg iSCSI) could make this one a multipath member
        if device.format.type != "multipath_member":
            log.debug("%s newly detected as multipath member, dropping old format and removing kids", device.name)
            # remove children from tree so that we don't stumble upon them later
            self.recursive_remove(device, actions=False, remove_device=False)

    def _mark_readonly_device(self, info, device):
        # If this device is read-only, mark it as such now.
        if udev.device_is_disk(info) and \
                util.get_sysfs_attr(udev.device_get_sysfs_path(info), 'ro') == '1':
            device.readonly = True

    def _update_exclusive_disks(self, device):
        # If we just added a multipath or fwraid disk that is in exclusive_disks
        # we have to make sure all of its members are in the list too.
        mdclasses = (DMRaidArrayDevice, MDRaidArrayDevice, MultipathDevice)
        if device.is_disk and isinstance(device, mdclasses):
            if device.name in self.exclusive_disks:
                for ancestor in device.ancestors:
                    if ancestor.is_disk and ancestor.name not in self.exclusive_disks:
                        self.exclusive_disks.append(ancestor.name)

    def _get_format_helper(self, info, device=None):
        return get_format_helper(info, device=device)

    def _get_device_helper(self, info):
        return get_device_helper(info)

    def handle_device(self, info, update_orig_fmt=False):
        """
            :param :class:`pyudev.Device` info: udev info for the device
            :keyword bool update_orig_fmt: update original format unconditionally

            If a device is added to the tree based on info its original format
            will be saved after the format has been detected. If the device
            that corresponds to info is already in the tree, its original format
            will not be updated unless update_orig_fmt is True.
        """
        name = udev.device_get_name(info)
        log_method_call(self, name=name, info=pprint.pformat(dict(info)))
        sysfs_path = udev.device_get_sysfs_path(info)

        reason = self._reason_to_skip_device(info)
        if reason:
            log.debug("skipping %s device %s", reason, name)
            callbacks.device_scanned(device_name=name)
            return

        log.info("scanning %s (%s)...", name, sysfs_path)
        if udev.device_is_hidden(info):
            log.info("device %s is marked as hidden in sysfs, ignoring")
            return

        # make sure we note the name of every device we see
        self._add_name(name)
        device = self.get_device_by_name(name)
        device = self._handle_degraded_md(info, device)
        self._clear_new_multipath_member(device)

        device_added = True
        helper_class = None
        if device:
            device_added = False
        else:
            helper_class = self._get_device_helper(info)

        if helper_class is not None:
            device = helper_class(self, info).run()

        if not device:
            log.debug("no device obtained for %s", name)
            callbacks.device_scanned(device_name=name)
            return

        log.info("got device: %r", device)
        self._mark_readonly_device(info, device)
        self._update_exclusive_disks(device)

        # now handle the device's formatting
        self.handle_format(info, device)
        if device_added or update_orig_fmt:
            device.original_format = copy.deepcopy(device.format)
        device.device_links = udev.device_get_symlinks(info)
        callbacks.device_scanned(device_name=name)

    def handle_format(self, info, device):
        log_method_call(self, name=getattr(device, "name", None))

        if not info:
            info = udev.get_device(device.sysfs_path)
            if not info:
                log.debug("no information for device %s", device.name)
                return
        if not device.media_present:
            log.debug("no media present for device %s", device.name)
            return

        name = udev.device_get_name(info)
        if (not device or
            (not udev.device_get_format(info) and not udev.device_get_disklabel_type(info)) or
           device.format.type):
            # this device has no formatting or it has already been set up
            log.debug("no type or existing type for %s, bailing", name)
            return

        helper_class = self._get_format_helper(info, device=device)
        if helper_class is not None:
            helper_class(self, info, device).run()

        log.info("got format: %s", device.format)

    def _handle_inconsistencies(self):
        for vg in [d for d in self.devices if d.type == "lvmvg"]:
            if vg.complete:
                continue

            # Make sure lvm doesn't get confused by PVs that belong to
            # incomplete VGs. We will remove the PVs from the reject list when/if
            # the time comes to remove the incomplete VG and its PVs.
            for pv in vg.pvs:
                lvm.lvm_cc_addFilterRejectRegexp(pv.name)

    def set_disk_images(self, images):
        """ Set the disk images and reflect them in exclusive_disks.

            :param images: dict with image name keys and filename values
            :type images: dict

            .. note::

                Disk images are automatically exclusive. That means that, in the
                presence of disk images, any local storage not associated with
                the disk images is ignored.
        """
        self.disk_images = images
        # disk image files are automatically exclusive
        self.exclusive_disks = list(self.disk_images.keys())

    def setup_disk_images(self):
        """ Set up devices to represent the disk image files. """
        for (name, path) in self.disk_images.items():
            log.info("setting up disk image file '%s' as '%s'", path, name)
            dmdev = self.get_device_by_name(name)
            if dmdev and isinstance(dmdev, DMLinearDevice) and \
               path in (d.path for d in dmdev.ancestors):
                log.debug("using %s", dmdev)
                dmdev.setup()
                continue

            try:
                filedev = FileDevice(path, exists=True)
                filedev.setup()
                log.debug("%s", filedev)

                loop_name = blockdev.loop.get_loop_name(filedev.path)
                loop_sysfs = None
                if loop_name:
                    loop_sysfs = "/class/block/%s" % loop_name
                loopdev = LoopDevice(name=loop_name,
                                     parents=[filedev],
                                     sysfs_path=loop_sysfs,
                                     exists=True)
                loopdev.setup()
                log.debug("%s", loopdev)
                dmdev = DMLinearDevice(name,
                                       dm_uuid="ANACONDA-%s" % name,
                                       parents=[loopdev],
                                       exists=True)
                dmdev.setup()
                dmdev.update_sysfs_path()
                dmdev.update_size()
                log.debug("%s", dmdev)
            except (ValueError, DeviceError) as e:
                log.error("failed to set up disk image: %s", e)
            else:
                self._add_device(filedev)
                self._add_device(loopdev)
                self._add_device(dmdev)
                info = udev.get_device(dmdev.sysfs_path)
                self.handle_device(info, update_orig_fmt=True)

    def teardown_disk_images(self):
        """ Tear down any disk image stacks. """
        if not self.disk_images:
            return

        self.teardown_all()
        for (name, _path) in self.disk_images.items():
            dm_device = self.get_device_by_name(name)
            if not dm_device:
                continue

            dm_device.deactivate()
            loop_device = dm_device.parents[0]
            loop_device.teardown()

    def save_luks_passphrase(self, device):
        """ Save a device's LUKS passphrase in case of reset. """
        # Method is here for compatibility with blivet 1.x
        luks_data.save_passphrase(device)

    def populate(self, cleanup_only=False):
        """ Locate all storage devices.

            Everything should already be active. We just go through and gather
            details as needed and set up the relations between various devices.

            Devices excluded via disk filtering (or because of disk images) are
            scanned just the rest, but then they are hidden at the end of this
            process.
        """
        if cleanup_only:
            self._cleanup = True

        parted.register_exn_handler(parted_exn_handler)
        try:
            self._populate()
        finally:
            parted.clear_exn_handler()
            self._hide_ignored_disks()

    def _populate(self):
        log.info("DeviceTree.populate: ignored_disks is %s ; exclusive_disks is %s",
                 self.ignored_disks, self.exclusive_disks)

        disklib.update_volume_info()
        self.drop_lvm_cache()
        mpath_members.drop_cache()

        if flags.auto_dev_updates and availability.BLOCKDEV_MPATH_PLUGIN.available:
            blockdev.mpath.set_friendly_names(flags.multipath_friendly_names)

        self.setup_disk_images()

        old_devices = {}
        n_devices = 0
        report = True

        # Now, loop and scan for devices that have appeared since the two above
        # blocks or since previous iterations.
        while True:
            devices = []
            new_devices = udev.get_devices()

            for new_device in new_devices:
                new_name = udev.device_get_name(new_device)
                if new_name not in old_devices:
                    old_devices[new_name] = new_device
                    n_devices += 1
                    devices.append(new_device)

            if len(devices) == 0:
                # nothing is changing -- we are finished building devices
                break

            if report:
                callbacks.populate_started(n_devices=n_devices)
                report = False

            log.info("devices to scan: %s", [udev.device_get_name(d) for d in devices])
            for dev in devices:
                self.handle_device(dev)

        # After having the complete tree we make sure that the system
        # inconsistencies are ignored or resolved.
        self._handle_inconsistencies()

    def drop_lvm_cache(self):
        """ Drop cached lvm information. """
        lvs_info.drop_cache()
        pvs_info.drop_cache()
        vgs_info.drop_cache()

    def handle_nodev_filesystems(self):
        for line in open("/proc/mounts").readlines():
            try:
                (_devspec, mountpoint, fstype, _options, _rest) = line.split(None, 4)
            except ValueError:
                log.error("failed to parse /proc/mounts line: %s", line)
                continue
            if fstype in formats.fslib.nodev_filesystems:
                if not flags.include_nodev:
                    continue

                log.info("found nodev %s filesystem mounted at %s",
                         fstype, mountpoint)
                # nodev filesystems require some special handling.
                # For now, a lot of this is based on the idea that it's a losing
                # battle to require the presence of an FS class for every type
                # of nodev filesystem. Based on that idea, we just instantiate
                # NoDevFS directly and then hack in the fstype as the device
                # attribute.
                fmt = formats.get_format("nodev")
                fmt.device = fstype

                # NoDevice also needs some special works since they don't have
                # per-instance names in the kernel.
                device = NoDevice(fmt=fmt)
                n = len([d for d in self.devices if d.format.type == fstype])
                device._name += ".%d" % n
                self._add_device(device)
