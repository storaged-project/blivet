import unittest
from mock import patch
from mock import PropertyMock
from pykickstart.version import returnClassForVersion
from blivet import Blivet
from blivet.devices import PartitionDevice
from blivet import formats
from blivet.size import Size


class BlivetTestCase(unittest.TestCase):
    '''
    Define tests for the Blivet class
    '''
    def test_bootloader_in_kickstart(self):
        '''
        test that a bootloader such as prepboot/biosboot shows up
        in the kickstart data
        '''

        with patch('blivet.Blivet.bootLoaderDevice', new_callable=PropertyMock) as mockBootLoaderDevice:
            with patch('blivet.Blivet.mountpoints', new_callable=PropertyMock) as mockMountpoints:
                # set up prepboot partition
                bootloader_device_obj = PartitionDevice("test_partition_device")
                bootloader_device_obj.size = Size('5MiB')
                bootloader_device_obj.format = formats.getFormat("prepboot")

                blivet_obj = Blivet()

                # mountpoints must exist for updateKSData to run
                mockBootLoaderDevice.return_value = bootloader_device_obj
                mockMountpoints.values.return_value = []

                # initialize ksdata
                test_ksdata = returnClassForVersion()()
                blivet_obj.ksdata = test_ksdata
                blivet_obj.updateKSData()

        self.assertTrue("part prepboot" in str(blivet_obj.ksdata))
