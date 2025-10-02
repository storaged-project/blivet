import os
import unittest

from .storagetestcase import StorageTestCase

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


@unittest.skipUnless(os.environ.get("JENKINS_HOME"), "jenkins only test")
class BlivetResetTestCase(StorageTestCase):

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

    def _set_up_storage(self):
        for disk in self.storage.disks:
            self.storage.initialize_disk(disk)

    def collect_expected_data(self):
        """ Collect the attribute data we plan to validate later. """
        # only look at devices on the disk images -- no loops, &c
        for device in (d for d in self.storage.devices
                       if d.disks and
                       set(d.disks).issubset(set(self.storage.disks))):
            attr_dict = {}
            device._parted_device = None  # force update from disk for size, &c
            for attr in self._validate_attrs:
                attr_dict[attr] = recursive_getattr(device, attr)

            self.device_attr_dicts.append(attr_dict)

    def setUp(self):
        super().setUp()
        self._blivet_setup()
        self._set_up_storage()
        self.storage.do_it()

        trigger(subsystem="block", action="change")

        self.device_attr_dicts = []
        self.collect_expected_data()

    def _clean_up(self):
        self._blivet_cleanup()
        return super()._clean_up()

    def skip_attr(self, device, attr):
        """ Return True if attr should not be checked for device. """
        # pylint: disable=unused-argument
        return False

    def find_device(self, attr_dict):
        devices = self.storage.devices
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
        self.storage.reset()

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
        super()._set_up_storage()
        # This isn't exactly autopart, but it should be plenty close to it.
        self.storage.factory_device(devicefactory.DeviceTypes.LVM,
                                    size=Size("500 MiB"),
                                    disks=self.storage.disks[:],
                                    fstype="swap")
        self.storage.factory_device(devicefactory.DeviceTypes.LVM,
                                    disks=self.storage.disks[:])


class LVMSnapShotTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        super()._set_up_storage()
        self.storage.factory_device(devicefactory.DeviceTypes.LVM,
                                    size=Size("1 GiB"),
                                    label="ROOT",
                                    disks=self.storage.disks[:],
                                    container_name="blivet_test",
                                    container_size=devicefactory.SIZE_POLICY_MAX)

    def setUp(self):
        super().setUp()
        root = self.storage.lvs[0]
        snap = LVMLogicalVolumeDevice("rootsnap1", parents=[root.vg], origin=root,
                                      size=Size("768MiB"))
        self.storage.create_device(snap)
        self.storage.do_it()

        self.device_attr_dicts = []
        self.collect_expected_data()


class LVMThinpTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        super()._set_up_storage()
        self.storage.factory_device(devicefactory.DeviceTypes.LVM,
                                    size=Size("500 MiB"),
                                    fstype="swap",
                                    disks=self.storage.disks[:])
        self.storage.factory_device(devicefactory.DeviceTypes.LVM_THINP,
                                    label="ROOT",
                                    disks=self.storage.disks[:])


class LVMThinSnapShotTestCase(LVMThinpTestCase):

    def setUp(self):
        super().setUp()

        root = self.storage.thinlvs[0]
        snap = LVMLogicalVolumeDevice("rootsnap1", parents=[root.pool],
                                      origin=root, seg_type="thin")
        self.storage.create_device(snap)
        self.storage.do_it()

        self.device_attr_dicts = []
        self.collect_expected_data()


class LVMRaidTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        super()._set_up_storage()
        self.storage.factory_device(devicefactory.DeviceTypes.LVM,
                                    size=Size("500 MiB"),
                                    disks=self.storage.disks[:],
                                    container_size=devicefactory.SIZE_POLICY_MAX)

    def setUp(self):
        super().setUp()
        vg_name = self.storage.vgs[0].name
        util.run_program(["lvcreate", "-n", "raid", "--type", "raid1",
                          "-L", "100%", vg_name])
        self.device_attr_dicts = []
        self.collect_expected_data()


class StratisTestCase(BlivetResetTestCase):

    def _set_up_storage(self):
        if not devicefactory.is_supported_device_type(devicefactory.DeviceTypes.STRATIS):
            self.skipTest("Stratis not supported, skipping")
        super()._set_up_storage()

        self.storage.factory_device(devicefactory.DeviceTypes.STRATIS,
                                    size=Size("1 GiB"),
                                    disks=self.storage.disks[:],
                                    name="stratisfs",
                                    pool_name="stratispool")


class MDRaid0TestCase(BlivetResetTestCase):
    _num_disks = 2

    """ Verify correct detection of MD RAID0 arrays. """
    level = "raid0"
    _validate_attrs = BlivetResetTestCase._validate_attrs + ["level", "spares"]

    def skip_attr(self, device, attr):
        return (attr in ["name", "path"] and
                getattr(device, "metadata_version", "").startswith("0.9"))

    def _set_up_storage(self):
        super()._set_up_storage()
        device = self.storage.factory_device(devicefactory.DeviceTypes.MD,
                                             size=Size("200 MiB"),
                                             disks=self.storage.disks[:],
                                             raid_level=self.level,
                                             label="v1",
                                             name="one")
        device.metadata_version = "1.0"

        device = self.storage.factory_device(devicefactory.DeviceTypes.MD,
                                             size=Size("200 MiB"),
                                             disks=self.storage.disks[:],
                                             raid_level=self.level,
                                             label="v11",
                                             name="oneone")
        device.metadata_version = "1.1"

        device = self.storage.factory_device(devicefactory.DeviceTypes.MD,
                                             size=Size("200 MiB"),
                                             disks=self.storage.disks[:],
                                             raid_level=self.level,
                                             label="v12",
                                             name="onetwo")
        device.metadata_version = "1.2"

        device = self.storage.factory_device(devicefactory.DeviceTypes.MD,
                                             size=Size("200 MiB"),
                                             disks=self.storage.disks[:],
                                             raid_level=self.level,
                                             label="vdefault",
                                             name="default")
