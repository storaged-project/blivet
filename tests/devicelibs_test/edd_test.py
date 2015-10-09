import unittest
import mock
import os
import inspect

from blivet.devicelibs.edd import EddEntry

class FakeDevice(object):
    def __init__(self, name):
        self.name = name

class FakeEddEntry(EddEntry):
    def __init__(self, sysfspath, **kw):
        EddEntry.__init__(self, sysfspath)
        for (name,value) in kw.items():
            self.__dict__[name] = value

    def load(self):
        pass

    def __lt__(self, other):
        return self.__dict__ < other.__dict__

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

class EddTestCase(unittest.TestCase):
    def _set_fs_root(self, edd_module, fsroot):
        if fsroot is None:
            edd_module.fsroot = ""
        else:
            dirname = os.path.dirname(inspect.getfile(edd_module))
            edd_module.fsroot = os.path.join(dirname, "../../tests/devicelibs_test/edd_data/", fsroot)

    def test_biosdev_to_edd_dir(self):
        from blivet.devicelibs import edd
        self._set_fs_root(edd, None)
        path = edd.biosdev_to_edd_dir(138)
        self.assertEqual("/sys/firmware/edd/int13_dev8a", path)

    def test_collect_edd_data_sata_usb(self):
        # test with sata sda, usb sdb
        from blivet.devicelibs import edd
        self._set_fs_root(edd, "sata_usb")
        edd_dict = edd.collect_edd_data()
        dev80 = FakeEddEntry(version="0x30", mbr_sig="0x00000000",
                             sectors=312581808, host_bus="PCI", type="SATA",
                             pci_dev="00:1f.2", channel=255, ata_device=1,
                             interface="SATA    \tdevice: 1",
                             sysfspath=os.path.join(edd.fsroot,
                                            "sys/firmware/edd/int13_dev80"))
        dev81 = FakeEddEntry(version="0x21", mbr_sig="0x96a20d28",
                             sectors=31293440, host_bus="PCI", type="USB",
                             pci_dev="ff:ff.255", channel=255,
                             usb_serial=0x30302e31,
                             interface="USB     \tserial_number: 30302e31",
                             sysfspath=os.path.join(edd.fsroot,
                                            "sys/firmware/edd/int13_dev81"))
        self.assertEqual(len(edd_dict), 2)
        self.assertEqual(dev80, edd_dict[0x80])
        self.assertEqual(dev81, edd_dict[0x81])

    def test_get_edd_dict_sata_usb(self):
        from blivet.devicelibs import edd

        # test with sata sda, usb sdb
        self._set_fs_root(edd, "sata_usb")
        devices=(FakeDevice("sda"),
                 FakeDevice("sdb"),
                 )
        edd_dict = edd.get_edd_dict(devices)
        self.assertEqual(len(edd_dict), 2)
        self.assertEqual(edd_dict["sda"], 0x80)
        self.assertEqual(edd_dict["sdb"], 0x81)

    @unittest.skip("not implemented")
    def test_collect_edd_data_cciss(self):
        from blivet.devicelibs import edd
        EddTestFS(self, edd).sda_cciss()
        edd_dict = edd.collect_edd_data()

        self.assertEqual(edd_dict[0x80].pci_dev, None)
        self.assertEqual(edd_dict[0x80].channel, None)

    @unittest.skip("not implemented")
    def test_edd_entry_str(self):
        from blivet.devicelibs import edd
        EddTestFS(self, edd).sda_vda()
        edd_dict = edd.collect_edd_data()
        expected_output = """\ttype: ATA, ata_device: 0
\tchannel: 0, mbr_signature: 0x000ccb01
\tpci_dev: 00:01.1, scsi_id: None
\tscsi_lun: None, sectors: 2097152"""
        self.assertEqual(str(edd_dict[0x80]), expected_output)

    @unittest.skip("not implemented")
    def test_matcher_device_path(self):
        from blivet.devicelibs import edd
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
        from blivet.devicelibs import edd
        EddTestFS(self, edd).sda_vda_no_pcidev()
        edd_dict = edd.collect_edd_data()

        analyzer = edd.EddMatcher(edd_dict[0x80])
        path = analyzer.devname_from_pci_dev()
        self.assertEqual(path, None)

    @unittest.skip("not implemented")
    def test_bad_host_bus(self):
        from blivet.devicelibs import edd
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
        from blivet.devicelibs import edd
        EddTestFS(self, edd).sda_vda()
        self.assertEqual(edd.get_edd_dict([]),
                         {'sda' : 0x80,
                          'vda' : 0x81})

    @unittest.skip("not implemented")
    def test_get_edd_dict_2(self):
        """ Test get_edd_dict()'s pci_dev matching. """
        from blivet.devicelibs import edd
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
        from blivet.devicelibs import edd
        edd.log = mock.Mock()
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
