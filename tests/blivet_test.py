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

        # prepboot test case
        with patch('blivet.Blivet.bootLoaderDevice', new_callable=PropertyMock) as mockBootLoaderDevice:
            with patch('blivet.Blivet.mountpoints', new_callable=PropertyMock) as mockMountpoints:
                # set up prepboot partition
                bootloader_device_obj = PartitionDevice("test_partition_device")
                bootloader_device_obj.size = Size('5MiB')
                bootloader_device_obj.format = formats.getFormat("prepboot")

                prepboot_blivet_obj = Blivet()

                # mountpoints must exist for updateKSData to run
                mockBootLoaderDevice.return_value = bootloader_device_obj
                mockMountpoints.values.return_value = []

                # initialize ksdata
                prepboot_ksdata = returnClassForVersion()()
                prepboot_blivet_obj.ksdata = prepboot_ksdata
                prepboot_blivet_obj.updateKSData()

        self.assertIn("part prepboot", str(prepboot_blivet_obj.ksdata))

        # biosboot test case
        with patch('blivet.Blivet.devices', new_callable=PropertyMock) as mockDevices:
            with patch('blivet.Blivet.mountpoints', new_callable=PropertyMock) as mockMountpoints:
                # set up biosboot partition
                biosboot_device_obj = PartitionDevice("biosboot_partition_device")
                biosboot_device_obj.size = Size('1MiB')
                biosboot_device_obj.format = formats.getFormat("biosboot")

                biosboot_blivet_obj = Blivet()

                # mountpoints must exist for updateKSData to run
                mockDevices.return_value = [biosboot_device_obj]
                mockMountpoints.values.return_value = []

                # initialize ksdata
                biosboot_ksdata = returnClassForVersion()()
                biosboot_blivet_obj.ksdata = biosboot_ksdata
                biosboot_blivet_obj.updateKSData()

        self.assertIn("part biosboot", str(biosboot_blivet_obj.ksdata))
