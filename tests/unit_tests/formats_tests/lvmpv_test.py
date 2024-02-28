import unittest
from unittest.mock import patch

from contextlib import contextmanager

from blivet.formats.lvmpv import LVMPhysicalVolume
from blivet.flags import flags


class LVMPVNodevTestCase(unittest.TestCase):

    @contextmanager
    def patches(self):
        patchers = dict()
        mocks = dict()

        patchers["blockdev"] = patch("blivet.formats.lvmpv.blockdev")
        patchers["lvm"] = patch("blivet.formats.lvmpv.lvm")
        patchers["vgs_info"] = patch("blivet.formats.lvmpv.vgs_info")
        patchers["os"] = patch("blivet.formats.lvmpv.os")

        for name, patcher in patchers.items():
            mocks[name] = patcher.start()

        yield mocks

        for patcher in patchers.values():
            patcher.stop()

    def test_lvm_devices(self):
        fmt = LVMPhysicalVolume(device="/dev/test")

        with self.patches() as mock:
            # LVM devices file not enabled/supported -> devices_add should not be called
            mock["lvm"].HAVE_LVMDEVICES = False

            fmt._create()

            mock["blockdev"].lvm.devices_add.assert_not_called()

        with self.patches() as mock:
            # LVM devices file enabled and devices file exists -> devices_add should be called
            mock["lvm"].HAVE_LVMDEVICES = True
            mock["os"].path.exists.return_value = True

            fmt._create()

            mock["blockdev"].lvm.devices_add.assert_called_with("/dev/test")

        with self.patches() as mock:
            # LVM devices file enabled and devices file doesn't exist
            # and no existing VGs present -> devices_add should be called
            mock["lvm"].HAVE_LVMDEVICES = True
            mock["os"].path.exists.return_value = False
            mock["vgs_info"].cache = {}

            fmt._create()

            mock["blockdev"].lvm.devices_add.assert_called_with("/dev/test")

        with self.patches() as mock:
            # LVM devices file enabled and devices file doesn't exist
            # and existing VGs present -> devices_add should not be called
            mock["lvm"].HAVE_LVMDEVICES = True
            mock["os"].path.exists.return_value = False
            mock["vgs_info"].cache = {"fake_vg_uuid": "fake_vg_data"}

            fmt._create()

            mock["blockdev"].lvm.devices_add.assert_not_called()

        with self.patches() as mock:
            # LVM devices file enabled and devices file exists
            # but flag set to false -> devices_add should not be called
            mock["lvm"].HAVE_LVMDEVICES = True
            mock["os"].path.exists.return_value = True
            mock["vgs_info"].cache = {}
            flags.lvm_devices_file = False

            fmt._create()

            mock["blockdev"].lvm.devices_add.assert_not_called()

            # reset the flag back
            flags.lvm_devices_file = True
