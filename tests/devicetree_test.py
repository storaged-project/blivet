import unittest
from unittest.mock import Mock, patch, sentinel

from tests.imagebackedtestcase import ImageBackedTestCase

from blivet.size import Size
from blivet import devicelibs
from blivet import devicefactory
from blivet import util
from blivet.actionlist import ActionList
from blivet.errors import DeviceTreeError
from blivet.udev import trigger
from blivet.devicelibs import lvm
from blivet.devices import StorageDevice
from blivet.devices.lvm import LVMLogicalVolumeDevice
from blivet.devicetree import DeviceTree
from blivet.formats import get_format

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

    def test_reset(self):
        dt = DeviceTree()
        names = ["fakedev1", "fakedev2"]
        for name in names:
            device = Mock(name=name, spec=StorageDevice, parents=[], exists=True)
            dt._devices.append(device)

        dt.names = names[:]

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
        self.assertRaisesRegex(ValueError, "already in tree", dt._add_device, dev1)

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


def recursive_getattr(x, attr, default=None):
    """ Resolve a possibly-dot-containing attribute name. """
    val = x
    for sub_attr in attr.split("."):
        try:
            val = getattr(val, sub_attr)
        except AttributeError:
            return default

    return val


class BlivetResetTestCase(ImageBackedTestCase):

    """ A class to test the results of Blivet.reset (and DeviceTree.populate).

        Create a device stack on disk images, catalog a set of attributes of
        every device we created, reset the Blivet instance, and then verify
        that the devices are all discovered and have attributes matching those
        we cataloged previously.
    """
    _validate_attrs = ["name", "type", "size",
                       "format.type", "format.mountpoint", "format.label"]
    """ List of StorageDevice attributes to verify match across the reset. """

    _identifying_attrs = ["name", "type"]
    """ List of attributes that must match to identify a device. """

    def collect_expected_data(self):
        """ Collect the attribute data we plan to validate later. """
        # only look at devices on the disk images -- no loops, &c
        for device in (d for d in self.blivet.devices
                       if d.disks and
                       set(d.disks).issubset(set(self.blivet.disks))):
            attr_dict = {}
            device._parted_device = None  # force update from disk for size, &c
            for attr in self._validate_attrs:
                attr_dict[attr] = recursive_getattr(device, attr)

            self.device_attr_dicts.append(attr_dict)

    def setUp(self):
        super(BlivetResetTestCase, self).setUp()

        trigger(subsystem="block", action="change")

        self.device_attr_dicts = []
        self.collect_expected_data()

    def tearDown(self):
        """ Clean up after testing is complete. """
        super(BlivetResetTestCase, self).tearDown()

        # XXX The only reason for this may be lvmetad
        for disk in self.blivet.disks:
            self.blivet.recursive_remove(disk)

        try:
            self.blivet.do_it()
        except Exception:
            self.blivet.reset()
            raise

    def skip_attr(self, device, attr):
        """ Return True if attr should not be checked for device. """
        # pylint: disable=unused-argument
        return False

    def find_device(self, attr_dict):
        devices = self.blivet.devices  # + self.blivet.devicetree._hidden
        device = None
        for check in devices:
            match = all(attr_dict[attr] == recursive_getattr(check, attr)
                        for attr in self._identifying_attrs)
            if match:
                device = check
                break

        return device

    def run_test(self):
        """ Verify that the devices and their attributes match across reset. """
        #
        # populate the devicetree
        # XXX it would be better to test the results of a reboot
        #
        self.blivet.reset()

        for attr_dict in self.device_attr_dicts:
            #
            # verify we can find the device that corresponds to this attr_dict
            #
            device = self.find_device(attr_dict)
            device_id = "/".join(attr_dict[attr] for attr in self._identifying_attrs)
            self.assertIsNotNone(device, msg="failed to find %s" % device_id)

            #
            # verify that all attributes match across the reset
            #
            for attr, expected in iter(attr_dict.items()):
                if self.skip_attr(device, attr):
                    continue

                actual = recursive_getattr(device, attr)
                self.assertEqual(actual, expected,
                                 msg=("attribute mismatch for %s: %s (%s/%s)"
                                      % (device_id, attr, expected, actual)))


class LVMTestCase(BlivetResetTestCase):

    """ Test that the devicetree can populate with the product of autopart. """

    def _set_up_storage(self):
        # This isn't exactly autopart, but it should be plenty close to it.
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   Size("500 MiB"),
                                   disks=self.blivet.disks[:],
                                   fstype="swap")
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   None,
                                   disks=self.blivet.disks[:])


class LVMSnapShotTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   Size("1 GiB"),
                                   label="ROOT",
                                   disks=self.blivet.disks[:],
                                   container_name="blivet_test",
                                   container_size=devicefactory.SIZE_POLICY_MAX)

    def setUp(self):
        super(BlivetResetTestCase, self).setUp()  # pylint: disable=bad-super-call
        root = self.blivet.lvs[0]
        snap = LVMLogicalVolumeDevice("rootsnap1", parents=[root.vg], origin=root,
                                      size=Size("768MiB"))
        self.blivet.create_device(snap)
        self.blivet.do_it()

        self.device_attr_dicts = []
        self.collect_expected_data()


class LVMThinpTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   Size("500 MiB"),
                                   fstype="swap",
                                   disks=self.blivet.disks[:])
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM_THINP,
                                   None,
                                   label="ROOT",
                                   disks=self.blivet.disks[:])


class LVMThinSnapShotTestCase(LVMThinpTestCase):

    def _set_up_storage(self):
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM_THINP,
                                   Size("1 GiB"),
                                   label="ROOT",
                                   disks=self.blivet.disks[:])

    def setUp(self):
        super(BlivetResetTestCase, self).setUp()  # pylint: disable=bad-super-call

        root = self.blivet.thinlvs[0]
        snap = LVMLogicalVolumeDevice("rootsnap1", parents=[root.pool],
                                      origin=root)
        self.blivet.create_device(snap)
        self.blivet.do_it()

        self.device_attr_dicts = []
        self.collect_expected_data()


class LVMRaidTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        # This isn't exactly autopart, but it should be plenty close to it.
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   Size("500 MiB"),
                                   disks=self.blivet.disks[:],
                                   container_size=devicefactory.SIZE_POLICY_MAX)

    def setUp(self):
        super(BlivetResetTestCase, self).setUp()  # pylint: disable=bad-super-call
        vg_name = self.blivet.vgs[0].name
        util.run_program(["lvcreate", "-n", "raid", "--type", "raid1",
                          "-L", "100%", vg_name])
        self.device_attr_dicts = []
        self.collect_expected_data()


@unittest.skip("temporarily disabled due to mdadm issues")
class MDRaid0TestCase(BlivetResetTestCase):

    """ Verify correct detection of MD RAID0 arrays. """
    level = "raid0"
    _validate_attrs = BlivetResetTestCase._validate_attrs + ["level", "spares"]

    def set_up_disks(self):
        level = devicelibs.mdraid.raid_levels.raid_level(self.level)
        disk_count = level.min_members
        self.disks = dict()
        for i in range(disk_count):
            name = "disk%d" % (i + 1)
            size = Size("2 GiB")
            self.disks[name] = size

        super(MDRaid0TestCase, self).set_up_disks()

    def skip_attr(self, device, attr):
        return (attr in ["name", "path"] and
                getattr(device, "metadata_version", "").startswith("0.9"))

    def _set_up_storage(self):
        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v090",
                                            name="2")
        device.metadata_version = "0.90"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v1",
                                            name="one")
        device.metadata_version = "1.0"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v11",
                                            name="oneone")
        device.metadata_version = "1.1"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v12",
                                            name="onetwo")
        device.metadata_version = "1.2"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="vdefault",
                                            name="default")


@unittest.skip("temporarily disabled due to mdadm issues")
class LVMOnMDTestCase(BlivetResetTestCase):
    # This also tests raid1 with the default metadata version.

    def _set_up_storage(self):
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   Size("200 MiB"),
                                   disks=self.blivet.disks[:],
                                   container_raid_level="raid1",
                                   fstype="swap")
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   None,
                                   disks=self.blivet.disks[:],
                                   container_raid_level="raid1")
