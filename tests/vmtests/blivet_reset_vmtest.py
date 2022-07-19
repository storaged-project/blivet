import unittest

from .vmbackedtestcase import VMBackedTestCase

from blivet.size import Size
from blivet import devicefactory
from blivet import util

from blivet.udev import trigger
from blivet.devices.lvm import LVMLogicalVolumeDevice


def recursive_getattr(x, attr, default=None):
    """ Resolve a possibly-dot-containing attribute name. """
    val = x
    for sub_attr in attr.split("."):
        try:
            val = getattr(val, sub_attr)
        except AttributeError:
            return default

    return val


class BlivetResetTestCase(VMBackedTestCase):

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

    def test_run(self):
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
                                   size=Size("500 MiB"),
                                   disks=self.blivet.disks[:],
                                   fstype="swap")
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   disks=self.blivet.disks[:])


class LVMSnapShotTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   size=Size("1 GiB"),
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
                                   size=Size("500 MiB"),
                                   fstype="swap",
                                   disks=self.blivet.disks[:])
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM_THINP,
                                   label="ROOT",
                                   disks=self.blivet.disks[:])


class LVMThinSnapShotTestCase(LVMThinpTestCase):

    def _set_up_storage(self):
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM_THINP,
                                   size=Size("1 GiB"),
                                   label="ROOT",
                                   disks=self.blivet.disks[:])

    def setUp(self):
        super(BlivetResetTestCase, self).setUp()  # pylint: disable=bad-super-call

        root = self.blivet.thinlvs[0]
        snap = LVMLogicalVolumeDevice("rootsnap1", parents=[root.pool],
                                      origin=root, seg_type="thin")
        self.blivet.create_device(snap)
        self.blivet.do_it()

        self.device_attr_dicts = []
        self.collect_expected_data()


class LVMRaidTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        # This isn't exactly autopart, but it should be plenty close to it.
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   size=Size("500 MiB"),
                                   disks=self.blivet.disks[:],
                                   container_size=devicefactory.SIZE_POLICY_MAX)

    def setUp(self):
        super(BlivetResetTestCase, self).setUp()  # pylint: disable=bad-super-call
        vg_name = self.blivet.vgs[0].name
        util.run_program(["lvcreate", "-n", "raid", "--type", "raid1",
                          "-L", "100%", vg_name])
        self.device_attr_dicts = []
        self.collect_expected_data()


class LVMVDOTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        if not devicefactory.is_supported_device_type(devicefactory.DEVICE_TYPE_LVM_VDO):
            self.skipTest("VDO not supported, skipping")

        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM_VDO,
                                   size=Size("10 GiB"),
                                   fstype="ext4",
                                   disks=self.blivet.disks[:],
                                   name="vdolv",
                                   pool_name="vdopool",
                                   virtual_size=Size("40 GiB"))


class StratisTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        if not devicefactory.is_supported_device_type(devicefactory.DEVICE_TYPE_STRATIS):
            self.skipTest("Stratis not supported, skipping")

        self.blivet.factory_device(devicefactory.DEVICE_TYPE_STRATIS,
                                   size=Size("10 GiB"),
                                   disks=self.blivet.disks[:],
                                   name="stratisfs",
                                   pool_name="stratispool")


@unittest.skip("temporarily disabled due to issues with raids with metadata version 0.90")
class MDRaid0TestCase(BlivetResetTestCase):

    """ Verify correct detection of MD RAID0 arrays. """
    level = "raid0"
    _validate_attrs = BlivetResetTestCase._validate_attrs + ["level", "spares"]

    def skip_attr(self, device, attr):
        return (attr in ["name", "path"] and
                getattr(device, "metadata_version", "").startswith("0.9"))

    def _set_up_storage(self):
        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            size=Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v090",
                                            name="2")
        device.metadata_version = "0.90"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            size=Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v1",
                                            name="one")
        device.metadata_version = "1.0"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            size=Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v11",
                                            name="oneone")
        device.metadata_version = "1.1"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            size=Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="v12",
                                            name="onetwo")
        device.metadata_version = "1.2"

        device = self.blivet.factory_device(devicefactory.DEVICE_TYPE_MD,
                                            size=Size("200 MiB"),
                                            disks=self.blivet.disks[:],
                                            raid_level=self.level,
                                            label="vdefault",
                                            name="default")


class LVMOnMDTestCase(BlivetResetTestCase):
    # This also tests raid1 with the default metadata version.

    def _set_up_storage(self):
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   size=Size("200 MiB"),
                                   disks=self.blivet.disks[:],
                                   container_raid_level="raid1",
                                   fstype="swap")
        self.blivet.factory_device(devicefactory.DEVICE_TYPE_LVM,
                                   disks=self.blivet.disks[:],
                                   container_raid_level="raid1")
