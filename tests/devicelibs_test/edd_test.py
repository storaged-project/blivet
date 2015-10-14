import unittest
import mock
import os
import inspect
import copy

import blivet
from blivet.devicelibs import edd

class FakeDevice(object):
    def __init__(self, name):
        self.name = name

class FakeEddEntry(edd.EddEntry):
    def __init__(self, sysfspath, **kw):
        edd.EddEntry.__init__(self, sysfspath)
        for (name,value) in kw.items():
            self.__dict__[name] = value

    @property
    def sysfspath(self):
        return "%s/%s" % (edd.fsroot, self._sysfspath[1:])

    def load(self):
        pass

    def __repr__(self):
        return "<FakeEddEntry%s>" % (self._fmt(' ', ''),)

    def __lt__(self, other):
        return self.__dict__ < other.__dict__

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

class EddTestCase(unittest.TestCase):
    _edd_logger = None
    maxDiff = None

    def setUp(self):
        super(EddTestCase, self).setUp()
        self._edd_logger = edd.log
        edd.log = mock.MagicMock(name='log')
        edd.log.info = mock.MagicMock(name='info')
        edd.log.warning = mock.MagicMock(name='warning')
        edd.log.error = mock.MagicMock(name='error')
        edd.log.debug = mock.MagicMock(name='debug')

    def tearDown(self):
        edd.log = self._edd_logger
        super(EddTestCase, self).tearDown()

    def _set_fs_root(self, edd_module, fsroot):
        if fsroot is None:
            edd_module.fsroot = ""
        else:
            dirname = os.path.dirname(inspect.getfile(edd_module))
            edd_module.fsroot = os.path.join(dirname, "../../tests/devicelibs_test/edd_data/", fsroot)

    def _respool_logs(self):
        log = edd.log
        for logname in ["debug", "info", "warning", "error"]:
            logger = getattr(log, logname)
            newlogger = getattr(self._edd_logger, logname)
            for call in logger.call_args_list:
                newlogger(*call[0])

    def _clear_logs(self):
        edd.log = mock.MagicMock(name='log')
        edd.log.info = mock.MagicMock(name='info')
        edd.log.warning = mock.MagicMock(name='warning')
        edd.log.error = mock.MagicMock(name='error')
        edd.log.debug = mock.MagicMock(name='debug')

    def _check_logs(self, debugs=None, infos=None, warnings=None, errors=None):
        for (left, right) in ((debugs, edd.log.debug),
                            (infos, edd.log.info),
                            (warnings, edd.log.warning),
                            (errors, edd.log.error)):
            left = [mock.call(*x) for x in left or []]
            left.sort()
            right = copy.copy(right.call_args_list) or []
            right.sort()
            self.assertEqual(left, right)

    def test_collect_edd_data_sata_usb(self):
        self._edd_logger.info("starting test test_collect_edd_data_sata_usb")
        # test with sata sda, usb sdb
        self._set_fs_root(edd, "sata_usb")
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                           sectors=312581808, host_bus="PCI", type="SATA",
                           pci_dev="00:1f.2", channel=255, ata_device=1,
                           interface="SATA    \tdevice: 1",
                           sysfspath="/sys/firmware/edd/int13_dev80"),
            0x81: FakeEddEntry(version="0x21", mbr_sig="0x96a20d28",
                           sectors=31293440, host_bus="PCI", type="USB",
                           pci_dev="ff:ff.255", channel=255,
                           usb_serial=0x30302e31,
                           interface="USB     \tserial_number: 30302e31",
                           sysfspath="/sys/firmware/edd/int13_dev81"),
            }

        edd_dict = edd.collect_edd_data()
        self._respool_logs()
        self.assertEqual(len(edd_dict), 2)
        self.assertEqual(fakeedd[0x80], edd_dict[0x80])
        self.assertEqual(fakeedd[0x81], edd_dict[0x81])
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
                    "/sys/firmware/edd/int13_dev80"),
            ("edd: found device 0x%x at %s", 0x81,
                    "/sys/firmware/edd/int13_dev81"),
            ]
        self._check_logs(debugs=debugs)
        self.assertEqual(edd.log.info.called, False)
        self.assertEqual(edd.log.warning.called, False)
        self.assertEqual(edd.log.error.called, False)
        self._clear_logs()

    def test_get_edd_dict_sata_usb(self):
        self._edd_logger.info("starting test test_get_edd_dict_sata_usb")
        # test with sata sda, usb sdb
        self._set_fs_root(edd, "sata_usb")
        devices=(FakeDevice("sda"),
                 FakeDevice("sdb"),
                 )
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                           sectors=312581808, host_bus="PCI", type="SATA",
                           pci_dev="00:1f.2", channel=255, ata_device=1,
                           interface="SATA    \tdevice: 1",
                           sysfspath="/sys/firmware/edd/int13_dev80",
                           sysfslink="../devices/pci0000:00/0000:00:1f.2/ata2"\
                                     "/host1/target1:0:0/1:0:0:0/block/sda"),
            0x81: FakeEddEntry(version="0x21", mbr_sig="0x96a20d28",
                           sectors=31293440, host_bus="PCI", type="USB",
                           pci_dev="ff:ff.255", channel=255,
                           usb_serial=0x30302e31,
                           interface="USB     \tserial_number: 30302e31",
                           sysfspath="/sys/firmware/edd/int13_dev81"),
            }

        edd_dict = edd.get_edd_dict(devices)
        self.assertEqual(len(edd_dict), 2)
        self.assertEqual(edd_dict["sda"], 0x80)
        self.assertEqual(edd_dict["sdb"], 0x81)
        debugs = [
            ("edd: data extracted from 0x%x:\n%r", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:\n%r", 0x81, fakeedd[0x81]),
            ("edd: found device 0x%x at %s", 0x80,
                    "/sys/firmware/edd/int13_dev80"),
            ("edd: found device 0x%x at %s", 0x81,
                    "/sys/firmware/edd/int13_dev81"),
            ]
        infos = [
            ("edd: MBR signature on %s is zero. new disk image?", "sda"),
            ("edd: collected mbr signatures: %s",{'sdb': '0x96a20d28'}),
            ("edd: matched 0x%x to %s using PCI dev", 0x80, "sda"),
            ("edd: matched 0x%x to %s using MBR sig", 0x81, "sdb"),
            ]
        warnings = [
            ("edd: interface type %s is not implemented (%s)", "USB",
                "/sys/firmware/edd/int13_dev81"),
            ("edd: interface details: %s", "USB     \tserial_number: 30302e31"),
            ]
        self._respool_logs()
        self._check_logs(debugs, infos, warnings)
        self.assertEqual(edd.log.error.called, False)
        self._clear_logs()

    def test_collect_edd_data_absurd_virt(self):
        self._edd_logger.info("starting test test_collect_edd_data_absurd_virt")
        self._set_fs_root(edd, "absurd_virt")
        # siiiigh - this is actually the data out of sysfs on a virt I have
        # created.  Apparently even qemu claims 3.0 sometimes and gives us
        # bad data.
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760, host_bus="PCI", type="SCSI",
                               pci_dev="00:07.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfspath="/sys/firmware/edd/int13_dev80"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716, host_bus="PCI", type="ATA",
                               pci_dev="00:01.1", channel=0,
                               interface="ATA     \tdevice: 1", ata_device=1,
                               sysfspath="/sys/firmware/edd/int13_dev81"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432,
                               sysfspath="/sys/firmware/edd/int13_dev82"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0xfa0a111d",
                               sectors=629146,
                               sysfspath="/sys/firmware/edd/int13_dev83"),
            0x84: FakeEddEntry(version="0x30", mbr_sig="0x63f1d7d8",
                               sectors=838862, host_bus="PCI", type="SCSI",
                               pci_dev="00:0b.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfspath="/sys/firmware/edd/int13_dev84"),
            0x85: FakeEddEntry(version="0x30", mbr_sig="0xee331b19",
                               sectors=1258292,
                               sysfspath="/sys/firmware/edd/int13_dev85"),
            }
        edd_dict = edd.collect_edd_data()
        self._respool_logs()
        self.assertEqual(len(edd_dict), 6)
        self.assertEqual(fakeedd[0x80], edd_dict[0x80])
        self.assertEqual(fakeedd[0x81], edd_dict[0x81])
        self.assertEqual(fakeedd[0x82], edd_dict[0x82])
        self.assertEqual(fakeedd[0x83], edd_dict[0x83])
        self.assertEqual(fakeedd[0x84], edd_dict[0x84])
        self.assertEqual(fakeedd[0x85], edd_dict[0x85])
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
                    "/sys/firmware/edd/int13_dev80"),
            ("edd: found device 0x%x at %s", 0x81,
                    "/sys/firmware/edd/int13_dev81"),
            ("edd: found device 0x%x at %s", 0x82,
                    "/sys/firmware/edd/int13_dev82"),
            ("edd: found device 0x%x at %s", 0x83,
                    "/sys/firmware/edd/int13_dev83"),
            ("edd: found device 0x%x at %s", 0x84,
                    "/sys/firmware/edd/int13_dev84"),
            ("edd: found device 0x%x at %s", 0x85,
                    "/sys/firmware/edd/int13_dev85"),
            ]
        self._check_logs(debugs=debugs)
        self.assertEqual(edd.log.info.called, False)
        self.assertEqual(edd.log.warning.called, False)
        self.assertEqual(edd.log.error.called, False)
        self._clear_logs()

    def test_get_edd_dict_absurd_virt(self):
        self._edd_logger.info("starting test test_get_edd_dict_absurd_virt")
        self._set_fs_root(edd, "absurd_virt")
        # siiiigh - this is actually the data out of sysfs on a virt I have
        # created.  Apparently even qemu claims 3.0 sometimes and gives us
        # bad data.
        fakeedd = {
            0x80: FakeEddEntry(version="0x30", mbr_sig="0x86531966",
                               sectors=10485760, host_bus="PCI", type="SCSI",
                               pci_dev="00:07.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfslink="../devices/pci0000:00"\
                                         "/0000:00:07.0/virtio1/vda",
                               sysfspath="/sys/firmware/edd/int13_dev80"),
            0x81: FakeEddEntry(version="0x30", mbr_sig="0x7dfff0db",
                               sectors=209716, host_bus="PCI", type="ATA",
                               pci_dev="00:01.1", channel=0,
                               interface="ATA     \tdevice: 1", ata_device=1,
                               sysfslink="../devices/pci0000:00/0000:00:01.1/"\
                                        "ata7/host6/target6:0:1/6:0:1:0/"\
                                        "block/sdb",
                               sysfspath="/sys/firmware/edd/int13_dev81"),
            0x82: FakeEddEntry(version="0x30", mbr_sig="0xe3bf124b",
                               sectors=419432,
                               sysfspath="/sys/firmware/edd/int13_dev82"),
            0x83: FakeEddEntry(version="0x30", mbr_sig="0xfa0a111d",
                               sectors=629146,
                               sysfspath="/sys/firmware/edd/int13_dev83"),
            0x84: FakeEddEntry(version="0x30", mbr_sig="0x63f1d7d8",
                               sectors=838862, host_bus="PCI", type="SCSI",
                               pci_dev="00:0b.0", channel=0, scsi_id=0,
                               scsi_lun=0, interface="SCSI    \tid: 0  lun: 0",
                               sysfslink="../devices/pci0000:00/0000:00:0b.0/"\
                                         "virtio3/host8/target8:0:0/8:0:0:0/"\
                                         "block/sdc",
                               sysfspath="/sys/firmware/edd/int13_dev84"),
            0x85: FakeEddEntry(version="0x30", mbr_sig="0xee331b19",
                               sectors=1258292,
                               sysfspath="/sys/firmware/edd/int13_dev85"),
            }
        devices=(FakeDevice("sda"),
                 FakeDevice("sdb"),
                 FakeDevice("sdc"),
                 FakeDevice("sdd"),
                 FakeDevice("sde"),
                 FakeDevice("vda"),
                 )

        edd_dict = edd.get_edd_dict(devices)
        self._edd_logger.debug(edd_dict)
        self.assertEqual(len(edd_dict), 6)
        # this order is *completely unlike* the order in virt-manager,
        # but it does appear to be what EDD is displaying.
        self.assertEqual(edd_dict["vda"], 0x80)
        self.assertEqual(edd_dict["sdb"], 0x81)
        self.assertEqual(edd_dict["sda"], 0x82)
        self.assertEqual(edd_dict["sde"], 0x83)
        self.assertEqual(edd_dict["sdc"], 0x84)
        self.assertEqual(edd_dict["sdd"], 0x85)
        debugs = [
            ("edd: data extracted from 0x%x:\n%r", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:\n%r", 0x81, fakeedd[0x81]),
            ("edd: data extracted from 0x%x:\n%r", 0x82, fakeedd[0x82]),
            ("edd: data extracted from 0x%x:\n%r", 0x83, fakeedd[0x83]),
            ("edd: data extracted from 0x%x:\n%r", 0x84, fakeedd[0x84]),
            ("edd: data extracted from 0x%x:\n%r", 0x85, fakeedd[0x85]),
            ("edd: found device 0x%x at %s", 0x80,
                    "/sys/firmware/edd/int13_dev80"),
            ("edd: found device 0x%x at %s", 0x81,
                    "/sys/firmware/edd/int13_dev81"),
            ("edd: found device 0x%x at %s", 0x82,
                    "/sys/firmware/edd/int13_dev82"),
            ("edd: found device 0x%x at %s", 0x83,
                    "/sys/firmware/edd/int13_dev83"),
            ("edd: found device 0x%x at %s", 0x84,
                    "/sys/firmware/edd/int13_dev84"),
            ("edd: found device 0x%x at %s", 0x85,
                    "/sys/firmware/edd/int13_dev85"),
            ]
        infos = [
            ("edd: collected mbr signatures: %s", { 'vda': '0x86531966',
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
            ]
        self._respool_logs()
        self._check_logs(debugs, infos)
        self.assertEqual(edd.log.warning.called, False)
        self.assertEqual(edd.log.error.called, False)
        self._clear_logs()

try:
    blivet.util.set_up_logging(log_file=os.path.join(os.environ['WORKSPACE'],
                                                     "blivet.log"))
except KeyError:
    blivet.util.set_up_logging("/tmp/blivet.log")
