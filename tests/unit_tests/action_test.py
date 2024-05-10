import unittest
from unittest.mock import Mock, patch

from .blivettestcase import BlivetTestCase
import blivet
from blivet.formats import get_format
from blivet.size import Size

# device classes for brevity's sake -- later on, that is
from blivet.devices import StorageDevice
from blivet.devices import DiskDevice
from blivet.devices import DMDevice
from blivet.devices import PartitionDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices.lvm import LVMLogicalVolumeBase, LVMVDOPoolMixin
from blivet.devices.lvm import LVMVDOLogicalVolumeMixin

# format classes
from blivet.formats.fs import Ext2FS
from blivet.formats.fs import Ext3FS
from blivet.formats.fs import Ext4FS
from blivet.formats.fs import FATFS
from blivet.formats.fs import XFS
from blivet.formats.lvmpv import LVMPhysicalVolume
from blivet.formats.mdraid import MDRaidMember
from blivet.formats.swap import SwapSpace

# action classes
from blivet.deviceaction import ActionCreateDevice
from blivet.deviceaction import ActionResizeDevice
from blivet.deviceaction import ActionDestroyDevice
from blivet.deviceaction import ActionCreateFormat
from blivet.deviceaction import ActionResizeFormat
from blivet.deviceaction import ActionDestroyFormat
from blivet.deviceaction import ActionAddMember
from blivet.deviceaction import ActionRemoveMember
from blivet.deviceaction import ActionConfigureFormat
from blivet.deviceaction import ActionConfigureDevice

DEVICE_CLASSES = [
    DiskDevice,
    DMDevice,
    PartitionDevice,
    MDRaidArrayDevice,
    LVMVolumeGroupDevice,
    LVMLogicalVolumeDevice,
    LVMLogicalVolumeBase,
    LVMVDOPoolMixin,
    LVMVDOLogicalVolumeMixin
]

FORMAT_CLASSES = [
    Ext2FS,
    Ext3FS,
    Ext4FS,
    FATFS,
    XFS,
    LVMPhysicalVolume,
    MDRaidMember,
    SwapSpace
]


def _patch_device_dependencies(fn):
    def fn_with_patch(*args, **kwargs):
        for cls in DEVICE_CLASSES:
            patcher = patch.object(cls, "_external_dependencies", new=[])
            patcher.start()

        fn(*args, **kwargs)

        patch.stopall()

    return fn_with_patch


def _patch_format_dependencies(fn):
    def fn_with_patch(*args, **kwargs):
        for cls in FORMAT_CLASSES:
            patcher = patch.object(cls, "destroyable", return_value=True)
            patcher.start()

            patcher = patch.object(cls, "formattable", return_value=True)
            patcher.start()

            if cls._resizable:
                patcher = patch.object(cls, "resizable", return_value=True)
                patcher.start()

        fn(*args, **kwargs)

        patch.stopall()

    return fn_with_patch


class DeviceActionTestCase(BlivetTestCase):

    """ DeviceActionTestSuite """

    def setUp(self, *args):  # pylint: disable=unused-argument
        """ Create something like a preexisting autopart on two disks (sda,sdb).

            The other two disks (sdc,sdd) are left for individual tests to use.
        """
        super(DeviceActionTestCase, self).setUp()

        for name in ["sda", "sdb", "sdc", "sdd"]:
            disk = self.new_device(device_class=DiskDevice,
                                   name=name, size=Size("100 GiB"))
            disk.format = self.new_format("disklabel", path=disk.path,
                                          exists=True)
            self.storage.devicetree._add_device(disk)

        # create a layout similar to autopart as a starting point
        sda = self.storage.devicetree.get_device_by_name("sda")
        sdb = self.storage.devicetree.get_device_by_name("sdb")

        sda1 = self.new_device(device_class=PartitionDevice,
                               exists=True, name="sda1", parents=[sda],
                               size=Size("500 MiB"))
        sda1.format = self.new_format("ext4", mountpoint="/boot",
                                      device_instance=sda1,
                                      device=sda1.path, exists=True)
        self.storage.devicetree._add_device(sda1)

        sda2 = self.new_device(device_class=PartitionDevice,
                               size=Size("99.5 GiB"), name="sda2",
                               parents=[sda], exists=True)
        sda2.format = self.new_format("lvmpv", device=sda2.path, exists=True)
        self.storage.devicetree._add_device(sda2)

        sdb1 = self.new_device(device_class=PartitionDevice,
                               size=Size("99.999 GiB"), name="sdb1",
                               parents=[sdb], exists=True)
        sdb1.format = self.new_format("lvmpv", device=sdb1.path, exists=True)
        self.storage.devicetree._add_device(sdb1)

        vg = self.new_device(device_class=LVMVolumeGroupDevice,
                             name="VolGroup", parents=[sda2, sdb1],
                             exists=True)
        self.storage.devicetree._add_device(vg)

        lv_root = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_root", parents=[vg],
                                  size=Size("160 GiB"), exists=True)
        lv_root.format = self.new_format("ext4", mountpoint="/",
                                         device_instance=lv_root,
                                         device=lv_root.path, exists=True)
        self.storage.devicetree._add_device(lv_root)

        lv_swap = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_swap", parents=[vg],
                                  size=Size("4000 MiB"), exists=True)
        lv_swap.format = self.new_format("swap", device=lv_swap.path,
                                         device_instance=lv_swap,
                                         exists=True)
        self.storage.devicetree._add_device(lv_swap)

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_actions(self):
        """ Verify correct management of actions.

            - action creation/registration/cancellation
                - ActionCreateDevice adds device to tree
                - ActionDestroyDevice removes device from tree
                - ActionCreateFormat sets device.format in tree
                - ActionDestroyFormat unsets device.format in tree
                - cancelled action's registration side-effects reversed
                - failure to register destruction of non-leaf device
                - failure to register creation of device already in tree?
                - failure to register destruction of device not in tree?

            - action pruning
                - non-existent-device create..destroy cycles removed
                    - all actions on this device should get removed
                - all actions pruned from to-be-destroyed devices
                    - resize, format, &c
                - redundant resize/format actions pruned
                    - last one registered stays

            - action sorting
                - destroy..resize..create
                - creation
                    - leaves-last, including formatting
                - destruction
                    - leaves-first
        """
        devicetree = self.storage.devicetree

        # clear the disks
        self.destroy_all_devices()
        self.assertEqual([d for d in devicetree.devices if d.type == "lvmlv"], [])
        self.assertEqual(self.storage.vgs, [])
        self.assertEqual(self.storage.partitions, [])

        sda = devicetree.get_device_by_name("sda")
        self.assertNotEqual(sda, None, "failed to find disk 'sda'")

        sda1 = self.new_device(device_class=PartitionDevice,
                               name="sda1", size=Size("500 MiB"),
                               parents=[sda])
        self.schedule_create_device(sda1)

        sda2 = self.new_device(device_class=PartitionDevice,
                               name="sda2", size=Size("100 GiB"),
                               parents=[sda])
        self.schedule_create_device(sda2)
        fmt = self.new_format("lvmpv", device=sda2.path)
        self.schedule_create_format(device=sda2, fmt=fmt)

        vg = self.new_device(device_class=LVMVolumeGroupDevice,
                             name="vg", parents=[sda2])
        self.schedule_create_device(vg)

        lv_root = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_root", parents=[vg],
                                  size=Size("60 GiB"))
        self.schedule_create_device(lv_root)
        fmt = self.new_format("ext4", device=lv_root.path, mountpoint="/")
        self.schedule_create_format(device=lv_root, fmt=fmt)

        lv_swap = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_swap", parents=[vg],
                                  size=Size("4000 MiB"))
        self.schedule_create_device(lv_swap)
        fmt = self.new_format("swap", device=lv_swap.path)
        self.schedule_create_format(device=lv_swap, fmt=fmt)

        sda3 = self.new_device(device_class=PartitionDevice,
                               name="sda3", parents=[sda],
                               size=Size("40 GiB"))
        self.schedule_create_device(sda3)
        fmt = self.new_format("mdmember", device=sda3.path)
        self.schedule_create_format(device=sda3, fmt=fmt)

        sdb = devicetree.get_device_by_name("sdb")
        self.assertNotEqual(sdb, None, "failed to find disk 'sdb'")

        sdb1 = self.new_device(device_class=PartitionDevice,
                               name="sdb1", parents=[sdb],
                               size=Size("40 GiB"))
        self.schedule_create_device(sdb1)
        fmt = self.new_format("mdmember", device=sdb1.path,)
        self.schedule_create_format(device=sdb1, fmt=fmt)

        md0 = self.new_device(device_class=MDRaidArrayDevice,
                              name="md0", level="raid0", minor=0,
                              member_devices=2, total_devices=2,
                              parents=[sdb1, sda3])
        self.schedule_create_device(md0)

        fmt = self.new_format("ext4", device=md0.path, mountpoint="/home")
        self.schedule_create_format(device=md0, fmt=fmt)

        fmt = self.new_format("ext4", mountpoint="/boot", device=sda1.path)
        self.schedule_create_format(device=sda1, fmt=fmt)

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_action_creation(self):
        """ Verify correct operation of action class constructors. """
        # instantiation of device resize action for non-existent device should
        # fail
        # XXX resizable depends on existence, so this is covered implicitly
        sdd = self.storage.devicetree.get_device_by_name("sdd")
        p = self.new_device(device_class=PartitionDevice,
                            name="sdd1", size=Size("32 GiB"), parents=[sdd])
        with self.assertRaises(ValueError):
            ActionResizeDevice(p, p.size + Size("7232 MiB"))

        # instantiation of device resize action for non-resizable device
        # should fail
        vg = self.storage.devicetree.get_device_by_name("VolGroup")
        self.assertNotEqual(vg, None)
        with self.assertRaises(ValueError):
            ActionResizeDevice(vg, vg.size + Size("32 MiB"))

        # instantiation of format resize action for non-resizable format type
        # should fail
        lv_swap = self.storage.devicetree.get_device_by_name("VolGroup-lv_swap")
        self.assertNotEqual(lv_swap, None)
        with self.assertRaises(ValueError):
            ActionResizeFormat(lv_swap, lv_swap.size + Size("32 MiB"))

        # instantiation of format resize action for non-existent format
        # should fail
        lv_root = self.storage.devicetree.get_device_by_name("VolGroup-lv_root")
        self.assertNotEqual(lv_root, None)
        lv_root.format.exists = False

        # instantiation of device create action for existing device should
        # fail
        lv_swap = self.storage.devicetree.get_device_by_name("VolGroup-lv_swap")
        self.assertNotEqual(lv_swap, None)
        self.assertEqual(lv_swap.exists, True)
        with self.assertRaises(ValueError):
            ActionCreateDevice(lv_swap)

        # instantiation of format destroy action for device causes device's
        # format attribute to be a DeviceFormat instance
        lv_swap = self.storage.devicetree.get_device_by_name("VolGroup-lv_swap")
        self.assertNotEqual(lv_swap, None)
        orig_format = lv_swap.format
        self.assertEqual(lv_swap.format.type, "swap")
        destroy_swap = ActionDestroyFormat(lv_swap)
        self.assertEqual(lv_swap.format.type, "swap")
        destroy_swap.apply()
        self.assertEqual(lv_swap.format.type, None)

        # instantiation of format create action for device causes new format
        # to be accessible via device's format attribute
        new_format = get_format("vfat", device=lv_swap.path)
        create_swap = ActionCreateFormat(lv_swap, new_format)
        self.assertEqual(lv_swap.format.type, None)
        create_swap.apply()
        self.assertEqual(lv_swap.format, new_format)
        lv_swap.format = orig_format

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_action_registration(self):
        """ Verify correct operation of action registration and cancelling. """
        # self.setUp has just been run, so we should have something like
        # a preexisting autopart config in the devicetree.

        # registering a destroy action for a non-leaf device should fail
        vg = self.storage.devicetree.get_device_by_name("VolGroup")
        self.assertNotEqual(vg, None)
        self.assertEqual(vg.isleaf, False)
        a = ActionDestroyDevice(vg)
        with self.assertRaises(ValueError):
            self.storage.devicetree.actions.add(a)

        # registering any action other than create for a device that's not in
        # the devicetree should fail
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        self.assertNotEqual(sdc, None)
        sdc1 = self.new_device(device_class=PartitionDevice,
                               name="sdc1", size=Size("100 GiB"),
                               parents=[sdc], exists=True)

        sdc1_format = self.new_format("ext2", device=sdc1.path, mountpoint="/", size=Size("100 GiB"))
        create_sdc1_format = ActionCreateFormat(sdc1, sdc1_format)
        create_sdc1_format.apply()
        with self.assertRaises(blivet.errors.DeviceTreeError):
            self.storage.devicetree.actions.add(create_sdc1_format)

        sdc1_format.exists = True
        sdc1_format._resizable = True
        resize_sdc1_format = ActionResizeFormat(sdc1,
                                                sdc1.size - Size("10 GiB"))
        resize_sdc1_format.apply()
        with self.assertRaises(blivet.errors.DeviceTreeError):
            self.storage.devicetree.actions.add(resize_sdc1_format)

        resize_sdc1 = ActionResizeDevice(sdc1, sdc1.size - Size("10 GiB"))
        resize_sdc1.apply()
        with self.assertRaises(blivet.errors.DeviceTreeError):
            self.storage.devicetree.actions.add(resize_sdc1)

        resize_sdc1.cancel()
        resize_sdc1_format.cancel()

        destroy_sdc1_format = ActionDestroyFormat(sdc1)
        with self.assertRaises(blivet.errors.DeviceTreeError):
            self.storage.devicetree.actions.add(destroy_sdc1_format)

        destroy_sdc1 = ActionDestroyDevice(sdc1)
        with self.assertRaises(blivet.errors.DeviceTreeError):
            self.storage.devicetree.actions.add(destroy_sdc1)

        # registering a device destroy action should cause the device to be
        # removed from the devicetree
        lv_root = self.storage.devicetree.get_device_by_name("VolGroup-lv_root")
        self.assertNotEqual(lv_root, None)
        a = ActionDestroyDevice(lv_root)
        self.storage.devicetree.actions.add(a)
        lv_root = self.storage.devicetree.get_device_by_name("VolGroup-lv_root")
        self.assertEqual(lv_root, None)
        self.storage.devicetree.actions.remove(a)

        # registering a device create action should cause the device to be
        # added to the devicetree
        sdd = self.storage.devicetree.get_device_by_name("sdd")
        self.assertNotEqual(sdd, None)
        sdd1 = self.storage.devicetree.get_device_by_name("sdd1")
        self.assertEqual(sdd1, None)
        sdd1 = self.new_device(device_class=PartitionDevice,
                               name="sdd1", size=Size("100 GiB"),
                               parents=[sdd])
        a = ActionCreateDevice(sdd1)
        self.storage.devicetree.actions.add(a)
        sdd1 = self.storage.devicetree.get_device_by_name("sdd1")
        self.assertNotEqual(sdd1, None)

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_action_obsoletes(self):
        """ Verify correct operation of DeviceAction.obsoletes. """
        self.destroy_all_devices(disks=["sdc"])
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        self.assertNotEqual(sdc, None)

        sdc1 = self.new_device(device_class=PartitionDevice,
                               name="sdc1", parents=[sdc], size=Size("40 GiB"))

        # ActionCreateDevice
        #
        # - obsoletes other ActionCreateDevice instances w/ lower id and same
        #   device
        create_device_1 = ActionCreateDevice(sdc1)
        create_device_1.apply()
        create_device_2 = ActionCreateDevice(sdc1)
        create_device_2.apply()
        self.assertEqual(create_device_2.obsoletes(create_device_1), True)
        self.assertEqual(create_device_1.obsoletes(create_device_2), False)

        # ActionConfigureDevice
        #
        # - obsoletes all but ActionConfigureDevice actions w/ lower id on the
        #   same existing device with the same attribute being configured
        sdc1._rename = Mock()  # XXX partitions are actually not renamable
        configure_device_1 = ActionConfigureDevice(sdc1, "name", "new_name")
        configure_device_1.apply()
        configure_device_2 = ActionConfigureDevice(sdc1, "name", "new_name2")
        configure_device_2.apply()
        self.assertTrue(configure_device_2.obsoletes(configure_device_1))

        # ActionCreateFormat
        #
        # - obsoletes other ActionCreateFormat instances w/ lower id and same
        #   device
        format_1 = self.new_format("ext3", mountpoint="/home", device=sdc1.path)
        format_2 = self.new_format("ext3", mountpoint="/opt", device=sdc1.path)
        create_format_1 = ActionCreateFormat(sdc1, format_1)
        create_format_1.apply()
        create_format_2 = ActionCreateFormat(sdc1, format_2)
        create_format_2.apply()
        self.assertEqual(create_format_2.obsoletes(create_format_1), True)
        self.assertEqual(create_format_1.obsoletes(create_format_2), False)

        # ActionResizeFormat
        #
        # - obsoletes other ActionResizeFormat instances w/ lower id and same
        #   device
        sdc1.exists = True
        sdc1.format.exists = True
        sdc1.format._resizable = True
        resize_format_1 = ActionResizeFormat(sdc1, sdc1.size - Size("1000 MiB"))
        resize_format_1.apply()
        resize_format_2 = ActionResizeFormat(sdc1, sdc1.size - Size("5000 MiB"))
        resize_format_2.apply()
        self.assertEqual(resize_format_2.obsoletes(resize_format_1), True)
        self.assertEqual(resize_format_1.obsoletes(resize_format_2), False)
        sdc1.exists = False
        sdc1.format.exists = False

        # ActionCreateFormat
        #
        # - obsoletes resize format actions w/ lower id on same device
        new_format = self.new_format("ext4", mountpoint="/foo", device=sdc1.path)
        create_format_3 = ActionCreateFormat(sdc1, new_format)
        create_format_3.apply()
        self.assertEqual(create_format_3.obsoletes(resize_format_1), True)
        self.assertEqual(create_format_3.obsoletes(resize_format_2), True)

        # ActionConfigureFormat
        #
        # - obsoletes all but ActionConfigureFormat actions w/ lower id on the
        #   same existing device with the same attribute being configured
        sdc1.format._writelabel = Mock(available=True)
        configure_format_1 = ActionConfigureFormat(sdc1, "label", "new_label")
        configure_format_1.apply()
        configure_format_2 = ActionConfigureFormat(sdc1, "label", "new_label2")
        configure_format_2.apply()
        self.assertTrue(configure_format_2.obsoletes(configure_format_1))
        # XXX just pretend we can change uuid too
        sdc1.format.config_actions_map["uuid"] = "write_label"
        configure_format_3 = ActionConfigureFormat(sdc1, "uuid", "new_uuid")
        configure_format_3.apply()
        self.assertFalse(configure_format_3.obsoletes(configure_format_1))
        self.assertFalse(configure_format_3.obsoletes(configure_format_2))

        # ActionResizeDevice
        #
        # - obsoletes other ActionResizeDevice instances w/ lower id and same
        #   device
        sdc1.exists = True
        sdc1.format.exists = True
        sdc1.format._resizable = True
        resize_device_1 = ActionResizeDevice(sdc1,
                                             sdc1.size + Size("10 GiB"))
        resize_device_1.apply()
        resize_device_2 = ActionResizeDevice(sdc1,
                                             sdc1.size - Size("10 GiB"))
        resize_device_2.apply()
        self.assertEqual(resize_device_2.obsoletes(resize_device_1), True)
        self.assertEqual(resize_device_1.obsoletes(resize_device_2), False)
        sdc1.exists = False
        sdc1.format.exists = False

        # ActionDestroyFormat
        #
        # - obsoletes all format actions w/ higher id on same device (including
        #   self if format does not exist)
        destroy_format_1 = ActionDestroyFormat(sdc1)
        destroy_format_1.apply()
        destroy_format_2 = ActionDestroyFormat(sdc1)
        destroy_format_2.apply()
        self.assertEqual(destroy_format_1.obsoletes(create_format_1), True)
        self.assertEqual(destroy_format_1.obsoletes(resize_format_1), True)
        self.assertEqual(destroy_format_1.obsoletes(destroy_format_1), True)
        self.assertEqual(destroy_format_1.obsoletes(configure_format_1), True)
        self.assertEqual(destroy_format_1.obsoletes(configure_format_2), True)
        self.assertEqual(destroy_format_2.obsoletes(destroy_format_1), False)
        self.assertEqual(destroy_format_1.obsoletes(destroy_format_2), True)

        # ActionDestroyDevice
        #
        # - obsoletes all actions w/ lower id that act on the same non-existent
        #   device (including self)
        # sdc1 does not exist
        destroy_sdc1 = ActionDestroyDevice(sdc1)
        destroy_sdc1.apply()
        self.assertEqual(destroy_sdc1.obsoletes(create_format_2), True)
        self.assertEqual(destroy_sdc1.obsoletes(resize_format_2), True)
        self.assertEqual(destroy_sdc1.obsoletes(create_device_1), True)
        self.assertEqual(destroy_sdc1.obsoletes(resize_device_1), True)
        self.assertEqual(destroy_sdc1.obsoletes(configure_format_1), True)
        self.assertEqual(destroy_sdc1.obsoletes(configure_format_2), True)
        self.assertEqual(destroy_sdc1.obsoletes(configure_device_1), True)
        self.assertEqual(destroy_sdc1.obsoletes(configure_device_2), True)
        self.assertEqual(destroy_sdc1.obsoletes(destroy_sdc1), True)

        # ActionDestroyDevice
        #
        # - obsoletes all but ActionDestroyFormat actions w/ lower id on the
        #   same existing device
        # sda1 exists
        sda1 = self.storage.devicetree.get_device_by_name("sda1")
        self.assertNotEqual(sda1, None)
        # sda1.format._resizable = True
        resize_sda1_format = ActionResizeFormat(sda1,
                                                sda1.size - Size("50 MiB"))
        resize_sda1_format.apply()
        resize_sda1 = ActionResizeDevice(sda1, sda1.size - Size("50 MiB"))
        resize_sda1.apply()
        destroy_sda1_format = ActionDestroyFormat(sda1)
        destroy_sda1_format.apply()
        destroy_sda1 = ActionDestroyDevice(sda1)
        destroy_sda1.apply()
        self.assertEqual(destroy_sda1.obsoletes(resize_sda1_format), True)
        self.assertEqual(destroy_sda1.obsoletes(resize_sda1), True)
        self.assertEqual(destroy_sda1.obsoletes(destroy_sda1), False)
        self.assertEqual(destroy_sda1.obsoletes(destroy_sda1_format), False)

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_action_pruning(self):
        """ Verify correct functioning of action pruning. """
        self.destroy_all_devices()

        sda = self.storage.devicetree.get_device_by_name("sda")
        self.assertNotEqual(sda, None, "failed to find disk 'sda'")

        sda1 = self.new_device(device_class=PartitionDevice,
                               name="sda1", size=Size("500 MiB"),
                               parents=[sda])
        self.schedule_create_device(sda1)

        sda2 = self.new_device(device_class=PartitionDevice,
                               name="sda2", size=Size("100 GiB"),
                               parents=[sda])
        self.schedule_create_device(sda2)
        fmt = self.new_format("lvmpv", device=sda2.path)
        self.schedule_create_format(device=sda2, fmt=fmt)

        vg = self.new_device(device_class=LVMVolumeGroupDevice,
                             name="vg", parents=[sda2])
        self.schedule_create_device(vg)

        lv_root = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_root", parents=[vg],
                                  size=Size("60 GiB"))
        self.schedule_create_device(lv_root)
        fmt = self.new_format("ext4", device=lv_root.path, mountpoint="/")
        self.schedule_create_format(device=lv_root, fmt=fmt)

        lv_swap = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_swap", parents=[vg],
                                  size=Size("4 GiB"))
        self.schedule_create_device(lv_swap)
        fmt = self.new_format("swap", device=lv_swap.path)
        self.schedule_create_format(device=lv_swap, fmt=fmt)

        # we'll soon schedule destroy actions for these members and the array,
        # which will test pruning. the whole mess should reduce to nothing
        sda3 = self.new_device(device_class=PartitionDevice,
                               name="sda3", parents=[sda],
                               size=Size("40 GiB"))
        self.schedule_create_device(sda3)
        fmt = self.new_format("mdmember", device=sda3.path)
        self.schedule_create_format(device=sda3, fmt=fmt)

        sdb = self.storage.devicetree.get_device_by_name("sdb")
        self.assertNotEqual(sdb, None, "failed to find disk 'sdb'")

        sdb1 = self.new_device(device_class=PartitionDevice,
                               name="sdb1", parents=[sdb],
                               size=Size("40 GiB"))
        self.schedule_create_device(sdb1)
        fmt = self.new_format("mdmember", device=sdb1.path,)
        self.schedule_create_format(device=sdb1, fmt=fmt)

        md0 = self.new_device(device_class=MDRaidArrayDevice,
                              name="md0", level="raid0", minor=0,
                              member_devices=2, total_devices=2,
                              parents=[sdb1, sda3])
        self.schedule_create_device(md0)

        fmt = self.new_format("ext4", device=md0.path, mountpoint="/home")
        self.schedule_create_format(device=md0, fmt=fmt)

        # now destroy the md and its components
        self.schedule_destroy_format(md0)
        self.schedule_destroy_device(md0)
        self.schedule_destroy_device(sdb1)
        self.schedule_destroy_device(sda3)

        fmt = self.new_format("ext4", mountpoint="/boot", device=sda1.path)
        self.schedule_create_format(device=sda1, fmt=fmt)

        # verify the md actions are present prior to pruning
        md0_actions = self.storage.devicetree.actions.find(devid=md0.id)
        self.assertNotEqual(len(md0_actions), 0)

        sdb1_actions = self.storage.devicetree.actions.find(devid=sdb1.id)
        self.assertNotEqual(len(sdb1_actions), 0)

        sda3_actions = self.storage.devicetree.actions.find(devid=sda3.id)
        self.assertNotEqual(len(sda3_actions), 0)

        self.storage.devicetree.actions.prune()

        # verify the md actions are gone after pruning
        md0_actions = self.storage.devicetree.actions.find(devid=md0.id)
        self.assertEqual(len(md0_actions), 0)

        sdb1_actions = self.storage.devicetree.actions.find(devid=sdb1.id)
        self.assertEqual(len(sdb1_actions), 0)

        sda3_actions = self.storage.devicetree.actions.find(sda3.id)
        self.assertEqual(len(sda3_actions), 0)

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_action_dependencies(self):
        """ Verify correct functioning of action dependencies. """
        # ActionResizeDevice
        # an action that shrinks a device should require the action that
        # shrinks the device's format
        lv_root = self.storage.devicetree.get_device_by_name("VolGroup-lv_root")
        self.assertNotEqual(lv_root, None)
        lv_root.format._min_instance_size = Size("10 MiB")
        lv_root.format._target_size = lv_root.format._min_instance_size
        lv_root.format._size = lv_root.size
        # lv_root.format._resizable = True
        shrink_format = ActionResizeFormat(lv_root,
                                           lv_root.size - Size("5 GiB"))
        shrink_format.apply()
        shrink_device = ActionResizeDevice(lv_root,
                                           lv_root.size - Size("5 GiB"))
        shrink_device.apply()
        self.assertEqual(shrink_device.requires(shrink_format), True)
        self.assertEqual(shrink_format.requires(shrink_device), False)
        shrink_format.cancel()
        shrink_device.cancel()

        # ActionResizeDevice
        # an action that grows a format should require the action that
        # grows the device
        orig_size = lv_root.current_size
        grow_device = ActionResizeDevice(lv_root,
                                         orig_size + Size("100 MiB"))
        grow_device.apply()
        grow_format = ActionResizeFormat(lv_root,
                                         orig_size + Size("100 MiB"))
        grow_format.apply()
        self.assertEqual(grow_format.requires(grow_device), True)
        self.assertEqual(grow_device.requires(grow_format), False)

        # create something like uncommitted autopart
        self.destroy_all_devices()
        sda = self.storage.devicetree.get_device_by_name("sda")
        sdb = self.storage.devicetree.get_device_by_name("sdb")
        sda1 = self.new_device(device_class=PartitionDevice, name="sda1",
                               size=Size("500 MiB"), parents=[sda])
        sda1_format = self.new_format("ext4", mountpoint="/boot",
                                      device=sda1.path)
        self.schedule_create_device(sda1)
        self.schedule_create_format(device=sda1, fmt=sda1_format)

        sda2 = self.new_device(device_class=PartitionDevice, name="sda2",
                               size=Size("99.5 GiB"), parents=[sda])
        sda2_format = self.new_format("lvmpv", device=sda2.path)
        self.schedule_create_device(sda2)
        self.schedule_create_format(device=sda2, fmt=sda2_format)

        sdb1 = self.new_device(device_class=PartitionDevice, name="sdb1",
                               size=Size("100 GiB"), parents=[sdb])
        sdb1_format = self.new_format("lvmpv", device=sdb1.path)
        self.schedule_create_device(sdb1)
        self.schedule_create_format(device=sdb1, fmt=sdb1_format)

        vg = self.new_device(device_class=LVMVolumeGroupDevice,
                             name="VolGroup", parents=[sda2, sdb1])
        self.schedule_create_device(vg)

        lv_root = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_root", parents=[vg],
                                  size=Size("160 GiB"))
        self.schedule_create_device(lv_root)
        fmt = self.new_format("ext4", device=lv_root.path, mountpoint="/")
        self.schedule_create_format(device=lv_root, fmt=fmt)

        lv_swap = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_swap", parents=[vg],
                                  size=Size("4 GiB"))
        self.schedule_create_device(lv_swap)
        fmt = self.new_format("swap", device=lv_swap.path)
        self.schedule_create_format(device=lv_swap, fmt=fmt)

        # ActionCreateDevice
        # creation of an LV should require the actions that create the VG,
        # its PVs, and the devices that contain the PVs
        lv_root = self.storage.devicetree.get_device_by_name("VolGroup-lv_root")
        self.assertNotEqual(lv_root, None)
        actions = self.storage.devicetree.actions.find(action_type="create",
                                                       object_type="device",
                                                       device=lv_root)
        self.assertEqual(len(actions), 1,
                         "wrong number of device create actions for lv_root: "
                         "%d" % len(actions))
        create_lv_action = actions[0]

        vgs = [d for d in self.storage.vgs if d.name == "VolGroup"]
        self.assertNotEqual(vgs, [])
        vg = vgs[0]
        actions = self.storage.devicetree.actions.find(action_type="create",
                                                       object_type="device",
                                                       device=vg)
        self.assertEqual(len(actions), 1,
                         "wrong number of device create actions for VolGroup")
        create_vg_action = actions[0]

        self.assertEqual(create_lv_action.requires(create_vg_action), True)

        create_pv_actions = []
        pvs = [d for d in self.storage.pvs if d in vg.pvs]
        self.assertNotEqual(pvs, [])
        for pv in pvs:
            # include device and format create actions for each pv
            actions = self.storage.devicetree.actions.find(action_type="create",
                                                           device=pv)
            self.assertEqual(len(actions), 2,
                             "wrong number of device create actions for "
                             "pv %s" % pv.name)
            create_pv_actions.append(actions[0])

        for pv_action in create_pv_actions:
            self.assertEqual(create_lv_action.requires(pv_action), True)
            # also check that the vg create action requires the pv actions
            self.assertEqual(create_vg_action.requires(pv_action), True)

        # ActionCreateDevice
        # the higher numbered partition of two that are scheduled to be
        # created on a single disk should require the action that creates the
        # lower numbered of the two, eg: create sda2 before creating sda3
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        self.assertNotEqual(sdc, None)

        sdc1 = self.new_device(device_class=PartitionDevice, name="sdc1",
                               parents=[sdc], size=Size("50 GiB"))
        create_sdc1 = self.schedule_create_device(sdc1)
        self.assertEqual(isinstance(create_sdc1, ActionCreateDevice), True)

        sdc2 = self.new_device(device_class=PartitionDevice, name="sdc2",
                               parents=[sdc], size=Size("50 GiB"))
        create_sdc2 = self.schedule_create_device(sdc2)
        self.assertEqual(isinstance(create_sdc2, ActionCreateDevice), True)

        self.assertEqual(create_sdc2.requires(create_sdc1), True)
        self.assertEqual(create_sdc1.requires(create_sdc2), False)

        # ActionCreateDevice
        # actions that create partitions on two separate disks should not
        # require each other, regardless of the partitions' numbers
        sda1 = self.storage.devicetree.get_device_by_name("sda1")
        self.assertNotEqual(sda1, None)
        actions = self.storage.devicetree.actions.find(action_type="create",
                                                       object_type="device",
                                                       device=sda1)
        self.assertEqual(len(actions), 1,
                         "wrong number of create actions found for sda1")
        create_sda1 = actions[0]
        self.assertEqual(create_sdc2.requires(create_sda1), False)
        self.assertEqual(create_sda1.requires(create_sdc1), False)

        # ActionDestroyDevice
        # an action that destroys a device containing an mdmember format
        # should require the action that destroys the md array it is a
        # member of if an array is defined
        self.destroy_all_devices(disks=["sdc", "sdd"])
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        self.assertNotEqual(sdc, None)
        sdd = self.storage.devicetree.get_device_by_name("sdd")
        self.assertNotEqual(sdd, None)

        sdc1 = self.new_device(device_class=PartitionDevice, name="sdc1",
                               parents=[sdc], size=Size("40 GiB"))
        self.schedule_create_device(sdc1)
        fmt = self.new_format("mdmember", device=sdc1.path)
        self.schedule_create_format(device=sdc1, fmt=fmt)

        sdd1 = self.new_device(device_class=PartitionDevice, name="sdd1",
                               parents=[sdd], size=Size("40 GiB"))
        self.schedule_create_device(sdd1)
        fmt = self.new_format("mdmember", device=sdd1.path,)
        self.schedule_create_format(device=sdd1, fmt=fmt)

        md0 = self.new_device(device_class=MDRaidArrayDevice,
                              name="md0", level="raid0", minor=0,
                              member_devices=2, total_devices=2,
                              parents=[sdc1, sdd1])
        self.schedule_create_device(md0)
        fmt = self.new_format("ext4", device=md0.path, mountpoint="/home")
        self.schedule_create_format(device=md0, fmt=fmt)

        destroy_md0_format = self.schedule_destroy_format(md0)
        destroy_md0 = self.schedule_destroy_device(md0)
        destroy_members = [self.schedule_destroy_device(sdc1)]
        destroy_members.append(self.schedule_destroy_device(sdd1))

        for member in destroy_members:
            # device and format destroy actions for md members should require
            # both device and format destroy actions for the md array
            for array in [destroy_md0_format, destroy_md0]:
                self.assertEqual(member.requires(array), True)

        # ActionDestroyDevice
        # when there are two actions that will each destroy a partition on the
        # same disk, the action that will destroy the lower-numbered
        # partition should require the action that will destroy the higher-
        # numbered partition, eg: destroy sda2 before destroying sda1
        self.destroy_all_devices(disks=["sdc", "sdd"])
        sdc1 = self.new_device(device_class=PartitionDevice, name="sdc1",
                               parents=[sdc], size=Size("50 GiB"))
        self.schedule_create_device(sdc1)

        sdc2 = self.new_device(device_class=PartitionDevice, name="sdc2",
                               parents=[sdc], size=Size("40 GiB"))
        self.schedule_create_device(sdc2)

        destroy_sdc1 = self.schedule_destroy_device(sdc1)
        destroy_sdc2 = self.schedule_destroy_device(sdc2)
        self.assertEqual(destroy_sdc1.requires(destroy_sdc2), True)
        self.assertEqual(destroy_sdc2.requires(destroy_sdc1), False)

        self.destroy_all_devices(disks=["sdc", "sdd"])
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        self.assertNotEqual(sdc, None)
        sdd = self.storage.devicetree.get_device_by_name("sdd")
        self.assertNotEqual(sdd, None)

        sdc1 = self.new_device(device_class=PartitionDevice, name="sdc1",
                               parents=[sdc], size=Size("50 GiB"))
        create_pv = self.schedule_create_device(sdc1)
        fmt = self.new_format("lvmpv", device=sdc1.path)
        create_pv_format = self.schedule_create_format(device=sdc1, fmt=fmt)

        testvg = self.new_device(device_class=LVMVolumeGroupDevice,
                                 name="testvg", parents=[sdc1])
        create_vg = self.schedule_create_device(testvg)
        testlv = self.new_device(device_class=LVMLogicalVolumeDevice,
                                 name="testlv", parents=[testvg],
                                 size=Size("30 GiB"))
        create_lv = self.schedule_create_device(testlv)
        fmt = self.new_format("ext4", device=testlv.path)
        create_lv_format = self.schedule_create_format(device=testlv, fmt=fmt)

        # ActionCreateFormat
        # creation of a format on a non-existent device should require the
        # action that creates the device
        self.assertEqual(create_lv_format.requires(create_lv), True)

        # ActionCreateFormat
        # an action that creates a format on a device should require an action
        # that creates a device that the format's device depends on
        self.assertEqual(create_lv_format.requires(create_pv), True)
        self.assertEqual(create_lv_format.requires(create_vg), True)

        # ActionCreateFormat
        # an action that creates a format on a device should require an action
        # that creates a format on a device that the format's device depends on
        self.assertEqual(create_lv_format.requires(create_pv_format), True)

        # XXX from here on, the devices are existing but not in the tree, so
        #     we instantiate and use actions directly
        self.destroy_all_devices(disks=["sdc", "sdd"])
        sdc1 = self.new_device(device_class=PartitionDevice, exists=True,
                               name="sdc1", parents=[sdc],
                               size=Size("50 GiB"))
        sdc1.format = self.new_format("lvmpv", device=sdc1.path, exists=True,
                                      device_instance=sdc1)
        testvg = self.new_device(device_class=LVMVolumeGroupDevice, exists=True,
                                 name="testvg", parents=[sdc1],
                                 size=Size("50 GiB"))
        testlv = self.new_device(device_class=LVMLogicalVolumeDevice,
                                 exists=True, size=Size("30 GiB"),
                                 name="testlv", parents=[testvg])
        testlv.format = self.new_format("ext4", device=testlv.path,
                                        exists=True, device_instance=testlv)

        # ActionResizeDevice
        # an action that resizes a device should require an action that grows
        # a device that the first action's device depends on, eg: grow
        # device containing PV before resize of VG or LVs
        sdc1.format._resizable = True   # override lvmpv.resizable
        sdc1.exists = True
        sdc1.format.exists = True
        grow_pv = ActionResizeDevice(sdc1, sdc1.size + Size("10 GiB"))
        grow_pv.apply()
        grow_lv = ActionResizeDevice(testlv, testlv.size + Size("5 GiB"))
        grow_lv.apply()
        grow_lv_format = ActionResizeFormat(testlv,
                                            testlv.size + Size("5 GiB"))
        grow_lv_format.apply()
        sdc1.exists = False
        sdc1.format.exists = False

        self.assertEqual(grow_lv.requires(grow_pv), True)
        self.assertEqual(grow_pv.requires(grow_lv), False)

        # ActionResizeDevice
        # an action that grows a device should require an action that shrinks
        # a device with ancestors in common
        testlv2 = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  exists=True, size=Size("10 GiB"),
                                  name="testlv2", parents=[testvg])
        testlv2.format = self.new_format("ext4", device=testlv2.path,
                                         exists=True, device_instance=testlv2)
        shrink_lv2 = ActionResizeDevice(testlv2, testlv2.size - Size("10 GiB") + Ext4FS._min_size)
        shrink_lv2.apply()

        self.assertTrue(grow_lv.requires(shrink_lv2))

        # ActionResizeFormat
        # an action that grows a format should require the action that grows
        # the format's device
        self.assertEqual(grow_lv_format.requires(grow_lv), True)
        self.assertEqual(grow_lv.requires(grow_lv_format), False)

        # ActionResizeFormat
        # an action that resizes a device's format should depend on an action
        # that grows a device the first device depends on
        self.assertEqual(grow_lv_format.requires(grow_pv), True)
        self.assertEqual(grow_pv.requires(grow_lv_format), False)

        # ActionResizeFormat
        # an action that resizes a device's format should depend on an action
        # that grows a format on a device the first device depends on
        # XXX resize of PV format is not allowed, so there's no real-life
        #     example of this to test

        grow_lv_format.cancel()
        grow_lv.cancel()
        grow_pv.cancel()

        # ActionResizeDevice
        # an action that resizes a device should require an action that grows
        # a format on a device that the first action's device depends on, eg:
        # grow PV format before resize of VG or LVs
        # XXX resize of PV format is not allowed, so there's no real-life
        #     example of this to test

        # ActionResizeDevice
        # an action that resizes a device should require an action that
        # shrinks a device that depends on the first action's device, eg:
        # shrink LV before resizing VG or PV devices
        testlv.format._min_instance_size = Size("10 MiB")
        testlv.format._target_size = testlv.format._min_instance_size
        shrink_lv = ActionResizeDevice(testlv,
                                       testlv.size - Size("10 GiB"))
        shrink_lv.apply()
        sdc1.exists = True
        sdc1.format.exists = True
        shrink_pv = ActionResizeDevice(sdc1, sdc1.size - Size("5 GiB"))
        shrink_pv.apply()
        sdc1.exists = False
        sdc1.format.exists = False

        self.assertEqual(shrink_pv.requires(shrink_lv), True)
        self.assertEqual(shrink_lv.requires(shrink_pv), False)

        # ActionResizeDevice
        # an action that resizes a device should require an action that
        # shrinks a format on a device that depends on the first action's
        # device, eg: shrink LV format before resizing VG or PV devices
        shrink_lv_format = ActionResizeFormat(testlv, testlv.size)
        shrink_lv_format.apply()
        self.assertEqual(shrink_pv.requires(shrink_lv_format), True)
        self.assertEqual(shrink_lv_format.requires(shrink_pv), False)

        # ActionResizeFormat
        # an action that resizes a device's format should depend on an action
        # that shrinks a device that depends on the first device
        # XXX can't think of a real-world example of this since PVs and MD
        #     member devices are not resizable in anaconda

        # ActionResizeFormat
        # an action that resizes a device's format should depend on an action
        # that shrinks a format on a device that depends on the first device
        # XXX can't think of a real-world example of this since PVs and MD
        #     member devices are not resizable in anaconda

        shrink_lv_format.cancel()
        shrink_lv.cancel()
        shrink_pv.cancel()

        # ActionCreateFormat
        # an action that creates a format on a device should require an action
        # that resizes a device that the format's device depends on
        # XXX Really? Is this always so?

        # ActionCreateFormat
        # an action that creates a format on a device should require an action
        # that resizes a format on a device that the format's device depends on
        # XXX Same as above.

        # ActionCreateFormat
        # an action that creates a format on a device should require an action
        # that resizes the device that will contain the format
        grow_lv = ActionResizeDevice(testlv, testlv.size + Size("1 GiB"))
        fmt = self.new_format("disklabel", device=testlv.path)
        format_lv = ActionCreateFormat(testlv, fmt)
        self.assertEqual(format_lv.requires(grow_lv), True)
        self.assertEqual(grow_lv.requires(format_lv), False)

        # ActionDestroyFormat
        # an action that destroys a format should require an action that
        # destroys a device that depends on the format's device
        destroy_pv_format = ActionDestroyFormat(sdc1)
        destroy_lv_format = ActionDestroyFormat(testlv)
        destroy_lv = ActionDestroyDevice(testlv)
        self.assertEqual(destroy_pv_format.requires(destroy_lv), True)
        self.assertEqual(destroy_lv.requires(destroy_pv_format), False)

        # ActionDestroyFormat
        # an action that destroys a format should require an action that
        # destroys a format on a device that depends on the first format's
        # device
        self.assertEqual(destroy_pv_format.requires(destroy_lv_format), True)
        self.assertEqual(destroy_lv_format.requires(destroy_pv_format), False)

        sdc2 = self.new_device(device_class=PartitionDevice, name="sdc2",
                               size=Size("5 GiB"), parents=[sdc])
        create_sdc2 = self.schedule_create_device(sdc2)

        # create actions should always require destroy actions -- even for
        # unrelated devices -- since, after pruning, it should always be the
        # case that destroy actions are processed before create actions (no
        # create/destroy loops are allowed)
        self.assertEqual(create_sdc2.requires(destroy_lv), True)

        # similarly, create actions should also require resize actions
        self.assertEqual(create_sdc2.requires(grow_lv), True)

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_action_apply_cancel(self):
        lv_root = self.storage.devicetree.get_device_by_name("VolGroup-lv_root")

        # ActionResizeFormat
        lv_root.format._min_instance_size = Size("10 MiB")
        lv_root.format._size = lv_root.size
        lv_root.format._target_size = lv_root.size
        original_format_size = lv_root.format.current_size
        target_size = lv_root.size - Size("1 GiB")
        # lv_root.format._resizable = True
        action = ActionResizeFormat(lv_root, target_size)
        self.assertEqual(lv_root.format.size, original_format_size)
        action.apply()
        self.assertEqual(lv_root.format.size, target_size)
        action.cancel()
        self.assertEqual(lv_root.format.size, original_format_size)

        # ActionResizeDevice
        original_device_size = lv_root.current_size
        action = ActionResizeDevice(lv_root, target_size)
        self.assertEqual(lv_root.size, original_device_size)
        action.apply()
        self.assertEqual(lv_root.size, target_size)
        action.cancel()
        self.assertEqual(lv_root.size, original_device_size)

        # ActionDestroyFormat
        original_format = lv_root.format
        action = ActionDestroyFormat(lv_root)
        orig_ignore_skip = lv_root.ignore_skip_activation
        self.assertEqual(lv_root.format, original_format)
        self.assertNotEqual(lv_root.format.type, None)
        action.apply()
        self.assertEqual(lv_root.format.type, None)
        self.assertEqual(lv_root.ignore_skip_activation, orig_ignore_skip + 1)
        action.cancel()
        self.assertEqual(lv_root.format, original_format)
        self.assertEqual(lv_root.ignore_skip_activation, orig_ignore_skip)

        # ActionDestroyDevice
        action1 = ActionDestroyFormat(lv_root)
        orig_ignore_skip = lv_root.ignore_skip_activation
        action1.apply()
        self.assertEqual(lv_root.ignore_skip_activation, orig_ignore_skip + 1)
        action2 = ActionDestroyDevice(lv_root)
        action2.apply()
        self.assertEqual(lv_root.ignore_skip_activation, orig_ignore_skip + 2)
        action2.cancel()
        self.assertEqual(lv_root.ignore_skip_activation, orig_ignore_skip + 1)
        action1.cancel()
        self.assertEqual(lv_root.ignore_skip_activation, orig_ignore_skip)

        sdc = self.storage.devicetree.get_device_by_name("sdc")
        sdc.format = None
        pv_fmt = self.new_format("lvmpv", device_instance=sdc, device=sdc.path)
        self.schedule_create_format(device=sdc, fmt=pv_fmt)
        vg = self.storage.devicetree.get_device_by_name("VolGroup")
        original_pvs = vg.parents[:]

        # ActionAddMember
        # XXX ActionAddMember and ActionRemoveMember make no effort to restore
        #     the original ordering of the container's parents list when
        #     canceled.
        pvs = original_pvs[:]
        action = ActionAddMember(vg, sdc)
        self.assertEqual(list(vg.parents), original_pvs)
        action.apply()
        pvs.append(sdc)
        self.assertEqual(list(vg.parents), pvs)
        action.cancel()
        pvs.remove(sdc)
        self.assertEqual(list(vg.parents), original_pvs)

        # ActionRemoveMember
        pvs = original_pvs[:]
        sdb1 = self.storage.devicetree.get_device_by_name("sdb1")
        action = ActionRemoveMember(vg, sdb1)
        self.assertEqual(list(vg.parents), original_pvs)
        action.apply()
        pvs.remove(sdb1)
        self.assertEqual(list(vg.parents), pvs)
        action.cancel()
        self.assertEqual(list(vg.parents), original_pvs)

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_container_actions(self):
        self.destroy_all_devices()
        sda = self.storage.devicetree.get_device_by_name("sda")
        sdb = self.storage.devicetree.get_device_by_name("sdb")

        #
        # create something like an existing lvm autopart layout across two disks
        #
        sda1 = self.new_device(device_class=PartitionDevice,
                               exists=True, name="sda1", parents=[sda],
                               size=Size("500 MiB"))
        sda1.format = self.new_format("ext4", mountpoint="/boot",
                                      device_instance=sda1,
                                      device=sda1.path, exists=True)
        self.storage.devicetree._add_device(sda1)

        sda2 = self.new_device(device_class=PartitionDevice,
                               size=Size("99.5 GiB"), name="sda2",
                               parents=[sda], exists=True)
        sda2.format = self.new_format("lvmpv", device=sda2.path, exists=True)
        self.storage.devicetree._add_device(sda2)

        sdb1 = self.new_device(device_class=PartitionDevice,
                               size=Size("99.999 GiB"), name="sdb1",
                               parents=[sdb], exists=True)
        sdb1.format = self.new_format("lvmpv", device=sdb1.path, exists=True)
        self.storage.devicetree._add_device(sdb1)

        vg = self.new_device(device_class=LVMVolumeGroupDevice,
                             name="VolGroup", parents=[sda2, sdb1],
                             exists=True)
        self.storage.devicetree._add_device(vg)

        lv_root = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_root", parents=[vg],
                                  size=Size("160 GiB"), exists=True)
        lv_root.format = self.new_format("ext4", mountpoint="/",
                                         device_instance=lv_root,
                                         device=lv_root.path, exists=True)
        self.storage.devicetree._add_device(lv_root)

        lv_swap = self.new_device(device_class=LVMLogicalVolumeDevice,
                                  name="lv_swap", parents=[vg],
                                  size=Size("4000 MiB"), exists=True)
        lv_swap.format = self.new_format("swap", device=lv_swap.path,
                                         device_instance=lv_swap,
                                         exists=True)
        self.storage.devicetree._add_device(lv_swap)

        #
        # test some modifications to the VG
        #
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        sdc1 = self.new_device(device_class=PartitionDevice, name="sdc1",
                               size=Size("50 GiB"), parents=[sdc])
        sdc1_format = self.new_format("lvmpv", device=sdc1.path)
        create_sdc1 = self.schedule_create_device(sdc1)
        create_sdc1_format = self.schedule_create_format(device=sdc1,
                                                         fmt=sdc1_format)

        self.assertEqual(len(vg.parents), 2)

        add_sdc1 = ActionAddMember(vg, sdc1)
        self.assertEqual(len(vg.parents), 2)
        add_sdc1.apply()
        self.assertEqual(len(vg.parents), 3)

        self.assertEqual(add_sdc1.requires(create_sdc1), True)
        self.assertEqual(add_sdc1.requires(create_sdc1_format), True)

        new_lv = self.new_device(device_class=LVMLogicalVolumeDevice,
                                 name="newlv", parents=[vg],
                                 size=Size("20 GiB"))
        create_new_lv = self.schedule_create_device(new_lv)
        new_lv_format = self.new_format("xfs", device=new_lv.path)
        create_new_lv_format = self.schedule_create_format(device=new_lv,
                                                           fmt=new_lv_format)

        self.assertEqual(create_new_lv.requires(add_sdc1), True)
        self.assertEqual(create_new_lv_format.requires(add_sdc1), False)

        self.storage.devicetree.actions.remove(create_new_lv_format)
        self.storage.devicetree.actions.remove(create_new_lv)

        remove_sdb1 = ActionRemoveMember(vg, sdb1)
        self.assertEqual(len(vg.parents), 3)
        remove_sdb1.apply()
        self.assertEqual(len(vg.parents), 2)

        self.assertEqual(remove_sdb1.requires(add_sdc1), True)

        vg.parents.append(sdb1)
        remove_sdb1_2 = ActionRemoveMember(vg, sdb1)
        remove_sdb1_2.apply()
        self.assertEqual(remove_sdb1_2.obsoletes(remove_sdb1), False)
        self.assertEqual(remove_sdb1.obsoletes(remove_sdb1_2), True)

        remove_sdc1 = ActionRemoveMember(vg, sdc1)
        remove_sdc1.apply()
        self.assertEqual(remove_sdc1.obsoletes(add_sdc1), True)
        self.assertEqual(add_sdc1.obsoletes(remove_sdc1), True)

        # add/remove loops (same member&container) should obsolete both actions
        add_sdb1 = ActionAddMember(vg, sdb1)
        add_sdb1.apply()
        self.assertEqual(add_sdb1.obsoletes(remove_sdb1), True)
        self.assertEqual(remove_sdb1.obsoletes(add_sdb1), True)

        sdc2 = self.new_device(device_class=PartitionDevice, name="sdc2",
                               size=Size("5 GiB"), parents=[sdc])
        create_sdc2 = self.schedule_create_device(sdc2)

        # destroy/resize/create sequencing does not apply to container actions
        self.assertEqual(create_sdc2.requires(remove_sdc1), False)
        self.assertEqual(remove_sdc1.requires(create_sdc2), False)

        # destroy sdc1, the ActionRemoveMember should not be obsoleted
        sdc1.exists = True
        destroy_sdc1 = ActionDestroyDevice(sdc1)
        destroy_sdc1.apply()
        self.assertFalse(destroy_sdc1.obsoletes(remove_sdc1))
        self.assertTrue(destroy_sdc1.requires(remove_sdc1))

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_action_sorting(self, *args, **kwargs):
        """ Verify correct functioning of action sorting. """

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_lv_from_lvs_actions(self):
        self.destroy_all_devices()
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        sdc1 = self.new_device(device_class=PartitionDevice, name="sdc1",
                               size=Size("50 GiB"), parents=[sdc], fmt=blivet.formats.get_format("lvmpv"))
        self.schedule_create_device(sdc1)

        vg = self.new_device(device_class=LVMVolumeGroupDevice,
                             name="vg", parents=[sdc1])
        self.schedule_create_device(vg)

        lv1 = self.new_device(device_class=LVMLogicalVolumeDevice,
                              name="data", parents=[vg],
                              size=Size("10 GiB"))
        create_lv1 = self.schedule_create_device(lv1)
        lv2 = self.new_device(device_class=LVMLogicalVolumeDevice,
                              name="meta", parents=[vg],
                              size=Size("1 GiB"))
        create_lv2 = self.schedule_create_device(lv2)

        self.assertEqual(set(self.storage.lvs), {lv1, lv2})

        pool = self.storage.new_lv_from_lvs(vg, name="pool", seg_type="thin-pool", from_lvs=(lv1, lv2))
        create_pool = self.schedule_create_device(pool)

        self.assertTrue(create_pool.requires(create_lv1))
        self.assertTrue(create_pool.requires(create_lv2))

        self.assertEqual(set(self.storage.lvs), {pool})

        # removing the action should put the LVs back into the DT
        self.storage.devicetree.actions.remove(create_pool)
        self.assertEqual(set(self.storage.lvs), {lv1, lv2})
        self.assertEqual(set(self.storage.vgs[0].lvs), {lv1, lv2})

        # doing everything again should just do the same changes as above
        pool = self.storage.new_lv_from_lvs(vg, name="pool", seg_type="thin-pool", from_lvs=(lv1, lv2))
        create_pool = self.schedule_create_device(pool)
        self.assertTrue(create_pool.requires(create_lv1))
        self.assertTrue(create_pool.requires(create_lv2))
        self.assertEqual(set(self.storage.lvs), {pool})

        # destroying the device should put the LVs back into the DT
        remove_pool = self.schedule_destroy_device(pool)
        self.assertEqual(set(self.storage.lvs), {lv1, lv2})
        self.assertEqual(set(self.storage.vgs[0].lvs), {lv1, lv2})

        # cancelling the destroy action should put the pool and its internal LVs
        # back
        self.storage.devicetree.actions.remove(remove_pool)
        self.assertEqual(set(self.storage.lvs), {pool})
        self.assertEqual(set(pool._internal_lvs), {lv1, lv2})


class DeviceActionLVMVDOTestCase(DeviceActionTestCase):

    @_patch_device_dependencies
    @_patch_format_dependencies
    def test_lvm_vdo_destroy(self):
        self.destroy_all_devices()
        sdc = self.storage.devicetree.get_device_by_name("sdc")
        sdc1 = self.new_device(device_class=PartitionDevice, name="sdc1",
                               size=Size("50 GiB"), parents=[sdc],
                               fmt=blivet.formats.get_format("lvmpv"))
        self.schedule_create_device(sdc1)

        vg = self.new_device(device_class=LVMVolumeGroupDevice,
                             name="vg", parents=[sdc1])
        self.schedule_create_device(vg)

        pool = self.new_device(device_class=LVMLogicalVolumeDevice,
                               name="data", parents=[vg],
                               size=Size("10 GiB"),
                               seg_type="vdo-pool", exists=True)
        self.storage.devicetree._add_device(pool)
        lv = self.new_device(device_class=LVMLogicalVolumeDevice,
                             name="meta", parents=[pool],
                             size=Size("50 GiB"),
                             seg_type="vdo", exists=True)
        self.storage.devicetree._add_device(lv)

        remove_lv = self.schedule_destroy_device(lv)
        self.assertListEqual(pool.lvs, [])
        self.assertNotIn(lv, vg.lvs)

        # cancelling the action should put lv back to both vg and pool lvs
        self.storage.devicetree.actions.remove(remove_lv)
        self.assertListEqual(pool.lvs, [lv])
        self.assertIn(lv, vg.lvs)

        # can't remove non-leaf pool
        with self.assertRaises(ValueError):
            self.schedule_destroy_device(pool)

        self.schedule_destroy_device(lv)
        self.schedule_destroy_device(pool)


class ConfigurationActionsTest(unittest.TestCase):

    def test_device_configuration(self):

        mock_device = Mock(spec=StorageDevice)
        mock_device.configure_mock(unavailable_direct_dependencies=[])
        mock_device.configure_mock(config_actions_map={"conf1": "do_conf1", "conf2": "do_conf2", "conf3": None})
        attrs = {"conf1": "old_value", "do_conf1": Mock(return_value=None), "conf2": "old_value", "do_conf2": None, "conf3": "old_value"}
        mock_device.configure_mock(**attrs)

        # attribute 'conf0' not in 'config_actions_map'
        with self.assertRaises(ValueError):
            ActionConfigureDevice(mock_device, "conf0", "new_value")

        # wrong method for 'conf2' attribute in config_actions_map -- not callable
        with self.assertRaises(RuntimeError):
            ActionConfigureDevice(mock_device, "conf2", "new_value")

        # set 'conf1' attribute to 'new_value'
        # action is created and right configuration function was called with 'dry_run=True'
        ac = ActionConfigureDevice(mock_device, "conf1", "new_value")
        mock_device.do_conf1.assert_called_once_with(old_conf1="old_value", new_conf1="new_value",
                                                     dry_run=True)
        mock_device.reset_mock()

        # try to apply, cancel and execute the action
        ac.apply()
        self.assertEqual(mock_device.conf1, "new_value")

        ac.cancel()
        self.assertEqual(mock_device.conf1, "old_value")

        ac.apply()
        ac.execute()
        mock_device.do_conf1.assert_called_once_with(old_conf1="old_value", new_conf1="new_value",
                                                     dry_run=False)

    def test_format_configuration(self):

        mock_format = Mock()
        mock_device = Mock(spec=StorageDevice, format=mock_format)
        mock_device.configure_mock(unavailable_dependencies=[])
        mock_format.configure_mock(config_actions_map={"conf1": "do_conf1", "conf2": "do_conf2", "conf3": None})
        attrs = {"conf1": "old_value", "do_conf1.return_value": None, "conf2": "old_value", "do_conf2": None, "conf3": "old_value"}
        mock_format.configure_mock(**attrs)

        # attribute 'conf0' not in 'config_actions_map'
        with self.assertRaises(ValueError):
            ActionConfigureFormat(mock_device, "conf0", "new_value")

        # wrong method for 'conf2' attribute in config_actions_map -- not callable
        with self.assertRaises(RuntimeError):
            ActionConfigureFormat(mock_device, "conf2", "new_value")

        # set 'conf1' attribute to 'new_value'
        # action is created and right configuration function was called with 'dry_run=True'
        ac = ActionConfigureFormat(mock_device, "conf1", "new_value")
        mock_format.do_conf1.assert_called_once_with(dry_run=True)
        mock_format.reset_mock()

        # try to apply, cancel and execute the action
        ac.apply()
        self.assertEqual(mock_format.conf1, "new_value")

        ac.cancel()
        self.assertEqual(mock_format.conf1, "old_value")

        ac.apply()
        ac.execute()
        mock_format.do_conf1.assert_called_once_with(dry_run=False)
