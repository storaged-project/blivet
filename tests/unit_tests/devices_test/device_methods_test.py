import unittest
from unittest.mock import patch, Mock, PropertyMock

from blivet.devices import StorageDevice
from blivet.devices import DiskDevice, PartitionDevice
from blivet.devices import LVMVolumeGroupDevice, LVMLogicalVolumeDevice
from blivet.devices import MDRaidArrayDevice
from blivet.errors import DeviceError
from blivet.formats import get_device_format_class
from blivet.size import Size


# pylint: disable=no-member
class StorageDeviceMethodsTestCase(unittest.TestCase):
    device_class = StorageDevice

    def __init__(self, methodName='runTest'):
        super(StorageDeviceMethodsTestCase, self).__init__(methodName=methodName)
        self.patchers = dict()
        self.patches = dict()

    #
    # patch setup
    #
    def set_patches(self):
        self.patchers["update_sysfs_path"] = patch.object(self.device, "update_sysfs_path")
        self.patchers["udev"] = patch("blivet.devices.storage.udev")
        self.patchers["update_size"] = patch.object(self.device, "update_size")
        self.patchers["setup_parents"] = patch.object(self.device, "setup_parents")
        self.patchers["teardown_parents"] = patch.object(self.device, "teardown_parents")
        self.patchers["media_present"] = patch.object(self.device_class, "media_present",
                                                      new=PropertyMock(return_value=True))
        self.patchers["status"] = patch.object(self.device_class, "status", new=PropertyMock())

    def start_patches(self):
        for target, patcher in self.patchers.items():
            self.patches[target] = patcher.start()

    def stop_patches(self):
        for target, patcher in self.patchers.items():
            patcher.stop()
            del self.patches[target]

    #
    # device constructor arguments
    #
    def _ctor_args(self):
        return ["testdev1"]

    def _ctor_kwargs(self):
        return {"size": Size("10 GiB")}

    def setUp(self):
        self.device = self.device_class(*self._ctor_args(), **self._ctor_kwargs())

        self.set_patches()
        self.start_patches()
        self.addCleanup(self.stop_patches)

    #
    # some expected values
    #
    @property
    def create_updates_sysfs_path(self):
        return True

    @property
    def create_calls_udev_settle(self):
        return True

    @property
    def destroy_updates_sysfs_path(self):
        return False

    @property
    def destroy_calls_udev_settle(self):
        return True

    @property
    def setup_updates_sysfs_path(self):
        return True

    @property
    def setup_calls_udev_settle(self):
        return True

    @property
    def teardown_updates_sysfs_path(self):
        return False

    @property
    def teardown_calls_udev_settle(self):
        return True

    @property
    def teardown_method_mock(self):
        return self.device._teardown

    #
    # tests
    #
    def test_create(self):
        # an existing device's create method should raise DeviceError
        self.device.exists = True
        self.patches["status"].return_value = True
        with patch.object(self.device, "_create"):
            self.assertRaisesRegex(DeviceError, "has already been created", self.device.create)
            self.assertFalse(self.device._create.called)
        self.device.exists = False

        # if _create raises an exception _post_create should not be called
        def _create():
            raise RuntimeError("problems")

        with patch.object(self.device, "_create"):
            with patch.object(self.device, "_post_create"):
                with patch.object(self.device, "_pre_create"):
                    self.device._create.side_effect = _create
                    self.assertRaisesRegex(RuntimeError, "problems", self.device.create)
                    self.assertTrue(self.device._create.called)
                    self.assertFalse(self.device._post_create.called)
                    self.assertTrue(self.device._pre_create.called)

        # successful create call
        with patch.object(self.device, "_create"):
            with patch.object(self.device, "_pre_create"):
                self.device.create()
                self.assertTrue(self.device._create.called)
                self.assertTrue(self.device._pre_create.called)

        self.assertTrue(self.device.exists)
        self.assertEqual(self.device.update_sysfs_path.called, self.create_updates_sysfs_path)
        self.assertEqual(self.patches["udev"].settle.called, self.create_calls_udev_settle)
        self.patches["udev"].reset_mock()
        self.device.update_sysfs_path.reset_mock()

    def test_destroy(self):
        # an non-existing device's destroy method should raise DeviceError
        self.device.exists = False
        self.patches["status"].return_value = True
        with patch.object(self.device, "_destroy"):
            self.assertRaisesRegex(DeviceError, "has not been created", self.device.destroy)
            self.assertFalse(self.device._destroy.called)
        self.device.exists = True

        # if _destroy raises an exception _post_destroy should not be called
        def _destroy():
            raise RuntimeError("problems")

        with patch.object(self.device, "_destroy"):
            with patch.object(self.device, "_post_destroy"):
                self.device._destroy.side_effect = _destroy
                self.assertRaisesRegex(RuntimeError, "problems", self.device.destroy)
                self.assertTrue(self.device._destroy.called)
                self.assertFalse(self.device._post_destroy.called)

        # successful destroy call
        self.assertTrue(self.device.exists)
        with patch.object(self.device, "_destroy"):
            self.device.destroy()
            self.assertTrue(self.device._destroy.called)

        self.assertFalse(self.device.exists)
        self.assertEqual(self.device.update_sysfs_path.called, self.destroy_updates_sysfs_path)
        self.patches["udev"].reset_mock()
        self.device.update_sysfs_path.reset_mock()

    def test_setup(self):
        self.device.exists = False
        self.patches["status"].return_value = False
        with patch.object(self.device, "_setup"):
            self.assertRaisesRegex(DeviceError, "has not been created", self.device.setup)
            self.assertFalse(self.device._setup.called)

        self.device.exists = True
        self.patches["status"].return_value = True
        with patch.object(self.device, "_setup"):
            self.device.setup()
            self.assertFalse(self.device._setup.called)

        self.patches["udev"].reset_mock()
        self.device.update_sysfs_path.reset_mock()
        self.patches["status"].return_value = False
        with patch.object(self.device, "_setup"):
            self.device.setup()
            self.assertTrue(self.device._setup.called)

        # called from _pre_setup
        self.assertTrue(self.device.setup_parents.called)

        # called from _post_setup
        self.assertEqual(self.patches["udev"].settle.called, self.setup_calls_udev_settle)
        self.assertEqual(self.device.update_sysfs_path.called, self.setup_updates_sysfs_path)
        self.assertFalse(self.device.update_size.called)

        #
        # a device whose size is 0 will call self.update_size from _post_setup
        #
        self.patches["udev"].reset_mock()
        self.device.update_sysfs_path.reset_mock()
        self.patches["status"].return_value = False
        self.device._size = Size(0)
        with patch.object(self.device, "_setup"):
            self.device.setup()

        # called from _post_setup
        self.assertTrue(self.device.update_size.called)

        self.patches["udev"].reset_mock()
        self.device.update_sysfs_path.reset_mock()

    def test_teardown(self):
        self.device.exists = False
        with patch.object(self.device, "_teardown"):
            self.assertRaisesRegex(DeviceError, "has not been created", self.device.teardown)
            self.assertFalse(self.device._teardown.called)

        self.device.exists = True
        self.patches["status"].return_value = False
        with patch.object(self.device, "_teardown"):
            self.device.teardown()
            self.assertFalse(self.device._teardown.called)

        self.patches["udev"].reset_mock()
        self.device.update_sysfs_path.reset_mock()
        self.patches["status"].return_value = True
        with patch.object(self.device, "_teardown"):
            self.device.teardown()
            self.assertTrue(self.teardown_method_mock.called)

        self.assertEqual(self.device.update_sysfs_path.called, self.teardown_updates_sysfs_path)
        self.patches["udev"].reset_mock()
        self.device.update_sysfs_path.reset_mock()


class DiskDeviceMethodsTestCase(StorageDeviceMethodsTestCase):
    device_class = DiskDevice

    def test_create(self):
        unittest.skip("disks cannot be created or destroyed")

    def test_destroy(self):
        unittest.skip("disks cannot be created or destroyed")


class PartitionDeviceMethodsTestCase(StorageDeviceMethodsTestCase):
    device_class = PartitionDevice

    def set_patches(self):
        super(PartitionDeviceMethodsTestCase, self).set_patches()
        self.patchers["parted_partition"] = patch.object(self.device_class, "parted_partition",
                                                         new=PropertyMock())
        self.patchers["disk"] = patch.object(self.device_class, "disk", new=PropertyMock())

    @patch("blivet.devices.partition.DeviceFormat")
    def test_create(self, *args):  # pylint: disable=unused-argument,arguments-differ
        with patch.object(self.device, "_wipe"):
            super(PartitionDeviceMethodsTestCase, self).test_create()

        with patch.object(self.device, "_wipe"):
            self.device.parted_partition.type_uuid = bytes([0] * 16)
            self.device._create()
            self.assertTrue(self.device.disk.format.add_partition.called)
            self.assertTrue(self.device.disk.format.commit.called)

    def test_destroy(self):
        super(PartitionDeviceMethodsTestCase, self).test_destroy()

        self.device._destroy()
        self.assertTrue(self.device.disk.original_format.remove_partition.called)
        self.assertTrue(self.device.disk.original_format.commit.called)

        self.assertFalse(self.device.disk.format.remove_partition.called)
        self.assertFalse(self.device.disk.format.commit.called)

        # If the format is also a disklabel and its parted.Disk is not the same
        # one as the original_format's, we remove the partition from the current
        # disklabel as well.
        self.device.disk.format.type = "disklabel"
        self.device._destroy()
        self.assertTrue(self.device.disk.original_format.remove_partition.called)
        self.assertTrue(self.device.disk.original_format.commit.called)
        self.assertTrue(self.device.disk.format.remove_partition.called)
        self.assertTrue(self.device.disk.format.commit.called)


class LVMVolumeGroupDeviceMethodsTestCase(StorageDeviceMethodsTestCase):
    device_class = LVMVolumeGroupDevice

    @property
    def destroy_calls_udev_settle(self):
        return False

    def set_patches(self):
        super(LVMVolumeGroupDeviceMethodsTestCase, self).set_patches()
        self.patchers["complete"] = patch.object(self.device_class, "complete",
                                                 new=PropertyMock(return_value=True))

    def test_create(self):
        super(LVMVolumeGroupDeviceMethodsTestCase, self).test_create()

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.device._create()
            self.assertTrue(lvm.vgcreate.called)

    def test_destroy(self):
        with patch.object(self.device, "teardown"):
            super(LVMVolumeGroupDeviceMethodsTestCase, self).test_destroy()

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.device._destroy()
            self.assertTrue(lvm.vgreduce.called)
            self.assertTrue(lvm.vgremove.called)

    def test_teardown(self):
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.device._teardown()
            self.assertTrue(lvm.vgdeactivate.called)


class LVMLogicalVolumeDeviceMethodsTestCase(StorageDeviceMethodsTestCase):
    device_class = LVMLogicalVolumeDevice

    def _ctor_kwargs(self):
        kwargs = super(LVMLogicalVolumeDeviceMethodsTestCase, self)._ctor_kwargs()
        vg_mock = Mock(name="testvg", spec=LVMVolumeGroupDevice)
        vg_mock.name = "testvg"
        vg_mock.pvs = vg_mock.parents = [Mock(name="pv.1", protected=False)]
        vg_mock.protected = False
        vg_mock.readonly = False
        kwargs["parents"] = [vg_mock]
        kwargs["pvs"] = []
        return kwargs

    @property
    def destroy_calls_udev_settle(self):
        return False

    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    def test_setup(self, *args):  # pylint: disable=unused-argument,arguments-differ
        super(LVMLogicalVolumeDeviceMethodsTestCase, self).test_setup()
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.device._setup()
            self.assertTrue(lvm.lvactivate.called)

    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    def test_teardown(self, *args):  # pylint: disable=unused-argument,arguments-differ
        with patch("blivet.devicelibs.lvm.lvmetad_socket_exists", return_value=False):
            super(LVMLogicalVolumeDeviceMethodsTestCase, self).test_teardown()

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.device._teardown()
            self.assertTrue(lvm.lvdeactivate.called)

    def test_create(self):
        super(LVMLogicalVolumeDeviceMethodsTestCase, self).test_create()
        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.device._create()
            self.assertTrue(lvm.lvcreate.called)

    def test_destroy(self):
        with patch.object(self.device, "teardown"):
            super(LVMLogicalVolumeDeviceMethodsTestCase, self).test_destroy()

        with patch("blivet.devices.lvm.blockdev.lvm") as lvm:
            self.device._destroy()
            self.assertTrue(lvm.lvremove.called)


class MDRaidArrayDeviceMethodsTestCase(StorageDeviceMethodsTestCase):
    device_class = MDRaidArrayDevice

    def _ctor_kwargs(self):
        kwargs = super(MDRaidArrayDeviceMethodsTestCase, self)._ctor_kwargs()
        kwargs["level"] = "raid0"
        kwargs["parents"] = [Mock(name="member1", spec=StorageDevice),
                             Mock(name="member2", spec=StorageDevice)]
        mdmember = get_device_format_class("mdmember")
        for member in kwargs["parents"]:
            member.format = Mock(spec=mdmember, exists=True)
            member.protected = False
            member.readonly = False
        return kwargs

    def set_patches(self):
        super(MDRaidArrayDeviceMethodsTestCase, self).set_patches()
        self.patchers["md"] = patch("blivet.devices.md.blockdev.md")
        self.patchers["is_disk"] = patch.object(self.device_class, "is_disk",
                                                new=PropertyMock(return_value=False))
        self.patchers["controllable"] = patch.object(self.device_class, "controllable",
                                                     new=PropertyMock(return_value=True))
        self.patchers["pvs_info"] = patch("blivet.devices.md.pvs_info")
        self.patchers["lvm"] = patch("blivet.devices.md.blockdev.lvm")

    @property
    def teardown_method_mock(self):
        return self.patches["md"].deactivate

    def test_teardown(self):
        with patch("blivet.devices.md.os.path.exists") as exists:
            exists.return_value = True
            super(MDRaidArrayDeviceMethodsTestCase, self).test_teardown()

    def test_setup(self):
        super(MDRaidArrayDeviceMethodsTestCase, self).test_setup()
        self.patches["md"].reset_mock()
        self.device._setup()
        self.assertTrue(self.patches["md"].activate.called)

    def test_create(self):
        with patch("blivet.devices.md.DeviceFormat"):
            super(MDRaidArrayDeviceMethodsTestCase, self).test_create()
        self.device._create()
        self.assertTrue(self.patches["md"].create.called)
