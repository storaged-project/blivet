import unittest
import mock
import os
import inspect
import logging
import copy

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

    def tearDown(self):
        edd.log = self._edd_logger
        edd.log.setLevel(self._edd_logger_level)
        edd.log.removeHandler(self.log_handler)
        edd.testdata_log.removeHandler(self.td_log_handler)
        super(EddTestCase, self).tearDown()

    def checkLogs(self, debugs=None, infos=None, warnings=None, errors=None):
        def check(left, right_object):
            left = [mock.call(*x) for x in left or []]
            left.sort()
            right = copy.copy(right_object.call_args_list or [])
            right.sort()
            self.assertEqual(left, right)
            if len(left) == 0:
                self.assertEqual(right_object.called, False)
            else:
                self.assertEqual(right_object.called, True)

        check(debugs, edd.log.debug)
        check(infos, edd.log.info)
        check(warnings, edd.log.warning)
        check(errors, edd.log.error)

    def _set_fs_root(self, edd_module, fsroot):
        if fsroot is None:
            edd_module.fsroot = ""
        else:
            dirname = os.path.dirname(inspect.getfile(edd_module))
            edd_module.fsroot = os.path.abspath(os.path.join(dirname, "../../tests/devicelibs_test/edd_data/", fsroot))

    def debug(self, *args):
        fmt = "edd_test: "
        if len(args) >= 0:
            fmt += args[0]
            args = args[1:]
        self._edd_logger.debug(fmt, *args)

    def test_collect_edd_data_sata_usb(self):
        # test with sata sda, usb sdb
        self._set_fs_root(edd, "sata_usb")
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
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
        self.debug('edd_dict: %s', edd_dict)
        debugs = [
            ("edd: found device 0x%x at %s", 0x80,
                    '/sys/firmware/edd/int13_dev80'),
            ("edd: found device 0x%x at %s", 0x81,
                    '/sys/firmware/edd/int13_dev81'),
            ]
        self.assertEqual(len(edd_dict), 2)
        self.assertEqual(fakeedd[0x80], edd_dict[0x80])
        self.assertEqual(fakeedd[0x81], edd_dict[0x81])
        self.checkLogs(debugs=debugs)

    def test_get_edd_dict_sata_usb(self):
        # test with sata sda, usb sdb
        self._set_fs_root(edd, "sata_usb")
        self._edd_logger.debug("starting test %s", self._testMethodName)
        edd.testdata_log.debug("starting test %s", self._testMethodName)
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
        self.debug('edd_dict: %s', edd_dict)
        self.assertEqual(len(edd_dict), 2)
        self.assertEqual(edd_dict["sda"], 0x80)
        self.assertEqual(edd_dict["sdb"], 0x81)
        debugs = [
            ("edd: data extracted from 0x%x:\n%s", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:\n%s", 0x81, fakeedd[0x81]),
            ("edd: found device 0x%x at %s", 0x80,
                    '/sys/firmware/edd/int13_dev80'),
            ("edd: found device 0x%x at %s", 0x81,
                    '/sys/firmware/edd/int13_dev81'),
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
        self.checkLogs(debugs=debugs, infos=infos, warnings=warnings)
