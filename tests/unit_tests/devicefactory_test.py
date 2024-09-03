import os
import unittest
from unittest.mock import patch

from decimal import Decimal

import blivet

from blivet import devicefactory
from blivet.devicelibs import raid, crypto
from blivet.devices import BTRFSVolumeDevice
from blivet.devices import DiskDevice
from blivet.devices import DiskFile
from blivet.devices import LUKSDevice
from blivet.devices import LVMLogicalVolumeDevice
from blivet.devices import MDRaidArrayDevice
from blivet.devices import PartitionDevice
from blivet.devices import StratisFilesystemDevice
from blivet.devices.lvm import DEFAULT_THPOOL_RESERVE
from blivet.errors import RaidError
import blivet.flags
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

    factory_class = None
    """ devicefactory class used in this test case """

    _disk_size = Size("2 GiB")

    @patch("blivet.formats.fs.Ext4FS.supported", return_value=True)
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def setUp(self, *args):  # pylint: disable=unused-argument,arguments-differ
        if self.device_type is None:
            raise unittest.SkipTest("abstract base class")

        self.b = blivet.Blivet()  # don't populate it
        self.disk_files = [create_sparse_tempfile("factorytest", self._disk_size),
                           create_sparse_tempfile("factorytest", self._disk_size)]
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

        # sizes with VDO are special, we have a special check in LVMVDOFactoryTestCase._validate_factory_device
        if device_type != devicefactory.DEVICE_TYPE_LVM_VDO:
            self.assertLessEqual(device.size, kwargs.get("size"))
            self.assertGreaterEqual(device.size, device.format.min_size)
            if device.format.max_size:
                self.assertLessEqual(device.size, device.format.max_size)

        self.assertEqual(device.encrypted,
                         kwargs.get("encrypted", False) or
                         kwargs.get("container_encrypted", False))
        if kwargs.get("encrypted", False):
            self.assertEqual(device.parents[0].format.luks_version,
                             kwargs.get("luks_version", crypto.DEFAULT_LUKS_VERSION))
            self.assertEqual(device.raw_device.format.luks_sector_size,
                             kwargs.get("luks_sector_size", 0))

        self.assertTrue(set(device.disks).issubset(kwargs["disks"]))

    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    @patch("blivet.devices.dm.DMDevice.type_external_dependencies", return_value=set())
    def test_device_factory(self, *args):  # pylint: disable=unused-argument
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "size": Size("400 MiB"),
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        if device.type == "lvmvdolv":
            self.b.recursive_remove(device.pool)
        else:
            self.b.recursive_remove(device)

        if self.encryption_supported:
            # Encrypt the leaf device
            kwargs["encrypted"] = True
            device = self._factory_device(device_type, **kwargs)
            self._validate_factory_device(device, device_type, **kwargs)
            for partition in self.b.partitions:
                self.b.recursive_remove(partition)

        ##
        # Reconfigure device
        ##

        # Create a basic stack
        kwargs = {"disks": self.b.disks,
                  "size": Size('800 MiB'),
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        if self.encryption_supported:
            # Encrypt the leaf device
            kwargs["encrypted"] = True
            kwargs["device"] = device
            device = self._factory_device(device_type, **kwargs)
            self._validate_factory_device(device, device_type, **kwargs)

        # Change the mountpoint
        kwargs["mountpoint"] = "/a/different/dir"
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # Change the fstype and size.
        kwargs["fstype"] = "xfs"
        kwargs["device"] = device
        kwargs["size"] = Size("650 MiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # change size up
        kwargs["device"] = device
        kwargs["size"] = Size("900 MiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # Change LUKS version
        kwargs["luks_version"] = "luks1"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["luks_version"] = "luks2"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # Change LUKS sector size
        kwargs["luks_sector_size"] = 4096
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

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

    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def test_get_free_disk_space(self, *args):  # pylint: disable=unused-argument
        # get_free_disk_space should return the total free space on disks
        kwargs = self._get_test_factory_args()
        kwargs["size"] = max(Size("500 MiB"), self.factory_class._device_min_size)
        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
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
                                                   disks=self.b.disks,
                                                   **kwargs)
        # disks contain a 500 MiB device, which includes varying amounts of
        # metadata and space lost to partition alignment.
        self.assertAlmostEqual(factory._get_free_disk_space(),
                               sum(d.size for d in self.b.disks) - device_space,
                               delta=self._get_size_delta(devices=[device]))

    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def test_normalize_size(self, *args):  # pylint: disable=unused-argument
        # _normalize_size should adjust target size to within the format limits
        fstype = "ext2"
        ext2 = get_format(fstype)
        self.assertTrue(ext2.max_size > Size(0))
        size = Size("9 TiB")
        self.assertTrue(size > ext2.max_size)

        kwargs = self._get_test_factory_args()
        kwargs["size"] = size
        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
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
        kwargs["size"] = self.b.disks[0].size - Size("4 MiB")
        device = self._factory_device(self.device_type,
                                      disks=self.b.disks, **kwargs)
        self.assertAlmostEqual(device.size, kwargs["size"], delta=self._get_size_delta())

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

    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def test_default_factory_type(self, *args):  # pylint: disable=unused-argument
        factory = devicefactory.get_device_factory(self.b)
        self.assertIsInstance(factory, devicefactory.LVMFactory)

    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    @patch("blivet.formats.swap.SwapSpace.formattable", return_value=True)
    def test_factory_defaults(self, *args):  # pylint: disable=unused-argument
        ctor_kwargs = self._get_test_factory_args()
        factory = devicefactory.get_device_factory(self.b, self.device_type, **ctor_kwargs)
        for setting, value in factory._default_settings.items():
            if setting not in ctor_kwargs:
                self.assertEqual(getattr(factory, setting), value)

        self.assertEqual(factory.fstype, self.b.get_fstype())

        kwargs = self._get_test_factory_args()
        kwargs.update({"disks": self.b.disks[:],
                       "fstype": "swap",
                       "size": max(Size("2GiB"), self.factory_class._device_min_size),
                       "label": "SWAP"})
        device = self._factory_device(self.device_type, **kwargs)
        factory = devicefactory.get_device_factory(self.b, self.device_type,
                                                   device=device)
        self.assertEqual(factory.size, getattr(device, "req_size", device.size))
        if self.device_type == devicefactory.DEVICE_TYPE_PARTITION:
            self.assertIn(device.disk, factory.disks)
        else:
            self.assertEqual(factory.disks, device.disks)
        self.assertEqual(factory.fstype, device.format.type)
        self.assertEqual(factory.label, device.format.label)


class PartitionFactoryTestCase(DeviceFactoryTestCase):
    device_class = PartitionDevice
    device_type = devicefactory.DEVICE_TYPE_PARTITION
    factory_class = devicefactory.PartitionFactory

    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def test_bug1178884(self, *args):  # pylint: disable=unused-argument
        # Test a change of format and size where old size is too large for the
        # new format but not for the old one.
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "size": Size('400 MiB'),
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["device"] = device
        kwargs["fstype"] = "prepboot"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

    def _get_size_delta(self, devices=None):
        delta = Size("2 MiB")
        if devices:
            delta += Size("2 MiB") * len(devices)

        return delta


class LVMFactoryTestCase(DeviceFactoryTestCase):
    device_class = LVMLogicalVolumeDevice
    device_type = devicefactory.DEVICE_TYPE_LVM
    factory_class = devicefactory.LVMFactory

    def _validate_factory_device(self, *args, **kwargs):
        super(LVMFactoryTestCase, self)._validate_factory_device(*args, **kwargs)

        device = args[0]

        if kwargs.get("encrypted"):
            container = device.parents[0].container
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

            if pv.encrypted:
                self.assertEqual(pv.parents[0].format.luks_version,
                                 kwargs.get("luks_version", crypto.DEFAULT_LUKS_VERSION))

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    @patch("blivet.formats.mdraid.MDRaidMember.formattable", return_value=True)
    @patch("blivet.formats.mdraid.MDRaidMember.destroyable", return_value=True)
    @patch("blivet.devices.md.MDRaidArrayDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.dm.DMDevice.type_external_dependencies", return_value=set())
    def test_device_factory(self, *args):  # pylint: disable=unused-argument,arguments-differ
        super(LVMFactoryTestCase, self).test_device_factory()

        ##
        # New device
        ##
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "size": Size('400 MiB'),
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}

        if self.encryption_supported:
            # encrypt the PVs
            kwargs["encrypted"] = False
            kwargs["container_encrypted"] = True
            device = self._factory_device(device_type, **kwargs)
            self._validate_factory_device(device, device_type, **kwargs)
            for partition in self.b.partitions:
                self.b.recursive_remove(partition)

        # Add mirroring of PV using MD
        kwargs["container_encrypted"] = False
        kwargs["container_raid_level"] = "raid1"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)
        for partition in self.b.partitions:
            self.b.recursive_remove(partition)

        ##
        # Reconfigure device
        ##

        # Create a basic LVM stack
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "size": Size('800 MiB'),
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        if self.encryption_supported:
            # Encrypt the LV
            # Yes, this is duplicated from the base class but this allows us to
            # test a reconfiguration from encrypted leaf to encrypted container
            # members in the next test.
            kwargs["encrypted"] = True
            kwargs["device"] = device
            kwargs["luks_version"] = "luks1"
            device = self._factory_device(device_type, **kwargs)
            self._validate_factory_device(device, device_type, **kwargs)

            # Decrypt the LV, but encrypt the PVs
            kwargs["encrypted"] = False
            kwargs["container_encrypted"] = True
            kwargs["device"] = device
            device = self._factory_device(device_type, **kwargs)
            self._validate_factory_device(device, device_type, **kwargs)

        # Switch to an encrypted raid0 md pv
        kwargs["container_raid_level"] = "raid0"
        kwargs["device"] = device
        kwargs["size"] = Size("400 MiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # remove encryption from the md pv
        kwargs["container_encrypted"] = False
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # switch back to normal partition pvs
        kwargs["container_raid_level"] = None
        kwargs["device"] = device
        kwargs["size"] = Size("750 MiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # limit the vg to the first disk
        kwargs["disks"] = self.b.disks[:1]
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # expand it back to all disks
        kwargs["disks"] = self.b.disks
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # Change LUKS version
        kwargs["luks_version"] = "luks1"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["luks_version"] = "luks2"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # enable, disable and enable container encryption
        kwargs["container_encrypted"] = True
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["container_encrypted"] = False
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["container_encrypted"] = True
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    def test_factory_defaults(self, *args):  # pylint: disable=unused-argument
        super(LVMFactoryTestCase, self).test_factory_defaults()

    def _get_size_delta(self, devices=None):
        if not devices:
            delta = Size("2 MiB") * len(self.b.disks)
        else:
            delta = Size("4 MiB") * len(self.b.disks) * (len(devices) + 1)

        return delta

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    def test_get_container(self, *args):  # pylint: disable=unused-argument
        for disk in self.b.disks:
            self.b.format_device(disk, get_format("lvmpv"))

        vg = self.b.new_vg(parents=self.b.disks, name="newvg")
        self.b.create_device(vg)
        self.assertEqual(self.b.vgs, [vg])

        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
                                                   size=Size("500 MiB"),
                                                   fstype="xfs")

        # get_container on lvm factory should return the lone non-existent vg
        self.assertEqual(factory.get_container(), vg)

        # get_container should require allow_existing to return an existing vg
        vg.exists = True
        vg._complete = True
        self.assertEqual(factory.get_container(), None)
        self.assertEqual(factory.get_container(allow_existing=True), vg)

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    def test_get_free_disk_space(self, *args):
        super(LVMFactoryTestCase, self).test_get_free_disk_space()

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    def test_normalize_size(self, *args):  # pylint: disable=unused-argument
        super(LVMFactoryTestCase, self).test_normalize_size()

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def test_lv_unique_name(self, *args):  # pylint: disable=unused-argument,arguments-differ
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "size": max(Size("500 MiB"), self.factory_class._device_min_size),
                  "fstype": 'ext4',
                  "mountpoint": "/factorytest",
                  "device_name": "name"}

        device1 = self._factory_device(device_type, **kwargs)
        self.assertEqual(device1.lvname, "name")

        # second device with same name should be automatically renamed
        device2 = self._factory_device(device_type, **kwargs)
        self.assertEqual(device2.lvname, "name00")


class LVMThinPFactoryTestCase(LVMFactoryTestCase):
    # TODO: check that the LV we get is a thin pool
    device_class = LVMLogicalVolumeDevice
    device_type = devicefactory.DEVICE_TYPE_LVM_THINP
    encryption_supported = False
    factory_class = devicefactory.LVMThinPFactory

    def _validate_factory_device(self, *args, **kwargs):
        super(LVMThinPFactoryTestCase, self)._validate_factory_device(*args,
                                                                      **kwargs)
        device = args[0]

        if kwargs.get("encrypted", False):
            thinlv = device.parents[0]
        else:
            thinlv = device

        self.assertTrue(hasattr(thinlv, "pool"))

        return device

    def _get_size_delta(self, devices=None):
        delta = super(LVMThinPFactoryTestCase, self)._get_size_delta(devices=devices)
        if devices:
            # we reserve 20% in the VG for pool to grow
            if sum(d.size for d in devices) * Decimal('0.20') > DEFAULT_THPOOL_RESERVE.min:
                delta += sum(d.size for d in devices) * (DEFAULT_THPOOL_RESERVE.percent / 100)
            else:
                delta += DEFAULT_THPOOL_RESERVE.min

        return delta


class LVMVDOFactoryTestCase(LVMFactoryTestCase):
    device_class = LVMLogicalVolumeDevice
    device_type = devicefactory.DEVICE_TYPE_LVM_VDO
    encryption_supported = False
    _disk_size = Size("10 GiB")  # we need bigger disks for VDO
    factory_class = devicefactory.LVMVDOFactory

    def _validate_factory_device(self, *args, **kwargs):
        super(LVMVDOFactoryTestCase, self)._validate_factory_device(*args,
                                                                    **kwargs)
        device = args[0]

        if kwargs.get("encrypted", False):
            vdolv = device.parents[0]
        else:
            vdolv = device

        self.assertTrue(hasattr(vdolv, "pool"))

        virtual_size = kwargs.get("virtual_size", 0)
        if virtual_size:
            self.assertEqual(vdolv.size, virtual_size)
        else:
            self.assertEqual(vdolv.size, vdolv.pool.size)
        self.assertGreaterEqual(vdolv.size, vdolv.pool.size)

        compression = kwargs.get("compression", True)
        self.assertEqual(vdolv.pool.compression, compression)

        deduplication = kwargs.get("deduplication", True)
        self.assertEqual(vdolv.pool.deduplication, deduplication)

        pool_name = kwargs.get("pool_name", None)
        if pool_name:
            self.assertEqual(vdolv.pool.lvname, pool_name)

        # nodiscard should be always set for VDO LV format
        if vdolv.format.type:
            self.assertTrue(vdolv.format._mkfs_nodiscard)

        return device

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOPoolMixin.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def test_device_factory(self, *args):  # pylint: disable=unused-argument,arguments-differ
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "size": Size("6 GiB"),
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)
        self.b.recursive_remove(device.pool)

        kwargs = {"disks": self.b.disks,
                  "size": Size("6 GiB"),
                  "fstype": 'ext4',
                  "mountpoint": '/factorytest',
                  "pool_name": "vdopool",
                  "deduplication": True,
                  "compression": True}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # change size without specifying virtual_size: both sizes should grow
        kwargs["size"] = Size("8 GiB")
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # change virtual size
        kwargs["virtual_size"] = Size("40 GiB")
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # change virtual size to smaller than size
        kwargs["virtual_size"] = Size("10 GiB")
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # change deduplication and compression
        kwargs["deduplication"] = False
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["compression"] = False
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # rename the pool
        kwargs["pool_name"] = "vdopool2"
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # change fstype
        kwargs["fstype"] = "xfs"

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOPoolMixin.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin.type_external_dependencies", return_value=set())
    def test_factory_defaults(self, *args):  # pylint: disable=unused-argument
        super(LVMVDOFactoryTestCase, self).test_factory_defaults()

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOPoolMixin.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin.type_external_dependencies", return_value=set())
    def test_get_free_disk_space(self, *args):
        super(LVMVDOFactoryTestCase, self).test_get_free_disk_space()

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOPoolMixin.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin.type_external_dependencies", return_value=set())
    def test_normalize_size(self, *args):  # pylint: disable=unused-argument
        super(LVMVDOFactoryTestCase, self).test_normalize_size()

    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.formattable", return_value=True)
    @patch("blivet.formats.lvmpv.LVMPhysicalVolume.destroyable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.devices.lvm.LVMVolumeGroupDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMLogicalVolumeBase.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOPoolMixin.type_external_dependencies", return_value=set())
    @patch("blivet.devices.lvm.LVMVDOLogicalVolumeMixin.type_external_dependencies", return_value=set())
    def test_lv_unique_name(self, *args):  # pylint: disable=unused-argument,arguments-differ
        super(LVMVDOFactoryTestCase, self).test_lv_unique_name()


@patch("blivet.formats.mdraid.MDRaidMember.formattable", return_value=True)
@patch("blivet.formats.mdraid.MDRaidMember.destroyable", return_value=True)
@patch("blivet.devices.md.MDRaidArrayDevice.type_external_dependencies", return_value=set())
class MDFactoryTestCase(DeviceFactoryTestCase):
    device_type = devicefactory.DEVICE_TYPE_MD
    device_class = MDRaidArrayDevice
    factory_class = devicefactory.MDFactory

    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    @patch("blivet.formats.swap.SwapSpace.formattable", return_value=True)
    @patch("blivet.devices.dm.DMDevice.type_external_dependencies", return_value=set())
    def test_device_factory(self, *args):  # pylint: disable=unused-argument,arguments-differ
        # RAID0 across two disks
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "size": Size('1 GiB'),
                  "fstype": 'ext4',
                  "raid_level": "raid0",
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)
        self.b.recursive_remove(device)

        # Encrypt the leaf device
        kwargs["encrypted"] = True
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)
        for partition in self.b.partitions:
            self.b.recursive_remove(partition)

        # RAID1 across two disks
        kwargs = {"disks": self.b.disks,
                  "size": Size('500 MiB'),
                  "fstype": 'ext4',
                  "raid_level": "raid1",
                  "mountpoint": '/factorytest'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)
        for partition in self.b.partitions:
            self.b.recursive_remove(partition)

        ##
        # Reconfigure device
        ##

        # RAID0 across two disks w/ swap
        kwargs = {"disks": self.b.disks,
                  "size": Size('800 MiB'),
                  "fstype": 'swap',
                  "raid_level": "raid0",
                  "label": 'SWAP00'}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # Encrypt the leaf device
        kwargs["encrypted"] = True
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # Change the mountpoint
        kwargs["size"] = Size('400 MiB')
        kwargs["raid_level"] = "raid1"
        kwargs["mountpoint"] = "/a/different/dir"
        kwargs["label"] = "fedora 53 root"
        kwargs["fstype"] = "xfs"
        kwargs["device"] = device
        # kwargs["encrypted"] = False
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # enable, disable and enable container encryption
        kwargs["container_encrypted"] = True
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["container_encrypted"] = False
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        kwargs["container_encrypted"] = True
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

    def _get_size_delta(self, devices=None):
        return Size("2 MiB") * len(self.b.disks)

    def _get_test_factory_args(self):
        return {"raid_level": "raid0"}

    """Note that the following tests postdate the code that they test.
       Therefore, they capture the behavior of the code as it is now,
       not necessarily its intended or its correct behavior. See the
       initial commit message for this file for further details.
    """

    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    def test_mdfactory(self, *args):  # pylint: disable=unused-argument
        factory1 = devicefactory.get_device_factory(self.b,
                                                    devicefactory.DEVICE_TYPE_MD,
                                                    size=Size("1 GiB"),
                                                    raid_level=raid.RAID1)

        factory2 = devicefactory.get_device_factory(self.b,
                                                    devicefactory.DEVICE_TYPE_MD,
                                                    size=Size("1 GiB"),
                                                    raid_level=0)

        with self.assertRaisesRegex(devicefactory.DeviceFactoryError, "must have some RAID level"):
            devicefactory.get_device_factory(
                self.b,
                devicefactory.DEVICE_TYPE_MD,
                size=Size("1 GiB"))

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


# we use stratis tools to predict metadata use so we can't simply "mask" the dependencies here
@unittest.skipUnless(not StratisFilesystemDevice.unavailable_type_dependencies(), "some unsupported device classes required for this test")
class StratisFactoryTestCase(DeviceFactoryTestCase):
    device_class = StratisFilesystemDevice
    device_type = devicefactory.DEVICE_TYPE_STRATIS
    encryption_supported = False
    factory_class = devicefactory.StratisFactory

    _disk_size = Size("3 GiB")

    # pylint: disable=unused-argument
    def _get_size_delta(self, devices=None):
        """ Return size delta for a specific factory type.

            :keyword devices: list of factory-managed devices or None
            :type devices: list(:class:`blivet.devices.StorageDevice`) or NoneType
        """
        return Size("1.3 GiB")  # huge stratis pool metadata

    def _validate_factory_device(self, *args, **kwargs):
        device = args[0]

        self.assertEqual(device.type, "stratis filesystem")
        self.assertLessEqual(device.size, kwargs.get("size"))
        self.assertTrue(hasattr(device, "pool"))
        self.assertIsNotNone(device.pool)
        self.assertEqual(device.pool.type, "stratis pool")
        self.assertIsNotNone(device.format)
        self.assertEqual(device.format.type, "stratis xfs")
        self.assertEqual(device.format.mountpoint, kwargs.get("mountpoint"))

        if kwargs.get("name"):
            self.assertEqual(device.fsname, kwargs.get("name"))

        self.assertTrue(set(device.disks).issubset(kwargs["disks"]))

        if kwargs.get("container_size"):
            self.assertAlmostEqual(device.pool.size,
                                   kwargs.get("container_size"),
                                   delta=self._get_size_delta())
        else:
            self.assertAlmostEqual(device.pool.size,
                                   device.size,
                                   delta=Size("1.3 GiB"))

        self.assertEqual(device.pool.encrypted, kwargs.get("container_encrypted", False))

        return device

    @patch("blivet.devices.stratis.StratisFilesystemDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.stratis.StratisPoolDevice.type_external_dependencies", return_value=set())
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    @patch("blivet.formats.fs.XFS.formattable", return_value=True)
    def test_device_factory(self, *args):  # pylint: disable=unused-argument,arguments-differ
        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "mountpoint": "/factorytest",
                  "size": Size("2.5 GiB")}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # rename the device
        kwargs["name"] = "stratisfs"
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # new mountpoint
        kwargs["mountpoint"] = "/a/different/dir"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # resize the device
        kwargs["size"] = Size("4 GiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # resize the device down
        kwargs["size"] = Size("3 GiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # change container size
        kwargs = {"disks": self.b.disks,
                  "mountpoint": "/factorytest",
                  "container_size": Size("5 GiB"),
                  "size": Size("2.5 GiB")}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # enable encryption on the container
        kwargs["container_encrypted"] = True
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # disable encryption on the container
        kwargs["container_encrypted"] = False
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

    @patch("blivet.devices.stratis.StratisFilesystemDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.stratis.StratisPoolDevice.type_external_dependencies", return_value=set())
    def test_normalize_size(self, *args):  # pylint: disable=unused-argument
        super(StratisFactoryTestCase, self).test_normalize_size()

    @patch("blivet.devices.stratis.StratisFilesystemDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.stratis.StratisPoolDevice.type_external_dependencies", return_value=set())
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    def test_get_free_disk_space(self, *args):  # pylint: disable=unused-argument
        # get_free_disk_space should return the total free space on disks
        kwargs = self._get_test_factory_args()
        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
                                                   disks=self.b.disks,
                                                   **kwargs)
        # disks contain empty disklabels, so free space is sum of disk sizes
        self.assertAlmostEqual(factory._get_free_disk_space(),
                               sum(d.size for d in self.b.disks),
                               delta=self._get_size_delta())

        factory.configure()
        factory = devicefactory.get_device_factory(self.b,
                                                   self.device_type,
                                                   disks=self.b.disks,
                                                   **kwargs)
        # default container size policy for Stratis factory is SIZE_POLICY_MAX so there should
        # be (almost) no free space on the disks
        self.assertAlmostEqual(factory._get_free_disk_space(),
                               Size("2 MiB"),
                               delta=self._get_size_delta())


class BlivetFactoryTestCase(DeviceFactoryTestCase):
    device_class = BTRFSVolumeDevice
    device_type = devicefactory.DEVICE_TYPE_BTRFS
    encryption_supported = False
    factory_class = devicefactory.BTRFSFactory

    def tearDown(self):
        blivet.flags.flags.btrfs_compression = None
        return super().tearDown()

    # pylint: disable=unused-argument
    def _get_size_delta(self, devices=None):
        """ Return size delta for a specific factory type.

            :keyword devices: list of factory-managed devices or None
            :type devices: list(:class:`blivet.devices.StorageDevice`) or NoneType
        """
        return Size("16 MiB")

    def _get_test_factory_args(self):
        return {"container_raid_level": "single"}

    def _validate_factory_device(self, *args, **kwargs):
        device = args[0]

        self.assertEqual(device.type, "btrfs subvolume")
        self.assertLessEqual(device.size, kwargs.get("size"))
        self.assertIsNotNone(device.format)
        self.assertEqual(device.format.type, "btrfs")
        self.assertEqual(device.format.mountpoint, kwargs.get("mountpoint"))

        if kwargs.get("name"):
            self.assertEqual(device.name, kwargs.get("name"))

        self.assertTrue(set(device.disks).issubset(kwargs["disks"]))

        self.assertEqual(device.volume.encrypted, kwargs.get("container_encrypted", False))

        if blivet.flags.flags.btrfs_compression:
            self.assertIn("compress=%s" % blivet.flags.flags.btrfs_compression,
                          device.format.mountopts)

        return device

    @patch("blivet.devices.btrfs.BTRFSVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.btrfs.BTRFSSubVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.BTRFS.formattable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    def test_device_factory(self, *args):  # pylint: disable=unused-argument,arguments-differ

        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "mountpoint": "/factorytest",
                  "size": Size("2.5 GiB")}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # rename the device
        kwargs["name"] = "btrfsroot"
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # new mountpoint
        kwargs["mountpoint"] = "/a/different/dir"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # resize the device
        kwargs["size"] = Size("4 GiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # resize the device down
        kwargs["size"] = Size("3 GiB")
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # enable encryption on the container
        kwargs["container_encrypted"] = True
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # disable encryption on the container
        kwargs["container_encrypted"] = False
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

    @patch("blivet.devices.btrfs.BTRFSVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.btrfs.BTRFSSubVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.BTRFS.formattable", return_value=True)
    def test_normalize_size(self, *args):  # pylint: disable=unused-argument
        super(BlivetFactoryTestCase, self).test_normalize_size()

    @patch("blivet.devices.btrfs.BTRFSVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.btrfs.BTRFSSubVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.BTRFS.formattable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    def test_get_free_disk_space(self, *args):  # pylint: disable=unused-argument
        super(BlivetFactoryTestCase, self).test_get_free_disk_space()

    @patch("blivet.devices.btrfs.BTRFSVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.btrfs.BTRFSSubVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.BTRFS.formattable", return_value=True)
    @patch("blivet.static_data.lvm_info.blockdev.lvm.lvs", return_value=[])
    def test_btrfs_mount_opts(self, *args):  # pylint: disable=unused-argument,arguments-differ
        blivet.flags.flags.btrfs_compression = "zstd:1"

        device_type = self.device_type
        kwargs = {"disks": self.b.disks,
                  "mountpoint": "/factorytest",
                  "size": Size("2.5 GiB")}
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # rename the device
        kwargs["name"] = "btrfsroot"
        kwargs["device"] = device
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

        # new mountpoint
        kwargs["mountpoint"] = "/a/different/dir"
        device = self._factory_device(device_type, **kwargs)
        self._validate_factory_device(device, device_type, **kwargs)

    @patch("blivet.devices.btrfs.BTRFSVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.devices.btrfs.BTRFSSubVolumeDevice.type_external_dependencies", return_value=set())
    @patch("blivet.formats.fs.BTRFS.formattable", return_value=True)
    def test_factory_defaults(self, *args):
        super(BlivetFactoryTestCase, self).test_factory_defaults()
