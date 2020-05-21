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

import logging
import os
import re
import struct
import copy

from .. import util

log = logging.getLogger("blivet")
testdata_log = logging.getLogger("testdata")
testdata_log.setLevel(logging.DEBUG)

re_bios_device_number = re.compile(r'.*/int13_dev([0-9a-fA-F]+)/*$')
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


class EddEntry(object):

    """ This object merely collects what the /sys/firmware/edd/* entries can
        provide.
    """

    def __init__(self, sysfspath, root=None):
        self.root = util.Path(root or "", root="")

        # some misc data from various files...
        self.sysfspath = util.Path(sysfspath, root=self.root)
        """ sysfspath is the path we're probing
        """

        match = re_bios_device_number.match(sysfspath)
        self.bios_device_number = int(match.group(1), base=16)
        """ The device number from the EDD path """

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

    def _fmt(self, line_pad, separator):
        s = "%(t)spath: %(sysfspath)s version: %(version)s %(nl)s" \
            "%(t)smbr_signature: %(mbr_sig)s sectors: %(sectors)s"
        if self.type is not None:
            s += " %(type)s"
        if self.sysfslink is not None:
            s += "%(nl)s%(t)ssysfs pci path: %(sysfslink)s"
        if any([self.host_bus, self.pci_dev, self.channel is not None]):
            s += "%(nl)s%(t)shost_bus: %(host_bus)s pci_dev: %(pci_dev)s "\
                "channel: %(channel)s"
        if self.interface is not None:
            s += "%(nl)s%(t)sinterface: \"%(interface)s\""
        if any([self.atapi_device is not None, self.atapi_lun is not None]):
            s += "%(nl)s%(t)satapi_device: %(atapi_device)s " \
                 "atapi_lun: %(atapi_lun)s"
        if self.ata_device is not None:
            s += "%(nl)s%(t)sata_device: %(ata_device)s"
            if self.ata_pmp is not None:
                s += ", ata_pmp: %(ata_pmp)s"
        if any([self.scsi_id is not None, self.scsi_lun is not None]):
            s += "%(nl)s%(t)sscsi_id: %(scsi_id)s, scsi_lun: %(scsi_lun)s"
        if self.usb_serial is not None:
            s += "%(nl)s%(t)susb_serial: %(usb_serial)s"
        if self.ieee1394_eui64 is not None:
            s += "%(nl)s%(t)s1394_eui: %(ieee1394_eui64)s"
        if any([self.fibre_wwid, self.fibre_lun]):
            s += "%(nl)s%(t)sfibre wwid: %(fibre_wwid)s lun: %(fibre_lun)s"
        if self.i2o_identity is not None:
            s += "%(nl)s%(t)si2o_identity: %(i2o_identity)s"
        if any([self.sas_address, self.sas_lun]):
            s += "%(nl)s%(t)ssas_address: %(sas_address)s sas_lun: %(sas_lun)s"

        d = copy.copy(self.__dict__)
        d['t'] = line_pad
        d['nl'] = separator

        return s % d

    def __gt__(self, other):
        if not isinstance(self, other.__class__) and \
           not isinstance(other, self.__class__):
            return self.__class__ > other.__class__
        ldict = copy.copy(self.__dict__)
        rdict = copy.copy(other.__dict__)
        del ldict["root"]
        del rdict["root"]
        return ldict > rdict

    def __eq__(self, other):
        if not isinstance(self, other.__class__) and \
           not isinstance(other, self.__class__):
            return self.__class__ == other.__class__
        ldict = copy.copy(self.__dict__)
        rdict = copy.copy(other.__dict__)
        del ldict["root"]
        del rdict["root"]
        return ldict == rdict

    def __lt__(self, other):
        if not isinstance(self, other.__class__) and \
           not isinstance(other, self.__class__):
            return self.__class__ < other.__class__
        ldict = copy.copy(self.__dict__)
        rdict = copy.copy(other.__dict__)
        del ldict["root"]
        del rdict["root"]
        return ldict < rdict

    def __str__(self):
        return self._fmt('\t', '\n')

    def __repr__(self):
        return "<EddEntry%s>" % (self._fmt(' ', ''),)

    def __getitem__(self, idx):
        return str(self)[idx]

    def __len__(self):
        return len(str(self))

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
                        self.sas_address = int(unknown_match.group(2), base=16)
                        self.sas_lun = int(unknown_match.group(3), base=16)
                    else:
                        log.warning("edd: can not match interface for %s: %s",
                                    self.sysfspath, interface)
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
            match = re_host_bus_pci.match(hbus)
            if match:
                self.host_bus = match.group(1)
                self.pci_dev = match.group(2)
                self.channel = int(match.group(3))
            else:
                log.warning("edd: can not match host_bus for %s: %s",
                            self.sysfspath, hbus)


class EddMatcher(object):

    """ This object tries to match given entry to a disk device name.

        Assuming, heuristic analysis and guessing hapens here.
    """

    def __init__(self, edd_entry, root=None):
        self.edd = edd_entry
        self.root = root or ""

    def devname_from_ata_pci_dev(self):
        pattern = util.Path('/sys/block/*', root=self.root)
        retries = []

        def match_port(components, ata_port, ata_port_idx, path, link):
            fn = util.Path(util.join_paths(components[0:6] +
                                           ['ata_port', ata_port]), root=self.root)
            port_no = int(util.get_sysfs_attr(fn, 'port_no'))

            if self.edd.type == "ATA":
                # On ATA, port_no is kernel's ata_port->local_port_no, which
                # should be the same as the ata device number.
                if port_no != self.edd.ata_device:
                    return
            else:
                # On SATA, "port_no" is the kernel's ata_port->print_id, which
                # is awesomely ata_port->id + 1, where ata_port->id is edd's
                # ata_device
                if port_no != self.edd.ata_device + 1:
                    return

            fn = components[0:6] + ['link%d' % (ata_port_idx,), ]
            exp = [r'.*'] + fn + [r'dev%d\.(\d+)(\.(\d+)){0,1}$' % (ata_port_idx,)]
            exp = util.join_paths(exp)
            expmatcher = re.compile(exp)

            pmp = util.join_paths(fn + ['dev%d.*.*' % (ata_port_idx,)])
            pmp = util.Path(pmp, root=self.root)
            dev = util.join_paths(fn + ['dev%d.*' % (ata_port_idx,)])
            dev = util.Path(dev, root=self.root)
            for ataglob in [pmp, dev]:
                for atapath in ataglob.glob():
                    match = expmatcher.match(atapath.ondisk)
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
                            yield ({'link': util.Path(link, root=self.root),
                                    'path': path.split('/')[-1]})
                    else:
                        pmp = int(match.group(1))
                        if self.edd.ata_pmp == pmp:
                            yield ({'link': util.Path(link, root=self.root),
                                    'path': path.split('/')[-1]})

        answers = []
        for path in pattern.glob():
            emptyslash = util.Path("/", root=self.root)
            path = util.Path(path, root=self.root)
            link = util.sysfs_readlink(path=emptyslash, link=path)
            testdata_log.debug("sysfs link: \"%s\" -> \"%s\"", path, link)
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

            # strictly this should always be required, but #!@#!@#!@ seabios
            # iterates the sata device number /independently/ of the host
            # bridge it claims things are attached to.  In that case this
            # the scsi target will always have "0" as the ID component.
            args = {'device': self.edd.ata_device}
            exp = r"target\d+:0:%(device)s/\d+:0:%(device)s:0/block/.*" % args
            matcher = re.compile(exp)
            match = matcher.match("/".join(components[7:]))
            if not match:
                retries.append({
                    'components': components,
                    'ata_port': ata_port,
                    'ata_port_idx': ata_port_idx,
                    'path': path,
                    'link': link,
                })
                continue

            for port in match_port(components, ata_port, ata_port_idx, path,
                                   link):
                answers.append(port)

        # now handle the ones we discarded because libata's scsi id doesn't
        # match the ata_device.
        for retry in retries:
            for port in match_port(**retry):
                if answers:
                    log.warning("edd: ignoring possible extra match for ATA device %s channel %s ata %d pmp %s: %s",
                                self.edd.pci_dev, self.edd.channel,
                                self.edd.ata_device, self.edd.ata_pmp,
                                retry['path'])
                else:
                    log.warning("edd: using possible extra match for ATA device %s channel %s ata %d pmp %s: %s",
                                self.edd.pci_dev, self.edd.channel,
                                self.edd.ata_device, self.edd.ata_pmp,
                                retry['path'])
                    answers.append(port)

        if len(answers) > 1:
            log.error("edd: Found too many ATA devices for EDD device 0x%x: %s",
                      self.edd.bios_device_number,
                      [a['link'] for a in answers])
        if len(answers) > 0:
            self.edd.sysfslink = answers[0]['link']
            return answers[0]['path']
        else:
            log.warning(
                "edd: Could not find ATA device for pci dev %s channel %s ata %d pmp %s",
                self.edd.pci_dev, self.edd.channel,
                self.edd.ata_device, self.edd.ata_pmp)

        return None

    def devname_from_virtio_scsi_pci_dev(self):
        if self.edd.scsi_id is None or self.edd.scsi_lun is None:
            return None
        # Virtio SCSI looks like scsi but with a virtio%d/ stuck in the middle
        # channel appears to be a total lie on VirtIO SCSI devices.
        tmpl = "../devices/pci0000:00/0000:%(pci_dev)s/virtio*/" \
            "host*/target*:0:%(dev)d/*:0:%(dev)d:%(lun)d/block/"
        args = {
            'pci_dev': self.edd.pci_dev,
            'dev': self.edd.scsi_id,
            'lun': self.edd.scsi_lun,
        }
        pattern = util.Path(tmpl % args, root=self.root + "/sys/block/")
        answers = []
        for mp in pattern.glob():
            # Normal VirtIO devices just have the block link right there...
            block_entries = os.listdir(mp.ondisk)
            for be in block_entries:
                link = mp + be
                answers.append({'link': link, 'path': be})

        if len(answers) > 1:
            log.error("Found too many VirtIO SCSI devices for EDD device 0x%x: %s",
                      self.edd.bios_device_number,
                      [a['link'] for a in answers])
        if len(answers) > 0:
            self.edd.sysfslink = answers[0]['link']
            return answers[0]['path']
        else:
            log.info("edd: Could not find VirtIO SCSI device for pci dev %s "
                     "channel %s scsi id %s lun %s", self.edd.pci_dev,
                     self.edd.channel, self.edd.scsi_id, self.edd.scsi_lun)

    def devname_from_scsi_pci_dev(self):
        tmpl = "../devices/pci0000:00/0000:%(pci_dev)s/" \
            "host%(chan)d/target%(chan)d:0:%(dev)d/" \
            "%(chan)d:0:%(dev)d:%(lun)d/block/"
        args = {
            'pci_dev': self.edd.pci_dev,
            'chan': self.edd.channel,
            'dev': self.edd.scsi_id,
            'lun': self.edd.scsi_lun,
        }
        pattern = util.Path(tmpl % args, root=self.root + "/sys/block/")
        answers = []
        for mp in pattern.glob():
            # Normal VirtIO devices just have the block link right there...
            block_entries = os.listdir(mp.ondisk)
            for be in block_entries:
                link = mp + be
                answers.append({'link': link, 'path': be})

        if len(answers) > 1:
            log.error("Found too many SCSI devices for EDD device 0x%x: %s",
                      self.edd.bios_device_number,
                      [a['link'] for a in answers])
        if len(answers) > 0:
            self.edd.sysfslink = answers[0]['link']
            return answers[0]['path']
        else:
            log.warning("edd: Could not find SCSI device for pci dev %s "
                        "channel %s scsi id %s lun %s", self.edd.pci_dev,
                        self.edd.channel, self.edd.scsi_id, self.edd.scsi_lun)
        return None

    def devname_from_virt_pci_dev(self):
        pattern = util.Path("../devices/pci0000:00/0000:%s/virtio*/block/" %
                            (self.edd.pci_dev,), root=self.root + "/sys/block/")
        answers = []
        for mp in pattern.glob():
            # Normal VirtIO devices just have the block link right there...
            block_entries = os.listdir(mp.ondisk)
            for be in block_entries:
                link = mp + be
                answers.append({'link': link, 'path': be})

        if len(answers) > 1:
            log.error("Found too many VirtIO devices for EDD device 0x%x: %s",
                      self.edd.bios_device_number,
                      [a['link'] for a in answers])
        if len(answers) > 0:
            self.edd.sysfslink = answers[0]['link']
            return answers[0]['path']
        else:
            log.info(
                "edd: Could not find Virtio device for pci dev %s channel %s",
                self.edd.pci_dev, self.edd.channel)

        return None

    def devname_from_pci_dev(self):
        if self.edd.pci_dev is None:
            return None
        name = self.devname_from_virt_pci_dev()
        if name is not None:
            return name
        name = self.devname_from_virtio_scsi_pci_dev()
        if name is not None:
            return name

        unsupported = ("ATAPI", "USB", "1394", "I2O", "RAID", "FIBRE", "SAS")
        if self.edd.type in unsupported:
            log.warning("edd: interface type %s is not implemented (%s)",
                        self.edd.type, self.edd.sysfspath)
            log.warning("edd: interface details: %s", self.edd.interface)
        if self.edd.type in ("ATA", "SATA") and \
                self.edd.ata_device is not None:
            name = self.devname_from_ata_pci_dev()
        elif self.edd.type == "SCSI":
            name = self.devname_from_scsi_pci_dev()
        if self.edd.sysfslink:
            path = util.Path("/sys/block/", root=self.root) \
                + self.edd.sysfslink \
                + "/device"
            link = os.readlink(path.ondisk)
            testdata_log.debug("sysfs link: \"%s\" -> \"%s\"", path, link)

        return name

    def match_via_mbrsigs(self, mbr_dict):
        """ Try to match the edd entry based on its mbr signature.

            This will obviously fail for a fresh drive/image, but in extreme
            cases can also show false positives for randomly matching data.
        """
        sysblock = util.Path("/sys/block/", root=self.root)
        for (name, mbr_sig) in mbr_dict.items():
            if mbr_sig == self.edd.mbr_sig:
                self.edd.sysfslink = util.sysfs_readlink(sysblock, link=name)
                return name
        return None


def collect_edd_data(root=None):
    edd_data_dict = {}
    globstr = util.Path("/sys/firmware/edd/int13_dev*/", root=root)
    for path in globstr.glob():
        match = re_bios_device_number.match(path)
        biosdev = int("0x%s" % (match.group(1),), base=16)
        log.debug("edd: found device 0x%x at %s", biosdev, path)
        edd_data_dict[biosdev] = EddEntry(path, root=root)
    return edd_data_dict


def collect_mbrs(devices, root=None):
    """ Read MBR signatures from devices.

        Returns a dict mapping device names to their MBR signatures. It is not
        guaranteed this will succeed, with a new disk for instance.
    """
    mbr_dict = {}
    for dev in devices:
        try:
            path = util.Path("/dev", root=root) + dev.name
            fd = os.open(path.ondisk, os.O_RDONLY)
            # The signature is the unsigned integer at byte 440:
            os.lseek(fd, 440, 0)
            data = os.read(fd, 4)
            mbrsig = struct.unpack('I', data)
            sdata = struct.unpack("BBBB", data)
            sdata = "".join(["%02x" % (x,) for x in sdata])
            os.close(fd)
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


def get_edd_dict(devices, root=None):
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
    mbr_dict = collect_mbrs(devices, root=root)
    edd_entries_dict = collect_edd_data(root=root)
    edd_dict = {}
    for (edd_number, edd_entry) in edd_entries_dict.items():
        matcher = EddMatcher(edd_entry, root=root)
        # first try to match through the pci dev etc.
        name = matcher.devname_from_pci_dev()
        log.debug("edd: data extracted from 0x%x:%r", edd_number, edd_entry)
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
