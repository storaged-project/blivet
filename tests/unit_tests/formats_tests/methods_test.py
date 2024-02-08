import unittest
from unittest.mock import patch, sentinel, PropertyMock

from blivet.errors import DeviceFormatError
from blivet.formats import DeviceFormat
from blivet.formats.luks import LUKS
from blivet.formats.lvmpv import LVMPhysicalVolume
from blivet.formats.mdraid import MDRaidMember
from blivet.formats.swap import SwapSpace
from blivet.formats.fs import EFIFS, Ext4FS, XFS


class FormatMethodsTestCase(unittest.TestCase):
    format_class = DeviceFormat

    def __init__(self, methodName='runTest'):
        super(FormatMethodsTestCase, self).__init__(methodName=methodName)
        self.patchers = dict()
        self.patches = dict()

    #
    # patch setup
    #
    def set_patches(self):
        # self.patchers["update_sysfs_path"] = patch.object(self.device, "update_sysfs_path")
        self.patchers["status"] = patch.object(self.format_class, "status", new=PropertyMock(return_value=False))
        self.patchers["os"] = patch("blivet.formats.os")

    def start_patches(self):
        for target, patcher in self.patchers.items():
            self.patches[target] = patcher.start()

    def stop_patches(self):
        for target, patcher in self.patchers.items():
            patcher.stop()
            del self.patches[target]

    #
    # device constructor arguments
    #
    def _ctor_args(self):
        return []

    def _ctor_kwargs(self):
        return {"device": "/fake/device"}

    def setUp(self):
        self.format = self.format_class(*self._ctor_args(), **self._ctor_kwargs())

        self.set_patches()
        self.start_patches()
        self.addCleanup(self.stop_patches)

    # some formats use os from multiple modules, eg: fs
    def set_os_path_exists(self, value):
        self.patches["os"].path.exists.return_value = value

    #
    # tests for format backend usage
    #
    def _test_create_backend(self):
        pass

    def _test_destroy_backend(self):
        with patch("blivet.formats.blockdev") as blockdev:
            blockdev.fs.clean.return_value = True
            self.format.exists = True
            self.format.destroy()
            self.assertFalse(self.format.exists)
            blockdev.fs.clean.assert_called_with(self.format.device, force=True)

    def _test_setup_backend(self):
        pass

    def _test_teardown_backend(self):
        pass

    #
    # format method tests
    #
    def test_create(self):
        # fmt cannot exist
        self.format.exists = True
        with patch.object(self.format, "_create"):
            self.set_os_path_exists(True)
            self.assertRaisesRegex(DeviceFormatError, "format already exists", self.format.create)
            self.assertFalse(self.format._create.called)  # pylint: disable=no-member
        self.format.exists = False

        # device must be accessible
        with patch.object(self.format, "_create"):
            # device must be accessible
            self.set_os_path_exists(False)
            self.assertRaisesRegex(DeviceFormatError, "invalid device specification", self.format.create)
            self.assertFalse(self.format._create.called)  # pylint: disable=no-member
        self.set_os_path_exists(True)

        # _pre_create raises -> no _create
        self.assertFalse(self.format.exists)

        # pylint: disable=unused-argument
        def _fail(*args, **kwargs):
            raise RuntimeError("problems")

        with patch.object(self.format, "_create"):
            with patch.object(self.format, "_pre_create") as m:
                m.side_effect = _fail
                self.assertRaisesRegex(RuntimeError, "problems", self.format.create)
                self.assertFalse(self.format._create.called)  # pylint: disable=no-member
                self.assertFalse(self.format.exists)

        # _create raises -> no _post_create -> exists == False
        with patch.object(self.format, "_create") as m:
            m.side_effect = _fail
            self.assertRaisesRegex(RuntimeError, "problems", self.format.create)
            self.assertTrue(self.format._create.called)  # pylint: disable=no-member
            self.assertFalse(self.format.exists)

        # _create succeeds -> make sure _post_create sets existence
        with patch.object(self.format, "_create"):
            with patch.object(self.format, "_post_create"):
                self.format.create()
                self.assertTrue(self.format._create.called)  # pylint: disable=no-member
                self.assertFalse(self.format.exists)

        # _post_create sets exists to True
        with patch.object(self.format, "_create"):
            self.format.create()
            self.assertTrue(self.format._create.called)  # pylint: disable=no-member
            self.assertTrue(self.format.exists)

        self._test_create_backend()

    def test_destroy(self):
        # fmt must exist
        self.format.exists = False
        with patch.object(self.format, "_destroy"):
            self.patches["os"].access.return_value = True
            self.assertRaisesRegex(DeviceFormatError, "has not been created", self.format.destroy)
            self.assertFalse(self.format._destroy.called)  # pylint: disable=no-member

        self.format.exists = True

        # format must be inactive
        with patch.object(self.format, "_destroy"):
            self.patches["status"].return_value = True
            self.assertRaisesRegex(DeviceFormatError, "is active", self.format.destroy)
            self.assertFalse(self.format._destroy.called)  # pylint: disable=no-member

        # device must be accessible
        with patch.object(self.format, "_destroy"):
            self.patches["os"].access.return_value = False
            self.patches["status"].return_value = False
            self.assertRaisesRegex(DeviceFormatError, "device path does not exist", self.format.destroy)
            self.assertFalse(self.format._destroy.called)  # pylint: disable=no-member

        self.patches["os"].access.return_value = True
        # _pre_destroy raises -> no _create

        # pylint: disable=unused-argument
        def _fail(*args, **kwargs):
            raise RuntimeError("problems")

        self.assertTrue(self.format.exists)
        with patch.object(self.format, "_destroy"):
            with patch.object(self.format, "_pre_destroy") as m:
                m.side_effect = _fail
                self.assertRaisesRegex(RuntimeError, "problems", self.format.destroy)
                self.assertFalse(self.format._destroy.called)  # pylint: disable=no-member
                self.assertTrue(self.format.exists)

        # _destroy raises -> no _post_destroy -> exists == True
        with patch.object(self.format, "_destroy") as m:
            m.side_effect = _fail
            self.assertRaisesRegex(RuntimeError, "problems", self.format.destroy)
            self.assertTrue(self.format._destroy.called)  # pylint: disable=no-member
            self.assertTrue(self.format.exists)

        # _destroy succeeds -> _post_destroy is what updates existence
        with patch.object(self.format, "_destroy"):
            with patch.object(self.format, "_post_destroy"):
                self.format.destroy()
                self.assertTrue(self.format._destroy.called)  # pylint: disable=no-member
                self.assertTrue(self.format.exists)

        # _post_destroy set exists to False
        with patch.object(self.format, "_destroy"):
            self.format.destroy()
            self.assertTrue(self.format._destroy.called)  # pylint: disable=no-member
            self.assertFalse(self.format.exists)

        self._test_destroy_backend()

    def test_setup(self):
        # fmt must exist
        self.format.exists = False
        with patch.object(self.format, "_setup"):
            self.set_os_path_exists(True)
            self.assertRaisesRegex(DeviceFormatError, "has not been created", self.format.setup)
            # _pre_setup raises exn -> no _setup
            self.assertFalse(self.format._setup.called)  # pylint: disable=no-member
        self.format.exists = True

        # device must be accessible
        with patch.object(self.format, "_setup"):
            self.set_os_path_exists(False)
            self.assertRaisesRegex(DeviceFormatError, "invalid|does not exist", self.format.setup)
            # _pre_setup raises exn -> no _setup
            self.assertFalse(self.format._setup.called)  # pylint: disable=no-member

        # _pre_setup returns False -> no _setup
        with patch.object(self.format, "_setup"):
            self.set_os_path_exists(True)
            self.patches["status"].return_value = True
            self.format.setup()
            self.assertEqual(self.format._setup.called, isinstance(self, FSMethodsTestCase))  # pylint: disable=no-member

        # _setup fails -> no _post_setup
        self.patches["status"].return_value = False

        # pylint: disable=unused-argument
        def _fail(*args, **kwargs):
            raise RuntimeError("problems")

        with patch.object(self.format, "_setup", side_effect=_fail):
            with patch.object(self.format, "_post_setup"):
                self.assertRaisesRegex(RuntimeError, "problems", self.format.setup)
                self.assertFalse(self.format._post_setup.called)  # pylint: disable=no-member

        # _setup succeeds -> _post_setup
        with patch.object(self.format, "_setup"):
            with patch.object(self.format, "_post_setup"):
                self.format.setup()
                self.assertTrue(self.format._post_setup.called)  # pylint: disable=no-member

        self._test_setup_backend()

    def test_teardown(self):
        # device must be accessible

        # fmt must exist
        self.format.exists = False
        with patch.object(self.format, "_teardown"):
            self.set_os_path_exists(True)
            self.assertRaisesRegex(DeviceFormatError, "has not been created", self.format.teardown)
            self.assertFalse(self.format._teardown.called)  # pylint: disable=no-member
        self.format.exists = True

        # FIXME -- _pre_teardown should be checking for an accessible device
        # device must be accessible
        # with patch.object(self.format, "_teardown"):
        #    self.set_os_path_exists(False)
        #    self.assertRaisesRegex(DeviceFormatError, "invalid device specification", self.format.teardown)
        #    self.assertFalse(self.format._teardown.called)  # pylint: disable=no-member

        # _teardown fails -> no _post_teardown
        self.patches["status"].return_value = True

        # pylint: disable=unused-argument
        def _fail(*args, **kwargs):
            raise RuntimeError("problems")

        with patch.object(self.format, "_teardown", side_effect=_fail):
            with patch.object(self.format, "_post_teardown"):
                self.assertRaisesRegex(RuntimeError, "problems", self.format.teardown)
                self.assertFalse(self.format._post_teardown.called)  # pylint: disable=no-member

        # _teardown succeeds -> _post_teardown
        with patch.object(self.format, "_teardown"):
            with patch.object(self.format, "_post_teardown"):
                self.format.teardown()
                self.assertTrue(self.format._post_teardown.called)  # pylint: disable=no-member

        self._test_teardown_backend()


class FSMethodsTestCase(FormatMethodsTestCase):
    format_class = None

    def set_patches(self):
        super(FSMethodsTestCase, self).set_patches()
        self.patchers["udev"] = patch("blivet.formats.fs.udev")
        self.patchers["util"] = patch("blivet.formats.fs.util")
        self.patchers["system_mountpoint"] = patch.object(self.format_class,
                                                          "system_mountpoint",
                                                          new=PropertyMock(return_value='/fake/mountpoint'))
        self.patchers["fs_os"] = patch("blivet.formats.fs.os")

    def setUp(self):
        if self.format_class is None:
            return unittest.skip('abstract base class')

        super(FSMethodsTestCase, self).setUp()

    def set_os_path_exists(self, value):
        super(FSMethodsTestCase, self).set_os_path_exists(value)
        self.patches["fs_os"].path.exists.return_value = value

    def _test_create_backend(self):
        with patch.object(self.format, "_mkfs"):
            self.format.exists = False
            self.format.create()
            # pylint: disable=no-member
            self.format._mkfs.do_task.assert_called_with(
                options=None,
                label=not self.format.relabels(),
                set_uuid=self.format.can_set_uuid(),
                nodiscard=self.format.can_nodiscard()
            )

    def _test_setup_backend(self):
        with patch.object(self.format, "_mount"):
            self.patches["fs_os"].path.normpath.return_value = sentinel.mountpoint
            self.format.setup()
            self.format._mount.do_task.assert_called_with(sentinel.mountpoint, options="")  # pylint: disable=no-member

    def _test_teardown_backend(self):
        self.patches["util"].umount.return_value = 0
        self.format.teardown()
        self.patches["util"].umount.assert_called_with(self.format.system_mountpoint)  # pylint: disable=no-member

    def test_create(self):
        if self.format_class is None:
            return unittest.skip('abstract base class')
        super(FSMethodsTestCase, self).test_create()

    def test_destroy(self):
        if self.format_class is None:
            return unittest.skip('abstract base class')
        super(FSMethodsTestCase, self).test_destroy()

    def test_setup(self):
        if self.format_class is None:
            return unittest.skip('abstract base class')
        self.format.mountpoint = "/fake/mountpoint"
        super(FSMethodsTestCase, self).test_setup()

    def test_teardown(self):
        if self.format_class is None:
            return unittest.skip('abstract base class')

        super(FSMethodsTestCase, self).test_teardown()


class Ext4FSMethodsTestCase(FSMethodsTestCase):
    format_class = Ext4FS


class EFIFSMethodsTestCase(FSMethodsTestCase):
    format_class = EFIFS


class LUKSMethodsTestCase(FormatMethodsTestCase):
    format_class = LUKS

    def set_patches(self):
        super(LUKSMethodsTestCase, self).set_patches()
        self.patchers["configured"] = patch.object(self.format_class, "configured", new=PropertyMock(return_value=True))
        self.patchers["has_key"] = patch.object(self.format_class, "has_key", new=PropertyMock(return_value=True))
        self.patchers["blockdev"] = patch("blivet.formats.luks.blockdev")

    def _test_create_backend(self):
        self.format.exists = False
        self.format.passphrase = "passphrase"
        with patch("blivet.devicelibs.crypto.get_optimal_luks_sector_size", return_value=512):
            with patch("blivet.devicelibs.crypto.is_fips_enabled", return_value=False):
                self.format.create()
        self.assertTrue(self.patches["blockdev"].crypto.luks_format.called)  # pylint: disable=no-member

    def _test_setup_backend(self):
        self.format.passphrase = "passphrase"
        self.format.setup()
        self.assertTrue(self.patches["blockdev"].crypto.luks_open.called)

    def _test_teardown_backend(self):
        self.format.teardown()
        self.assertTrue(self.patches["blockdev"].crypto.luks_close.called)


class LVMPhysicalVolumeMethodsTestCase(FormatMethodsTestCase):
    format_class = LVMPhysicalVolume

    def set_patches(self):
        super(LVMPhysicalVolumeMethodsTestCase, self).set_patches()
        self.patchers["blockdev"] = patch("blivet.formats.lvmpv.blockdev")
        self.patchers["vgs_info"] = patch("blivet.formats.lvmpv.vgs_info")

    def _test_destroy_backend(self):
        self.format.exists = True
        self.format.destroy()
        self.assertFalse(self.format.exists)
        self.patches["blockdev"].lvm.pvremove.assert_called_with(self.format.device)

    def _test_create_backend(self):
        self.patches["blockdev"].ExtraArg.new.return_value = sentinel.extra_arg
        self.format.exists = False
        self.format.create()
        self.patches["blockdev"].lvm.pvcreate.assert_called_with(self.format.device,
                                                                 data_alignment=self.format.data_alignment,  # pylint: disable=no-member
                                                                 extra=[sentinel.extra_arg])


class MDRaidMemberMethodsTestCase(FormatMethodsTestCase):
    format_class = MDRaidMember

    def set_patches(self):
        super(MDRaidMemberMethodsTestCase, self).set_patches()
        self.patchers["blockdev"] = patch("blivet.formats.mdraid.blockdev")

    def _test_destroy_backend(self):
        self.format.exists = True
        self.format.destroy()
        self.assertFalse(self.format.exists)
        self.patches["blockdev"].md.destroy.assert_called_with(self.format.device)


class SwapMethodsTestCase(FormatMethodsTestCase):
    format_class = SwapSpace

    def set_patches(self):
        super(SwapMethodsTestCase, self).set_patches()
        self.patchers["blockdev"] = patch("blivet.formats.swap.blockdev")

    def _test_create_backend(self):
        self.format.exists = False
        self.format.create()
        self.patches["blockdev"].swap.mkswap.assert_called_with(self.format.device,
                                                                label=self.format.label,  # pylint: disable=no-member
                                                                uuid=self.format.uuid)

    def _test_setup_backend(self):
        self.format.setup()
        self.patches["blockdev"].swap.swapon.assert_called_with(self.format.device,
                                                                priority=self.format.priority)  # pylint: disable=no-member

    def _test_teardown_backend(self):
        self.format.teardown()
        self.patches["blockdev"].swap.swapoff.assert_called_with(self.format.device)


class XFSMethodsTestCase(FSMethodsTestCase):
    format_class = XFS
