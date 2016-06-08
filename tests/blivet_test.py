import unittest
from unittest.mock import PropertyMock
from unittest.mock import patch
from pykickstart.version import returnClassForVersion
from blivet.osinstall import InstallerStorage
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

        with patch('blivet.osinstall.InstallerStorage.bootloader_device', new_callable=PropertyMock) as mock_bootloader_device:
            with patch('blivet.osinstall.InstallerStorage.mountpoints', new_callable=PropertyMock) as mock_mountpoints:
                # set up prepboot partition
                bootloader_device_obj = PartitionDevice("test_partition_device")
                bootloader_device_obj.size = Size('5 MiB')
                bootloader_device_obj.format = formats.get_format("prepboot")

                blivet_obj = InstallerStorage()

                # mountpoints must exist for update_ksdata to run
                mock_bootloader_device.return_value = bootloader_device_obj
                mock_mountpoints.values.return_value = []

                # initialize ksdata
                test_ksdata = returnClassForVersion()()
                blivet_obj.ksdata = test_ksdata
                blivet_obj.update_ksdata()

        self.assertTrue("part prepboot" in str(blivet_obj.ksdata))
