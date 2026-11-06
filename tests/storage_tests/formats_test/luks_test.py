import os
import glob
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import blivet
from blivet.formats.luks import LUKS, Integrity, LUKS2PBKDFArgs
from blivet.devicelibs import crypto
from blivet.errors import LUKSError
from blivet.size import Size
from blivet import arch, blockdev, udev
from blivet.devices import StorageDevice
from blivet.devicetree import DeviceTree
from blivet.populator.helpers.luks import LUKSFormatPopulator
from blivet.populator.helpers.formatpopulator import FormatPopulator
from blivet.tasks import availability
import blivet.static_data

from . import loopbackedtestcase
from ..storagetestcase import StorageTestCase


class LUKSTestCase(loopbackedtestcase.LoopBackedTestCase):

    version = None

    def __init__(self, methodName='run_test'):
        super().__init__(methodName=methodName, device_spec=[Size("100 MiB")])
        self.fmt = LUKS(passphrase="password", luks_version=self.version)

    def test_size(self):
        self.fmt.device = self.loop_devices[0]

        # create and open the luks format
        self.fmt.create()
        self.fmt.setup()
        self.addCleanup(self._luks_close)

        # without update_size_info size should be 0
        self.assertEqual(self.fmt.current_size, Size(0))

        # get current size
        self.fmt.update_size_info()
        self.assertGreater(self.fmt.current_size, Size(0))

    def test_resize(self):
        self.fmt.device = self.loop_devices[0]

        # create and open the luks format
        self.fmt.create()
        self.fmt.setup()
        self.addCleanup(self._luks_close)

        # get current size to make format resizable
        self.assertFalse(self.fmt.resizable)
        self.fmt.update_size_info()
        self.assertTrue(self.fmt.resizable)

        # resize the format
        new_size = Size("50 MiB")
        self.fmt.target_size = new_size
        self.fmt.do_resize()

        # get current size
        self.fmt.update_size_info()
        self.assertEqual(self.fmt.current_size, new_size)

    def test_map_name(self):
        self.fmt.device = self.loop_devices[0]

        # create and open the luks format
        self.fmt.create()
        self.fmt.setup()
        self.addCleanup(self._luks_close)

        self.assertEqual(self.fmt.map_name, "luks-%s" % self.fmt.uuid)
        self.assertTrue(self.fmt.status)

        self.fmt.teardown()
        self.assertFalse(self.fmt.status)

    def test_add_remove_passphrase(self):
        self.fmt.device = self.loop_devices[0]

        # create the luks format
        self.fmt.create()

        # add a new passphrase
        self.fmt.add_passphrase("password2")

        # we should now be able to setup the format using this passphrase
        self.fmt.passphrase = "password2"
        self.fmt.setup()
        self.fmt.teardown()

        # remove the original passphrase
        self.fmt.remove_passphrase("password")
        self.fmt.passphrase = None

        # now setup should fail
        with self.assertRaises(LUKSError):
            self.fmt.setup()

        # setup with the new passphrase should still be possible
        self.fmt.passphrase = "password2"
        self.fmt.setup()
        self.fmt.teardown()

    def test_setup_keyfile(self):
        self.fmt.device = self.loop_devices[0]

        with tempfile.NamedTemporaryFile(prefix="blivet_test") as temp:
            temp.write(b"password2")
            temp.flush()

            # create the luks format with both passphrase and keyfile
            self.fmt.key_file = temp.name
            self.fmt.create()

            # open first with just password
            self.fmt.key_file = None
            self.fmt.setup()
            self.fmt.teardown()

            # now with keyfile
            self.fmt.key_file = temp.name
            self.fmt.passphrase = None
            self.fmt.setup()
            self.fmt.teardown()

    def _luks_close(self):
        self.fmt.teardown()


class LUKSTestCaseLUKS1(LUKSTestCase):
    version = "luks1"


class LUKSTestCaseLUKS2(LUKSTestCase):
    version = "luks2"


# prevent unittest from running the "abstract" test case
del LUKSTestCase


@unittest.skipUnless(arch.is_s390() and availability.BLOCKDEV_S390_PLUGIN_PAES.available and
                     os.path.exists("/dev/pkey") and glob.glob("/sys/bus/ap/devices/card*/*.*"),
                     "requires IBM Z with PAES support and crypto adapters")
class PAESLUKSTestCase(loopbackedtestcase.LoopBackedTestCase):
    def __init__(self, methodName="run_test"):
        super().__init__(methodName=methodName, device_spec=[Size("100 MiB"), Size("100 MiB")])

    def _new_format(self, device=None, **kwargs):
        fmt = LUKS(device=device or self.loop_devices[0], cipher=crypto.PAES_CIPHER,
                   passphrase="paes-test-password",
                   pbkdf_args=LUKS2PBKDFArgs(type="pbkdf2", iterations=1000), **kwargs)
        self._register_cleanup(fmt)
        return fmt

    def _register_cleanup(self, fmt):
        # Remember the generated key even when a failing destroy test clears
        # the format's cached name but leaves a repository association behind.
        key_name = fmt._zkey_name

        def cleanup():
            name = fmt._zkey_name or key_name
            try:
                if fmt.exists:
                    fmt.teardown()
                    fmt.destroy()
            finally:
                if name and any(key.name == name for key in blockdev.s390.zkey_list(None)):
                    crypto.remove_secure_key(name)

        self.addCleanup(cleanup)

    def _discover_format(self, device):
        udev.settle()
        data = udev.get_device("/sys/class/block/%s" % os.path.basename(device))
        storage_device = StorageDevice(os.path.basename(device), exists=True)
        helper = LUKSFormatPopulator(DeviceTree(), data, storage_device)
        # Populate actual udev metadata without attempting automatic activation.
        FormatPopulator.run(helper)
        fmt = storage_device.format
        self._register_cleanup(fmt)
        return fmt

    def test_create_discover_destroy(self):
        self._test_create_discover_destroy(dummy_passphrase=False)

    def test_dummy_passphrase(self):
        self._test_create_discover_destroy(dummy_passphrase=True)

    def _test_create_discover_destroy(self, dummy_passphrase):
        fmt = self._new_format(zkey_dummy_passphrase=dummy_passphrase)
        fmt.create()
        self._register_cleanup(fmt)
        self.assertTrue(fmt.pervasive)
        self.assertEqual(fmt.luks_version, "luks2")
        info = crypto.find_secure_key_for_volume(fmt.device)
        self.assertIsNotNone(info)
        self.assertEqual(fmt.key_size, info.secure_key_size * 8)
        self.assertEqual(info.volumes, ["%s:%s" % (crypto.luks_uuid_path(fmt.uuid), fmt.map_name)])
        fmt.setup()
        self.assertTrue(fmt.status)
        fmt.teardown()
        if dummy_passphrase:
            self.assertTrue(info.dummy_passphrase)
            # Check interoperability with zkey's generated open command, which
            # uses the repository dummy passphrase, not the user's passphrase.
            result = subprocess.run(["zkey", "cryptsetup", "--volumes", crypto.luks_uuid_path(fmt.uuid),
                                     "--open", "--run", "--batch-mode"],
                                    capture_output=True, text=True, timeout=120, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(fmt.status)
            fmt.teardown()
        discovered = self._discover_format(fmt.device)
        self.assertTrue(discovered.pervasive)
        self.assertEqual(discovered.uuid, fmt.uuid)
        self.assertEqual(discovered._zkey_name, fmt._zkey_name)
        discovered.passphrase = "paes-test-password"
        discovered.setup()
        discovered.teardown()
        discovered.destroy()
        fmt.exists = False
        self.assertIsNone(crypto.find_secure_key_for_volume(fmt.device))

    def test_sector_size(self):
        fmt = self._new_format(luks_sector_size=4096)
        fmt.create()
        self.assertEqual(blockdev.crypto.luks_info(fmt.device).sector_size, 4096)
        self.assertEqual(crypto.find_secure_key_for_volume(fmt.device).sector_size, 4096)

    def test_shared_key_destroy_recreate(self):
        fmt = self._new_format()
        fmt.create()
        self._register_cleanup(fmt)
        info = crypto.find_secure_key_for_volume(fmt.device)
        shared = self._new_format(device=self.loop_devices[1])
        key = crypto.KeyslotContext(volume_key=crypto.read_secure_key(info.key_file_name))
        blockdev.crypto.luks_format_volume_key(
            shared.device, cipher=crypto.PAES_CIPHER, key_size=info.secure_key_size * 8,
            context=fmt.contexts.get_context()._context, volume_key=key._context,
            extra=blockdev.CryptoLUKSExtra(pbkdf=blockdev.CryptoLUKSPBKDF(type="pbkdf2", iterations=1000)))
        shared.exists = True
        shared.uuid = blockdev.crypto.luks_info(shared.device).uuid
        udev.settle()
        shared_volume = "%s:%s" % (crypto.luks_uuid_path(shared.uuid), shared.map_name)
        crypto.change_secure_key_volumes(info.name, info.volumes + [shared_volume])
        fmt.destroy()
        remaining = crypto.find_secure_key_for_volume(shared.device)
        self.assertEqual(remaining.name, info.name)
        self.assertEqual(remaining.volumes, [shared_volume])
        replacement = self._new_format(device=fmt.device)
        replacement.create()
        replacement.destroy()
        shared.setup()
        shared.teardown()
        shared.destroy()
        self.assertFalse(any(key.name == info.name for key in blockdev.s390.zkey_list(None)))

    def test_device_renumber(self):
        fmt = self._new_format()
        fmt.create()
        self._register_cleanup(fmt)
        name = fmt._zkey_name
        original, backing = self._loop_map[0]
        # Occupy the old minor with private, unrelated storage, then attach the
        # original image at a different minor, as after a reboot/renumbering.
        with tempfile.NamedTemporaryFile(prefix="paes-placeholder-", dir="/var/tmp", delete=False) as placeholder:
            placeholder.truncate(int(Size("100 MiB")))
        self.addCleanup(os.unlink, placeholder.name)
        loopbackedtestcase.remove_loop_dev(original)
        loopbackedtestcase.make_loop_dev(original, placeholder.name)
        moved = loopbackedtestcase.get_free_loop_dev()
        loopbackedtestcase.make_loop_dev(moved, backing)
        fmt.device = moved
        # The placeholder file is cleaned separately, after detaching it.
        self._loop_map[0] = (moved, backing)
        self.addCleanup(loopbackedtestcase.remove_loop_dev, original)
        discovered = self._discover_format(moved)
        self.assertNotEqual(moved, original)
        self.assertEqual(discovered._zkey_name, name)
        discovered.passphrase = "paes-test-password"
        discovered.setup()
        discovered.teardown()
        discovered.destroy()
        fmt.exists = False
        self.assertFalse(any(key.name == name for key in blockdev.s390.zkey_list(None)))

    def test_invalid_additional_keyfile(self):
        fmt = self._new_format()
        fmt.contexts.add_keyfile("/nonexistent/paes-test-keyfile")
        with self.assertRaises(LUKSError):
            fmt.create()
        self.assertFalse(fmt.exists)
        self.assertFalse(blockdev.crypto.device_is_luks(fmt.device))
        self.assertIsNone(crypto.find_secure_key_for_volume(fmt.device))

    def test_partial_creation_rollback(self):
        fmt = self._new_format()
        with patch.object(crypto, "set_verification_pattern", side_effect=LUKSError("injected failure")):
            with self.assertRaisesRegex(LUKSError, "injected failure"):
                fmt.create()
        self.assertFalse(fmt.exists)
        self.assertFalse(blockdev.crypto.device_is_luks(fmt.device))
        self.assertIsNone(crypto.find_secure_key_for_volume(fmt.device))
        fmt.create()
        fmt.setup()
        fmt.teardown()


class LUKSContextTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(LUKSContextTestCase, self).__init__(methodName=methodName, device_spec=[Size("100 MiB")])

    def setUp(self):
        super().setUp()
        self.fmt = LUKS()
        self.fmt.device = self.loop_devices[0]

    def _clean_up(self):
        self.fmt.teardown()
        super()._clean_up()

    def test_passphrase_context(self):
        self.assertFalse(self.fmt.has_key)

        self.fmt.contexts.add_passphrase("passphrase")
        self.assertTrue(self.fmt.has_key)

        self.fmt.create()
        self.fmt.setup()

    def test_keyfile_context(self):
        self.assertFalse(self.fmt.has_key)

        self.fmt.contexts.add_keyfile("/non/existing")
        self.assertFalse(self.fmt.has_key)

        self.fmt.contexts.clear_contexts()

        with tempfile.NamedTemporaryFile(prefix="blivet_test") as temp:
            temp.write(b"password2")
            temp.flush()

            # create the luks format with both passphrase and keyfile
            self.fmt.contexts.add_keyfile(temp.name)
            self.assertTrue(self.fmt.has_key)
            self.fmt.create()

            self.fmt.setup()
            self.fmt.teardown()

    def test_multiple_contexts(self):
        self.fmt.contexts.add_passphrase("passphrase")
        self.fmt.contexts.add_passphrase("passphrase1")

        with tempfile.NamedTemporaryFile(prefix="blivet_test") as temp:
            temp.write(b"password2")
            temp.flush()

            # create the luks format with both passphrase and keyfile
            self.fmt.contexts.add_keyfile(temp.name)
            self.fmt.create()

            # we should now have three key slots, lets test one by one
            self.fmt.contexts.clear_contexts()

            # first passphrase
            self.fmt.contexts.clear_contexts()
            self.fmt.contexts.add_passphrase("passphrase")
            self.fmt.setup()
            self.fmt.teardown()

            # second passphrase
            self.fmt.contexts.clear_contexts()
            self.fmt.contexts.add_passphrase("passphrase1")
            self.fmt.setup()
            self.fmt.teardown()

            # keyfile
            self.fmt.contexts.clear_contexts()
            self.fmt.contexts.add_keyfile(temp.name)
            self.fmt.setup()
            self.fmt.teardown()

    def test_add_remove_context(self):
        self.fmt.contexts.add_passphrase("passphrase")
        self.fmt.create()

        # add new passphrase and test it
        self.fmt.add_key(crypto.KeyslotContext(passphrase="passphrase1"))
        self.fmt.contexts.clear_contexts()
        self.fmt.contexts.add_passphrase("passphrase1")
        self.fmt.setup()
        self.fmt.teardown()

        # remove the passphrase and test that the old one can still be used
        self.fmt.remove_key(crypto.KeyslotContext(passphrase="passphrase1"))
        self.fmt.contexts.clear_contexts()
        self.fmt.contexts.add_passphrase("passphrase1")

        # removed passphrase should no longer be usable
        with self.assertRaises(LUKSError):
            self.fmt.setup()

        self.fmt.contexts.clear_contexts()
        self.fmt.contexts.add_passphrase("passphrase")
        self.fmt.setup()
        self.fmt.teardown()


@unittest.skipUnless(Integrity._plugin.available, "Integrity support not available")
class IntegrityTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(IntegrityTestCase, self).__init__(methodName=methodName, device_spec=[Size("100 MiB")])

    def test_integrity(self):
        fmt = Integrity(device=self.loop_devices[0])
        self.assertEqual(fmt.algorithm, crypto.DEFAULT_INTEGRITY_ALGORITHM)

        # create and open the integrity format
        fmt.create()
        fmt.setup()
        self.assertTrue(fmt.status)
        self.assertTrue(os.path.exists("/dev/mapper/%s" % fmt.map_name))

        fmt.teardown()
        self.assertFalse(fmt.status)
        self.assertFalse(os.path.exists("/dev/mapper/%s" % fmt.map_name))


class LUKSResetTestCase(StorageTestCase):

    _num_disks = 1

    def setUp(self):
        super().setUp()

        disks = [os.path.basename(vdev) for vdev in self.vdevs]
        self.storage = blivet.Blivet()
        self.storage.exclusive_disks = disks
        self.storage.reset()

        # make sure only the targetcli disks are in the devicetree
        for disk in self.storage.disks:
            self.assertTrue(disk.path in self.vdevs)
            self.assertIsNone(disk.format.type)
            self.assertFalse(disk.children)

    def _clean_up(self):
        self.storage.reset()
        for disk in self.storage.disks:
            if disk.path not in self.vdevs:
                raise RuntimeError("Disk %s found in devicetree but not in disks created for tests" % disk.name)
            self.storage.recursive_remove(disk)

        self.storage.do_it()

        return super()._clean_up()

    def test_luks_save_passphrase(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        fmt = LUKS(passphrase="password")
        self.storage.format_device(disk, fmt)
        self.storage.do_it()

        blivet.static_data.luks_data.save_passphrase(disk)
        self.storage.devicetree.populate()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.assertTrue(disk.format.has_key)

        # remove passphrase and try to save it (should not fail)
        disk.format.passphrase = None
        blivet.static_data.luks_data.save_passphrase(disk)

    def test_label_subsystem(self):
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)

        fmt = LUKS(passphrase="password", label="label", subsystem="subsystem")
        self.storage.format_device(disk, fmt)
        self.storage.do_it()

        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.assertEqual(disk.format.type, "luks")
        self.assertEqual(disk.format.label, "label")
        self.assertEqual(disk.format.subsystem, "subsystem")

        disk.format.label = "new_label"
        disk.format.write_label()

        self.storage.reset()
        disk = self.storage.devicetree.get_device_by_path(self.vdevs[0])
        self.assertIsNotNone(disk)
        self.assertEqual(disk.format.type, "luks")
        self.assertEqual(disk.format.label, "new_label")
