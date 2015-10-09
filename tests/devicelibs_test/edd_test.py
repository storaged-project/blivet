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

    def test_collect_edd_data_absurd_virt(self):
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
        self.assertEqual(len(edd_dict), 6)
        self.assertEqual(fakeedd[0x80], edd_dict[0x80])
        self.assertEqual(fakeedd[0x81], edd_dict[0x81])
        self.assertEqual(fakeedd[0x82], edd_dict[0x82])
        self.assertEqual(fakeedd[0x83], edd_dict[0x83])
        self.assertEqual(fakeedd[0x84], edd_dict[0x84])
        self.assertEqual(fakeedd[0x85], edd_dict[0x85])
        self.assertEqual(edd.log.debug.called, False)
        self.assertEqual(edd.log.info.called, False)
        self.assertEqual(edd.log.warning.called, False)
        self.assertEqual(edd.log.error.called, False)

    def test_get_edd_dict_absurd_virt(self):
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
            ("edd: data extracted from 0x%x:\n%s", 0x80, fakeedd[0x80]),
            ("edd: data extracted from 0x%x:\n%s", 0x81, fakeedd[0x81]),
            ("edd: data extracted from 0x%x:\n%s", 0x82, fakeedd[0x82]),
            ("edd: data extracted from 0x%x:\n%s", 0x83, fakeedd[0x83]),
            ("edd: data extracted from 0x%x:\n%s", 0x84, fakeedd[0x84]),
            ("edd: data extracted from 0x%x:\n%s", 0x85, fakeedd[0x85]),
            ]
        infos = [
            ("edd: matched 0x%x to %s using PCI dev", 0x80, "vda"),
            ("edd: matched 0x%x to %s using PCI dev", 0x81, "sdb"),
            ("edd: matched 0x%x to %s using MBR sig", 0x82, "sda"),
            ("edd: matched 0x%x to %s using MBR sig", 0x83, "sde"),
            ("edd: matched 0x%x to %s using PCI dev", 0x84, "sdc"),
            ("edd: matched 0x%x to %s using MBR sig", 0x85, "sdd"),
            ]
        for debug in debugs:
            self.assertIn(mock.call(*debug), edd.log.debug.call_args_list)
        for info in infos:
            self.assertIn(mock.call(*info), edd.log.info.call_args_list)
        self.assertEqual(edd.log.warning.called, False)
        self.assertEqual(edd.log.error.called, False)

    @unittest.skip("not implemented")
    def test_collect_edd_data_cciss(self):
        EddTestFS(self, edd).sda_cciss()
        edd_dict = edd.collect_edd_data()

        self.assertEqual(edd_dict[0x80].pci_dev, None)
        self.assertEqual(edd_dict[0x80].channel, None)

    @unittest.skip("not implemented")
    def test_edd_entry_str(self):
        EddTestFS(self, edd).sda_vda()
        edd_dict = edd.collect_edd_data()
        expected_output = """\ttype: ATA, ata_device: 0
\tchannel: 0, mbr_signature: 0x000ccb01
\tpci_dev: 00:01.1, scsi_id: None
\tscsi_lun: None, sectors: 2097152"""
        self.assertEqual(str(edd_dict[0x80]), expected_output)

    @unittest.skip("not implemented")
    def test_matcher_device_path(self):
        EddTestFS(self, edd).sda_vda()
        edd_dict = edd.collect_edd_data()

        analyzer = edd.EddMatcher(edd_dict[0x80])
        path = analyzer.devname_from_pci_dev()
        self.assertEqual(path, "sda")

        analyzer = edd.EddMatcher(edd_dict[0x81])
        path = analyzer.devname_from_pci_dev()
        self.assertEqual(path, "vda")

    @unittest.skip("not implemented")
    def test_bad_device_path(self):
        EddTestFS(self, edd).sda_vda_no_pcidev()
        edd_dict = edd.collect_edd_data()

        analyzer = edd.EddMatcher(edd_dict[0x80])
        path = analyzer.devname_from_pci_dev()
        self.assertEqual(path, None)

    @unittest.skip("not implemented")
    def test_bad_host_bus(self):
        EddTestFS(self, edd).sda_vda_no_host_bus()

        edd_dict = edd.collect_edd_data()

        # 0x80 entry is basted so fail without an exception
        analyzer = edd.EddMatcher(edd_dict[0x80])
        devname = analyzer.devname_from_pci_dev()
        self.assertEqual(devname, None)

        # but still succeed on 0x81
        analyzer = edd.EddMatcher(edd_dict[0x81])
        devname = analyzer.devname_from_pci_dev()
        self.assertEqual(devname, "vda")

    @unittest.skip("not implemented")
    def test_get_edd_dict_1(self):
        """ Test get_edd_dict()'s pci_dev matching. """
        EddTestFS(self, edd).sda_vda()
        self.assertEqual(edd.get_edd_dict([]),
                         {'sda' : 0x80,
                          'vda' : 0x81})

    @unittest.skip("not implemented")
    def test_get_edd_dict_2(self):
        """ Test get_edd_dict()'s pci_dev matching. """
        edd.collect_mbrs = mock.Mock(return_value = {
                'sda' : '0x000ccb01',
                'vda' : '0x0006aef1'})
        EddTestFS(self, edd).sda_vda_missing_details()
        self.assertEqual(edd.get_edd_dict([]),
                         {'sda' : 0x80,
                          'vda' : 0x81})

    @unittest.skip("not implemented")
    def test_get_edd_dict_3(self):
        """ Test scenario when the 0x80 and 0x81 edd directories contain the
            same data and give no way to distinguish among the two devices.
        """
        edd.collect_mbrs = mock.Mock(return_value={'sda' : '0x000ccb01',
                                                   'vda' : '0x0006aef1'})
        EddTestFS(self, edd).sda_sdb_same()
        self.assertEqual(edd.get_edd_dict([]), {})
        self.assertIn((('edd: both edd entries 0x80 and 0x81 seem to map to sda',), {}),
                      edd.log.info.call_args_list)

class EddTestFS(object):
    def __init__(self, test_case, target_module):
        self.fs = mock.DiskIO() # pylint: disable=no-member
        test_case.take_over_io(self.fs, target_module)

    def sda_vda_missing_details(self):
        self.fs["/sys/firmware/edd/int13_dev80"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev80/mbr_signature"] = "0x000ccb01\n"
        self.fs["/sys/firmware/edd/int13_dev81"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev81/mbr_signature"] = "0x0006aef1\n"

    def sda_vda(self):
        self.fs["/sys/firmware/edd/int13_dev80"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev80/host_bus"] = "PCI 	00:01.1  channel: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/interface"] = "ATA     	device: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/mbr_signature"] = "0x000ccb01\n"
        self.fs["/sys/firmware/edd/int13_dev80/sectors"] = "2097152\n"

        self.fs["/sys/firmware/edd/int13_dev81"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev81/host_bus"] = "PCI 	00:05.0  channel: 0\n"
        self.fs["/sys/firmware/edd/int13_dev81/interface"] = "SCSI    	id: 0  lun: 0\n"
        self.fs["/sys/firmware/edd/int13_dev81/mbr_signature"] = "0x0006aef1\n"
        self.fs["/sys/firmware/edd/int13_dev81/sectors"] = "16777216\n"

        self.fs["/sys/devices/pci0000:00/0000:00:01.1/host0/target0:0:0/0:0:0:0/block"] = self.fs.Dir()
        self.fs["/sys/devices/pci0000:00/0000:00:01.1/host0/target0:0:0/0:0:0:0/block/sda"] = self.fs.Dir()

        self.fs["/sys/devices/pci0000:00/0000:00:05.0/virtio2/block"] = self.fs.Dir()
        self.fs["/sys/devices/pci0000:00/0000:00:05.0/virtio2/block/vda"] = self.fs.Dir()

        return self.fs

    def sda_vda_no_pcidev(self):
        self.sda_vda()
        entries = [e for e in self.fs.fs if e.startswith("/sys/devices/pci")]
        for e in entries:
            self.fs.os_remove(e)
        return self.fs

    def sda_vda_no_host_bus(self):
        self.sda_vda()
        self.fs["/sys/firmware/edd/int13_dev80/host_bus"] = "PCI 	00:01.1  channel: \n"
        self.fs.os_remove("/sys/firmware/edd/int13_dev80/mbr_signature")
        self.fs.os_remove("/sys/firmware/edd/int13_dev81/mbr_signature")

    def sda_cciss(self):
        self.fs["/sys/firmware/edd/int13_dev80"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev80/host_bus"] = "PCIX	05:00.0  channel: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/interface"] = "RAID    	identity_tag: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/mbr_signature"] = "0x000ccb01\n"
        self.fs["/sys/firmware/edd/int13_dev80/sectors"] = "2097152\n"

        return self.fs

    def vda_vdb(self):
        self.fs["/sys/firmware/edd/int13_dev80"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev80/host_bus"] = "PCI 	00:05.0  channel: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/interface"] = "SCSI    	id: 0  lun: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/sectors"] = "16777216\n"

        self.fs["/sys/firmware/edd/int13_dev81"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev81/host_bus"] = "PCI 	00:06.0  channel: 0\n"
        self.fs["/sys/firmware/edd/int13_dev81/interface"] = "SCSI    	id: 0  lun: 0\n"
        self.fs["/sys/firmware/edd/int13_dev81/sectors"] = "4194304\n"

        return self.fs

    def sda_sdb_same(self):
        self.fs["/sys/firmware/edd/int13_dev80"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev80/host_bus"] = "PCI 	00:01.1  channel: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/interface"] = "ATA     	device: 0\n"
        self.fs["/sys/firmware/edd/int13_dev80/mbr_signature"] = "0x000ccb01"
        self.fs["/sys/firmware/edd/int13_dev80/sectors"] = "2097152\n"

        self.fs["/sys/firmware/edd/int13_dev81"] = self.fs.Dir()
        self.fs["/sys/firmware/edd/int13_dev81/host_bus"] = "PCI 	00:01.1  channel: 0\n"
        self.fs["/sys/firmware/edd/int13_dev81/interface"] = "ATA     	device: 0\n"
        self.fs["/sys/firmware/edd/int13_dev81/mbr_signature"] = "0x0006aef1"
        self.fs["/sys/firmware/edd/int13_dev81/sectors"] = "2097152\n"

        self.fs["/sys/devices/pci0000:00/0000:00:01.1/host0/target0:0:0/0:0:0:0/block"] = self.fs.Dir()
        self.fs["/sys/devices/pci0000:00/0000:00:01.1/host0/target0:0:0/0:0:0:0/block/sda"] = self.fs.Dir()
