import unittest
import mock
import os
import inspect

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
    def setUp(self):
        super(EddTestCase, self).setUp()
        self._edd_logger = edd.log
        edd.log = mock.MagicMock(name='log')
        edd.log.info = mock.MagicMock(name='info')
        edd.log.warning = mock.MagicMock(name='warning')
        edd.log.error = mock.MagicMock(name='error')
        edd.log.debug = mock.MagicMock(name='debug')

    def tearDown(self):
        super(EddTestCase, self).tearDown()
        edd.log = self._edd_logger

    def _set_fs_root(self, edd_module, fsroot):
        if fsroot is None:
            edd_module.fsroot = ""
        else:
            dirname = os.path.dirname(inspect.getfile(edd_module))
            edd_module.fsroot = os.path.join(dirname, "../../tests/devicelibs_test/edd_data/", fsroot)

    def test_biosdev_to_edd_dir(self):
        self._set_fs_root(edd, None)
        path = edd.biosdev_to_edd_dir(138)
        self.assertEqual("/sys/firmware/edd/int13_dev8a", path)
        self.assertEqual(edd.log.debug.called, False)
        self.assertEqual(edd.log.info.called, False)
        self.assertEqual(edd.log.warning.called, False)
        self.assertEqual(edd.log.error.called, False)

    def test_collect_edd_data_sata_usb(self):
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
        self.assertEqual(len(edd_dict), 2)
        self.assertEqual(fakeedd[0x80], edd_dict[0x80])
        self.assertEqual(fakeedd[0x81], edd_dict[0x81])
        self.assertEqual(edd.log.debug.called, False)
        self.assertEqual(edd.log.info.called, False)
        self.assertEqual(edd.log.warning.called, False)
        self.assertEqual(edd.log.error.called, False)

    def test_get_edd_dict_sata_usb(self):
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
            ("edd: data extracted from 0x%x:\n%s", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:\n%s", 0x81, fakeedd[0x81]),
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
        for debug in debugs:
            self.assertIn(mock.call(*debug), edd.log.debug.call_args_list)
        for info in infos:
            self.assertIn(mock.call(*info), edd.log.info.call_args_list)
        for warning in warnings:
            self.assertIn(mock.call(*warning), edd.log.warning.call_args_list)
        self.assertEqual(edd.log.error.called, False)
