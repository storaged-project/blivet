import unittest
from mock import Mock
from pykickstart.version import returnClassForVersion
from blivet import Blivet
from blivet.devices import PartitionDevice
from blivet import formats
from blivet.size import Size
import re

class BlivetTestCase(unittest.TestCase):
    '''
    Define tests for the Blivet class
    '''
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_bootloader_in_kickstart(self):
        '''
        test that a bootloader such as prepboot/biosboot shows up
        in the kickstart data
        '''
        # set up arbitrary partition to pass mountpoints check
        my_root_device = PartitionDevice("test_mount_device")
        my_root_device.size = Size('100 MiB')
        my_root_device.format = formats.getFormat("xfs", mountpoint="/")

        # set up prepboot partition
        my_bootloader_device = PartitionDevice("test_partition_device")
        my_bootloader_device.size = Size('5 MiB')
        my_bootloader_device.format = formats.getFormat("prepboot")

        # Mock _bootloader to get it to recognize device
        my_blivet = Blivet()
        my_blivet._bootloader = Mock()
        my_blivet._bootloader.stage1_device = my_bootloader_device

        # initialize ksdata
        my_ksdata = returnClassForVersion()()
        my_blivet.ksdata = my_ksdata

        # add device and update ksdata
        my_blivet.devicetree._addDevice(my_bootloader_device)
        my_blivet.devicetree._addDevice(my_root_device)

        my_blivet.updateKSData()

        my_result = re.search('part prepboot --fstype="prepboot" --size=5',
                              str(my_blivet.ksdata))

        self.assertTrue(my_result is not None)
