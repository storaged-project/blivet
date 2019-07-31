import test_compat  # pylint: disable=unused-import

from six.moves.mock import Mock, patch, PropertyMock, sentinel  # pylint: disable=no-name-in-module,import-error
import six
import unittest

from blivet.actionlist import ActionList
from blivet.errors import DeviceTreeError, DuplicateUUIDError
from blivet.devicelibs import lvm
from blivet.devices import DiskDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import StorageDevice
from blivet.devices import MultipathDevice
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
        dev1 = StorageDevice("dev1", exists=True, fmt=fmt1)
        dt._add_device(dev1)

        dev2_label = "dev2_label"
        fmt2 = get_format("swap", label=dev2_label)
        dev2 = StorageDevice("dev2", exists=True, fmt=fmt2)
        dt._add_device(dev2)

        dev3 = StorageDevice("sdp2", exists=True)
        dt._add_device(dev3)

        dt.edd_dict.update({"dev1": 0x81,
                            "dev2": 0x82})

        self.assertEqual(dt.resolve_device(dev1.name), dev1)
        self.assertEqual(dt.resolve_device("LABEL=%s" % dev1_label), dev1)
        self.assertEqual(dt.resolve_device("UUID=%s" % dev1_label), None)
        self.assertEqual(dt.resolve_device("UUID=%s" % dev1_uuid), dev1)
        self.assertEqual(dt.resolve_device("/dev/dev1"), dev1)

        self.assertEqual(dt.resolve_device("dev2"), dev2)
        self.assertEqual(dt.resolve_device("0x82"), dev2)

        self.assertEqual(dt.resolve_device(dev3.name), dev3)

    def test_device_name(self):
        # check that devicetree.names property contains all device's names

        # mock lvs_info to avoid blockdev call allowing run as non-root
        with patch.object(LVsInfo, 'cache', new_callable=PropertyMock) as mock_lvs_cache:
            mock_lvs_cache.return_value = {"sdmock": "dummy"}

            tree = DeviceTree()
            dev_names = ["sda", "sdb", "sdc"]

            for dev_name in dev_names:
                dev = DiskDevice(dev_name)
                tree._add_device(dev)
                self.assertTrue(dev in tree.devices)

            # frobnicate a bit with the hidden status of the devices:
            # * hide sda
            # * hide and unhide again sdb
            # * leave sdc unchanged
            tree.hide(tree.get_device_by_name("sda"))
            tree.hide(tree.get_device_by_name("sdb"))
            tree.unhide(tree.get_device_by_name("sdb", hidden=True))

            # some lvs names may be already present in the system (mocked)
            lv_info = list(lvs_info.cache.keys())

            # all devices should still be present in the tree.names
            self.assertEqual(sorted(tree.names), sorted(lv_info + dev_names))

    def test_reset(self):
        dt = DeviceTree()
        names = ["fakedev1", "fakedev2"]
        for name in names:
            device = Mock(name=name, spec=StorageDevice, parents=[], exists=True)
            dt._devices.append(device)

        dt.actions._actions.append(Mock(name="fake action"))

        lvm.lvm_cc_addFilterRejectRegexp("xxx")
        lvm.config_args_data["filterAccepts"].append("yyy")

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

        self.assertEqual(lvm.config_args_data["filterAccepts"], empty_list)
        self.assertEqual(lvm.config_args_data["filterRejects"], empty_list)

        self.assertEqual(dt.exclusive_disks, empty_list)
        self.assertEqual(dt.ignored_disks, empty_list)

        self.assertEqual(dt.edd_dict, dict())

    @patch.object(StorageDevice, "add_hook")
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
        six.assertRaisesRegex(self, DeviceTreeError, "Trying to add already existing device.", dt._add_device, dev1)

        # adding a device with the same UUID
        dev_clone = StorageDevice("dev_clone", exists=False, uuid=sentinel.dev1_uuid, parents=[])
        six.assertRaisesRegex(self, DuplicateUUIDError, "Duplicate UUID.*", dt._add_device, dev_clone)

        dev2 = StorageDevice("dev2", exists=False, parents=[])
        dev3 = StorageDevice("dev3", exists=False, parents=[dev1, dev2])

        # adding a device with one or more parents not already in the tree fails
        six.assertRaisesRegex(self, DeviceTreeError, "parent.*not in tree", dt._add_device, dev3)
        self.assertFalse(dev2 in dt.devices)
        self.assertFalse(dev2.name in dt.names)

        dt._add_device(dev2)
        self.assertTrue(dev2 in dt.devices)
        self.assertTrue(dev2.name in dt.names)

        dt._add_device(dev3)
        self.assertTrue(dev3 in dt.devices)
        self.assertTrue(dev3.name in dt.names)

    @patch.object(StorageDevice, "remove_hook")
    def test_remove_device(self, *args):  # pylint: disable=unused-argument
        dt = DeviceTree()

        dev1 = StorageDevice("dev1", exists=False, parents=[])

        # removing a device not in the tree raises an exception
        six.assertRaisesRegex(self, ValueError, "not in tree", dt._remove_device, dev1)

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
        six.assertRaisesRegex(self, ValueError, "non-leaf device", dt._remove_device, dev1)
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

    def test_hide_ignored_disks(self):
        tree = DeviceTree()

        sda = DiskDevice("sda")
        sdb = DiskDevice("sdb")
        sdc = DiskDevice("sdc")

        tree._add_device(sda)
        tree._add_device(sdb)
        tree._add_device(sdc)

        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)

        # test ignored_disks
        tree.ignored_disks = ["sdb"]

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

        # test exclusive_disks
        tree.ignored_disks = []
        tree.exclusive_disks = ["sdc"]
        with patch.object(tree, "hide") as hide:
            tree._hide_ignored_disks()
            hide.assert_any_call(sda)
            hide.assert_any_call(sdb)

        tree._hide_ignored_disks()
        self.assertFalse(sda in tree.devices)
        self.assertFalse(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)

        tree.unhide(sda)
        tree.unhide(sdb)
        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)

        # now test exclusive_disks special cases for multipath
        sda.format = get_format("multipath_member", exists=True)
        sdb.format = get_format("multipath_member", exists=True)
        sdc.format = get_format("multipath_member", exists=True)
        mpatha = MultipathDevice("mpatha", parents=[sda, sdb, sdc])
        tree._add_device(mpatha)

        tree.ignored_disks = []
        tree.exclusive_disks = ["mpatha"]

        with patch.object(tree, "hide") as hide:
            tree._hide_ignored_disks()
            self.assertFalse(hide.called)

        tree._hide_ignored_disks()
        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)
        self.assertTrue(mpatha in tree.devices)

        # all members in exclusive_disks implies the mpath in exclusive_disks
        tree.exclusive_disks = ["sda", "sdb", "sdc"]
        with patch.object(tree, "hide") as hide:
            tree._hide_ignored_disks()
            self.assertFalse(hide.called)

        tree._hide_ignored_disks()
        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertTrue(sdc in tree.devices)
        self.assertTrue(mpatha in tree.devices)

        tree.exclusive_disks = ["sda", "sdb"]
        with patch.object(tree, "hide") as hide:
            tree._hide_ignored_disks()
            hide.assert_any_call(mpatha)
            hide.assert_any_call(sdc)

        # verify that hide works as expected
        tree._hide_ignored_disks()
        self.assertTrue(sda in tree.devices)
        self.assertTrue(sdb in tree.devices)
        self.assertFalse(sdc in tree.devices)
        self.assertFalse(mpatha in tree.devices)

    def test_get_related_disks(self):
        tree = DeviceTree()

        sda = DiskDevice("sda", size=Size('300g'))
        sdb = DiskDevice("sdb", size=Size('300g'))
        sdc = DiskDevice("sdc", size=Size('300G'))

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
