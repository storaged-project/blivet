import unittest
from unittest.mock import patch, Mock, PropertyMock, sentinel

from blivet.actionlist import ActionList
from blivet.errors import DeviceTreeError, DuplicateUUIDError, InvalidMultideviceSelection
from blivet.deviceaction import ACTION_TYPE_DESTROY, ACTION_OBJECT_DEVICE
from blivet.devicelibs import lvm
from blivet.devices import BTRFSSubVolumeDevice, BTRFSVolumeDevice
from blivet.devices import DiskDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import StorageDevice
from blivet.devices import MultipathDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices.lib import Tags
from blivet.devicetree import DeviceTree
from blivet.formats import get_format
from blivet.size import Size
from blivet.static_data.lvm_info import lvs_info, LVsInfo

"""
    TODO:

        - add more lvm tests
            - thin pool with separate data and metadata volumes?
            - raid lvs
            - raid thin pool
"""


class DeviceTreeTestCase(unittest.TestCase):

    def test_resolve_device(self):
        dt = DeviceTree()

        dev1_label = "dev1_label"
        dev1_uuid = "1234-56-7890"
        fmt1 = get_format("ext4", label=dev1_label, uuid=dev1_uuid)
        dev1 = StorageDevice("dev1", exists=True, fmt=fmt1, size=fmt1.min_size)
        dt._add_device(dev1)

        dev2_label = "dev2_label"
        fmt2 = get_format("swap", label=dev2_label)
        dev2 = StorageDevice("dev2", exists=True, fmt=fmt2)
        dt._add_device(dev2)

        dev3 = StorageDevice("sdp2", exists=True)
        dt._add_device(dev3)

        dev4 = StorageDevice("10", exists=True)
        dt._add_device(dev4)

        dt.edd_dict.update({"dev1": 0x81,
                            "dev2": 0x82})

        self.assertEqual(dt.resolve_device(dev1.name), dev1)
        self.assertEqual(dt.resolve_device("LABEL=%s" % dev1_label), dev1)
        self.assertEqual(dt.resolve_device("UUID=%s" % dev1_label), None)
        self.assertEqual(dt.resolve_device("UUID=%s" % dev1_uuid), dev1)
        self.assertEqual(dt.resolve_device("PARTUUID=%s" % dev1_uuid), dev1)
        self.assertEqual(dt.resolve_device("/dev/dev1"), dev1)

        self.assertEqual(dt.resolve_device("dev2"), dev2)
        self.assertEqual(dt.resolve_device("0x82"), dev2)

        self.assertEqual(dt.resolve_device(dev3.name), dev3)
        self.assertEqual(dt.resolve_device(dev4.name), dev4)

    def test_resolve_device_btrfs(self):
        dt = DeviceTree()

        # same uuid for both volume and subvolume
        btrfs_uuid = "1234-56-7890"

        dev = StorageDevice("deva", exists=True,
                            fmt=get_format("btrfs", uuid=btrfs_uuid, exists=True),
                            size=get_format("btrfs").min_size)
        dt._add_device(dev)

        vol = BTRFSVolumeDevice("vol", exists=True,
                                parents=[dev],
                                fmt=get_format("btrfs", uuid=btrfs_uuid, exists=True))
        dt._add_device(vol)

        sub1 = BTRFSSubVolumeDevice("sub1", exists=True,
                                    parents=[vol],
                                    fmt=get_format("btrfs", options="subvol=sub1",
                                                   uuid=btrfs_uuid, exists=True,
                                                   subvolspec="sub1"))
        dt._add_device(sub1)

        sub2 = BTRFSSubVolumeDevice("sub2", exists=True,
                                    parents=[vol],
                                    fmt=get_format("btrfs", options="subvol=sub2",
                                                   uuid=btrfs_uuid, exists=True,
                                                   subvolspec="sub2"))
        dt._add_device(sub2)

        # resolve with name should work as usual
        self.assertEqual(dt.resolve_device(vol.name), vol)
        self.assertEqual(dt.resolve_device(sub1.name), sub1)
        self.assertEqual(dt.resolve_device(sub2.name), sub2)

        # resolve by UUID with subvolspec
        self.assertEqual(dt.resolve_device("UUID=%s" % btrfs_uuid, subvolspec=sub1.format.subvolspec), sub1)
        self.assertEqual(dt.resolve_device("UUID=%s" % btrfs_uuid, subvolspec=sub2.format.subvolspec), sub2)

        # resolve by UUID with options
        self.assertEqual(dt.resolve_device("UUID=%s" % btrfs_uuid, options="subvol=%s" % sub1.name), sub1)
        self.assertEqual(dt.resolve_device("UUID=%s" % btrfs_uuid, options="subvol=%s" % sub2.name), sub2)

    def test_device_name(self):
        # check that devicetree.names property contains all device's names

        # mock lvs_info to avoid blockdev call allowing run as non-root
        with patch.object(LVsInfo, 'cache', new_callable=PropertyMock) as mock_lvs_cache:
            mock_lvs_cache.return_value = {"sdmock": "dummy", "testvg-testlv": "dummy"}

            tree = DeviceTree()
            dev_names = ["test_sda", "test_sdb", "test_sdc"]

            for dev_name in dev_names:
                dev = DiskDevice(dev_name, size=Size("1 GiB"))
                tree._add_device(dev)
                self.assertTrue(dev in tree.devices)
                self.assertTrue(dev.name in tree.names)

            dev.format = get_format("lvmpv", device=dev.path)
            vg = LVMVolumeGroupDevice("testvg", parents=[dev])
            tree._add_device(vg)
            dev_names.append(vg.name)

            lv = LVMLogicalVolumeDevice("testlv", parents=[vg])
            tree._add_device(lv)
            dev_names.append(lv.name)

            # frobnicate a bit with the hidden status of the devices:
            # * hide sda
            # * hide and unhide again sdb
            # * leave sdc unchanged
            tree.hide(tree.get_device_by_name("test_sda"))
            tree.hide(tree.get_device_by_name("test_sdb"))
            tree.unhide(tree.get_device_by_name("test_sdb", hidden=True))

            # some lvs names may be already present in the system (mocked)
            lv_info = list(lvs_info.cache.keys())

            # all devices should still be present in the tree.names
            self.assertEqual(set(tree.names), set(lv_info + dev_names))

            # "remove" the LV, it should no longer be in the list
            tree.actions._actions.append(Mock(device=lv, type=ACTION_TYPE_DESTROY,
                                              obj=ACTION_OBJECT_DEVICE))
            tree._remove_device(lv)
            self.assertFalse(lv.name in tree.names)

    # XXX: the lvm_devices_* functions are decorated with needs_config_refresh decorator which
    #      at this point is already applied as a no-op because LVM libblockdev plugin is not available
    @patch("blivet.devicelibs.lvm.lvm_devices_add", new=lvm._lvm_devices.add)
    @patch("blivet.devicelibs.lvm.lvm_devices_remove", new=lvm._lvm_devices.remove)
    @patch("blivet.devicelibs.lvm.lvm_devices_reset", new=lvm._lvm_devices.clear)
    def test_reset(self):
        dt = DeviceTree()
        names = ["fakedev1", "fakedev2"]
        for name in names:
            device = Mock(name=name, spec=StorageDevice, parents=[], exists=True)
            dt._devices.append(device)

        dt.actions._actions.append(Mock(name="fake action"))

        lvm.lvm_devices_add("xxx")

        dt.ignored_disks.append(names[0])
        dt.exclusive_disks.append(names[1])

        dt._hidden.append(dt._devices.pop(1))

        dt.edd_dict = {"a": 22}

        dt.reset()

        empty_list = list()
        self.assertEqual(dt._devices, empty_list)

        self.assertEqual(list(dt.actions), empty_list)
        self.assertIsInstance(dt.actions, ActionList)

        self.assertEqual(dt._hidden, empty_list)

        self.assertEqual(lvm._lvm_devices, set())

        self.assertEqual(dt.exclusive_disks, empty_list)
        self.assertEqual(dt.ignored_disks, empty_list)

        self.assertEqual(dt.edd_dict, dict())

    @patch.object(StorageDevice, "add_hook")
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    def test_add_device(self, *args):  # pylint: disable=unused-argument
        dt = DeviceTree()

        dev1 = StorageDevice("dev1", exists=False, uuid=sentinel.dev1_uuid, parents=[])

        self.assertEqual(dt.devices, list())

        # things are called, updated as expected when a device is added
        with patch("blivet.devicetree.callbacks") as callbacks:
            dt._add_device(dev1)
            self.assertTrue(callbacks.device_added.called)

        self.assertEqual(dt.devices, [dev1])
        self.assertTrue(dev1 in dt.devices)
        self.assertTrue(dev1.name in dt.names)
        self.assertTrue(dev1.add_hook.called)  # pylint: disable=no-member

        # adding an already-added device fails
        self.assertRaisesRegex(DeviceTreeError, "Trying to add already existing device.", dt._add_device, dev1)

        # adding a device with the same UUID
        dev_clone = StorageDevice("dev_clone", exists=False, uuid=sentinel.dev1_uuid, parents=[])
        self.assertRaisesRegex(DuplicateUUIDError, "Duplicate UUID.*", dt._add_device, dev_clone)

        dev2 = StorageDevice("dev2", exists=False, parents=[])
        dev3 = StorageDevice("dev3", exists=False, parents=[dev1, dev2])

        # adding a device with one or more parents not already in the tree fails
        self.assertRaisesRegex(DeviceTreeError, "parent.*not in tree", dt._add_device, dev3)
        self.assertFalse(dev2 in dt.devices)
        self.assertFalse(dev2.name in dt.names)

        dt._add_device(dev2)
        self.assertTrue(dev2 in dt.devices)
        self.assertTrue(dev2.name in dt.names)

        dt._add_device(dev3)
        self.assertTrue(dev3 in dt.devices)
        self.assertTrue(dev3.name in dt.names)

    @patch.object(StorageDevice, "remove_hook")
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    def test_remove_device(self, *args):  # pylint: disable=unused-argument
        dt = DeviceTree()

        dev1 = StorageDevice("dev1", exists=False, parents=[])

        # removing a device not in the tree raises an exception
        self.assertRaisesRegex(ValueError, "not in tree", dt._remove_device, dev1)

        dt._add_device(dev1)
        with patch("blivet.devicetree.callbacks") as callbacks:
            dt._remove_device(dev1)
            self.assertTrue(callbacks.device_removed.called)

        self.assertFalse(dev1 in dt.devices)
        self.assertFalse(dev1.name in dt.names)
        self.assertTrue(dev1.remove_hook.called)  # pylint: disable=no-member

        dev2 = StorageDevice("dev2", exists=False, parents=[dev1])
        dt._add_device(dev1)
        dt._add_device(dev2)
        self.assertTrue(dev2 in dt.devices)
        self.assertTrue(dev2.name in dt.names)

        # removal of a non-leaf device raises an exception
        self.assertRaisesRegex(ValueError, "non-leaf device", dt._remove_device, dev1)
        self.assertTrue(dev1 in dt.devices)
        self.assertTrue(dev1.name in dt.names)
        self.assertTrue(dev2 in dt.devices)
        self.assertTrue(dev2.name in dt.names)

        # forcing removal of non-leaf device does not remove the children
        dt._remove_device(dev1, force=True)
        self.assertFalse(dev1 in dt.devices)
        self.assertFalse(dev1.name in dt.names)
        self.assertTrue(dev2 in dt.devices)
        self.assertTrue(dev2.name in dt.names)

    def test_get_device_by_name(self):
        dt = DeviceTree()

        dev1 = StorageDevice("dev1", exists=False, parents=[])
        dev2 = StorageDevice("dev2", exists=False, parents=[dev1])
        dt._add_device(dev1)
        dt._add_device(dev2)

        self.assertIsNone(dt.get_device_by_name("dev3"))
        self.assertEqual(dt.get_device_by_name("dev2"), dev2)
        self.assertEqual(dt.get_device_by_name("dev1"), dev1)

        dev2.complete = False
        self.assertEqual(dt.get_device_by_name("dev2"), None)
        self.assertEqual(dt.get_device_by_name("dev2", incomplete=True), dev2)

        dev3 = StorageDevice("dev3", exists=True, parents=[])
        dt._add_device(dev3)
        dt.hide(dev3)
        self.assertIsNone(dt.get_device_by_name("dev3"))
        self.assertEqual(dt.get_device_by_name("dev3", hidden=True), dev3)

    def test_get_device_by_device_id(self):
        dt = DeviceTree()

        # for StorageDevice, device_id is just name
        dev1 = StorageDevice("dev1", exists=False, parents=[])
        dev2 = StorageDevice("dev2", exists=False, parents=[dev1])
        dt._add_device(dev1)
        dt._add_device(dev2)

        self.assertIsNone(dt.get_device_by_device_id("dev3"))
        self.assertEqual(dt.get_device_by_device_id("dev2"), dev2)
        self.assertEqual(dt.get_device_by_device_id("dev1"), dev1)

        dev2.complete = False
        self.assertEqual(dt.get_device_by_device_id("dev2"), None)
        self.assertEqual(dt.get_device_by_device_id("dev2", incomplete=True), dev2)

        dev3 = StorageDevice("dev3", exists=True, parents=[])
        dt._add_device(dev3)
        dt.hide(dev3)
        self.assertIsNone(dt.get_device_by_device_id("dev3"))
        self.assertEqual(dt.get_device_by_device_id("dev3", hidden=True), dev3)

    def test_recursive_remove(self):
        dt = DeviceTree()
        dev1 = StorageDevice("dev1", exists=False, parents=[])
        dev2 = StorageDevice("dev2", exists=False, parents=[dev1])
        dt._add_device(dev1)
        dt._add_device(dev2)

        # normal
        self.assertTrue(dev1 in dt.devices)
        self.assertTrue(dev2 in dt.devices)
        self.assertEqual(dt.actions._actions, list())
        dt.recursive_remove(dev1)
        self.assertFalse(dev1 in dt.devices)
        self.assertFalse(dev2 in dt.devices)
        self.assertNotEqual(dt.actions._actions, list())

        dt.reset()
        dt._add_device(dev1)
        dt._add_device(dev2, new=False)  # restore parent/child relationships

        # remove_device clears descendants and formatting but preserves the device
        dev1.format = get_format("swap")
        self.assertEqual(dev1.format.type, "swap")
        self.assertEqual(dt.actions._actions, list())
        dt.recursive_remove(dev1, remove_device=False)
        self.assertTrue(dev1 in dt.devices)
        self.assertFalse(dev2 in dt.devices)
        self.assertEqual(dev1.format.type, None)
        self.assertNotEqual(dt.actions._actions, list())

        dt.reset()
        dt._add_device(dev1)
        dt._add_device(dev2, new=False)  # restore parent/child relationships

        # actions=False performs the removals without scheduling actions
        self.assertEqual(dt.actions._actions, list())
        dt.recursive_remove(dev1, actions=False)
        self.assertFalse(dev1 in dt.devices)
        self.assertFalse(dev2 in dt.devices)
        self.assertEqual(dt.actions._actions, list())

        dt.reset()
        dt._add_device(dev1)
        dt._add_device(dev2, new=False)  # restore parent/child relationships

        # modparent only works when actions=False is passed
        with patch.object(dt, "_remove_device") as remove_device:
            dt.recursive_remove(dev1, actions=False)
            remove_device.assert_called_with(dev1, modparent=True)

            dt.recursive_remove(dev1, actions=False, modparent=False)
            remove_device.assert_called_with(dev1, modparent=False)

    def test_ignored_disk_tags(self):
        tree = DeviceTree()

        fake_ssd = Mock(name="fake_ssd", spec=StorageDevice, parents=[],
                        tags=[Tags.ssd], exists=True)
        fake_local = Mock(name="fake_local", spec=StorageDevice, parents=[],
                          tags=[Tags.local], exists=True)
        tree._devices.extend([fake_ssd, fake_local])

        self.assertFalse(tree._is_ignored_disk(fake_ssd))
        self.assertFalse(tree._is_ignored_disk(fake_local))
        tree.ignored_disks.append("@ssd")
        self.assertTrue(tree._is_ignored_disk(fake_ssd))
        self.assertFalse(tree._is_ignored_disk(fake_local))
        tree.exclusive_disks.append("@local")
        self.assertTrue(tree._is_ignored_disk(fake_ssd))
        self.assertFalse(tree._is_ignored_disk(fake_local))

    def test_expand_taglist(self):
        tree = DeviceTree()

        sda = DiskDevice("test_sda")
        sdb = DiskDevice("test_sdb")
        sdc = DiskDevice("test_sdc")
        sdd = DiskDevice("test_sdd")

        tree._add_device(sda)
        tree._add_device(sdb)
        tree._add_device(sdc)
        tree._add_device(sdd)

        sda.tags = {Tags.remote}
        sdb.tags = {Tags.ssd}
        sdc.tags = {Tags.local, Tags.ssd}
        sdd.tags = set()

        self.assertEqual(tree.expand_taglist(["test_sda", "test_sdb"]), {"test_sda", "test_sdb"})
        self.assertEqual(tree.expand_taglist(["@local"]), {"test_sdc"})
        self.assertEqual(tree.expand_taglist(["@ssd"]), {"test_sdb", "test_sdc"})
        self.assertEqual(tree.expand_taglist(["@ssd", "test_sdd", "@local"]), {"test_sdb", "test_sdc", "test_sdd"})
        with self.assertRaises(ValueError):
            tree.expand_taglist(["test_sdd", "@invalid_tag"])

    def test_hide_ignored_disks(self):
        tree = DeviceTree()

        sda = DiskDevice("test_sda")
        sdb = DiskDevice("test_sdb")
        sdc = DiskDevice("test_sdc")

        tree._add_device(sda)
        tree._add_device(sdb)
        tree._add_device(sdc)

        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)

        # test ignored_disks
        tree.ignored_disks = ["test_sdb"]

        # verify hide is called as expected
        with patch.object(tree, "hide") as hide:
            tree._hide_ignored_disks()
            hide.assert_called_with(sdb)

        # verify that hide works as expected
        tree._hide_ignored_disks()
        self.assertTrue(sda in tree.devices)
        self.assertFalse(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)

        # unhide sdb and make sure it works
        tree.unhide(sdb)
        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)

        # now test with multipath and device ID
        sda.format = get_format("mdmember", exists=True)
        sdb.format = get_format("mdmember", exists=True)
        array = MDRaidArrayDevice("array", parents=[sda, sdb], level="raid1", exists=True)

        tree._add_device(array)

        tree.ignored_disks = ["MDRAID-array"]

        # verify hide is called as expected
        with patch.object(tree, "hide") as hide:
            tree._hide_ignored_disks()
            hide.assert_called_with(array)

        # unhide sdb and make sure it works
        tree.unhide(array)
        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)
        self.assertTrue(array in tree.devices)

        # test exclusive_disks
        tree.ignored_disks = []
        tree.exclusive_disks = ["test_sdc"]
        with patch.object(tree, "hide") as hide:
            tree._hide_ignored_disks()
            hide.assert_any_call(sda)
            hide.assert_any_call(sdb)

        tree._hide_ignored_disks()
        self.assertFalse(sda in tree.devices)
        self.assertFalse(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)
        self.assertFalse(array in tree.devices)

        tree.unhide(sda)
        tree.unhide(sdb)
        tree.unhide(array)
        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)
        self.assertTrue(array in tree.devices)

    def test_get_related_disks(self):
        tree = DeviceTree()

        sda = DiskDevice("test_sda", size=Size('300g'), exists=False)
        sdb = DiskDevice("test_sdb", size=Size('300g'), exists=False)
        sdc = DiskDevice("test_sdc", size=Size('300G'), exists=False)

        tree._add_device(sda)
        tree._add_device(sdb)
        tree._add_device(sdc)

        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)

        sda.format = get_format("lvmpv", device=sda.path)
        sdb.format = get_format("lvmpv", device=sdb.path)
        vg = LVMVolumeGroupDevice("relvg", parents=[sda, sdb])
        tree._add_device(vg)

        self.assertEqual(tree.get_related_disks(sda), set([sda, sdb]))
        self.assertEqual(tree.get_related_disks(sdb), set([sda, sdb]))
        self.assertEqual(tree.get_related_disks(sdc), set())
        tree.hide(sda)
        self.assertEqual(tree.get_related_disks(sda), set([sda, sdb]))
        self.assertEqual(tree.get_related_disks(sdb), set([sda, sdb]))
        tree.hide(sdb)
        self.assertEqual(tree.get_related_disks(sda), set([sda, sdb]))
        self.assertEqual(tree.get_related_disks(sdb), set([sda, sdb]))
        tree.unhide(sda)
        self.assertEqual(tree.get_related_disks(sda), set([sda, sdb]))
        self.assertEqual(tree.get_related_disks(sdb), set([sda, sdb]))

    # XXX: the lvm_devices_* functions are decorated with needs_config_refresh decorator which
    #      at this point is already applied as a no-op because LVM libblockdev plugin is not available
    @patch("blivet.devicelibs.lvm.lvm_devices_add", new=lvm._lvm_devices.add)
    @patch("blivet.devicelibs.lvm.lvm_devices_remove", new=lvm._lvm_devices.remove)
    def test_lvm_filter_hide_unhide(self):
        tree = DeviceTree()

        sda = DiskDevice("test_sda", size=Size("30 GiB"))
        sdb = DiskDevice("test_sdb", size=Size("30 GiB"))

        tree._add_device(sda)
        tree._add_device(sdb)

        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)

        sda.format = get_format("lvmpv", device=sda.path)
        sdb.format = get_format("lvmpv", device=sdb.path)

        # LVMPhysicalVolume._create would do this
        lvm.lvm_devices_add(sda.path)
        lvm.lvm_devices_add(sdb.path)

        self.assertSetEqual(lvm._lvm_devices, {sda.path, sdb.path})

        tree.hide(sda)
        self.assertSetEqual(lvm._lvm_devices, {sdb.path})
        tree.hide(sdb)
        self.assertSetEqual(lvm._lvm_devices, set())

        tree.unhide(sda)
        self.assertSetEqual(lvm._lvm_devices, {sda.path})
        tree.unhide(sdb)
        self.assertSetEqual(lvm._lvm_devices, {sda.path, sdb.path})


class DeviceTreeIgnoredExclusiveMultipathTestCase(unittest.TestCase):

    def setUp(self):
        self.tree = DeviceTree()

        self.sda = DiskDevice("test_sda")
        self.sdb = DiskDevice("test_sdb")
        self.sdc = DiskDevice("test_sdc")

        self.tree._add_device(self.sda)
        self.tree._add_device(self.sdb)
        self.tree._add_device(self.sdc)

        self.assertTrue(self.sda in self.tree.devices)
        self.assertTrue(self.sdb in self.tree.devices)
        self.assertTrue(self.sdc in self.tree.devices)

        # now test exclusive_disks special cases for multipath
        self.sda.format = get_format("multipath_member", exists=True)
        self.sdb.format = get_format("multipath_member", exists=True)
        self.sdc.format = get_format("multipath_member", exists=True)
        self.mpatha = MultipathDevice("mpatha", parents=[self.sda, self.sdb, self.sdc])
        self.tree._add_device(self.mpatha)

    def test_exclusive_disks_multipath_1(self):
        # multipath is exclusive -> all disks should be exclusive
        self.tree.ignored_disks = []
        self.tree.exclusive_disks = ["mpatha"]

        with patch.object(self.tree, "hide") as hide:
            self.tree._hide_ignored_disks()
            self.assertFalse(hide.called)

        self.tree._hide_ignored_disks()
        self.assertTrue(self.sda in self.tree.devices)
        self.assertTrue(self.sdb in self.tree.devices)
        self.assertTrue(self.sdc in self.tree.devices)
        self.assertTrue(self.mpatha in self.tree.devices)

    def test_exclusive_disks_multipath_2(self):
        # all disks exclusive -> mpath should also be exclusive
        self.tree.exclusive_disks = ["test_sda", "test_sdb", "test_sdc"]
        with patch.object(self.tree, "hide") as hide:
            self.tree._hide_ignored_disks()
            self.assertFalse(hide.called)

        self.tree._hide_ignored_disks()
        self.assertTrue(self.sda in self.tree.devices)
        self.assertTrue(self.sdb in self.tree.devices)
        self.assertTrue(self.sdc in self.tree.devices)
        self.assertTrue(self.mpatha in self.tree.devices)

    def test_exclusive_disks_multipath_3(self):
        # some disks exclusive -> mpath should be hidden
        self.tree.exclusive_disks = ["test_sda", "test_sdb"]
        with patch.object(self.tree, "hide") as hide:
            self.tree._hide_ignored_disks()
            hide.assert_any_call(self.mpatha)
            hide.assert_any_call(self.sdc)

        # verify that hide works as expected
        self.tree._hide_ignored_disks()
        self.assertTrue(self.sda in self.tree.devices)
        self.assertTrue(self.sdb in self.tree.devices)
        self.assertFalse(self.sdc in self.tree.devices)
        self.assertFalse(self.mpatha in self.tree.devices)

    def test_ignored_disks_multipath_1(self):
        # mpatha ignored -> disks should be hidden
        self.tree.ignored_disks = ["mpatha"]
        self.tree.exclusive_disks = []

        with patch.object(self.tree, "hide") as hide:
            self.tree._hide_ignored_disks()
            hide.assert_any_call(self.mpatha)
            hide.assert_any_call(self.sda)
            hide.assert_any_call(self.sdb)
            hide.assert_any_call(self.sdc)

        self.tree._hide_ignored_disks()
        self.assertFalse(self.sda in self.tree.devices)
        self.assertFalse(self.sdb in self.tree.devices)
        self.assertFalse(self.sdc in self.tree.devices)
        self.assertFalse(self.mpatha in self.tree.devices)

    def test_ignored_disks_multipath_2(self):
        # all disks ignored -> mpath should be hidden
        self.tree.ignored_disks = ["test_sda", "test_sdb", "test_sdc"]
        self.tree.exclusive_disks = []

        with patch.object(self.tree, "hide") as hide:
            self.tree._hide_ignored_disks()
            hide.assert_any_call(self.mpatha)
            hide.assert_any_call(self.sda)
            hide.assert_any_call(self.sdb)
            hide.assert_any_call(self.sdc)

        self.tree._hide_ignored_disks()
        self.assertFalse(self.sda in self.tree.devices)
        self.assertFalse(self.sdb in self.tree.devices)
        self.assertFalse(self.sdc in self.tree.devices)
        self.assertFalse(self.mpatha in self.tree.devices)

    def test_ignored_disks_multipath_3(self):
        # some disks ignored -> error
        self.tree.ignored_disks = ["test_sda", "test_sdb"]
        self.tree.exclusive_disks = []

        with self.assertRaises(InvalidMultideviceSelection):
            self.tree._hide_ignored_disks()
