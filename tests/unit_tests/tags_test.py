import unittest
from unittest.mock import patch

from blivet.devices import DiskDevice, FcoeDiskDevice, iScsiDiskDevice, MultipathDevice, StorageDevice, ZFCPDiskDevice
from blivet.devices.lib import Tags
from blivet.devices.device import Device


class DeviceTagsTest(unittest.TestCase):
    def _get_device(self, *args, **kwargs):
        return StorageDevice(*args, **kwargs)

    def test_tags(self):
        #
        # basic function on the tags property
        #
        d = Device('testdev')
        self.assertTrue(hasattr(d, 'tags'))
        self.assertIsInstance(d.tags, set)
        self.assertEqual(d.tags, set())

        d.tags.add('testlabel1')  # pylint: disable=no-member
        self.assertIn('testlabel1', d.tags)

        d.tags.add('testlabel2')  # pylint: disable=no-member
        self.assertIn('testlabel2', d.tags)

        d.tags.remove('testlabel1')
        self.assertNotIn('testlabel1', d.tags)
        self.assertIn('testlabel2', d.tags)

        new_tags = ["one", "two"]
        d.tags = new_tags
        self.assertEqual(d.tags, set(new_tags))

    def test_auto_tags(self):
        #
        # automatically-set tags for DiskDevice
        #
        with patch('blivet.devices.disk.util') as patched_util:
            patched_util.get_sysfs_attr.return_value = None
            d = DiskDevice('test1')
            self.assertIn(Tags.local, d.tags)
            self.assertNotIn(Tags.ssd, d.tags)
            self.assertNotIn(Tags.usb, d.tags)

            patched_util.get_sysfs_attr.return_value = '1'
            d = DiskDevice('test2')
            self.assertIn(Tags.local, d.tags)
            self.assertNotIn(Tags.ssd, d.tags)

            patched_util.get_sysfs_attr.return_value = '0'
            d = DiskDevice('test2')
            self.assertIn(Tags.local, d.tags)
            self.assertIn(Tags.ssd, d.tags)

        self.assertNotIn(Tags.usb, DiskDevice('test3').tags)
        self.assertIn(Tags.usb, DiskDevice('test4', bus='usb').tags)

        #
        # automatically-set tags for networked storage devices
        #
        iscsi_kwarg_names = ["initiator", "name", "offload", "target", "address", "port",
                             "lun", "iface", "node", "ibft", "nic", "id_path"]
        iscsi_device = iScsiDiskDevice('test5', **dict((k, None) for k in iscsi_kwarg_names))
        self.assertIn(Tags.remote, iscsi_device.tags)
        self.assertNotIn(Tags.local, iscsi_device.tags)
        fcoe_device = FcoeDiskDevice('test6', nic=None, identifier=None, id_path=None)
        self.assertIn(Tags.remote, fcoe_device.tags)
        self.assertNotIn(Tags.local, fcoe_device.tags)
        zfcp_device = ZFCPDiskDevice('test7', hba_id=None, wwpn=None, fcp_lun=None, id_path=None)
        self.assertIn(Tags.remote, zfcp_device.tags)
        self.assertNotIn(Tags.local, zfcp_device.tags)

        multipath_device = MultipathDevice('test8', parents=[iscsi_device])
        self.assertIn(Tags.remote, multipath_device.tags)
        self.assertNotIn(Tags.local, multipath_device.tags)

        #
        # built-in tags should also be accessible as str
        #
        self.assertIn("remote", multipath_device.tags)
