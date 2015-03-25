#!/usr/bin/python

import unittest

from tests.storagetestcase import StorageTestCase
import blivet
from blivet.formats import getFormat
from blivet.size import Size

# device classes for brevity's sake -- later on, that is
from blivet.devices import DiskDevice
from blivet.devices import PartitionDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import LVMVolumeGroupDevice
from blivet.devices import LVMLogicalVolumeDevice

# action classes
from blivet.deviceaction import ActionCreateDevice
from blivet.deviceaction import ActionResizeDevice
from blivet.deviceaction import ActionDestroyDevice
from blivet.deviceaction import ActionCreateFormat
from blivet.deviceaction import ActionResizeFormat
from blivet.deviceaction import ActionDestroyFormat
from blivet.deviceaction import ActionAddMember
from blivet.deviceaction import ActionRemoveMember

class DeviceActionTestCase(StorageTestCase):
    """ DeviceActionTestSuite """

    def setUp(self):
        """ Create something like a preexisting autopart on two disks (mocksda,mocksdb).

            The other two disks (mocksdc,mocksdd) are left for individual tests to use.
        """
        super(DeviceActionTestCase, self).setUp()

        for name in ["mocksda", "mocksdb", "mocksdc", "mocksdd"]:
            disk = self.newDevice(device_class=DiskDevice,
                                  name=name, size=Size("100 GiB"))
            disk.format = self.newFormat("disklabel", path=disk.path,
                                         exists=True)
            self.storage.devicetree._addDevice(disk)

        # create a layout similar to autopart as a starting point
        mocksda = self.storage.devicetree.getDeviceByName("mocksda")
        mocksdb = self.storage.devicetree.getDeviceByName("mocksdb")

        mocksda1 = self.newDevice(device_class=PartitionDevice,
                              exists=True, name="mocksda1", parents=[mocksda],
                              size=Size("500 MiB"))
        mocksda1.format = self.newFormat("ext4", mountpoint="/boot",
                                     device_instance=mocksda1,
                                     device=mocksda1.path, exists=True)
        self.storage.devicetree._addDevice(mocksda1)

        mocksda2 = self.newDevice(device_class=PartitionDevice,
                              size=Size("99.5 GiB"), name="mocksda2",
                              parents=[mocksda], exists=True)
        mocksda2.format = self.newFormat("lvmpv", device=mocksda2.path, exists=True)
        self.storage.devicetree._addDevice(mocksda2)

        mocksdb1 = self.newDevice(device_class=PartitionDevice,
                              size=Size("99.999 GiB"), name="mocksdb1",
                              parents=[mocksdb], exists=True)
        mocksdb1.format = self.newFormat("lvmpv", device=mocksdb1.path, exists=True)
        self.storage.devicetree._addDevice(mocksdb1)

        vg = self.newDevice(device_class=LVMVolumeGroupDevice,
                            name="VolGroup", parents=[mocksda2, mocksdb1],
                            exists=True)
        self.storage.devicetree._addDevice(vg)

        lv_root = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_root", parents=[vg],
                                 size=Size("160 GiB"), exists=True)
        lv_root.format = self.newFormat("ext4", mountpoint="/",
                                        device_instance=lv_root,
                                        device=lv_root.path, exists=True)
        self.storage.devicetree._addDevice(lv_root)

        lv_swap = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_swap", parents=[vg],
                                 size=Size("4000 MiB"), exists=True)
        lv_swap.format = self.newFormat("swap", device=lv_swap.path,
                                        device_instance=lv_swap,
                                        exists=True)
        self.storage.devicetree._addDevice(lv_swap)

    def testActions(self):
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
        self.destroyAllDevices()
        self.assertEqual(devicetree.getDevicesByType("lvmlv"), [])
        self.assertEqual(devicetree.getDevicesByType("lvmvg"), [])
        self.assertEqual(devicetree.getDevicesByType("partition"), [])

        mocksda = devicetree.getDeviceByName("mocksda")
        self.assertNotEqual(mocksda, None, "failed to find disk 'mocksda'")

        mocksda1 = self.newDevice(device_class=PartitionDevice,
                              name="mocksda1", size=Size("500 MiB"),
                              parents=[mocksda])
        self.scheduleCreateDevice(mocksda1)

        mocksda2 = self.newDevice(device_class=PartitionDevice,
                              name="mocksda2", size=Size("100 GiB"),
                              parents=[mocksda])
        self.scheduleCreateDevice(mocksda2)
        fmt = self.newFormat("lvmpv", device=mocksda2.path)
        self.scheduleCreateFormat(device=mocksda2, fmt=fmt)

        vg = self.newDevice(device_class=LVMVolumeGroupDevice,
                            name="vg", parents=[mocksda2])
        self.scheduleCreateDevice(vg)

        lv_root = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_root", parents=[vg],
                                 size=Size("60 GiB"))
        self.scheduleCreateDevice(lv_root)
        fmt = self.newFormat("ext4", device=lv_root.path, mountpoint="/")
        self.scheduleCreateFormat(device=lv_root, fmt=fmt)

        lv_swap = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_swap", parents=[vg],
                                 size=Size("4000 MiB"))
        self.scheduleCreateDevice(lv_swap)
        fmt = self.newFormat("swap", device=lv_swap.path)
        self.scheduleCreateFormat(device=lv_swap, fmt=fmt)

        mocksda3 = self.newDevice(device_class=PartitionDevice,
                              name="mocksda3", parents=[mocksda],
                              size=Size("40 GiB"))
        self.scheduleCreateDevice(mocksda3)
        fmt = self.newFormat("mdmember", device=mocksda3.path)
        self.scheduleCreateFormat(device=mocksda3, fmt=fmt)

        mocksdb = devicetree.getDeviceByName("mocksdb")
        self.assertNotEqual(mocksdb, None, "failed to find disk 'mocksdb'")

        mocksdb1 = self.newDevice(device_class=PartitionDevice,
                              name="mocksdb1", parents=[mocksdb],
                              size=Size("40 GiB"))
        self.scheduleCreateDevice(mocksdb1)
        fmt = self.newFormat("mdmember", device=mocksdb1.path,)
        self.scheduleCreateFormat(device=mocksdb1, fmt=fmt)

        md0 = self.newDevice(device_class=MDRaidArrayDevice,
                             name="md0", level="raid0", minor=0,
                             memberDevices=2, totalDevices=2,
                             parents=[mocksdb1, mocksda3])
        self.scheduleCreateDevice(md0)

        fmt = self.newFormat("ext4", device=md0.path, mountpoint="/home")
        self.scheduleCreateFormat(device=md0, fmt=fmt)

        fmt = self.newFormat("ext4", mountpoint="/boot", device=mocksda1.path)
        self.scheduleCreateFormat(device=mocksda1, fmt=fmt)

    def testActionCreation(self):
        """ Verify correct operation of action class constructors. """
        # instantiation of device resize action for non-existent device should
        # fail
        # XXX resizable depends on existence, so this is covered implicitly
        mocksdd = self.storage.devicetree.getDeviceByName("mocksdd")
        p = self.newDevice(device_class=PartitionDevice,
                           name="mocksdd1", size=Size("32 GiB"), parents=[mocksdd])
        self.failUnlessRaises(ValueError,
                              ActionResizeDevice,
                              p,
                              p.size + Size("7232 MiB"))

        # instantiation of device resize action for non-resizable device
        # should fail
        vg = self.storage.devicetree.getDeviceByName("VolGroup")
        self.assertNotEqual(vg, None)
        self.failUnlessRaises(ValueError,
                              ActionResizeDevice,
                              vg,
                              vg.size + Size("32 MiB"))

        # instantiation of format resize action for non-resizable format type
        # should fail
        lv_swap = self.storage.devicetree.getDeviceByName("VolGroup-lv_swap")
        self.assertNotEqual(lv_swap, None)
        self.failUnlessRaises(ValueError,
                              ActionResizeFormat,
                              lv_swap,
                              lv_swap.size + Size("32 MiB"))

        # instantiation of format resize action for non-existent format
        # should fail
        lv_root = self.storage.devicetree.getDeviceByName("VolGroup-lv_root")
        self.assertNotEqual(lv_root, None)
        lv_root.format.exists = False
        self.failUnlessRaises(ValueError,
                              ActionResizeFormat,
                              lv_root,
                              lv_root.size - Size("1000 MiB"))
        lv_root.format.exists = True

        # instantiation of device create action for existing device should
        # fail
        lv_swap = self.storage.devicetree.getDeviceByName("VolGroup-lv_swap")
        self.assertNotEqual(lv_swap, None)
        self.assertEqual(lv_swap.exists, True)
        self.failUnlessRaises(ValueError,
                              ActionCreateDevice,
                              lv_swap)

        # instantiation of format destroy action for device causes device's
        # format attribute to be a DeviceFormat instance
        lv_swap = self.storage.devicetree.getDeviceByName("VolGroup-lv_swap")
        self.assertNotEqual(lv_swap, None)
        orig_format = lv_swap.format
        self.assertEqual(lv_swap.format.type, "swap")
        destroy_swap = ActionDestroyFormat(lv_swap)
        self.assertEqual(lv_swap.format.type, "swap")
        destroy_swap.apply()
        self.assertEqual(lv_swap.format.type, None)

        # instantiation of format create action for device causes new format
        # to be accessible via device's format attribute
        new_format = getFormat("vfat", device=lv_swap.path)
        create_swap = ActionCreateFormat(lv_swap, new_format)
        self.assertEqual(lv_swap.format.type, None)
        create_swap.apply()
        self.assertEqual(lv_swap.format, new_format)
        lv_swap.format = orig_format

    def testActionRegistration(self):
        """ Verify correct operation of action registration and cancelling. """
        # self.setUp has just been run, so we should have something like
        # a preexisting autopart config in the devicetree.

        # registering a destroy action for a non-leaf device should fail
        vg = self.storage.devicetree.getDeviceByName("VolGroup")
        self.assertNotEqual(vg, None)
        self.assertEqual(vg.isleaf, False)
        a = ActionDestroyDevice(vg)
        self.failUnlessRaises(ValueError,
                              self.storage.devicetree.registerAction,
			      a)

        # registering any action other than create for a device that's not in
        # the devicetree should fail
        mocksdc = self.storage.devicetree.getDeviceByName("mocksdc")
        self.assertNotEqual(mocksdc, None)
        mocksdc1 = self.newDevice(device_class=PartitionDevice,
                              name="mocksdc1", size=Size("100 GiB"),
                              parents=[mocksdc], exists=True)

        mocksdc1_format = self.newFormat("ext2", device=mocksdc1.path, mountpoint="/")
        create_mocksdc1_format = ActionCreateFormat(mocksdc1, mocksdc1_format)
        create_mocksdc1_format.apply()
        self.failUnlessRaises(blivet.errors.DeviceTreeError,
                              self.storage.devicetree.registerAction,
                              create_mocksdc1_format)

        mocksdc1_format.exists = True
        mocksdc1_format._resizable = True
        resize_mocksdc1_format = ActionResizeFormat(mocksdc1,
                                                mocksdc1.size - Size("10 GiB"))
        resize_mocksdc1_format.apply()
        self.failUnlessRaises(blivet.errors.DeviceTreeError,
                              self.storage.devicetree.registerAction,
                              resize_mocksdc1_format)

        resize_mocksdc1 = ActionResizeDevice(mocksdc1, mocksdc1.size - Size("10 GiB"))
        resize_mocksdc1.apply()
        self.failUnlessRaises(blivet.errors.DeviceTreeError,
                              self.storage.devicetree.registerAction,
                              resize_mocksdc1)

        resize_mocksdc1.cancel()
        resize_mocksdc1_format.cancel()

        destroy_mocksdc1_format = ActionDestroyFormat(mocksdc1)
        self.failUnlessRaises(blivet.errors.DeviceTreeError,
                              self.storage.devicetree.registerAction,
                              destroy_mocksdc1_format)


        destroy_mocksdc1 = ActionDestroyDevice(mocksdc1)
        self.failUnlessRaises(blivet.errors.DeviceTreeError,
                              self.storage.devicetree.registerAction,
                              destroy_mocksdc1)

        # registering a device destroy action should cause the device to be
        # removed from the devicetree
        lv_root = self.storage.devicetree.getDeviceByName("VolGroup-lv_root")
        self.assertNotEqual(lv_root, None)
        a = ActionDestroyDevice(lv_root)
        self.storage.devicetree.registerAction(a)
        lv_root = self.storage.devicetree.getDeviceByName("VolGroup-lv_root")
        self.assertEqual(lv_root, None)
        self.storage.devicetree.cancelAction(a)

        # registering a device create action should cause the device to be
        # added to the devicetree
        mocksdd = self.storage.devicetree.getDeviceByName("mocksdd")
        self.assertNotEqual(mocksdd, None)
        mocksdd1 = self.storage.devicetree.getDeviceByName("mocksdd1")
        self.assertEqual(mocksdd1, None)
        mocksdd1 = self.newDevice(device_class=PartitionDevice,
                              name="mocksdd1", size=Size("100 GiB"),
                              parents=[mocksdd])
        a = ActionCreateDevice(mocksdd1)
        self.storage.devicetree.registerAction(a)
        mocksdd1 = self.storage.devicetree.getDeviceByName("mocksdd1")
        self.assertNotEqual(mocksdd1, None)

    def testActionObsoletes(self):
        """ Verify correct operation of DeviceAction.obsoletes. """
        self.destroyAllDevices(disks=["mocksdc"])
        mocksdc = self.storage.devicetree.getDeviceByName("mocksdc")
        self.assertNotEqual(mocksdc, None)

        mocksdc1 = self.newDevice(device_class=PartitionDevice,
                              name="mocksdc1", parents=[mocksdc], size=Size("40 GiB"))

        # ActionCreateDevice
        #
        # - obsoletes other ActionCreateDevice instances w/ lower id and same
        #   device
        create_device_1 = ActionCreateDevice(mocksdc1)
        create_device_1.apply()
        create_device_2 = ActionCreateDevice(mocksdc1)
        create_device_2.apply()
        self.assertEqual(create_device_2.obsoletes(create_device_1), True)
        self.assertEqual(create_device_1.obsoletes(create_device_2), False)

        # ActionCreateFormat
        #
        # - obsoletes other ActionCreateFormat instances w/ lower id and same
        #   device
        format_1 = self.newFormat("ext3", mountpoint="/home", device=mocksdc1.path)
        format_2 = self.newFormat("ext3", mountpoint="/opt", device=mocksdc1.path)
        create_format_1 = ActionCreateFormat(mocksdc1, format_1)
        create_format_1.apply()
        create_format_2 = ActionCreateFormat(mocksdc1, format_2)
        create_format_2.apply()
        self.assertEqual(create_format_2.obsoletes(create_format_1), True)
        self.assertEqual(create_format_1.obsoletes(create_format_2), False)

        # ActionResizeFormat
        #
        # - obsoletes other ActionResizeFormat instances w/ lower id and same
        #   device
        mocksdc1.exists = True
        mocksdc1.format.exists = True
        mocksdc1.format._resizable = True
        resize_format_1 = ActionResizeFormat(mocksdc1, mocksdc1.size - Size("1000 MiB"))
        resize_format_1.apply()
        resize_format_2 = ActionResizeFormat(mocksdc1, mocksdc1.size - Size("5000 MiB"))
        resize_format_2.apply()
        self.assertEqual(resize_format_2.obsoletes(resize_format_1), True)
        self.assertEqual(resize_format_1.obsoletes(resize_format_2), False)
        mocksdc1.exists = False
        mocksdc1.format.exists = False

        # ActionCreateFormat
        #
        # - obsoletes resize format actions w/ lower id on same device
        new_format = self.newFormat("ext4", mountpoint="/foo", device=mocksdc1.path)
        create_format_3 = ActionCreateFormat(mocksdc1, new_format)
        create_format_3.apply()
        self.assertEqual(create_format_3.obsoletes(resize_format_1), True)
        self.assertEqual(create_format_3.obsoletes(resize_format_2), True)

        # ActionResizeDevice
        #
        # - obsoletes other ActionResizeDevice instances w/ lower id and same
        #   device
        mocksdc1.exists = True
        mocksdc1.format.exists = True
        mocksdc1.format._resizable = True
        resize_device_1 = ActionResizeDevice(mocksdc1,
                                             mocksdc1.size + Size("10 GiB"))
        resize_device_1.apply()
        resize_device_2 = ActionResizeDevice(mocksdc1,
                                             mocksdc1.size - Size("10 GiB"))
        resize_device_2.apply()
        self.assertEqual(resize_device_2.obsoletes(resize_device_1), True)
        self.assertEqual(resize_device_1.obsoletes(resize_device_2), False)
        mocksdc1.exists = False
        mocksdc1.format.exists = False

        # ActionDestroyFormat
        #
        # - obsoletes all format actions w/ higher id on same device (including
        #   self if format does not exist)
        destroy_format_1 = ActionDestroyFormat(mocksdc1)
        destroy_format_1.apply()
        destroy_format_2 = ActionDestroyFormat(mocksdc1)
        destroy_format_2.apply()
        self.assertEqual(destroy_format_1.obsoletes(create_format_1), True)
        self.assertEqual(destroy_format_1.obsoletes(resize_format_1), True)
        self.assertEqual(destroy_format_1.obsoletes(destroy_format_1), True)
        self.assertEqual(destroy_format_2.obsoletes(destroy_format_1), False)
        self.assertEqual(destroy_format_1.obsoletes(destroy_format_2), True)

        # ActionDestroyDevice
        #
        # - obsoletes all actions w/ lower id that act on the same non-existent
        #   device (including self)
        # mocksdc1 does not exist
        destroy_mocksdc1 = ActionDestroyDevice(mocksdc1)
        destroy_mocksdc1.apply()
        self.assertEqual(destroy_mocksdc1.obsoletes(create_format_2), True)
        self.assertEqual(destroy_mocksdc1.obsoletes(resize_format_2), True)
        self.assertEqual(destroy_mocksdc1.obsoletes(create_device_1), True)
        self.assertEqual(destroy_mocksdc1.obsoletes(resize_device_1), True)
        self.assertEqual(destroy_mocksdc1.obsoletes(destroy_mocksdc1), True)

        # ActionDestroyDevice
        #
        # - obsoletes all but ActionDestroyFormat actions w/ lower id on the
        #   same existing device
        # mocksda1 exists
        mocksda1 = self.storage.devicetree.getDeviceByName("mocksda1")
        self.assertNotEqual(mocksda1, None)
        #mocksda1.format._resizable = True
        resize_mocksda1_format = ActionResizeFormat(mocksda1,
                                                mocksda1.size - Size("50 MiB"))
        resize_mocksda1_format.apply()
        resize_mocksda1 = ActionResizeDevice(mocksda1, mocksda1.size - Size("50 MiB"))
        resize_mocksda1.apply()
        destroy_mocksda1_format = ActionDestroyFormat(mocksda1)
        destroy_mocksda1_format.apply()
        destroy_mocksda1 = ActionDestroyDevice(mocksda1)
        destroy_mocksda1.apply()
        self.assertEqual(destroy_mocksda1.obsoletes(resize_mocksda1_format), True)
        self.assertEqual(destroy_mocksda1.obsoletes(resize_mocksda1), True)
        self.assertEqual(destroy_mocksda1.obsoletes(destroy_mocksda1), False)
        self.assertEqual(destroy_mocksda1.obsoletes(destroy_mocksda1_format), False)

    def testActionPruning(self):
        """ Verify correct functioning of action pruning. """
        self.destroyAllDevices()

        mocksda = self.storage.devicetree.getDeviceByName("mocksda")
        self.assertNotEqual(mocksda, None, "failed to find disk 'mocksda'")

        mocksda1 = self.newDevice(device_class=PartitionDevice,
                              name="mocksda1", size=Size("500 MiB"),
                              parents=[mocksda])
        self.scheduleCreateDevice(mocksda1)

        mocksda2 = self.newDevice(device_class=PartitionDevice,
                              name="mocksda2", size=Size("100 GiB"),
                              parents=[mocksda])
        self.scheduleCreateDevice(mocksda2)
        fmt = self.newFormat("lvmpv", device=mocksda2.path)
        self.scheduleCreateFormat(device=mocksda2, fmt=fmt)

        vg = self.newDevice(device_class=LVMVolumeGroupDevice,
                            name="vg", parents=[mocksda2])
        self.scheduleCreateDevice(vg)

        lv_root = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_root", parents=[vg],
                                 size=Size("60 GiB"))
        self.scheduleCreateDevice(lv_root)
        fmt = self.newFormat("ext4", device=lv_root.path, mountpoint="/")
        self.scheduleCreateFormat(device=lv_root, fmt=fmt)

        lv_swap = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_swap", parents=[vg],
                                 size=Size("4 GiB"))
        self.scheduleCreateDevice(lv_swap)
        fmt = self.newFormat("swap", device=lv_swap.path)
        self.scheduleCreateFormat(device=lv_swap, fmt=fmt)

        # we'll soon schedule destroy actions for these members and the array,
        # which will test pruning. the whole mess should reduce to nothing
        mocksda3 = self.newDevice(device_class=PartitionDevice,
                              name="mocksda3", parents=[mocksda],
                              size=Size("40 GiB"))
        self.scheduleCreateDevice(mocksda3)
        fmt = self.newFormat("mdmember", device=mocksda3.path)
        self.scheduleCreateFormat(device=mocksda3, fmt=fmt)

        mocksdb = self.storage.devicetree.getDeviceByName("mocksdb")
        self.assertNotEqual(mocksdb, None, "failed to find disk 'mocksdb'")

        mocksdb1 = self.newDevice(device_class=PartitionDevice,
                              name="mocksdb1", parents=[mocksdb],
                              size=Size("40 GiB"))
        self.scheduleCreateDevice(mocksdb1)
        fmt = self.newFormat("mdmember", device=mocksdb1.path,)
        self.scheduleCreateFormat(device=mocksdb1, fmt=fmt)

        md0 = self.newDevice(device_class=MDRaidArrayDevice,
                             name="md0", level="raid0", minor=0,
                             memberDevices=2, totalDevices=2,
                             parents=[mocksdb1, mocksda3])
        self.scheduleCreateDevice(md0)

        fmt = self.newFormat("ext4", device=md0.path, mountpoint="/home")
        self.scheduleCreateFormat(device=md0, fmt=fmt)

        # now destroy the md and its components
        self.scheduleDestroyFormat(md0)
        self.scheduleDestroyDevice(md0)
        self.scheduleDestroyDevice(mocksdb1)
        self.scheduleDestroyDevice(mocksda3)

        fmt = self.newFormat("ext4", mountpoint="/boot", device=mocksda1.path)
        self.scheduleCreateFormat(device=mocksda1, fmt=fmt)

        # verify the md actions are present prior to pruning
        md0_actions = self.storage.devicetree.actions.find(devid=md0.id)
        self.assertNotEqual(len(md0_actions), 0)

        mocksdb1_actions = self.storage.devicetree.actions.find(devid=mocksdb1.id)
        self.assertNotEqual(len(mocksdb1_actions), 0)

        mocksda3_actions = self.storage.devicetree.actions.find(devid=mocksda3.id)
        self.assertNotEqual(len(mocksda3_actions), 0)

        self.storage.devicetree.actions.prune()

        # verify the md actions are gone after pruning
        md0_actions = self.storage.devicetree.actions.find(devid=md0.id)
        self.assertEqual(len(md0_actions), 0)

        mocksdb1_actions = self.storage.devicetree.actions.find(devid=mocksdb1.id)
        self.assertEqual(len(mocksdb1_actions), 0)

        mocksda3_actions = self.storage.devicetree.actions.find(mocksda3.id)
        self.assertEqual(len(mocksda3_actions), 0)

    def testActionDependencies(self):
        """ Verify correct functioning of action dependencies. """
        # ActionResizeDevice
        # an action that shrinks a device should require the action that
        # shrinks the device's format
        lv_root = self.storage.devicetree.getDeviceByName("VolGroup-lv_root")
        self.assertNotEqual(lv_root, None)
        lv_root.format._minInstanceSize = Size("10 MiB")
        lv_root.format._targetSize = lv_root.format._minInstanceSize
        #lv_root.format._resizable = True
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
        orig_size = lv_root.currentSize
        grow_device = ActionResizeDevice(lv_root,
                                         orig_size + Size("100 MiB"))
        grow_device.apply()
        grow_format = ActionResizeFormat(lv_root,
                                         orig_size + Size("100 MiB"))
        grow_format.apply()
        self.assertEqual(grow_format.requires(grow_device), True)
        self.assertEqual(grow_device.requires(grow_format), False)

        # create something like uncommitted autopart
        self.destroyAllDevices()
        mocksda = self.storage.devicetree.getDeviceByName("mocksda")
        mocksdb = self.storage.devicetree.getDeviceByName("mocksdb")
        mocksda1 = self.newDevice(device_class=PartitionDevice, name="mocksda1",
                              size=Size("500 MiB"), parents=[mocksda])
        mocksda1_format = self.newFormat("ext4", mountpoint="/boot",
                                     device=mocksda1.path)
        self.scheduleCreateDevice(mocksda1)
        self.scheduleCreateFormat(device=mocksda1, fmt=mocksda1_format)

        mocksda2 = self.newDevice(device_class=PartitionDevice, name="mocksda2",
                              size=Size("99.5 GiB"), parents=[mocksda])
        mocksda2_format = self.newFormat("lvmpv", device=mocksda2.path)
        self.scheduleCreateDevice(mocksda2)
        self.scheduleCreateFormat(device=mocksda2, fmt=mocksda2_format)

        mocksdb1 = self.newDevice(device_class=PartitionDevice, name="mocksdb1",
                              size=Size("100 GiB"), parents=[mocksdb])
        mocksdb1_format = self.newFormat("lvmpv", device=mocksdb1.path)
        self.scheduleCreateDevice(mocksdb1)
        self.scheduleCreateFormat(device=mocksdb1, fmt=mocksdb1_format)

        vg = self.newDevice(device_class=LVMVolumeGroupDevice,
                            name="VolGroup", parents=[mocksda2, mocksdb1])
        self.scheduleCreateDevice(vg)

        lv_root = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_root", parents=[vg],
                                 size=Size("160 GiB"))
        self.scheduleCreateDevice(lv_root)
        fmt = self.newFormat("ext4", device=lv_root.path, mountpoint="/")
        self.scheduleCreateFormat(device=lv_root, fmt=fmt)

        lv_swap = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_swap", parents=[vg],
                                 size=Size("4 GiB"))
        self.scheduleCreateDevice(lv_swap)
        fmt = self.newFormat("swap", device=lv_swap.path)
        self.scheduleCreateFormat(device=lv_swap, fmt=fmt)

        # ActionCreateDevice
        # creation of an LV should require the actions that create the VG,
        # its PVs, and the devices that contain the PVs
        lv_root = self.storage.devicetree.getDeviceByName("VolGroup-lv_root")
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
        # lower numbered of the two, eg: create mocksda2 before creating mocksda3
        mocksdc = self.storage.devicetree.getDeviceByName("mocksdc")
        self.assertNotEqual(mocksdc, None)

        mocksdc1 = self.newDevice(device_class=PartitionDevice, name="mocksdc1",
                              parents=[mocksdc], size=Size("50 GiB"))
        create_mocksdc1 = self.scheduleCreateDevice(mocksdc1)
        self.assertEqual(isinstance(create_mocksdc1, ActionCreateDevice), True)

        mocksdc2 = self.newDevice(device_class=PartitionDevice, name="mocksdc2",
                              parents=[mocksdc], size=Size("50 GiB"))
        create_mocksdc2 = self.scheduleCreateDevice(mocksdc2)
        self.assertEqual(isinstance(create_mocksdc2, ActionCreateDevice), True)

        self.assertEqual(create_mocksdc2.requires(create_mocksdc1), True)
        self.assertEqual(create_mocksdc1.requires(create_mocksdc2), False)

        # ActionCreateDevice
        # actions that create partitions on two separate disks should not
        # require each other, regardless of the partitions' numbers
        mocksda1 = self.storage.devicetree.getDeviceByName("mocksda1")
        self.assertNotEqual(mocksda1, None)
        actions = self.storage.devicetree.actions.find(action_type="create",
                                                      object_type="device",
                                                      device=mocksda1)
        self.assertEqual(len(actions), 1,
                         "wrong number of create actions found for mocksda1")
        create_mocksda1 = actions[0]
        self.assertEqual(create_mocksdc2.requires(create_mocksda1), False)
        self.assertEqual(create_mocksda1.requires(create_mocksdc1), False)

        # ActionDestroyDevice
        # an action that destroys a device containing an mdmember format
        # should require the action that destroys the md array it is a
        # member of if an array is defined
        self.destroyAllDevices(disks=["mocksdc", "mocksdd"])
        mocksdc = self.storage.devicetree.getDeviceByName("mocksdc")
        self.assertNotEqual(mocksdc, None)
        mocksdd = self.storage.devicetree.getDeviceByName("mocksdd")
        self.assertNotEqual(mocksdd, None)

        mocksdc1 = self.newDevice(device_class=PartitionDevice, name="mocksdc1",
                              parents=[mocksdc], size=Size("40 GiB"))
        self.scheduleCreateDevice(mocksdc1)
        fmt = self.newFormat("mdmember", device=mocksdc1.path)
        self.scheduleCreateFormat(device=mocksdc1, fmt=fmt)

        mocksdd1 = self.newDevice(device_class=PartitionDevice, name="mocksdd1",
                              parents=[mocksdd], size=Size("40 GiB"))
        self.scheduleCreateDevice(mocksdd1)
        fmt = self.newFormat("mdmember", device=mocksdd1.path,)
        self.scheduleCreateFormat(device=mocksdd1, fmt=fmt)

        md0 = self.newDevice(device_class=MDRaidArrayDevice,
                             name="md0", level="raid0", minor=0,
                             memberDevices=2, totalDevices=2,
                             parents=[mocksdc1, mocksdd1])
        self.scheduleCreateDevice(md0)
        fmt = self.newFormat("ext4", device=md0.path, mountpoint="/home")
        self.scheduleCreateFormat(device=md0, fmt=fmt)

        destroy_md0_format = self.scheduleDestroyFormat(md0)
        destroy_md0 = self.scheduleDestroyDevice(md0)
        destroy_members = [self.scheduleDestroyDevice(mocksdc1)]
        destroy_members.append(self.scheduleDestroyDevice(mocksdd1))

        for member in destroy_members:
            # device and format destroy actions for md members should require
            # both device and format destroy actions for the md array
            for array in [destroy_md0_format, destroy_md0]:
                self.assertEqual(member.requires(array), True)

        # ActionDestroyDevice
        # when there are two actions that will each destroy a partition on the
        # same disk, the action that will destroy the lower-numbered
        # partition should require the action that will destroy the higher-
        # numbered partition, eg: destroy mocksda2 before destroying mocksda1
        self.destroyAllDevices(disks=["mocksdc", "mocksdd"])
        mocksdc1 = self.newDevice(device_class=PartitionDevice, name="mocksdc1",
                              parents=[mocksdc], size=Size("50 GiB"))
        self.scheduleCreateDevice(mocksdc1)

        mocksdc2 = self.newDevice(device_class=PartitionDevice, name="mocksdc2",
                              parents=[mocksdc], size=Size("40 GiB"))
        self.scheduleCreateDevice(mocksdc2)

        destroy_mocksdc1 = self.scheduleDestroyDevice(mocksdc1)
        destroy_mocksdc2 = self.scheduleDestroyDevice(mocksdc2)
        self.assertEqual(destroy_mocksdc1.requires(destroy_mocksdc2), True)
        self.assertEqual(destroy_mocksdc2.requires(destroy_mocksdc1), False)

        self.destroyAllDevices(disks=["mocksdc", "mocksdd"])
        mocksdc = self.storage.devicetree.getDeviceByName("mocksdc")
        self.assertNotEqual(mocksdc, None)
        mocksdd = self.storage.devicetree.getDeviceByName("mocksdd")
        self.assertNotEqual(mocksdd, None)

        mocksdc1 = self.newDevice(device_class=PartitionDevice, name="mocksdc1",
                              parents=[mocksdc], size=Size("50 GiB"))
        create_pv = self.scheduleCreateDevice(mocksdc1)
        fmt = self.newFormat("lvmpv", device=mocksdc1.path)
        create_pv_format = self.scheduleCreateFormat(device=mocksdc1, fmt=fmt)

        testvg = self.newDevice(device_class=LVMVolumeGroupDevice,
                                name="testvg", parents=[mocksdc1])
        create_vg = self.scheduleCreateDevice(testvg)
        testlv = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                name="testlv", parents=[testvg],
                                size=Size("30 GiB"))
        create_lv = self.scheduleCreateDevice(testlv)
        fmt = self.newFormat("ext4", device=testlv.path)
        create_lv_format = self.scheduleCreateFormat(device=testlv, fmt=fmt)

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
        self.destroyAllDevices(disks=["mocksdc", "mocksdd"])
        mocksdc1 = self.newDevice(device_class=PartitionDevice, exists=True,
                              name="mocksdc1", parents=[mocksdc],
                              size=Size("50 GiB"))
        mocksdc1.format = self.newFormat("lvmpv", device=mocksdc1.path, exists=True,
                                     device_instance=mocksdc1)
        testvg = self.newDevice(device_class=LVMVolumeGroupDevice, exists=True,
                                name="testvg", parents=[mocksdc1],
                                size=Size("50 GiB"))
        testlv = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                exists=True, size=Size("30 GiB"),
                                name="testlv", parents=[testvg])
        testlv.format = self.newFormat("ext4", device=testlv.path,
                                       exists=True, device_instance=testlv)

        # ActionResizeDevice
        # an action that resizes a device should require an action that grows
        # a device that the first action's device depends on, eg: grow
        # device containing PV before resize of VG or LVs
        mocksdc1.format._resizable = True   # override lvmpv.resizable
        mocksdc1.exists = True
        mocksdc1.format.exists = True
        grow_pv = ActionResizeDevice(mocksdc1, mocksdc1.size + Size("10 GiB"))
        grow_pv.apply()
        grow_lv = ActionResizeDevice(testlv, testlv.size + Size("5 GiB"))
        grow_lv.apply()
        grow_lv_format = ActionResizeFormat(testlv,
                                            testlv.size + Size("5 GiB"))
        grow_lv_format.apply()
        mocksdc1.exists = False
        mocksdc1.format.exists = False

        self.assertEqual(grow_lv.requires(grow_pv), True)
        self.assertEqual(grow_pv.requires(grow_lv), False)

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
        testlv.format._minInstanceSize = Size("10 MiB")
        testlv.format._targetSize = testlv.format._minInstanceSize
        shrink_lv = ActionResizeDevice(testlv,
                                       testlv.size - Size("10 GiB"))
        shrink_lv.apply()
        mocksdc1.exists = True
        mocksdc1.format.exists = True
        shrink_pv = ActionResizeDevice(mocksdc1, mocksdc1.size - Size("5 GiB"))
        shrink_pv.apply()
        mocksdc1.exists = False
        mocksdc1.format.exists = False

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
        fmt = self.newFormat("disklabel", device=testlv.path)
        format_lv = ActionCreateFormat(testlv, fmt)
        self.assertEqual(format_lv.requires(grow_lv), True)
        self.assertEqual(grow_lv.requires(format_lv), False)

        # ActionDestroyFormat
        # an action that destroys a format should require an action that
        # destroys a device that depends on the format's device
        destroy_pv_format = ActionDestroyFormat(mocksdc1)
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

        mocksdc2 = self.newDevice(device_class=PartitionDevice, name="mocksdc2",
                              size=Size("5 GiB"), parents=[mocksdc])
        create_mocksdc2 = self.scheduleCreateDevice(mocksdc2)

        # create actions should always require destroy actions -- even for
        # unrelated devices -- since, after pruning, it should always be the
        # case that destroy actions are processed before create actions (no
        # create/destroy loops are allowed)
        self.assertEqual(create_mocksdc2.requires(destroy_lv), True)

        # similarly, create actions should also require resize actions
        self.assertEqual(create_mocksdc2.requires(grow_lv), True)

    def testActionApplyCancel(self):
        lv_root = self.storage.devicetree.getDeviceByName("VolGroup-lv_root")

        # ActionResizeFormat
        lv_root.format._minInstanceSize = Size("10 MiB")
        lv_root.format._size = lv_root.size
        lv_root.format._targetSize = lv_root.size
        original_format_size = lv_root.format.currentSize
        target_size = lv_root.size - Size("1 GiB")
        #lv_root.format._resizable = True
        action = ActionResizeFormat(lv_root, target_size)
        self.assertEqual(lv_root.format.size, original_format_size)
        action.apply()
        self.assertEqual(lv_root.format.size, target_size)
        action.cancel()
        self.assertEqual(lv_root.format.size, original_format_size)

        # ActionResizeDevice
        original_device_size = lv_root.currentSize
        action = ActionResizeDevice(lv_root, target_size)
        self.assertEqual(lv_root.size, original_device_size)
        action.apply()
        self.assertEqual(lv_root.size, target_size)
        action.cancel()
        self.assertEqual(lv_root.size, original_device_size)

        # ActionDestroyFormat
        original_format = lv_root.format
        action = ActionDestroyFormat(lv_root)
        self.assertEqual(lv_root.format, original_format)
        self.assertNotEqual(lv_root.format.type, None)
        action.apply()
        self.assertEqual(lv_root.format.type, None)
        action.cancel()
        self.assertEqual(lv_root.format, original_format)


        mocksdc = self.storage.devicetree.getDeviceByName("mocksdc")
        mocksdc.format = None
        pv_fmt = self.newFormat("lvmpv", device_instance=mocksdc, device=mocksdc.path)
        self.scheduleCreateFormat(device=mocksdc, fmt=pv_fmt)
        vg = self.storage.devicetree.getDeviceByName("VolGroup")
        original_pvs = vg.parents[:]

        # ActionAddMember
        # XXX ActionAddMember and ActionRemoveMember make no effort to restore
        #     the original ordering of the container's parents list when
        #     canceled.
        pvs = original_pvs[:]
        action = ActionAddMember(vg, mocksdc)
        self.assertEqual(list(vg.parents), original_pvs)
        action.apply()
        pvs.append(mocksdc)
        self.assertEqual(list(vg.parents), pvs)
        action.cancel()
        pvs.remove(mocksdc)
        self.assertEqual(list(vg.parents), original_pvs)

        # ActionRemoveMember
        pvs = original_pvs[:]
        mocksdb1 = self.storage.devicetree.getDeviceByName("mocksdb1")
        action = ActionRemoveMember(vg, mocksdb1)
        self.assertEqual(list(vg.parents), original_pvs)
        action.apply()
        pvs.remove(mocksdb1)
        self.assertEqual(list(vg.parents), pvs)
        action.cancel()
        self.assertEqual(list(vg.parents), original_pvs)

    def testContainerActions(self):
        self.destroyAllDevices()
        mocksda = self.storage.devicetree.getDeviceByName("mocksda")
        mocksdb = self.storage.devicetree.getDeviceByName("mocksdb")

        #
        # create something like an existing lvm autopart layout across two disks
        #
        mocksda1 = self.newDevice(device_class=PartitionDevice,
                              exists=True, name="mocksda1", parents=[mocksda],
                              size=Size("500 MiB"))
        mocksda1.format = self.newFormat("ext4", mountpoint="/boot",
                                     device_instance=mocksda1,
                                     device=mocksda1.path, exists=True)
        self.storage.devicetree._addDevice(mocksda1)

        mocksda2 = self.newDevice(device_class=PartitionDevice,
                              size=Size("99.5 GiB"), name="mocksda2",
                              parents=[mocksda], exists=True)
        mocksda2.format = self.newFormat("lvmpv", device=mocksda2.path, exists=True)
        self.storage.devicetree._addDevice(mocksda2)

        mocksdb1 = self.newDevice(device_class=PartitionDevice,
                              size=Size("99.999 GiB"), name="mocksdb1",
                              parents=[mocksdb], exists=True)
        mocksdb1.format = self.newFormat("lvmpv", device=mocksdb1.path, exists=True)
        self.storage.devicetree._addDevice(mocksdb1)

        vg = self.newDevice(device_class=LVMVolumeGroupDevice,
                            name="VolGroup", parents=[mocksda2, mocksdb1],
                            exists=True)
        self.storage.devicetree._addDevice(vg)

        lv_root = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_root", parents=[vg],
                                 size=Size("160 GiB"), exists=True)
        lv_root.format = self.newFormat("ext4", mountpoint="/",
                                        device_instance=lv_root,
                                        device=lv_root.path, exists=True)
        self.storage.devicetree._addDevice(lv_root)

        lv_swap = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                 name="lv_swap", parents=[vg],
                                 size=Size("4000 MiB"), exists=True)
        lv_swap.format = self.newFormat("swap", device=lv_swap.path,
                                        device_instance=lv_swap,
                                        exists=True)
        self.storage.devicetree._addDevice(lv_swap)

        #
        # test some modifications to the VG
        #
        mocksdc = self.storage.devicetree.getDeviceByName("mocksdc")
        mocksdc1 = self.newDevice(device_class=PartitionDevice, name="mocksdc1",
                              size=Size("50 GiB"), parents=[mocksdc])
        mocksdc1_format = self.newFormat("lvmpv", device=mocksdc1.path)
        create_mocksdc1 = self.scheduleCreateDevice(mocksdc1)
        create_mocksdc1_format = self.scheduleCreateFormat(device=mocksdc1,
                                                       fmt=mocksdc1_format)

        self.assertEqual(len(vg.parents), 2)

        add_mocksdc1 = ActionAddMember(vg, mocksdc1)
        self.assertEqual(len(vg.parents), 2)
        add_mocksdc1.apply()
        self.assertEqual(len(vg.parents), 3)

        self.assertEqual(add_mocksdc1.requires(create_mocksdc1), True)
        self.assertEqual(add_mocksdc1.requires(create_mocksdc1_format), True)

        new_lv = self.newDevice(device_class=LVMLogicalVolumeDevice,
                                name="newlv", parents=[vg],
                                size=Size("20 GiB"))
        create_new_lv = self.scheduleCreateDevice(new_lv)
        new_lv_format = self.newFormat("xfs", device=new_lv.path)
        create_new_lv_format = self.scheduleCreateFormat(device=new_lv,
                                                         fmt=new_lv_format)

        self.assertEqual(create_new_lv.requires(add_mocksdc1), True)
        self.assertEqual(create_new_lv_format.requires(add_mocksdc1), False)

        self.storage.devicetree.cancelAction(create_new_lv_format)
        self.storage.devicetree.cancelAction(create_new_lv)

        remove_mocksdb1 = ActionRemoveMember(vg, mocksdb1)
        self.assertEqual(len(vg.parents), 3)
        remove_mocksdb1.apply()
        self.assertEqual(len(vg.parents), 2)

        self.assertEqual(remove_mocksdb1.requires(add_mocksdc1), True)

        vg.parents.append(mocksdb1)
        remove_mocksdb1_2 = ActionRemoveMember(vg, mocksdb1)
        remove_mocksdb1_2.apply()
        self.assertEqual(remove_mocksdb1_2.obsoletes(remove_mocksdb1), False)
        self.assertEqual(remove_mocksdb1.obsoletes(remove_mocksdb1_2), True)

        remove_mocksdc1 = ActionRemoveMember(vg, mocksdc1)
        remove_mocksdc1.apply()
        self.assertEqual(remove_mocksdc1.obsoletes(add_mocksdc1), True)
        self.assertEqual(add_mocksdc1.obsoletes(remove_mocksdc1), True)

        # add/remove loops (same member&container) should obsolete both actions
        add_mocksdb1 = ActionAddMember(vg, mocksdb1)
        add_mocksdb1.apply()
        self.assertEqual(add_mocksdb1.obsoletes(remove_mocksdb1), True)
        self.assertEqual(remove_mocksdb1.obsoletes(add_mocksdb1), True)

        mocksdc2 = self.newDevice(device_class=PartitionDevice, name="mocksdc2",
                              size=Size("5 GiB"), parents=[mocksdc])
        create_mocksdc2 = self.scheduleCreateDevice(mocksdc2)

        # destroy/resize/create sequencing does not apply to container actions
        self.assertEqual(create_mocksdc2.requires(remove_mocksdc1), False)
        self.assertEqual(remove_mocksdc1.requires(create_mocksdc2), False)

    def testActionSorting(self, *args, **kwargs):
        """ Verify correct functioning of action sorting. """
        pass

if __name__ == "__main__":
    unittest.main()

