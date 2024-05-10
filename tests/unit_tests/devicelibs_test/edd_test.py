import copy
import logging
import os
import unittest

from unittest import mock

from blivet import arch
from blivet.devicelibs import edd
from . import lib


class FakeDevice(object):

    def __init__(self, name):
        self.name = name


class FakeEddEntry(edd.EddEntry):

    def __init__(self, sysfspath, **kw):
        edd.EddEntry.__init__(self, sysfspath)
        for (name, value) in kw.items():
            self.__dict__[name] = value

    def load(self):
        pass

    def __repr__(self):
        return "<FakeEddEntry%s>" % (self._fmt(' ', ''),)


@unittest.skipUnless(arch.get_arch() in ['x86', 'x86_64'],
                     reason='incompatible arch')
class EddTestCase(unittest.TestCase):

    def __init__(self, *args, **kwds):
        super(EddTestCase, self).__init__(*args, **kwds)
        self._edd_logger = None

        # these don't follow PEP8 because unittest.TestCase expects them this way
        self.maxDiff = None
        self.longMessage = True

    def setUp(self):
        super(EddTestCase, self).setUp()
        if 'WORKSPACE' in os.environ.keys():
            ws = os.environ['WORKSPACE']
        else:
            ws = "/tmp"
        self.log_handler = logging.FileHandler("%s/%s" % (ws, "blivet-edd.log"))
        self.log_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self.log_handler.setFormatter(formatter)
        edd.log.addHandler(self.log_handler)

        self.td_log_handler = logging.FileHandler("%s/%s" %
                                                  (ws, "blivet-edd-testdata.log"))
        self.td_log_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self.td_log_handler.setFormatter(formatter)
        edd.testdata_log.addHandler(self.td_log_handler)

        self._edd_logger = edd.log
        self._edd_logger_level = edd.log.level
        self._edd_testdata_logger = edd.testdata_log
        self._edd_testdata_logger_level = edd.testdata_log.level
        edd.log.setLevel(logging.DEBUG)
        newlog = mock.MagicMock(name='log')
        newlog.debug = mock.Mock(name='debug',
                                 side_effect=self._edd_logger.debug)
        newlog.info = mock.Mock(name='info',
                                side_effect=self._edd_logger.info)
        newlog.warning = mock.Mock(name='warning',
                                   side_effect=self._edd_logger.warning)
        newlog.error = mock.Mock(name='error',
                                 side_effect=self._edd_logger.error)
        edd.log = newlog

        self.addCleanup(self._clean_up)

    def _clean_up(self):
        edd.log = self._edd_logger
        edd.log.setLevel(self._edd_logger_level)
        edd.log.removeHandler(self.log_handler)
        os.remove(self.log_handler.baseFilename)
        edd.testdata_log.removeHandler(self.td_log_handler)
        os.remove(self.td_log_handler.baseFilename)

    def check_logs(self, debugs=None, infos=None, warnings=None, errors=None):
        def check(left, right_object):
            newleft = [mock.call(*x) for x in left or []]
            right = copy.copy(right_object.call_args_list or [])
            lib.assertVerboseListEqual(newleft, right)
            if len(newleft) == 0:
                lib.assertVerboseEqual(right_object.called, False)
            else:
                lib.assertVerboseEqual(right_object.called, True)

        check(debugs, edd.log.debug)
        check(infos, edd.log.info)
        check(warnings, edd.log.warning)
        check(errors, edd.log.error)

    def root(self, name):
        if name is None:
            return ""
        else:
            if name.endswith("/"):
                name = name[:-1]
            if name.startswith("/"):
                name = name[1:]
            dirname = os.path.abspath(os.path.dirname(__file__))
            return os.path.join(dirname,
                                "edd_data/",
                                name)

    def edd_debug(self, *args):
        fmt = "edd_test: "
        if len(args) >= 0:
            fmt += args[0]
            args = args[1:]
        self._edd_logger.debug(fmt, *args)

    def test_collect_edd_data_sata_usb(self):
        # test with sata sda, usb sdb
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                               sectors=312581808, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=1,
                               interface="SATA    \tdevice: 1",
                               sysfspath="/sys/firmware/edd/int13_dev80/"),
            0x81: FakeEddEntry(version="0x21", mbr_sig="0x96a20d28",
                               sectors=31293440, host_bus="PCI", type="USB",
                               pci_dev="ff:ff.255", channel=255,
                               usb_serial=0x30302e31,
                               interface="USB     \tserial_number: 30302e31",
                               sysfspath="/sys/firmware/edd/int13_dev81/"),
        }

        edd_dict = edd.collect_edd_data(root=self.root("sata_usb"))
        self.edd_debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
        ]
        lib.assertVerboseEqual(len(edd_dict), 2)
        lib.assertVerboseEqual(fakeedd[0x80], edd_dict[0x80])
        lib.assertVerboseEqual(fakeedd[0x81], edd_dict[0x81])
        self.check_logs(debugs=debugs)

    def test_get_edd_dict_sata_usb(self):
        # test with sata sda, usb sdb
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   )
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                               sectors=312581808, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=1,
                               interface="SATA    \tdevice: 1",
                               sysfspath="/sys/firmware/edd/int13_dev80/",
                               sysfslink="../devices/pci0000:00/0000:00:1f.2/"
                               "ata2/host1/target1:0:0/1:0:0:0/block/sda"),
            0x81: FakeEddEntry(version="0x21", mbr_sig="0x96a20d28",
                               sectors=31293440, host_bus="PCI", type="USB",
                               pci_dev="ff:ff.255", channel=255,
                               usb_serial=0x30302e31,
                               interface="USB     \tserial_number: 30302e31",
                               sysfspath="/sys/firmware/edd/int13_dev81/",
                               sysfslink="../devices/pci0000:00/0000:00:1d.0/"
                               "usb4/4-1/4-1.2/4-1.2:1.0/host6/target6:0:0/"
                               "6:0:0:0/block/sdb"),
        }

        edd_dict = edd.get_edd_dict(devices, root=self.root("sata_usb"))
        self.edd_debug('edd_dict: %s', edd_dict)
        lib.assertVerboseEqual(len(edd_dict), 2)
        lib.assertVerboseEqual(edd_dict["sda"], 0x80)
        lib.assertVerboseEqual(edd_dict["sdb"], 0x81)
        debugs = [
            ("edd: data extracted from 0x%x:%r", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:%r", 0x81, fakeedd[0x81]),
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
        ]
        infos = [
            ("edd: MBR signature on %s is zero. new disk image?", "sda"),
            ("edd: collected mbr signatures: %s", {'sdb': '0x96a20d28'}),
            ("edd: matched 0x%x to %s using PCI dev", 0x80, "sda"),
            ("edd: matched 0x%x to %s using MBR sig", 0x81, "sdb"),
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:1f.2', 255),
            ('edd: Could not find Virtio device for pci dev %s channel %s', 'ff:ff.255', 255),
        ]
        warnings = [
            ("edd: interface type %s is not implemented (%s)", "USB",
                "/sys/firmware/edd/int13_dev81/"),
            ("edd: interface details: %s", "USB     \tserial_number: 30302e31"),
            ('edd: using possible extra match for ATA device %s channel %s ata %d pmp %s: %s', '00:1f.2', 255, 1, None, '/sys/block/sda')
        ]
        self.check_logs(debugs=debugs, infos=infos, warnings=warnings)

    def test_collect_edd_data_absurd_virt(self):
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        # siiiigh - this is actually the data out of sysfs on a virt I have
        # created.  Apparently even qemu claims 3.0 sometimes and gives us
        # bad data.
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760, host_bus="PCI", type="SCSI",
                               pci_dev="00:07.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfspath="/sys/firmware/edd/int13_dev80/"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716, host_bus="PCI", type="ATA",
                               pci_dev="00:01.1", channel=0,
                               interface="ATA     \tdevice: 1", ata_device=1,
                               sysfspath="/sys/firmware/edd/int13_dev81/"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432,
                               sysfspath="/sys/firmware/edd/int13_dev82/"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0xfa0a111d",
                               sectors=629146,
                               sysfspath="/sys/firmware/edd/int13_dev83/"),
            0x84: FakeEddEntry(version="0x30", mbr_sig="0x63f1d7d8",
                               sectors=838862, host_bus="PCI", type="SCSI",
                               pci_dev="00:0b.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfspath="/sys/firmware/edd/int13_dev84/"),
            0x85: FakeEddEntry(version="0x30", mbr_sig="0xee331b19",
                               sectors=1258292,
                               sysfspath="/sys/firmware/edd/int13_dev85/"),
        }
        edd_dict = edd.collect_edd_data(root=self.root('absurd_virt'))
        self.edd_debug('edd_dict: %s', edd_dict)
        lib.assertVerboseEqual(len(edd_dict), 6)
        lib.assertVerboseEqual(fakeedd[0x80], edd_dict[0x80])
        lib.assertVerboseEqual(fakeedd[0x81], edd_dict[0x81])
        lib.assertVerboseEqual(fakeedd[0x82], edd_dict[0x82])
        lib.assertVerboseEqual(fakeedd[0x83], edd_dict[0x83])
        lib.assertVerboseEqual(fakeedd[0x84], edd_dict[0x84])
        lib.assertVerboseEqual(fakeedd[0x85], edd_dict[0x85])
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
            ("edd: found device 0x%x at %s", 0x83,
             '/sys/firmware/edd/int13_dev83/'),
            ("edd: found device 0x%x at %s", 0x84,
             '/sys/firmware/edd/int13_dev84/'),
            ("edd: found device 0x%x at %s", 0x85,
             '/sys/firmware/edd/int13_dev85/'),
        ]
        self.check_logs(debugs=debugs)

    def test_get_edd_dict_absurd_virt(self):
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        # siiiigh - this is actually the data out of sysfs on a virt I have
        # created.  Apparently even qemu claims 3.0 sometimes and gives us
        # bad data.
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760, host_bus="PCI", type="SCSI",
                               pci_dev="00:07.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfspath="/sys/firmware/edd/int13_dev80/",
                               sysfslink="../devices/pci0000:00/0000:00:07.0/"
                               "virtio1/block/vda"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716, host_bus="PCI", type="ATA",
                               pci_dev="00:01.1", channel=0,
                               interface="ATA     \tdevice: 1", ata_device=1,
                               sysfslink="../devices/pci0000:00/0000:00:01.1/"
                               "ata7/host6/target6:0:1/6:0:1:0/block/sdb",
                               sysfspath="/sys/firmware/edd/int13_dev81/"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432,
                               sysfslink="../devices/pci0000:00/0000:00:03.0/"
                               "ata1/host0/target0:0:0/0:0:0:0/block/sda",
                               sysfspath="/sys/firmware/edd/int13_dev82/"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0xfa0a111d",
                               sectors=629146,
                               sysfslink="../devices/pci0000:00/0000:00:0a.0/"
                               "host10/target10:0:1/10:0:1:0/block/sde",
                               sysfspath="/sys/firmware/edd/int13_dev83/"),
            0x84: FakeEddEntry(version="0x30", mbr_sig="0x63f1d7d8",
                               sectors=838862, host_bus="PCI", type="SCSI",
                               pci_dev="00:0b.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfslink="../devices/pci0000:00/0000:00:0b.0/"
                               "virtio3/host8/target8:0:0/8:0:0:0/block/sdc",
                               sysfspath="/sys/firmware/edd/int13_dev84/"),
            0x85: FakeEddEntry(version="0x30", mbr_sig="0xee331b19",
                               sectors=1258292,
                               sysfslink="../devices/pci0000:00/0000:00:06.7/"
                               "usb1/1-1/1-1:1.0/host9/target9:0:0/9:0:0:0/"
                               "block/sdd",
                               sysfspath="/sys/firmware/edd/int13_dev85/"),
        }
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   FakeDevice("sdc"),
                   FakeDevice("sdd"),
                   FakeDevice("sde"),
                   FakeDevice("vda"),
                   )

        edd_dict = edd.get_edd_dict(devices, root=self.root("absurd_virt"))
        self.edd_debug('edd_dict: %s', edd_dict)
        lib.assertVerboseEqual(len(edd_dict), 6)
        # this order is *completely unlike* the order in virt-manager,
        # but it does appear to be what EDD is displaying.
        lib.assertVerboseEqual(edd_dict["vda"], 0x80)
        lib.assertVerboseEqual(edd_dict["sdb"], 0x81)
        lib.assertVerboseEqual(edd_dict["sda"], 0x82)
        lib.assertVerboseEqual(edd_dict["sde"], 0x83)
        lib.assertVerboseEqual(edd_dict["sdc"], 0x84)
        lib.assertVerboseEqual(edd_dict["sdd"], 0x85)
        debugs = [
            ("edd: data extracted from 0x%x:%r", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:%r", 0x81, fakeedd[0x81]),
            ("edd: data extracted from 0x%x:%r", 0x82, fakeedd[0x82]),
            ("edd: data extracted from 0x%x:%r", 0x83, fakeedd[0x83]),
            ("edd: data extracted from 0x%x:%r", 0x84, fakeedd[0x84]),
            ("edd: data extracted from 0x%x:%r", 0x85, fakeedd[0x85]),
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
            ("edd: found device 0x%x at %s", 0x83,
             '/sys/firmware/edd/int13_dev83/'),
            ("edd: found device 0x%x at %s", 0x84,
             '/sys/firmware/edd/int13_dev84/'),
            ("edd: found device 0x%x at %s", 0x85,
             '/sys/firmware/edd/int13_dev85/'),
        ]
        infos = [
            ("edd: collected mbr signatures: %s", {'vda': '0x86531966',
                                                   'sda': '0xe3bf124b',
                                                   'sdb': '0x7dfff0db',
                                                   'sdc': '0x63f1d7d8',
                                                   'sdd': '0xee331b19',
                                                   'sde': '0xfa0a111d',
                                                   }),
            ("edd: matched 0x%x to %s using PCI dev", 0x80, "vda"),
            ("edd: matched 0x%x to %s using PCI dev", 0x81, "sdb"),
            ("edd: matched 0x%x to %s using MBR sig", 0x82, "sda"),
            ("edd: matched 0x%x to %s using MBR sig", 0x83, "sde"),
            ("edd: matched 0x%x to %s using PCI dev", 0x84, "sdc"),
            ("edd: matched 0x%x to %s using MBR sig", 0x85, "sdd"),
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:01.1', 0),
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:0b.0', 0),
        ]
        warnings = [
            ('edd: ignoring possible extra match for ATA device %s channel %s ata %d pmp %s: %s', '00:01.1', 0, 1, None, '/sys/block/sr0'),
        ]
        self.check_logs(debugs=debugs, infos=infos, warnings=warnings)

    def test_collect_mbrs_strawberry_mountain(self):
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   FakeDevice("sdc"),
                   FakeDevice("sdd"),
                   )
        fake_mbr_dict = {'sdc': '0x00033091',
                         'sdd': '0x91271645',
                         }
        mbr_dict = edd.collect_mbrs(devices,
                                    root=self.root('strawberry_mountain'))
        infos = [
            ("edd: MBR signature on %s is zero. new disk image?", "sda"),
            ("edd: MBR signature on %s is zero. new disk image?", "sdb"),
            ("edd: collected mbr signatures: %s", {'sdc': '0x00033091',
                                                   'sdd': '0x91271645',
                                                   }),
        ]
        warnings = [
        ]
        self.check_logs(infos=infos, warnings=warnings)
        lib.assertVerboseEqual(fake_mbr_dict, mbr_dict)

    def test_collect_edd_data_strawberry_mountain(self):
        # test with sata sda, usb sdb
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        fakeedd = {
            0x80: FakeEddEntry(version="0x21", mbr_sig="0x91271645",
                               sectors=31293440, host_bus="PCI", type="USB",
                               pci_dev="ff:ff.255", channel=255,
                               interface="USB     \tserial_number: 30302e31",
                               usb_serial=0x30302e31,
                               sysfspath="/sys/firmware/edd/int13_dev80/"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0x00033091",
                               sectors=312581808, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=2,
                               interface="SATA    \tdevice: 2",
                               sysfspath="/sys/firmware/edd/int13_dev81/"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                               sectors=156301488, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=1,
                               interface="SATA    \tdevice: 1",
                               sysfspath="/sys/firmware/edd/int13_dev82/"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                               sectors=312581808, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=0,
                               interface="SATA    \tdevice: 0",
                               sysfspath="/sys/firmware/edd/int13_dev83/"),
        }

        edd_dict = edd.collect_edd_data(root=self.root('strawberry_mountain'))
        self.edd_debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
            ("edd: found device 0x%x at %s", 0x83,
             '/sys/firmware/edd/int13_dev83/'),
        ]
        self.check_logs(debugs=debugs)
        lib.assertVerboseEqual(fakeedd[0x80], edd_dict[0x80])
        lib.assertVerboseEqual(fakeedd[0x81], edd_dict[0x81])
        lib.assertVerboseEqual(fakeedd[0x82], edd_dict[0x82])
        lib.assertVerboseEqual(fakeedd[0x83], edd_dict[0x83])
        lib.assertVerboseEqual(len(edd_dict), 4)

    def test_get_edd_dict_strawberry_mountain(self):
        # test with sata sda, usb sdb
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   FakeDevice("sdc"),
                   FakeDevice("sdd"),
                   )
        fakeedd = {
            0x80: FakeEddEntry(version="0x21", mbr_sig="0x91271645",
                               sectors=31293440, host_bus="PCI", type="USB",
                               pci_dev="ff:ff.255", channel=255,
                               interface="USB     \tserial_number: 30302e31",
                               usb_serial=0x30302e31,
                               sysfslink="../devices/pci0000:00/0000:00:1d.0/"
                               "usb4/4-1/4-1.2/4-1.2:1.0/host6/target6:0:0/"
                               "6:0:0:0/block/sdd",
                               sysfspath="/sys/firmware/edd/int13_dev80/"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0x00033091",
                               sectors=312581808, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=2,
                               interface="SATA    \tdevice: 2",
                               sysfspath="/sys/firmware/edd/int13_dev81/",
                               sysfslink="../devices/pci0000:00/0000:00:1f.2/"
                               "ata3/host2/target2:0:0/2:0:0:0/block/sdc"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                               sectors=156301488, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=1,
                               interface="SATA    \tdevice: 1",
                               sysfspath="/sys/firmware/edd/int13_dev82/",
                               sysfslink="../devices/pci0000:00/0000:00:1f.2/"
                               "ata2/host1/target1:0:0/1:0:0:0/block/sdb"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                               sectors=312581808, host_bus="PCI", type="SATA",
                               pci_dev="00:1f.2", channel=255, ata_device=0,
                               interface="SATA    \tdevice: 0",
                               sysfspath="/sys/firmware/edd/int13_dev83/",
                               sysfslink="../devices/pci0000:00/0000:00:1f.2/"
                               "ata1/host0/target0:0:0/0:0:0:0/block/sda"),
        }

        edd_dict = edd.get_edd_dict(devices,
                                    root=self.root('strawberry_mountain'))
        self.edd_debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: data extracted from 0x%x:%r", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:%r", 0x81, fakeedd[0x81]),
            ("edd: data extracted from 0x%x:%r", 0x82, fakeedd[0x82]),
            ("edd: data extracted from 0x%x:%r", 0x83, fakeedd[0x83]),
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
            ("edd: found device 0x%x at %s", 0x83,
             '/sys/firmware/edd/int13_dev83/'),
        ]
        infos = [
            ("edd: MBR signature on %s is zero. new disk image?", "sda"),
            ("edd: MBR signature on %s is zero. new disk image?", "sdb"),
            ("edd: collected mbr signatures: %s", {'sdc': '0x00033091',
                                                   'sdd': '0x91271645',
                                                   }),
            ("edd: matched 0x%x to %s using MBR sig", 0x80, "sdd"),
            ("edd: matched 0x%x to %s using PCI dev", 0x81, "sdc"),
            ("edd: matched 0x%x to %s using PCI dev", 0x82, "sdb"),
            ("edd: matched 0x%x to %s using PCI dev", 0x83, "sda"),
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:1f.2', 255),
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:1f.2', 255),
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:1f.2', 255),
            ('edd: Could not find Virtio device for pci dev %s channel %s', 'ff:ff.255', 255)
        ]
        warnings = [
            ("edd: interface type %s is not implemented (%s)", "USB",
                "/sys/firmware/edd/int13_dev80/"),
            ("edd: interface details: %s", "USB     \tserial_number: 30302e31"),
            ('edd: using possible extra match for ATA device %s channel %s ata %d pmp %s: %s', '00:1f.2', 255, 1, None, '/sys/block/sdb'),
            ('edd: using possible extra match for ATA device %s channel %s ata %d pmp %s: %s', '00:1f.2', 255, 2, None, '/sys/block/sdc'),
        ]
        self.check_logs(debugs=debugs, infos=infos, warnings=warnings)
        lib.assertVerboseEqual(edd_dict["sda"], 0x83)
        lib.assertVerboseEqual(edd_dict["sdb"], 0x82)
        lib.assertVerboseEqual(edd_dict["sdc"], 0x81)
        lib.assertVerboseEqual(edd_dict["sdd"], 0x80)
        lib.assertVerboseEqual(len(edd_dict), 4)

    def test_collect_mbrs_bad_sata_virt(self):
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   FakeDevice("sdc"),
                   )
        fake_mbr_dict = {'sda': '0xe3bf124b',
                         'sdb': '0x7dfff0db',
                         'sdc': '0x86531966',
                         }
        mbr_dict = edd.collect_mbrs(devices, root=self.root("bad_sata_virt"))
        infos = [
            ("edd: collected mbr signatures: %s", {'sda': '0xe3bf124b',
                                                   'sdb': '0x7dfff0db',
                                                   'sdc': '0x86531966',
                                                   }),
        ]
        self.check_logs(infos=infos)
        lib.assertVerboseEqual(fake_mbr_dict, mbr_dict)

    def test_collect_edd_data_bad_sata_virt(self):
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        # test with sata sda, usb sdb
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760,
                               sysfspath="/sys/firmware/edd/int13_dev80/"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432,
                               sysfspath="/sys/firmware/edd/int13_dev81/"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716,
                               sysfspath="/sys/firmware/edd/int13_dev82/"),
        }

        edd_dict = edd.collect_edd_data(root=self.root("bad_sata_virt"))
        self.edd_debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
        ]
        self.check_logs(debugs=debugs)
        lib.assertVerboseEqual(fakeedd[0x80], edd_dict[0x80])
        lib.assertVerboseEqual(fakeedd[0x81], edd_dict[0x81])
        lib.assertVerboseEqual(fakeedd[0x82], edd_dict[0x82])
        lib.assertVerboseEqual(len(edd_dict), 3)

    def test_get_edd_dict_bad_sata_virt(self):
        # test with sata sda, usb sdb
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   FakeDevice("sdc"),
                   )
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760,
                               sysfspath="/sys/firmware/edd/int13_dev80/",
                               sysfslink="../devices/pci0000:00/0000:00:0c.0/"
                               "ata11/host10/target10:0:0/10:0:0:0/block/sdc"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432,
                               sysfspath="/sys/firmware/edd/int13_dev81/",
                               sysfslink="../devices/pci0000:00/0000:00:03.0/"
                               "ata1/host0/target0:0:0/0:0:0:0/block/sda"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716,
                               sysfspath="/sys/firmware/edd/int13_dev82/",
                               sysfslink="../devices/pci0000:00/0000:00:0c.0/"
                               "ata10/host9/target9:0:0/9:0:0:0/block/sdb"),
        }

        edd_dict = edd.get_edd_dict(devices, root=self.root('bad_sata_virt'))
        self.edd_debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
            ('edd: data extracted from 0x%x:%r', 0x80, fakeedd[0x80]),
            ('edd: data extracted from 0x%x:%r', 0x81, fakeedd[0x81]),
            ('edd: data extracted from 0x%x:%r', 0x82, fakeedd[0x82]),
        ]
        infos = [
            ('edd: collected mbr signatures: %s', {'sda': '0xe3bf124b',
                                                   'sdb': '0x7dfff0db',
                                                   'sdc': '0x86531966',
                                                   }),
            ('edd: matched 0x%x to %s using MBR sig', 128, 'sdc'),
            ('edd: matched 0x%x to %s using MBR sig', 129, 'sda'),
            ('edd: matched 0x%x to %s using MBR sig', 130, 'sdb'),
        ]
        warnings = [
        ]
        self.check_logs(debugs=debugs, infos=infos, warnings=warnings)
        lib.assertVerboseEqual(edd_dict["sdc"], 0x80)
        lib.assertVerboseEqual(edd_dict["sda"], 0x81)
        lib.assertVerboseEqual(edd_dict["sdb"], 0x82)
        lib.assertVerboseEqual(len(edd_dict), 3)

    def test_collect_mbrs_mostly_fixed_virt(self):
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   FakeDevice("sdc"),
                   FakeDevice("vda"),
                   )
        fake_mbr_dict = {'sda': '0xe3bf124b',
                         'sdb': '0x7dfff0db',
                         'sdc': '0x648873aa',
                         'vda': '0x86531966',
                         }
        mbr_dict = edd.collect_mbrs(devices,
                                    root=self.root('mostly_fixed_virt'))
        infos = [
            ("edd: collected mbr signatures: %s", {'sda': '0xe3bf124b',
                                                   'sdb': '0x7dfff0db',
                                                   'sdc': '0x648873aa',
                                                   'vda': '0x86531966',
                                                   }),
        ]
        self.check_logs(infos=infos)
        lib.assertVerboseEqual(fake_mbr_dict, mbr_dict)

    def test_collect_edd_data_mostly_fixed_virt(self):
        # test with sata sda, usb sdb
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760, host_bus="PCI", type="SCSI",
                               pci_dev="00:07.0", channel=255, scsi_id=0xffff,
                               scsi_lun=281474976645120,
                               interface="SCSI    \tid: 65535  lun: 281474976645120",
                               sysfspath="/sys/firmware/edd/int13_dev80/"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432, host_bus="PCI", type="SATA",
                               pci_dev="00:03.0", channel=255, ata_device=0,
                               interface="SATA    \tdevice: 0",
                               sysfspath="/sys/firmware/edd/int13_dev81/"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716, host_bus="PCI", type="SATA",
                               pci_dev="00:0c.0", channel=255, ata_device=3,
                               interface="SATA    \tdevice: 3",
                               sysfspath="/sys/firmware/edd/int13_dev82/"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0x648873aa",
                               sectors=0,
                               sysfspath="/sys/firmware/edd/int13_dev83/"),
        }

        edd_dict = edd.collect_edd_data(root=self.root('mostly_fixed_virt'))
        self.edd_debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
            ("edd: found device 0x%x at %s", 0x83,
             '/sys/firmware/edd/int13_dev83/'),
        ]
        self.check_logs(debugs=debugs)
        lib.assertVerboseEqual(fakeedd[0x80], edd_dict[0x80])
        lib.assertVerboseEqual(fakeedd[0x81], edd_dict[0x81])
        lib.assertVerboseEqual(fakeedd[0x82], edd_dict[0x82])
        lib.assertVerboseEqual(fakeedd[0x83], edd_dict[0x83])
        lib.assertVerboseEqual(len(edd_dict), 4)

    def test_get_edd_dict_mostly_fixed_virt(self):
        # test with sata sda, usb sdb
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
        devices = (FakeDevice("sda"),
                   FakeDevice("sdb"),
                   FakeDevice("sdc"),
                   FakeDevice("vda"),
                   )
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760, host_bus="PCI", type="SCSI",
                               pci_dev="00:07.0", channel=255, scsi_id=0xffff,
                               scsi_lun=281474976645120,
                               interface="SCSI    \tid: 65535  lun: 281474976645120",
                               sysfslink="../devices/pci0000:00/0000:00:07.0/"
                               "virtio1/block/vda",
                               sysfspath="/sys/firmware/edd/int13_dev80/"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432, host_bus="PCI", type="SATA",
                               pci_dev="00:03.0", channel=255, ata_device=0,
                               interface="SATA    \tdevice: 0",
                               sysfslink="../devices/pci0000:00/0000:00:03.0/"
                               "ata1/host0/target0:0:0/0:0:0:0/block/sda",
                               sysfspath="/sys/firmware/edd/int13_dev81/"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716, host_bus="PCI", type="SATA",
                               pci_dev="00:0c.0", channel=255, ata_device=3,
                               interface="SATA    \tdevice: 3",
                               sysfslink="../devices/pci0000:00/0000:00:0c.0/"
                               "ata10/host9/target9:0:0/9:0:0:0/block/sdb",
                               sysfspath="/sys/firmware/edd/int13_dev82/"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0x648873aa",
                               sectors=0,
                               sysfslink="../devices/pci0000:00/0000:00:06.7/"
                               "usb1/1-1/1-1:1.0/host14/target14:0:0/14:0:0:0/"
                               "block/sdc",
                               sysfspath="/sys/firmware/edd/int13_dev83/"),
        }

        edd_dict = edd.get_edd_dict(devices, root=self.root('mostly_fixed_virt'))
        self.edd_debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
             '/sys/firmware/edd/int13_dev80/'),
            ("edd: found device 0x%x at %s", 0x81,
             '/sys/firmware/edd/int13_dev81/'),
            ("edd: found device 0x%x at %s", 0x82,
             '/sys/firmware/edd/int13_dev82/'),
            ("edd: found device 0x%x at %s", 0x83,
             '/sys/firmware/edd/int13_dev83/'),
            ('edd: data extracted from 0x%x:%r', 0x80, fakeedd[0x80]),
            ('edd: data extracted from 0x%x:%r', 0x81, fakeedd[0x81]),
            ('edd: data extracted from 0x%x:%r', 0x82, fakeedd[0x82]),
            ('edd: data extracted from 0x%x:%r', 0x83, fakeedd[0x83]),
        ]
        infos = [
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:03.0', 255),
            ('edd: Could not find Virtio device for pci dev %s channel %s', '00:0c.0', 255),
            ('edd: collected mbr signatures: %s', {'vda': '0x86531966',
                                                   'sda': '0xe3bf124b',
                                                   'sdb': '0x7dfff0db',
                                                   'sdc': '0x648873aa',
                                                   }),
            ('edd: matched 0x%x to %s using PCI dev', 0x80, 'vda'),
            ('edd: matched 0x%x to %s using PCI dev', 0x81, 'sda'),
            ('edd: matched 0x%x to %s using PCI dev', 0x82, 'sdb'),
            ('edd: matched 0x%x to %s using MBR sig', 0x83, 'sdc'),
        ]
        warnings = [
            ('edd: using possible extra match for ATA device %s channel %s ata %d pmp %s: %s', '00:0c.0', 255, 3, None, '/sys/block/sdb'),
        ]
        self.check_logs(debugs=debugs, infos=infos, warnings=warnings)
        lib.assertVerboseEqual(edd_dict["vda"], 0x80)
        lib.assertVerboseEqual(edd_dict["sda"], 0x81)
        lib.assertVerboseEqual(edd_dict["sdb"], 0x82)
        lib.assertVerboseEqual(edd_dict["sdc"], 0x83)
        lib.assertVerboseEqual(len(edd_dict), 4)
