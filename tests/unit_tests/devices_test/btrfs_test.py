import unittest
from unittest.mock import patch, PropertyMock

import blivet

from blivet.devices import StorageDevice
from blivet.devices import BTRFSVolumeDevice
from blivet.devices import BTRFSSubVolumeDevice
from blivet.devicelibs import btrfs
from blivet.size import Size
from blivet.formats.fs import BTRFS


DEVICE_CLASSES = [
    BTRFSVolumeDevice,
    BTRFSSubVolumeDevice,
    StorageDevice
]


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class BlivetNewBtrfsVolumeDeviceTest(unittest.TestCase):
    def test_new_btrfs(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=False)

        b.devicetree._add_device(bd)

        with patch("blivet.devicetree.DeviceTree.names", []):
            vol = b.new_btrfs(name="testvolume", parents=[bd])
        self.assertEqual(vol.name, "testvolume")
        self.assertEqual(vol.size, bd.size)
        self.assertIsNotNone(vol.format)
        self.assertEqual(vol.format.type, "btrfs")

        b.create_device(vol)

        with patch("blivet.devices.btrfs.blockdev.btrfs") as blockdev:
            with patch.object(vol, "_pre_create"):
                with patch.object(vol, "_post_create"):
                    vol.create()
                    blockdev.create_volume.assert_called()
                    args = blockdev.create_volume.call_args.args
                    self.assertEqual(args, (['/dev/bd1'],))
                    kwargs = blockdev.create_volume.call_args.kwargs
                    self.assertEqual(kwargs['label'], 'testvolume')
                    self.assertEqual(kwargs['data_level'], None)
                    self.assertEqual(kwargs['md_level'], None)

                    extra = kwargs['extra']
                    self.assertTrue(extra)
                    self.assertEqual(extra[0].opt, "-U")
                    self.assertEqual(extra[0].val, vol.uuid)

        with patch("blivet.devicetree.DeviceTree.names", []):
            sub = b.new_btrfs_sub_volume(name="testsub", parents=[vol])

        self.assertIsNotNone(sub.format)
        self.assertEqual(sub.format.type, "btrfs")
        self.assertEqual(sub.size, vol.size)
        self.assertEqual(sub.volume, vol)

    def test_new_btrfs_options(self):
        b = blivet.Blivet()
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=False)

        b.devicetree._add_device(bd)

        with patch("blivet.devicetree.DeviceTree.names", []):
            vol = b.new_btrfs(name="testvolume", parents=[bd], create_options="--csum xxhash")

        b.create_device(vol)

        with patch("blivet.devices.btrfs.blockdev.btrfs") as blockdev:
            with patch.object(vol, "_pre_create"):
                with patch.object(vol, "_post_create"):
                    vol.create()
                    blockdev.create_volume.assert_called()
                    args = blockdev.create_volume.call_args.args
                    self.assertEqual(args, (['/dev/bd1'],))
                    kwargs = blockdev.create_volume.call_args.kwargs
                    self.assertEqual(kwargs['label'], 'testvolume')
                    self.assertEqual(kwargs['data_level'], None)
                    self.assertEqual(kwargs['md_level'], None)

                    extra = kwargs['extra']
                    self.assertTrue(extra)
                    self.assertEqual(extra[0].opt, "-U")
                    self.assertEqual(extra[0].val, vol.uuid)
                    self.assertEqual(extra[1].opt, "--csum")
                    self.assertEqual(extra[2].opt, "xxhash")

    def test_device_id(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=False)

        vol = BTRFSVolumeDevice("testvolume", parents=[bd])
        self.assertEqual(vol.device_id, "BTRFS-" + vol.uuid)

        sub = BTRFSSubVolumeDevice("testsub", parents=[vol])
        self.assertEqual(sub.device_id, "BTRFS-" + vol.uuid + "-testsub")

    def test_btrfs_list_subvolumes(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=True)

        vol = BTRFSVolumeDevice("testvolume", parents=[bd])

        with patch("blivet.devices.btrfs.blockdev.btrfs") as blockdev:
            # not mounted and flags.auto_dev_updates is not set
            vol.list_subvolumes()
            blockdev.list_subvolumes.assert_not_called()
            blockdev.get_default_subvolume_id.assert_not_called()

            # mounted
            with patch.object(BTRFS, "system_mountpoint", new=PropertyMock(return_value='/fake/mountpoint')):
                vol.list_subvolumes()
                blockdev.list_subvolumes.assert_called_with("/fake/mountpoint", snapshots_only=False)
                blockdev.get_default_subvolume_id.assert_called_with("/fake/mountpoint")

                # mounted but libblockdev btrfs plugin not available
                blockdev.reset_mock()
                with patch("blivet.devices.btrfs.avail_plugs", new={"lvm"}):
                    vol.list_subvolumes()
                    blockdev.list_subvolumes.assert_not_called()
                    blockdev.get_default_subvolume_id.assert_not_called()

    def test_btrfs_update_raid_levels(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=True)

        vol = BTRFSVolumeDevice("testvolume", parents=[bd], exists=True)
        self.assertIsNone(vol.data_level)
        self.assertIsNone(vol.metadata_level)

        with patch("blivet.devices.btrfs.btrfs.get_raid_levels", return_value=("single", "dup")):
            vol._update_raid_levels()

        self.assertEqual(vol.data_level.name, "single")
        self.assertEqual(vol.metadata_level.name, "dup")

    def test_btrfs_update_raid_levels_raid56(self):
        bd = StorageDevice("bd1", fmt=blivet.formats.get_format("btrfs"),
                           size=Size("2 GiB"), exists=True)

        vol = BTRFSVolumeDevice("testvolume", parents=[bd], exists=True)

        with patch("blivet.devices.btrfs.btrfs.get_raid_levels", return_value=("raid5", "raid6")):
            vol._update_raid_levels()

        self.assertEqual(vol.data_level.name, "raid5")
        self.assertEqual(vol.metadata_level.name, "raid6")


@unittest.skipUnless(not any(x.unavailable_type_dependencies() for x in DEVICE_CLASSES), "some unsupported device classes required for this test")
class BtrfsGetRaidLevelsTest(unittest.TestCase):
    def test_get_raid_levels(self):
        def fake_isdir(path):
            dirs = {"/sys/fs/btrfs/fake-uuid/allocation",
                    "/sys/fs/btrfs/fake-uuid/allocation/data",
                    "/sys/fs/btrfs/fake-uuid/allocation/data/raid1",
                    "/sys/fs/btrfs/fake-uuid/allocation/metadata",
                    "/sys/fs/btrfs/fake-uuid/allocation/metadata/dup"}
            return path in dirs

        with patch("blivet.devicelibs.btrfs.os.path.isdir", side_effect=fake_isdir):
            with patch("blivet.devicelibs.btrfs.os.listdir") as mock_listdir:
                mock_listdir.side_effect = lambda path: {
                    "/sys/fs/btrfs/fake-uuid/allocation/data": ["bytes_used", "raid1", "total_bytes"],
                    "/sys/fs/btrfs/fake-uuid/allocation/metadata": ["bytes_used", "dup", "total_bytes"],
                }.get(path, [])
                data_level, metadata_level = btrfs.get_raid_levels("fake-uuid")

        self.assertEqual(data_level, "raid1")
        self.assertEqual(metadata_level, "dup")

    def test_get_raid_levels_raid1c(self):
        def fake_isdir(path):
            dirs = {"/sys/fs/btrfs/fake-uuid/allocation",
                    "/sys/fs/btrfs/fake-uuid/allocation/data",
                    "/sys/fs/btrfs/fake-uuid/allocation/data/raid1c3",
                    "/sys/fs/btrfs/fake-uuid/allocation/metadata",
                    "/sys/fs/btrfs/fake-uuid/allocation/metadata/raid1c4"}
            return path in dirs

        with patch("blivet.devicelibs.btrfs.os.path.isdir", side_effect=fake_isdir):
            with patch("blivet.devicelibs.btrfs.os.listdir") as mock_listdir:
                mock_listdir.side_effect = lambda path: {
                    "/sys/fs/btrfs/fake-uuid/allocation/data": ["raid1c3", "total_bytes"],
                    "/sys/fs/btrfs/fake-uuid/allocation/metadata": ["raid1c4", "total_bytes"],
                }.get(path, [])
                data_level, metadata_level = btrfs.get_raid_levels("fake-uuid")

        self.assertEqual(data_level, "raid1")
        self.assertEqual(metadata_level, "raid1")

        with patch("blivet.devicelibs.btrfs.os.path.isdir", return_value=False):
            data_level, metadata_level = btrfs.get_raid_levels("nonexistent-uuid")

        self.assertIsNone(data_level)
        self.assertIsNone(metadata_level)
