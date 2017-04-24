import sys
import abc
from six import add_metaclass
from unittest import skipIf

from tests import loopbackedtestcase
from blivet.devicetree import DeviceTree
from blivet.errors import FSError, FSWriteUUIDError
from blivet.size import Size


@add_metaclass(abc.ABCMeta)
class SetUUID(loopbackedtestcase.LoopBackedTestCase):

    """Base class for UUID tests without any test methods."""

    _fs_class = abc.abstractproperty(
        doc="The class of the filesystem being tested on.")

    _valid_uuid = abc.abstractproperty(
        doc="A valid UUID for this filesystem.")

    _invalid_uuid = abc.abstractproperty(
        doc="An invalid UUID for this filesystem.")

    def __init__(self, methodName='run_test'):
        super(SetUUID, self).__init__(methodName=methodName,
                                      device_spec=[Size("100 MiB")])

    def setUp(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        super(SetUUID, self).setUp()


class SetUUIDWithMkFs(SetUUID):

    """Tests various aspects of setting an UUID for a filesystem where the
       native mkfs tool can set the UUID.
    """

    @skipIf(sys.version_info < (3, 4), "assertLogs is not supported")
    def test_set_invalid_uuid(self):
        """Create the filesystem with an invalid UUID."""
        an_fs = self._fs_class(device=self.loop_devices[0],
                               uuid=self._invalid_uuid)
        if self._fs_class._type == "swap":
            with self.assertRaisesRegex(FSWriteUUIDError, "bad UUID format"):
                an_fs.create()
        else:
            with self.assertLogs('blivet', 'WARNING') as logs:
                an_fs.create()
            self.assertTrue(len(logs.output) >= 1)
            self.assertRegex(logs.output[0], "UUID format.*unacceptable")

    def test_set_uuid(self):
        """Create the filesystem with a valid UUID."""
        an_fs = self._fs_class(device=self.loop_devices[0],
                               uuid=self._valid_uuid)
        self.assertIsNone(an_fs.create())

        # Use DeviceTree for detecting the loop device and check whether the
        # UUID is correct.
        dt = DeviceTree()
        dt.reset()
        dt.populate()
        device = dt.get_device_by_path(self.loop_devices[0])
        self.assertEqual(device.format.uuid, self._valid_uuid)


class SetUUIDAfterMkFs(SetUUID):

    """Tests various aspects of setting an UUID for a filesystem where the
       native mkfs tool can't set the UUID.
    """

    def setUp(self):
        an_fs = self._fs_class()
        if an_fs._writeuuid.availability_errors:
            self.skipTest("can not write UUID for filesystem %s" % an_fs.name)
        super(SetUUIDAfterMkFs, self).setUp()

    def test_set_uuid_later(self):
        """Create the filesystem with random UUID and reassign later."""
        an_fs = self._fs_class(device=self.loop_devices[0])
        if an_fs._writeuuid.availability_errors:
            self.skipTest("can not write UUID for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())

        an_fs.uuid = self._valid_uuid
        self.assertIsNone(an_fs.write_uuid())

        # Use DeviceTree for detecting the loop device and check whether the
        # UUID is correct.
        dt = DeviceTree()
        dt.reset()
        dt.populate()
        device = dt.get_device_by_path(self.loop_devices[0])
        self.assertEqual(device.format.uuid, self._valid_uuid)

    def test_set_invalid_uuid_later(self):
        """Create the filesystem and try to reassign an invalid UUID later."""
        an_fs = self._fs_class(device=self.loop_devices[0])
        if an_fs._writeuuid.availability_errors:
            self.skipTest("can not write UUID for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())

        an_fs.uuid = self._invalid_uuid
        with self.assertRaisesRegex(FSError, "bad UUID format"):
            an_fs.write_uuid()
