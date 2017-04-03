import unittest

try:
    from mock import patch
except ImportError:
    has_mock = False
else:
    has_mock = True

from tests.imagebackedtestcase import ImageBackedTestCase

from blivet.size import Size
from blivet import devicelibs
from blivet import devicefactory
from blivet import util
from blivet.udev import trigger
from blivet.devices import LVMSnapShotDevice, LVMThinSnapShotDevice
from blivet.devices import StorageDevice
from blivet.devicetree import DeviceTree
from blivet.formats import getFormat

"""
    TODO:

        - add more lvm tests
            - thin pool with separate data and metadata volumes?
            - raid lvs
            - raid thin pool
"""

class DeviceTreeTestCase(unittest.TestCase):
    def testResolveDevice(self):
        dt = DeviceTree()

        dev1_label = "dev1_label"
        dev1_uuid = "1234-56-7890"
        fmt1 = getFormat("ext4", label=dev1_label, uuid=dev1_uuid)
        dev1 = StorageDevice("dev1", exists=True, fmt=fmt1)
        dt._addDevice(dev1)

        dev2_label = "dev2_label"
        fmt2 = getFormat("swap", label=dev2_label)
        dev2 = StorageDevice("dev2", exists=True, fmt=fmt2)
        dt._addDevice(dev2)

        dev3 = StorageDevice("sdp2", exists=True)
        dt._addDevice(dev3)

        self.assertEqual(dt.resolveDevice(dev1.name), dev1)
        self.assertEqual(dt.resolveDevice("LABEL=%s" % dev1_label), dev1)
        self.assertEqual(dt.resolveDevice("UUID=%s" % dev1_label), None)
        self.assertEqual(dt.resolveDevice("UUID=%s" % dev1_uuid), dev1)
        self.assertEqual(dt.resolveDevice("/dev/dev1"), dev1)

        self.assertEqual(dt.resolveDevice("dev2"), dev2)
        if has_mock:
            with patch("blivet.devicetree.edd") as patched_edd:
                patched_edd.edd_dict = {"dev1": 0x81, "dev2": 0x82}
                self.assertEqual(dt.resolveDevice("0x82"), dev2)

        self.assertEqual(dt.resolveDevice(dev3.name), dev3)

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
            device._partedDevice = None # force update from disk for size, &c
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
            self.blivet.recursiveRemove(disk)

        try:
            self.blivet.doIt()
        except Exception:
            self.blivet.reset()
            raise

    def skip_attr(self, device, attr):
        """ Return True if attr should not be checked for device. """
        # pylint: disable=unused-argument
        return False

    def find_device(self, attr_dict):
        devices = self.blivet.devices #+ self.blivet.devicetree._hidden
        device = None
        for check in devices:
            match = all(attr_dict[attr] == recursive_getattr(check, attr)
                        for attr in self._identifying_attrs)
            if match:
                device = check
                break

        return device

    def runTest(self):
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
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM,
                                  Size("500 MiB"),
                                  disks=self.blivet.disks[:],
                                  fstype="swap")
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM,
                                  None,
                                  disks=self.blivet.disks[:])

class LVMSnapShotTestCase(BlivetResetTestCase):
    def _set_up_storage(self):
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM,
                                  Size("1 GiB"),
                                  label="ROOT",
                                  disks=self.blivet.disks[:],
                                  container_name="blivet_test",
                                  container_size=devicefactory.SIZE_POLICY_MAX)

    def setUp(self):
        super(BlivetResetTestCase, self).setUp() # pylint: disable=bad-super-call
        root = self.blivet.lvs[0]
        snap = LVMSnapShotDevice("rootsnap1", parents=[root.vg], origin=root,
                                 size=Size("768MiB"))
        self.blivet.createDevice(snap)
        self.blivet.doIt()

        self.device_attr_dicts = []
        self.collect_expected_data()


class LVMThinpTestCase(BlivetResetTestCase):
    def _set_up_storage(self):
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM,
                                  Size("500 MiB"),
                                  fstype="swap",
                                  disks=self.blivet.disks[:])
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM_THINP,
                                  None,
                                  label="ROOT",
                                  disks=self.blivet.disks[:])

class LVMThinSnapShotTestCase(LVMThinpTestCase):
    def _set_up_storage(self):
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM_THINP,
                                  Size("1 GiB"),
                                  label="ROOT",
                                  disks=self.blivet.disks[:])

    def setUp(self):
        super(BlivetResetTestCase, self).setUp() # pylint: disable=bad-super-call

        root = self.blivet.thinlvs[0]
        snap = LVMThinSnapShotDevice("rootsnap1", parents=[root.pool],
                                     origin=root)
        self.blivet.createDevice(snap)
        self.blivet.doIt()

        self.device_attr_dicts = []
        self.collect_expected_data()

class LVMRaidTestCase(BlivetResetTestCase):
    def _set_up_storage(self):
        # This isn't exactly autopart, but it should be plenty close to it.
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM,
                          Size("500 MiB"),
                          disks=self.blivet.disks[:],
                          container_size=devicefactory.SIZE_POLICY_MAX)

    def setUp(self):
        super(BlivetResetTestCase, self).setUp() # pylint: disable=bad-super-call
        vg_name = self.blivet.vgs[0].name
        util.run_program(["lvcreate", "-n", "raid", "--type", "raid1",
                          "-L", "100%", vg_name])
        self.device_attr_dicts = []
        self.collect_expected_data()


class MDRaid0TestCase(BlivetResetTestCase):
    """ Verify correct detection of MD RAID0 arrays. """
    level = "raid0"
    _validate_attrs = BlivetResetTestCase._validate_attrs + ["level", "spares"]

    def set_up_disks(self):
        level = devicelibs.mdraid.RAID_levels.raidLevel(self.level)
        disk_count = level.min_members
        self.disks = dict()
        for i in range(disk_count):
            name = "disk%d" % (i+1)
            size = Size("2 GiB")
            self.disks[name] = size

        super(MDRaid0TestCase, self).set_up_disks()

    def skip_attr(self, device, attr):
        return (attr in ["name", "path"] and
                getattr(device, "metadataVersion", "").startswith("0.9"))

    def _set_up_storage(self):
        device = self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_MD,
                                           Size("200 MiB"),
                                           disks=self.blivet.disks[:],
                                           raid_level=self.level,
                                           label="v090",
                                           name="2")
        device.metadataVersion = "0.90"

        device = self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_MD,
                                           Size("200 MiB"),
                                           disks=self.blivet.disks[:],
                                           raid_level=self.level,
                                           label="v1",
                                           name="one")
        device.metadataVersion = "1.0"

        device = self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_MD,
                                           Size("200 MiB"),
                                           disks=self.blivet.disks[:],
                                           raid_level=self.level,
                                           label="v11",
                                           name="oneone")
        device.metadataVersion = "1.1"

        device = self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_MD,
                                           Size("200 MiB"),
                                           disks=self.blivet.disks[:],
                                           raid_level=self.level,
                                           label="v12",
                                           name="onetwo")
        device.metadataVersion = "1.2"

        device = self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_MD,
                                           Size("200 MiB"),
                                           disks=self.blivet.disks[:],
                                           raid_level=self.level,
                                           label="vdefault",
                                           name="default")

class LVMOnMDTestCase(BlivetResetTestCase):
    # This also tests raid1 with the default metadata version.
    def _set_up_storage(self):
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM,
                                  Size("200 MiB"),
                                  disks=self.blivet.disks[:],
                                  container_raid_level="raid1",
                                  fstype="swap")
        self.blivet.factoryDevice(devicefactory.DEVICE_TYPE_LVM,
                                  None,
                                  disks=self.blivet.disks[:],
                                  container_raid_level="raid1")

if __name__ == "__main__":
    unittest.main()
