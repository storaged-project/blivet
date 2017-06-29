import unittest
from unittest import mock

from blivet import platform


class PlatformTestCase(unittest.TestCase):
    def test_default_disklabel_type(self):
        for name in dir(platform):
            cls = getattr(platform, name)
            try:
                if not issubclass(cls, platform.Platform):
                    # not a platform class instance
                    continue
            except TypeError:
                # not a class
                continue

            if not cls._disklabel_types:
                continue

            obj = cls()
            type_one = obj.__class__._disklabel_types[0]
            self.assertEqual(obj.default_disklabel_type, type_one)
            if len(obj._disklabel_types) > 1:
                new_default = obj.__class__._disklabel_types[-1]
                obj.set_default_disklabel_type(new_default)
                self.assertEqual(obj.default_disklabel_type, new_default)

    def test_get_best_disklabel_type(self):
        def fresh_disk(device, ty):  # pylint: disable=unused-argument
            """ Return fake parted.Disk w/ maxPartitionStartSector values suitable for testing. """
            max_start = 1001
            if ty == "gpt":
                max_start = 5001

            return mock.Mock(maxPartitionStartSector=max_start)

        for name in dir(platform):
            cls = getattr(platform, name)
            try:
                if not issubclass(cls, platform.Platform):
                    # not a platform class instance
                    continue
            except TypeError:
                # not a class
                continue

            if not cls._disklabel_types:
                continue

            obj = cls()

            """
                1. is always in _disklabel_types
                2. is the default unless the device is too long for the default
                3. is msdos for fba dasd on S390
                4. is dasd for non-fba dasd on S390
            """
            length = 1000
            blivetdev = mock.Mock()
            blivetdev.name = "testdev1"
            parteddev = mock.Mock()
            parteddev.length = length
            with mock.patch("blivet.platform.parted") as _parted:
                _parted.freshDisk.return_value = mock.Mock(maxPartitionStartSector=length + 1)
                _parted.Device.return_value = parteddev
                with mock.patch("blivet.platform.blockdev.s390") as _s390:
                    if name == "S390":
                        _s390.dasd_is_fba.return_value = False
                        parteddev.type = platform.parted.DEVICE_DASD
                        self.assertEqual(obj.best_disklabel_type(blivetdev), "dasd")

                        _s390.dasd_is_fba.return_value = True
                        self.assertEqual(obj.best_disklabel_type(blivetdev), "msdos")

                        _s390.dasd_is_fba.return_value = False
                        parteddev.type = platform.parted.DEVICE_SCSI

                    best_label_type = obj.best_disklabel_type(blivetdev)

                self.assertEqual(best_label_type, obj.default_disklabel_type)

                if cls._disklabel_types != ["msdos", "gpt"]:
                    continue

                # Now just make sure that we suggest gpt for devices longer than the msdos
                # disklabel maximum.
                _parted.freshDisk.return_value = mock.Mock()
                _parted.freshDisk.side_effect = fresh_disk
                parteddev.length = 4000
                best_label_type = obj.best_disklabel_type(blivetdev)
                self.assertEqual(obj.default_disklabel_type, "msdos")
                self.assertEqual(best_label_type, "gpt")
