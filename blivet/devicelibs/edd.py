#
# edd.py
# BIOS EDD data parsing functions
#
# Copyright 2010-2015 Red Hat, Inc.
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
# Author(s):
#            Peter Jones <pjones@redhat.com>
#            Hans de Goede <hdegoede@redhat.com>
#            Ales Kozumplik <akozumpl@redhat.com>
#

import glob
import logging
import os
import re
import struct

from .. import util
from ..util import open # pylint: disable=redefined-builtin

log = logging.getLogger("blivet")

re_host_bus = re.compile(r'^PCI\S*\s*(\S*)\s*channel: (\S*)\s*$')
re_interface_scsi = re.compile(r'^SCSI\s*id: (\S*)\s*lun: (\S*)\s*$')
re_interface_ata = re.compile(r'^ATA\s*device: (\S*)\s*$')
re_interface_sata = re.compile(r'^SATA\s*device: (\S*)\s*$')

class EddEntry(object):
    """ This object merely collects what the /sys/firmware/edd/* entries can
        provide.
    """
    def __init__(self, sysfspath):
        self.type = None

        self.ata_device = None
        self.channel = None
        self.mbr_sig = None
        self.pci_dev = None
        self.scsi_id = None
        self.scsi_lun = None
        self.sectors = None
        self.sysfslink = ""
        self.sysfspath = sysfspath
        self.version = util.get_sysfs_attr(sysfspath, "version")

        self.load()

    def __str__(self):
        return \
            "\tpath: %(sysfspath)s version: %(version)s\n" \
            "\tsysfs pci path: %(sysfslink)s\n" \
            "\ttype: %(type)s, ata_device: %(ata_device)s\n" \
            "\tchannel: %(channel)s, mbr_signature: %(mbr_sig)s\n" \
            "\tpci_dev: %(pci_dev)s, scsi_id: %(scsi_id)s," \
            " scsi_lun: %(scsi_lun)s, sectors: %(sectors)s" % self.__dict__

    def load(self):
        interface = util.get_sysfs_attr(self.sysfspath, "interface")
        if interface:
            try:
                self.type = interface.split()[0]
                unsupported = ("ATAPI", "USB", "1394", "FIBRE", "I2O", "RAID")
                if self.type in unsupported:
                    log.warning("edd: interface type %s is not implemented (%s)",
                                self.type, self.sysfspath)
                    log.warning("edd: interface details: %s", interface)
                elif self.type == "ATA":
                    match = re_interface_ata.match(interface)
                    self.ata_device = int(match.group(1))
                elif self.type == "SCSI":
                    match = re_interface_scsi.match(interface)
                    self.scsi_id = int(match.group(1))
                    self.scsi_lun = int(match.group(2))
                elif self.type == "SATA":
                    match = re_interface_sata.match(interface)
                    self.ata_device = int(match.group(1))
                else:
                    log.warning("edd: can not match interface for %s: %s",
                                self.sysfspath, interface)
            except AttributeError as e:
                if e.args == "'NoneType' object has no attribute 'group'":
                    log.warning("edd: can not match interface for %s: %s",
                                self.sysfspath, interface)
                else:
                    raise e

        self.mbr_sig = util.get_sysfs_attr(self.sysfspath, "mbr_signature")
        sectors = util.get_sysfs_attr(self.sysfspath, "sectors")
        if sectors:
            self.sectors = int(sectors)
        hbus = util.get_sysfs_attr(self.sysfspath, "host_bus")
        if hbus:
            match = re_host_bus.match(hbus)
            if match:
                self.pci_dev = match.group(1)
                self.channel = int(match.group(2))
            else:
                log.warning("edd: can not match host_bus for %s: %s",
                    self.sysfspath, hbus)

class EddMatcher(object):
    """ This object tries to match given entry to a disk device name.

        Assuming, heuristic analysis and guessing hapens here.
    """
    def __init__(self, edd_entry):
        self.edd = edd_entry

    def devname_from_ata_pci_dev(self):
        pattern = '/sys/block/*'
        for path in glob.iglob(pattern):
            link = os.readlink(path)
            # just add /sys/block/ at the beginning so it's always valid
            # paths in the filesystem...
            components = ['/sys/block'] + link.split('/')
            if len(components) != 11:
                continue
            # ATA and SATA paths look like:
            # ../devices/pci0000:00/0000:00:1f.2/ata1/host0/target0:0:0/0:0:0:0/block/sda
            # where literally the only pieces of data here are
            # "pci0000:00:1f.2", "ata1", and "sda".
            #
            # EDD 3's "channel" doesn't really mean anything at all on SATA,
            # and 255 means "not in use".  Any other value should be an ATA
            # device (but might be a SATA device in compat mode), and that
            # matches N in devM.N .  So basically "channel" means master/slave
            # for ATA (non-SATA) devices.  Also in EDD 3, SATA port multipliers
            # aren't represented in any way.
            #
            if components[4] != '0000:%s' % (self.edd.pci_dev,):
                continue
            if not components[5].startswith('ata'):
                continue
            ata_port = components[5]
            ata_port_idx = int(components[5][3:])

            fn = components[0:6] + ['ata_port', ata_port]
            port_no = int(util.get_sysfs_attr(os.path.join(*fn), 'port_no'))

            if self.edd.type == "ATA":
                # On ATA, port_no is kernel's ata_port->local_port_no, which
                # should be the same as the ata device number.
                if port_no != self.edd.ata_device:
                    continue
            else:
                # On SATA, "port_no" is the kernel's ata_port->print_id, which
                # is awesomely ata_port->id + 1, where ata_port->id is edd's
                # ata_device
                if port_no != self.edd.ata_device+1:
                    continue

            fn = components[0:6] + ['link%d' % (ata_port_idx,),]
            exp = [r'^']+fn+[r'dev%d\.(\d+)(\.(\d+)){0,1}$' % (ata_port_idx,)]
            exp = os.path.join(*exp)
            expmatcher = re.compile(exp)
            pmp_glob = fn + ['dev%d.*.*' % (ata_port_idx,)]
            pmp_glob = os.path.join(*pmp_glob)
            dev_glob = fn + ['dev%d.*' % (ata_port_idx,)]
            dev_glob = os.path.join(*dev_glob)
            atapaths = tuple(glob.iglob(pmp_glob)) + tuple(glob.iglob(dev_glob))
            for atapath in atapaths:
                match = expmatcher.match(atapath)
                if match is None:
                    continue

                # so at this point it's devW.X.Y or devW.Z as such:
                # dev_set_name(dev, "dev%d.%d", ap->print_id,ata_dev->devno);
                # dev_set_name(dev, "dev%d.%d.0", ap->print_id, link->pmp);
                # we care about print_id and pmp for matching and the ATA
                # channel if applicable. We already checked print_id above.
                if match.group(3) is None:
                    channel = int(match.group(1))
                    if (self.edd.channel == 255 and channel == 0) or \
                            (self.edd.channel == channel):
                        self.edd.sysfslink = link
                        return path.split('/')[-1]
                else:
                    log.warning("edd: ATA Port multipliers are unsupported")
                    continue;
        return None

    def devname_from_scsi_pci_dev(self):
        name = None
        path = "/sys/devices/pci0000:00/0000:%(pci_dev)s/host%(chan)d/"\
            "target%(chan)d:0:%(dev)d/%(chan)d:0:%(dev)d:%(lun)d/block" % {
            'pci_dev' : self.edd.pci_dev,
            'chan' : self.edd.channel,
            'dev' : self.edd.scsi_id,
            'lun' : self.edd.scsi_lun,
            }
        if os.path.isdir(path):
            block_entries = os.listdir(path)
            if len(block_entries) == 1:
                name = block_entries[0]
        else:
            log.warning("edd: directory does not exist: %s", path)
        return name

    def devname_from_virt_pci_dev(self):
        name = None
        pattern = "/sys/devices/pci0000:00/0000:%(pci_dev)s/virtio*/block" % \
            {'pci_dev' : self.edd.pci_dev}
        matching_paths = glob.glob(pattern)
        if len(matching_paths) != 1 or not os.path.exists(matching_paths[0]):
            return None
        block_entries = os.listdir(matching_paths[0])
        if len(block_entries) == 1:
            name = block_entries[0]
        return name

    def devname_from_pci_dev(self):
        name = self.devname_from_virt_pci_dev()
        if not name is None:
            return name
        if self.edd.type in ("ATA", "SATA") and \
                self.edd.channel is not None and \
                self.edd.ata_device is not None:
            name = self.devname_from_ata_pci_dev()
        elif self.edd.type == "SCSI":
            name = self.devname_from_scsi_pci_dev()
        return name

    def match_via_mbrsigs(self, mbr_dict):
        """ Try to match the edd entry based on its mbr signature.

            This will obviously fail for a fresh drive/image, but in extreme
            cases can also show false positives for randomly matching data.
        """
        for (name, mbr_sig) in mbr_dict.items():
            if mbr_sig == self.edd.mbr_sig:
                return name
        return None

def biosdev_to_edd_dir(biosdev):
    return "/sys/firmware/edd/int13_dev%x" % biosdev

def collect_edd_data():
    edd_data_dict = {}
    # BIOS dev numbers are 0-127 , with 0x80 unset for floppies and set
    # for hard drives.  In practice, the kernel has had EDDMAXNR (the limit
    # on how many EDD structures it will load) set to 6 since before the
    # import into git, so that's good enough.
    for biosdev in range(0x80, 0x86):
        sysfspath = biosdev_to_edd_dir(biosdev)
        if not os.path.exists(sysfspath):
            break
        edd_data_dict[biosdev] = EddEntry(sysfspath)
    return edd_data_dict

def collect_mbrs(devices):
    """ Read MBR signatures from devices.

        Returns a dict mapping device names to their MBR signatures. It is not
        guaranteed this will succeed, with a new disk for instance.
    """
    mbr_dict = {}
    for dev in devices:
        try:
            fd = util.eintr_retry_call(os.open, dev.path, os.O_RDONLY)
            # The signature is the unsigned integer at byte 440:
            os.lseek(fd, 440, 0)
            mbrsig = struct.unpack('I', util.eintr_retry_call(os.read, fd, 4))
            util.eintr_ignore(os.close, fd)
        except OSError as e:
            log.warning("edd: error reading mbrsig from disk %s: %s",
                        dev.name, str(e))
            continue

        mbrsig_str = "0x%08x" % mbrsig
        # sanity check
        if mbrsig_str == '0x00000000':
            log.info("edd: MBR signature on %s is zero. new disk image?", dev.name)
            continue
        else:
            for (dev_name, mbrsig_str_old) in mbr_dict.items():
                if mbrsig_str_old == mbrsig_str:
                    log.error("edd: dupicite MBR signature %s for %s and %s",
                              mbrsig_str, dev_name, dev.name)
                    # this actually makes all the other data useless
                    return {}
        # update the dictionary
        mbr_dict[dev.name] = mbrsig_str
    log.info("edd: collected mbr signatures: %s", mbr_dict)
    return mbr_dict

def get_edd_dict(devices):
    """ Generates the 'device name' -> 'edd number' mapping.

        The EDD kernel module that exposes /sys/firmware/edd is thoroughly
        broken, the information there is incomplete and sometimes downright
        wrong. So after we mine out all useful information that the files under
        /sys/firmware/edd/int13_*/ can provide, we resort to heuristics and
        guessing. Our first attempt is, by looking at the device type int
        'interface', attempting to map pci device number, channel number etc. to
        a sysfs path, check that the path really exists, then read the device
        name (e.g 'sda') from there. Should this fail we try to match contents
        of 'mbr_signature' to a real MBR signature found on the existing block
        devices.
    """
    mbr_dict = collect_mbrs(devices)
    edd_entries_dict = collect_edd_data()
    for (edd_number, edd_entry) in edd_entries_dict.items():
        matcher = EddMatcher(edd_entry)
        # first try to match through the pci dev etc.
        name = matcher.devname_from_pci_dev()
        log.debug("edd: data extracted from 0x%x:\n%s", edd_number, edd_entry)
        if name:
            log.info("edd: matched 0x%x to %s using pci_dev", edd_number, name)
        # next try to compare mbr signatures
        else:
            name = matcher.match_via_mbrsigs(mbr_dict)
            if name:
                log.info("edd: matched 0x%x to %s using MBR sig", edd_number, name)

        if name:
            old_edd_number = edd_dict.get(name)
            if old_edd_number:
                log.info("edd: both edd entries 0x%x and 0x%x seem to map to %s",
                          old_edd_number, edd_number, name)
                # this means all the other data can be confused and useless
                return {}
            edd_dict[name] = edd_number
            continue
        log.error("edd: unable to match edd entry 0x%x", edd_number)
    return edd_dict

edd_dict = {}
