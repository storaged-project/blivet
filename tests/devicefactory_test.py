
import unittest
from decimal import Decimal
import os

import blivet

from blivet import devicefactory
from blivet.devicelibs import raid
from blivet.devices import DiskDevice
from blivet.devices import DiskFile
from blivet.devices import LUKSDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import PartitionDevice
from blivet.errors import RaidError
from blivet.formats import get_format
from blivet.size import Size
from blivet.util import create_sparse_tempfile

"""
    Things we're still not testing:

        - catches not enough disks for specified raid level
        - container
            - defined
            - existing
            - fixed, max, normal size

    Ideas that came up while working on this:

        - add properties to factory classes indicating relevance/support of
          various options (container_*, encrypted come to mind)
"""


class DeviceFactoryTestCase(unittest.TestCase):
    device_type = None
    """ device type constant to pass to devicefactory.get_device_factory """

    device_class = None
    """ device class to expect from devicefactory """

    encryption_supported = True
    """ whether encryption of this device type is supported by blivet """

    def setUp(self):
        if self.device_type is None:
            raise unittest.SkipTest("abstract base class")

        self.b = blivet.Blivet()  # don't populate it
        self.disk_files = [create_sparse_tempfile("factorytest", Size("1 GiB")),
                           create_sparse_tempfile("factorytest", Size("1 GiB"))]
        for filename in self.disk_files:
            disk = DiskFile(filename)
            self.b.devicetree._add_device(disk)
            self.b.initialize_disk(disk)

        self.addCleanup(self._clean_up_disk_files)

    def _clean_up_disk_files(self):
        for fn in self.disk_files:
            os.unlink(fn)

    def _factory_device(self, *args, **kwargs):
        """ Run the device factory and return the device it produces. """
        factory = devicefactory.get_device_factory(self.b,
                                                   *args, **kwargs)
        factory.configure()
        return factory.device

    def _validate_factory_device(self, *args, **kwargs):
        """ Validate the factory device against the factory args. """
        device = args[0]
        device_type = args[1]
        size = args[2]

        if kwargs.get("encrypted"):
            device_class = LUKSDevice
        else:
            device_class = self.device_class

        self.assertIsInstance(device, device_class)
        self.assertEqual(devicefactory.get_device_type(device), device_type)
        self.assertEqual(device.format.type, kwargs['fstype'])

        if hasattr(device.format, "mountpoint"):
            self.assertEqual(device.format.mountpoint,
                             kwargs.get('mountpoint'))

        if hasattr(device.format, "label"):
            self.assertEqual(device.format.label,
                             kwargs.get('label'))

        self.assertLessEqual(device.size, size)
        self.assertGreaterEqual(device.size, device.format.min_size)
        if device.format.max_size:
            self.assertLessEqual(device.size, device.format.max_size)

        self.assertEqual(device.encrypted,
                         kwargs.get("encrypted", False) or
                         kwargs.get("container_encrypted", False))

        self.assertTrue(set(device.disks).issubset(kwargs["disks"]))

    def test_device_factory(self):
        device_type = self.device_type
        size = Size('400 MiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)
        self.b.recursive_remove(device)

        if self.encryption_supported:
            # Encrypt the leaf device
            kwargs["encrypted"] = True
            device = self._factory_device(device_type, size, **kwargs)
            self._validate_factory_device(device, device_type, size, **kwargs)
            for partition in self.b.partitions:
                self.b.recursive_remove(partition)

        ##
        # Reconfigure device
        ##

        # Create a basic stack
        size = Size('800 MiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        if self.encryption_supported:
            # Encrypt the leaf device
            kwargs["encrypted"] = True
            kwargs["device"] = device
            device = self._factory_device(device_type, size, **kwargs)
            self._validate_factory_device(device, device_type, size, **kwargs)

        # Change the mountpoint
        kwargs["mountpoint"] = "/a/different/dir"
        kwargs["device"] = device
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        # Change the fstype and size.
        kwargs["fstype"] = "xfs"
        kwargs["device"] = device
        size = Size("650 MiB")
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

    def _get_test_factory_args(self):
        """ Return kwarg dict of type-specific factory ctor args. """
        return dict()

    # pylint: disable=unused-argument
    def _get_size_delta(self, devices=None):
        """ Return size delta for a specific factory type.

            :keyword devices: list of factory-managed devices or None
            :type devices: list(:class:`blivet.devices.StorageDevice`) or NoneType
        """
        return Size("1 MiB")

    def test_get_free_disk_space(self):
        # get_free_disk_space should return the total free space on disks
        kwargs = self._get_test_factory_args()
        size = Size("500 MiB")
        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
                                                   size,
                                                   disks=self.b.disks,
                                                   **kwargs)
        # disks contain empty disklabels, so free space is sum of disk sizes
        self.assertAlmostEqual(factory._get_free_disk_space(),
                               sum(d.size for d in self.b.disks),
                               delta=self._get_size_delta())

        factory.configure()
        device = factory.device

        device_space = factory._get_device_space()
        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
                                                   size,
                                                   disks=self.b.disks,
                                                   **kwargs)
        # disks contain a 500 MiB device, which includes varying amounts of
        # metadata and space lost to partition alignment.
        self.assertAlmostEqual(factory._get_free_disk_space(),
                               sum(d.size for d in self.b.disks) - device_space,
                               delta=self._get_size_delta(devices=[device]))

    def test_normalize_size(self):
        # _normalize_size should adjust target size to within the format limits
        fstype = "ext2"
        ext2 = get_format(fstype)
        self.assertTrue(ext2.max_size > Size(0))
        size = Size("9 TiB")
        self.assertTrue(size > ext2.max_size)

        kwargs = self._get_test_factory_args()
        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
                                                   size,
                                                   disks=self.b.disks,
                                                   fstype=fstype,
                                                   **kwargs)
        factory._normalize_size()
        self.assertTrue(factory.size <= ext2.max_size)

        # _normalize_size should convert a size of None to a reasonable guess
        # at the largest possible size based on disk free space
        factory.size = None
        factory._normalize_size()
        self.assertIsInstance(factory.size, blivet.size.Size)
        self.assertTrue(factory.size <= ext2.max_size)
        # Allow some variation in size for metadata, alignment, &c.
        self.assertAlmostEqual(factory.size, sum(d.size for d in self.b.disks),
                               delta=self._get_size_delta())

        # _handle_no_size should also take into account any specified factory
        # device, in case the factory is to be modifying a defined device
        # must be a couple MiB smaller than the disk to accommodate
        # PartitionFactory
        size = self.b.disks[0].size - Size("4 MiB")
        device = self._factory_device(self.device_type, size,
                                      disks=self.b.disks, **kwargs)
        self.assertAlmostEqual(device.size, size, delta=self._get_size_delta())

        factory.size = None
        factory.device = device
        factory._normalize_size()
        self.assertIsInstance(factory.size, blivet.size.Size)
        self.assertTrue(factory.size <= ext2.max_size)
        # factory size should be total disk space plus current device space
        # Allow some variation in size for metadata, alignment, &c.
        self.assertAlmostEqual(factory.size,
                               sum(d.size for d in self.b.disks),
                               delta=self._get_size_delta(devices=[device]))


class PartitionFactoryTestCase(DeviceFactoryTestCase):
    device_class = PartitionDevice
    device_type = devicefactory.DEVICE_TYPE_PARTITION

    def test_bug1178884(self):
        # Test a change of format and size where old size is too large for the
        # new format but not for the old one.
        device_type = self.device_type
        size = Size('400 MiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        kwargs["device"] = device
        kwargs["fstype"] = "prepboot"
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

    def _get_size_delta(self, devices=None):
        delta = Size("2 MiB")
        if devices:
            delta += Size("2 MiB") * len(devices)

        return delta


class LVMFactoryTestCase(DeviceFactoryTestCase):
    device_class = LVMLogicalVolumeDevice
    device_type = devicefactory.DEVICE_TYPE_LVM

    def _validate_factory_device(self, *args, **kwargs):
        super(LVMFactoryTestCase, self)._validate_factory_device(*args, **kwargs)

        device = args[0]

        if kwargs.get("encrypted"):
            container = device.slave.container
        else:
            container = device.container

        if kwargs.get("container_encrypted"):
            member_class = LUKSDevice
        elif kwargs.get("container_raid_level"):
            member_class = MDRaidArrayDevice
        else:
            member_class = PartitionDevice

        self.assertEqual(container.encrypted,
                         kwargs.get("container_encrypted", False))
        for pv in container.parents:
            self.assertEqual(pv.format.type, "lvmpv")
            self.assertEqual(pv.encrypted, kwargs.get("container_encrypted", False))
            self.assertIsInstance(pv, member_class)

    def test_device_factory(self):
        super(LVMFactoryTestCase, self).test_device_factory()

        ##
        # New device
        ##
        device_type = self.device_type
        size = Size('400 MiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}

        if self.encryption_supported:
            # encrypt the PVs
            kwargs["encrypted"] = False
            kwargs["container_encrypted"] = True
            device = self._factory_device(device_type, size, **kwargs)
            self._validate_factory_device(device, device_type, size, **kwargs)
            for partition in self.b.partitions:
                self.b.recursive_remove(partition)

        # Add mirroring of PV using MD
        kwargs["container_encrypted"] = False
        kwargs["container_raid_level"] = "raid1"
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)
        for partition in self.b.partitions:
            self.b.recursive_remove(partition)

        ##
        # Reconfigure device
        ##

        # Create a basic LVM stack
        device_type = self.device_type
        size = Size('800 MiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        if self.encryption_supported:
            # Encrypt the LV
            # Yes, this is duplicated from the base class but this allows us to
            # test a reconfiguration from encrypted leaf to encrypted container
            # members in the next test.
            kwargs["encrypted"] = True
            kwargs["device"] = device
            device = self._factory_device(device_type, size, **kwargs)
            self._validate_factory_device(device, device_type, size, **kwargs)

            # Decrypt the LV, but encrypt the PVs
            kwargs["encrypted"] = False
            kwargs["container_encrypted"] = True
            kwargs["device"] = device
            device = self._factory_device(device_type, size, **kwargs)
            self._validate_factory_device(device, device_type, size, **kwargs)

        # Switch to an encrypted raid0 md pv
        kwargs["container_raid_level"] = "raid0"
        kwargs["device"] = device
        size = Size("400 MiB")
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        # remove encryption from the md pv
        kwargs["container_encrypted"] = False
        kwargs["device"] = device
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        # switch back to normal partition pvs
        kwargs["container_raid_level"] = None
        kwargs["device"] = device
        size = Size("750 MiB")
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        # limit the vg to the first disk
        kwargs["disks"] = self.b.disks[:1]
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        # expand it back to all disks
        kwargs["disks"] = self.b.disks
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

    def _get_size_delta(self, devices=None):
        if not devices:
            delta = Size("2 MiB") * len(self.b.disks)
        else:
            delta = Size("4 MiB") * len(self.b.disks) * (len(devices) + 1)

        return delta

    def test_get_container(self):
        for disk in self.b.disks:
            self.b.format_device(disk, get_format("lvmpv"))

        vg = self.b.new_vg(parents=self.b.disks, name="newvg")
        self.b.create_device(vg)
        self.assertEqual(self.b.vgs, [vg])

        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
                                                   Size("500 MiB"),
                                                   fstype="xfs")

        # get_container on lvm factory should return the lone non-existent vg
        self.assertEqual(factory.get_container(), vg)

        # get_container should require allow_existing to return an existing vg
        vg.exists = True
        vg._complete = True
        self.assertEqual(factory.get_container(), None)
        self.assertEqual(factory.get_container(allow_existing=True), vg)


class LVMThinPFactoryTestCase(LVMFactoryTestCase):
    # TODO: check that the LV we get is a thin pool
    device_class = LVMLogicalVolumeDevice
    device_type = devicefactory.DEVICE_TYPE_LVM_THINP
    encryption_supported = False

    def _validate_factory_device(self, *args, **kwargs):
        super(LVMThinPFactoryTestCase, self)._validate_factory_device(*args,
                                                                      **kwargs)
        device = args[0]

        if kwargs.get("encrypted", False):
            thinlv = device.slave
        else:
            thinlv = device

        self.assertTrue(hasattr(thinlv, "pool"))

        return device

    def _get_size_delta(self, devices=None):
        delta = super(LVMThinPFactoryTestCase, self)._get_size_delta(devices=devices)
        if devices:
            # we reserve 20% of thin pool size in VG for pool metadata
            delta += sum(d.size for d in devices) * Decimal('0.20')

        return delta


class MDFactoryTestCase(DeviceFactoryTestCase):
    device_type = devicefactory.DEVICE_TYPE_MD
    device_class = MDRaidArrayDevice

    def test_device_factory(self):
        # RAID0 across two disks
        device_type = self.device_type
        size = Size('1 GiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'ext4',
                  "raid_level": "raid0",
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)
        self.b.recursive_remove(device)

        # Encrypt the leaf device
        kwargs["encrypted"] = True
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)
        for partition in self.b.partitions:
            self.b.recursive_remove(partition)

        # RAID1 across two disks
        size = Size('500 MiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'ext4',
                  "raid_level": "raid1",
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)
        for partition in self.b.partitions:
            self.b.recursive_remove(partition)

        ##
        # Reconfigure device
        ##

        # RAID0 across two disks w/ swap
        size = Size('800 MiB')
        kwargs = {"disks": self.b.disks,
                  "fstype": 'swap',
                  "raid_level": "raid0",
                  "label": 'SWAP00'}
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        # Encrypt the leaf device
        kwargs["encrypted"] = True
        kwargs["device"] = device
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

        # Change the mountpoint
        size = Size('400 MiB')
        kwargs["raid_level"] = "raid1"
        kwargs["mountpoint"] = "/a/different/dir"
        kwargs["label"] = "fedora 53 root"
        kwargs["fstype"] = "xfs"
        kwargs["device"] = device
        # kwargs["encrypted"] = False
        device = self._factory_device(device_type, size, **kwargs)
        self._validate_factory_device(device, device_type, size, **kwargs)

    def _get_size_delta(self, devices=None):
        return Size("2 MiB") * len(self.b.disks)

    def _get_test_factory_args(self):
        return {"raid_level": "raid0"}

    """Note that the following tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or its correct behavior. See the
       initial commit message for this file for further details.
    """

    def test_mdfactory(self):
        factory1 = devicefactory.get_device_factory(self.b,
                                                    devicefactory.DEVICE_TYPE_MD,
                                                    Size("1 GiB"),
                                                    raid_level=raid.RAID1)

        factory2 = devicefactory.get_device_factory(self.b,
                                                    devicefactory.DEVICE_TYPE_MD,
                                                    Size("1 GiB"),
                                                    raid_level=0)

        with self.assertRaisesRegex(devicefactory.DeviceFactoryError, "must have some RAID level"):
            devicefactory.get_device_factory(
                self.b,
                devicefactory.DEVICE_TYPE_MD,
                Size("1 GiB"))

        with self.assertRaisesRegex(RaidError, "requires at least"):
            factory1._get_device_space()

        with self.assertRaisesRegex(RaidError, "requires at least"):
            factory1._configure()

        self.assertEqual(factory1.container_list, [])

        self.assertIsNone(factory1.get_container())

        parents = [
            DiskDevice("name1", fmt=get_format("mdmember")),
            DiskDevice("name2", fmt=get_format("mdmember"))
        ]
        self.assertIsNotNone(factory1._get_new_device(parents=parents))

        with self.assertRaisesRegex(RaidError, "requires at least"):
            factory2._get_device_space()

        self.assertEqual(factory2.container_list, [])

        self.assertIsNone(factory2.get_container())
