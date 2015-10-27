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
import copy

from .. import util

log = logging.getLogger("blivet")
testdata_log = logging.getLogger("testdata")
testdata_log.setLevel(logging.DEBUG)

re_host_bus_pci = re.compile(r'^(PCIX|PCI|XPRS|HTPT)\s*(\S*)\s*channel: (\S*)\s*$')
re_interface_atapi = re.compile(r'^ATAPI\s*device: (\S*)\s*lun: (\S*)\s*$')
re_interface_ata = re.compile(r'^ATA\s*device: (\S*)\s*$')
re_interface_scsi = re.compile(r'^SCSI\s*id: (\S*)\s*lun: (\S*)\s*$')
re_interface_usb = re.compile(r'^USB\s*serial_number: (\S*)\s*$')
re_interface_1394 = re.compile(r'^1394\s*eui: (\S*)\s*$')
re_interface_fibre = re.compile(r'^FIBRE\s*wwid: (\S*)\s*lun: (\S*)\s*$')
re_interface_i2o = re.compile(r'^I2O\s*identity_tag: (\S*)\s*$')
# pretty sure the RAID definition using "identity_tag" is basically a kernel
# bug, but it's part of the ABI now, so it sticks.  The format of the
# scnprintf() is at least correct.
re_interface_raid = re.compile(r'^RAID\s*identity_tag: (\S*)\s*$')
re_interface_edd3_sata = re.compile(r'^SATA\s*device: (\S*)\s*$')
# EDD 4 features from 2010 and later.  Awesomely, the "version" output from
# int 13 AH=41h says: AH Version of extensions. Shall be set to 30h,
# so there's no way to distinguish these from EDD 3, even thuogh SATA does
# differ.  In theory, if we're on <4.0, pmp should always be all 0's.
re_interface_edd4_sata = re.compile(r'^SATA\s*device: (\S*)\s*pmp: (\S*)\s*$')
re_interface_sas = re.compile(r'^SAS\s*sas_address: (\S*)\s*lun: \(\S*\)\s*$')
# to make life difficult, when it finds an unknown interface type string,
# the kernel prints the values without the string.  But it does print the
# anchoring tab that would go between them...
re_interface_unknown = re.compile(r'^(\S*)\s*unknown: (\S*) (\S*)\s*$')

fsroot = ""


class EddEntry(object):

    """ This object merely collects what the /sys/firmware/edd/* entries can
        provide.
    """

    def __init__(self, sysfspath):
        # some misc data from various files...
        self._sysfspath = sysfspath
        """ sysfspath is the path we're probing
        """

        self.sysfslink = None
        """ The path /sys/block/BLAH is a symlink link to once we've resolved
            that this is a particular device.  Used for logging later.
        """

        self.version = util.get_sysfs_attr(self.sysfspath, "version")
        """ The edd version this entry claims conformance with, from
            /sys/firmware/edd/int13_devXX/version """

        self.mbr_sig = None
        """ The MBR signature data from edd/int13_devXX/mbr_signature """

        self.sectors = None
        """ The number of sectors on the device from edd/int13_devXX/sectors """

        # Now the data from edd/int13_devXX/host_bus
        self.host_bus = None
        """ The ID string for the host bus type, from
            edd/int13_devXX/host_bus.
        """
        self.pci_dev = None
        """ The host bus bus:device.function, from edd/int13_devXX/host_bus.
        """
        self.channel = None
        """ The host bus device's channel number edd/int13_devXX/host_bus.
            The spec says:
              Channel number. If more than one interface of the same type is
              accessed through a single Bus, Slot, Function, then the channel
              number shall identify each interface. If there is only one
              interface, the content of this field shall be cleared to zero. If
              there are two interfaces, such as an ATA Primary and Secondary
              interface, the primary interface shall be zero, and the secondary
              interface shall be one.

              Values 00h through FEh shall represent a valid Channel Number.

              Value FFh shall indicate that this field is not used.

              If the device is connected to a SATA controller functioning in
              non-PATA emulation mode, this byte shall be FFh.
        """

        # And now the various data from different formats of
        # edd/int13_devXX/interface .
        self.interface = None
        """ interface is the actual contents of the interface file,
            preserved for logging later.
        """

        self.type = None
        """ The device type from edd/int13_devXX/interface.
        """

        self.atapi_device = None
        """ The device number of the ATAPI device from
            edd/int13_devXX/interface when self.type is ATAPI.
        """
        self.atapi_lun = None
        """ The LUN of the ATAPI device from edd/int13_devXX/interface when
            self.type is ATAPI.
        """

        self.ata_device = None
        """ The device number from edd/int13_devXX/interface when self.type
            is ATA or SATA (because Linux treats these the same.)
        """
        self.ata_pmp = None
        """ The ATA port multiplier ID from edd/int13_devXX/interface when
            self.type is SATA.
        """

        self.scsi_id = None
        """ The SCSI device ID from edd/int13_devXX/interface when
            self.type is SCSI
        """
        self.scsi_lun = None
        """ The SCSI device LUN from edd/int13_devXX/interface when
            self.type is SCSI
        """

        self.usb_serial = None
        """ The USB storage device's serial number from
            edd/int13_devXX/interface when self.type is USB.
        """

        self.ieee1394_eui64 = None
        """ The Firewire/IEEE-1394 EUI-64 ID from edd/int13_devXX/interface
            when self.type is 1394.
        """

        self.fibre_wwid = None
        """ The FibreChannel WWID from edd/int13_devXX/interface when
            self.type is FIBRE.
        """
        self.fibre_lun = None
        """ The FibreChannel LUN from edd/int13_devXX/interface when
            self.type is FIBRE.
        """

        self.i2o_identity = None
        """ The I2O Identity from edd/int13_devXX/interface when self.type
            is I2O.
        """

        self.sas_address = None
        """ The SAS Address from edd/int13_devXX/interface when self.type
            is SAS.
        """
        self.sas_lun = None
        """ The SAS LUN from edd/int13_devXX/interface when self.type is SAS.
        """

        self.load()

    @property
    def sysfspath(self):
        return "%s/%s" % (fsroot, self._sysfspath[1:])

    def _fmt(self, line_pad, separator):
        s = "%(t)spath: %(_sysfspath)s version: %(version)s %(nl)s" \
            "mbr_signature: %(mbr_sig)s sectors: %(sectors)s"
        if self.type != None:
            s += " %(type)s"
        if self.sysfslink != None:
            s += "%(nl)s%(t)ssysfs pci path: %(sysfslink)s"
        if any([self.host_bus, self.pci_dev, self.channel != None]):
            s += "%(nl)s%(t)shost_bus: %(host_bus)s pci_dev: %(pci_dev)s "\
                "channel: %(channel)s"
        if self.interface != None:
            s += "%(nl)s%(t)sinterface: \"%(interface)s\""
        if any([self.atapi_device != None, self.atapi_lun != None]):
            s += "%(nl)s%(t)satapi_device: %(atapi_device)s " \
                 "atapi_lun: %(atapi_lun)s"
        if self.ata_device != None:
            s += "%(nl)s%(t)sata_device: %(ata_device)s"
            if self.ata_pmp != None:
                s += ", ata_pmp: %(ata_pmp)s"
        if any([self.scsi_id != None, self.scsi_lun != None]):
            s += "%(nl)s%(t)sscsi_id: %(scsi_id)s, scsi_lun: %(scsi_lun)s"
        if self.usb_serial != None:
            s += "%(nl)s%(t)susb_serial: %(usb_serial)s"
        if self.ieee1394_eui64 != None:
            s += "%(nl)s%(t)s1394_eui: %(ieee1394_eui64)s"
        if any([self.fibre_wwid, self.fibre_lun]):
            s += "%(nl)s%(t)sfibre wwid: %(fibre_wwid)s lun: %s(fibre_lun)s"
        if self.i2o_identity != None:
            s += "%(nl)s%(t)si2o_identity: %(i2o_identity)s"
        if any([self.sas_address, self.sas_lun]):
            s += "%(nl)s%(t)ssas_address: %(sas_address)s sas_lun: %(sas_lun)s"

        d = copy.copy(self.__dict__)
        d['_sysfspath'] = self._sysfspath
        d['t'] = line_pad
        d['nl'] = separator

        return s % d

    def __str__(self):
        return self._fmt('\t', '\n')

    def __repr__(self):
        return "<EddEntry%s>" % (self._fmt(' ', ''),)

    def load(self):
        interface = util.get_sysfs_attr(self.sysfspath, "interface")
        # save this so we can log it from the matcher.
        self.interface = interface
        if interface:
            try:
                self.type = interface.split()[0]
                if self.type == "ATAPI":
                    match = re_interface_atapi.match(interface)
                    self.atapi_device = int(match.group(1))
                    self.atapi_lun = int(match.group(2))
                elif self.type == "ATA":
                    match = re_interface_ata.match(interface)
                    self.ata_device = int(match.group(1))
                elif self.type == "SCSI":
                    match = re_interface_scsi.match(interface)
                    self.scsi_id = int(match.group(1))
                    self.scsi_lun = int(match.group(2))
                elif self.type == "USB":
                    match = re_interface_usb.match(interface)
                    self.usb_serial = int(match.group(1), base=16)
                elif self.type == "1394":
                    match = re_interface_1394.match(interface)
                    self.ieee1394_eui64 = int(match.group(1), base=16)
                elif self.type == "FIBRE":
                    match = re_interface_fibre.match(interface)
                    self.fibre_wwid = int(match.group(1), base=16)
                    self.fibre_lun = int(match.group(2), base=16)
                elif self.type == "I2O":
                    match = re_interface_i2o.match(interface)
                    self.i2o_identity = int(match.group(1), base=16)
                elif self.type == "RAID":
                    match = re_interface_raid.match(interface)
                    self.raid_array = int(match.group(1), base=16)
                elif self.type == "SATA":
                    match = re_interface_edd4_sata.match(interface)
                    if match:
                        self.ata_device = int(match.group(1))
                        self.ata_pmp = int(match.group(2))
                    else:
                        match = re_interface_edd3_sata.match(interface)
                        self.ata_device = int(match.group(1))
                elif self.type == "SAS":
                    sas_match = re_interface_sas.match(interface)
                    unknown_match = re_interface_unknown.match(interface)
                    if sas_match:
                        self.sas_address = int(sas_match.group(1), base=16)
                        self.sas_lun = int(sas_match.group(2), base=16)
                    elif unknown_match:
                        self.sas_address = int(unknown_match.group(1), base=16)
                        self.sas_lun = int(unknown_match.group(2), base=16)
                    else:
                        log.warning("edd: can not match interface for %s: %s",
                                    self._sysfspath, interface)
                else:
                    log.warning("edd: can not match interface for %s: %s",
                                self._sysfspath, interface)
            except AttributeError as e:
                if e.args == "'NoneType' object has no attribute 'group'":
                    log.warning("edd: can not match interface for %s: %s",
                                self._sysfspath, interface)
                else:
                    raise e

        self.mbr_sig = util.get_sysfs_attr(self.sysfspath, "mbr_signature")
        sectors = util.get_sysfs_attr(self.sysfspath, "sectors")
        if sectors:
            self.sectors = int(sectors)
        hbus = util.get_sysfs_attr(self.sysfspath, "host_bus")
        if hbus:
            match = re_host_bus_pci.match(hbus)
            if match:
                self.host_bus = match.group(1)
                self.pci_dev = match.group(2)
                self.channel = int(match.group(3))
            else:
                log.warning("edd: can not match host_bus for %s: %s",
                            self._sysfspath, hbus)


class EddMatcher(object):

    """ This object tries to match given entry to a disk device name.

        Assuming, heuristic analysis and guessing hapens here.
    """

    def __init__(self, edd_entry):
        self.edd = edd_entry

    def devname_from_ata_pci_dev(self):
        pattern = '%s/sys/block/*' % (fsroot,)
        testdata_log.debug("sysfs glob: %s", pattern[len(fsroot):])
        for path in glob.iglob(pattern):
            testdata_log.debug("sysfs glob match: %s", path[len(fsroot):])
            link = os.readlink(path)
            testdata_log.debug("sysfs link: \"%s\" -> \"%s\"",
                               path[len(fsroot):], link)
            # just add /sys/block/ at the beginning so it's always valid
            # paths in the filesystem...
            components = ['%s/sys/block' % (fsroot,)] + link.split('/')
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
            # In EDD 4, which unfortunately says to leave 0x30 as the version
            # number, the port multiplier id is an additional field on the
            # interface.  So basically we should try to use the value the
            # kernel gives us*, but we can't trust it.  Thankfully there
            # won't be a devX.Y.Z (i.e. a port multiplier device) in sysfs
            # that collides with devX.Z (a non-port-multiplied device),
            # so if we get a value from the kernel, we can try with and
            # without it.
            #
            # * When the kernel finally learns of these facts...
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
                if port_no != self.edd.ata_device + 1:
                    continue

            fn = components[0:6] + ['link%d' % (ata_port_idx,), ]
            exp = [r'^'] + fn + [r'dev%d\.(\d+)(\.(\d+)){0,1}$' % (ata_port_idx,)]
            exp = os.path.join(*exp)
            expmatcher = re.compile(exp)
            pmp_glob = fn + ['dev%d.*.*' % (ata_port_idx,)]
            pmp_glob = os.path.join(*pmp_glob)
            dev_glob = fn + ['dev%d.*' % (ata_port_idx,)]
            dev_glob = os.path.join(*dev_glob)
            for ataglob in [pmp_glob, dev_glob]:
                testdata_log.debug("sysfs glob: %s", ataglob)
                for atapath in glob.glob(ataglob):
                    testdata_log.debug("sysfs glob match: %s",
                                       atapath[len(fsroot):])
                    match = expmatcher.match(atapath)
                    if match is None:
                        continue

                    # so at this point it's devW.X.Y or devW.Z as such:
                    # dev_set_name(dev, "dev%d.%d",
                    # ap->print_id,ata_dev->devno); dev_set_name(dev,
                    # "dev%d.%d.0", ap->print_id, link->pmp); we care about
                    # print_id and pmp for matching and the ATA channel if
                    # applicable. We already checked print_id above.
                    if match.group(3) is None:
                        channel = int(match.group(1))
                        if (self.edd.channel == 255 and channel == 0) or \
                                (self.edd.channel == channel):
                            self.edd.sysfslink = link
                            return path[len(fsroot):].split('/')[-1]
                    else:
                        pmp = int(match.group(1))
                        if self.edd.ata_pmp == pmp:
                            self.edd.sysfslink = link
                            return path[len(fsroot):].split('/')[-1]
        return None

    def devname_from_scsi_pci_dev(self):
        name = None
        tmpl0 = "%(fsroot)s/sys/devices/pci0000:00/0000:%(pci_dev)s/" \
                "host%(chan)d/target%(chan)d:0:%(dev)d/" \
                "%(chan)d:0:%(dev)d:%(lun)d/block"
        # channel appears to be a total like on VirtIO SCSI devices.
        tmpl1 = "%(fsroot)s/sys/devices/pci0000:00/0000:%(pci_dev)s/virtio*/" \
                "host*/target*:0:%(dev)d/*:0:%(dev)d:%(lun)d/block"
        args = {
            'fsroot': fsroot,
            'pci_dev': self.edd.pci_dev,
            'chan': self.edd.channel,
            'dev': self.edd.scsi_id,
            'lun': self.edd.scsi_lun,
            }
        path = tmpl0 % args
        pattern = tmpl1 % args
        testdata_log.debug("sysfs glob: %s", pattern[len(fsroot):])
        matching_paths = glob.glob(pattern)
        for mp in matching_paths:
            testdata_log.debug("sysfs glob match: %s", mp[len(fsroot):])
        if os.path.isdir(path):
            block_entries = os.listdir(path)
            if len(block_entries) == 1:
                self.edd.sysfslink = "..%s/%s" % (
                                path[len(fsroot) + len("/sys"):],
                                block_entries[0])
                name = block_entries[0]
        elif len(matching_paths) > 1:
            log.error("edd: Too many devices match for pci dev %s channel %s "
                      "scsi id %s lun %s: ", self.edd.pci_dev, self.edd.channel,
                      self.edd.scsi_id, self.edd.scsi_lun)
            for matching_path in matching_paths:
                log.error("edd:   %s", matching_path)
        elif len(matching_paths) == 1 and os.path.exists(matching_paths[0]):
            block_entries = os.listdir(matching_paths[0])
            if len(block_entries) == 1:
                self.edd.sysfslink = "..%s/%s" % (
                                matching_paths[0][len(fsroot) + len("/sys"):],
                                block_entries[0])
                name = block_entries[0]
        else:
            log.warning("edd: Could not find SCSI device for pci dev %s "
                        "channel %s scsi id %s lun %s", self.edd.pci_dev,
                        self.edd.channel, self.edd.scsi_id, self.edd.scsi_lun)
        return name

    def devname_from_virt_pci_dev(self):
        args = {
            'fsroot': fsroot,
            'pci_dev': self.edd.pci_dev
            }
        pattern = "%(fsroot)s/sys/devices/pci0000:00/0000:%(pci_dev)s/virtio*"
        matching_paths = tuple(glob.glob(pattern % args))
        testdata_log.debug("sysfs glob: %s",
                           (pattern % args)[len(fsroot):])
        for mp in matching_paths:
            testdata_log.debug("sysfs glob match: %s", mp[len(fsroot):])

        if len(matching_paths) == 1 and os.path.exists(matching_paths[0]):
            # Normal VirtIO devices just have the block link right there...
            newpath = os.path.join(matching_paths[0], 'block')
            block_entries = []
            if os.path.exists(newpath):
                block_entries = os.listdir(newpath)
            if len(block_entries) == 1:
                self.edd.sysfslink = "..%s/%s" % (
                        matching_paths[0][len(fsroot) + len("/sys"):],
                        block_entries[0])
                return block_entries[0]
            else:
                # Virtio SCSI looks like scsi but with a virtio%d/ stuck in
                # the middle.
                return self.devname_from_scsi_pci_dev()

        return None

    def devname_from_pci_dev(self):
        name = self.devname_from_virt_pci_dev()
        if not name is None:
            return name

        unsupported = ("ATAPI", "USB", "1394", "I2O", "RAID", "FIBRE", "SAS")
        if self.edd.type in unsupported:
            log.warning("edd: interface type %s is not implemented (%s)",
                        self.edd.type, self.edd._sysfspath)
            log.warning("edd: interface details: %s", self.edd.interface)
        if self.edd.type in ("ATA", "SATA") and \
                self.edd.ata_device is not None:
            name = self.devname_from_ata_pci_dev()
        elif self.edd.type == "SCSI":
            name = self.devname_from_scsi_pci_dev()
        if self.edd.sysfslink:
            path = "/".join([fsroot, "sys/block", self.edd.sysfslink,
                             "device"])
            link = os.readlink(path)
            testdata_log.debug("sysfs link: \"%s\" -> \"%s\"",
                               path[len(fsroot):], link)

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


def collect_edd_data():
    edd_data_dict = {}
    exp = re.compile(r'.*/int13_dev(\d+)$')
    globstr = os.path.join(fsroot, "sys/firmware/edd/int13_dev*")
    testdata_log.debug("sysfs glob: %s", globstr[len(fsroot):])
    for path in glob.glob(globstr):
        testdata_log.debug("sysfs glob match: %s", path[len(fsroot):])
        match = exp.match(path)
        biosdev = int("0x%s" % (match.group(1),), base=16)
        log.debug("edd: found device 0x%x at %s", biosdev, path[len(fsroot):])
        edd_data_dict[biosdev] = EddEntry(path[len(fsroot):])
    return edd_data_dict


def collect_mbrs(devices):
    """ Read MBR signatures from devices.

        Returns a dict mapping device names to their MBR signatures. It is not
        guaranteed this will succeed, with a new disk for instance.
    """
    mbr_dict = {}
    for dev in devices:
        try:
            path = dev.name.split('/')
            path = os.path.join("dev", *path)
            path = "%s/%s" % (fsroot, path)
            fd = util.eintr_retry_call(os.open, path, os.O_RDONLY)
            # The signature is the unsigned integer at byte 440:
            os.lseek(fd, 440, 0)
            data = util.eintr_retry_call(os.read, fd, 4)
            mbrsig = struct.unpack('I', data)
            sdata = struct.unpack("BBBB", data)
            sdata = "".join(["%02x" % (x,) for x in sdata])
            util.eintr_ignore(os.close, fd)
            testdata_log.debug("device %s data[440:443] = %s", path, sdata)
        except OSError as e:
            testdata_log.debug("device %s data[440:443] raised %s", path, e)
            log.error("edd: could not read mbrsig from disk %s: %s",
                      dev.name, str(e))
            continue

        mbrsig_str = "0x%08x" % mbrsig
        # sanity check
        if mbrsig_str == '0x00000000':
            log.info("edd: MBR signature on %s is zero. new disk image?",
                     dev.name)
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
    edd_dict = {}
    for (edd_number, edd_entry) in edd_entries_dict.items():
        matcher = EddMatcher(edd_entry)
        # first try to match through the pci dev etc.
        name = matcher.devname_from_pci_dev()
        log.debug("edd: data extracted from 0x%x:\n%s", edd_number, edd_entry)
        if name:
            log.info("edd: matched 0x%x to %s using PCI dev", edd_number, name)
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
        else:
            log.error("edd: unable to match edd entry 0x%x", edd_number)
    return edd_dict
