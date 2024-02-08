import random

from unittest.mock import patch, Mock, call
from unittest import TestCase

import dbus

from blivet.dbus.action import DBusAction
from blivet.dbus.blivet import DBusBlivet
from blivet.dbus.device import DBusDevice
from blivet.dbus.format import DBusFormat
from blivet.dbus.object import DBusObject
from blivet.dbus.constants import ACTION_INTERFACE, BLIVET_INTERFACE, DEVICE_INTERFACE, FORMAT_INTERFACE
from blivet.dbus.constants import ACTION_OBJECT_PATH_BASE
from blivet.dbus.constants import DEVICE_OBJECT_PATH_BASE, DEVICE_REMOVED_OBJECT_PATH_BASE
from blivet.dbus.constants import FORMAT_OBJECT_PATH_BASE, FORMAT_REMOVED_OBJECT_PATH_BASE


def mock_dbus_device(obj_id):
    obj = Mock(name="DBusDevice [%d]" % obj_id,
               id=obj_id,
               transient=True,
               object_path="%s/%d" % (DEVICE_OBJECT_PATH_BASE, obj_id),
               _device=Mock(name="StorageDevice %d" % obj_id))
    return obj


class DBusBlivetTestCase(TestCase):
    @patch.object(DBusObject, "_init_dbus_object")
    @patch("blivet.dbus.blivet.callbacks")
    @patch("blivet.formats.fs.Ext4FS.supported", return_value=True)
    @patch("blivet.formats.fs.Ext4FS.formattable", return_value=True)
    def setUp(self, *args):  # pylint: disable=unused-argument,arguments-differ
        self.dbus_object = DBusBlivet(Mock(name="ObjectManager"))
        self.dbus_object._blivet = Mock()

    def test_ListDevices(self):
        """ Verify that ListDevices returns what it should.

            It should return a dbus.Array w/ signature 'o' containing the
            dbus object path of each device in the DBusBlivet.
        """
        device_ids = [1, 11, 20, 101]
        dbus_devices = [mock_dbus_device(i) for i in device_ids]
        object_paths = dbus.Array((d.object_path for d in sorted(dbus_devices, key=lambda d: d.id)),
                                  signature='o')
        with patch.object(self.dbus_object, "_list_dbus_devices", return_value=dbus_devices):
            self.assertEqual(self.dbus_object.ListDevices(), object_paths)

        # now test the devices property for good measure. it should have the
        # same value.
        with patch.object(self.dbus_object, "_list_dbus_devices", return_value=dbus_devices):
            self.assertEqual(self.dbus_object.Get(BLIVET_INTERFACE, 'Devices'), object_paths)

    def test_Reset(self):
        """ Verify that Reset calls the underlying Blivet's reset method. """
        self.dbus_object._blivet.reset_mock()
        self.dbus_object._blivet.devices = []
        self.dbus_object._blivet.devicetree.actions = []
        device_ids = [1, 11, 20, 101]
        dbus_devices = [mock_dbus_device(i) for i in device_ids]
        self.dbus_object._manager.objects = [self.dbus_object]
        self.dbus_object._manager.objects.extend(dbus_devices)
        self.dbus_object.Reset()
        self.dbus_object._blivet.reset.assert_called_once_with()
        self.dbus_object._manager.remove_object.assert_has_calls([call(d) for d in dbus_devices])
        self.assertNotIn(call(self.dbus_object),
                         self.dbus_object._manager.remove_object.mock_calls)
        self.dbus_object._blivet.reset_mock()

    def test_RemoveDevice(self):
        self.dbus_object._blivet.reset_mock()
        dbus_device = mock_dbus_device(23)
        with patch.object(self.dbus_object._manager, "get_object_by_path", return_value=dbus_device):
            with patch("blivet.dbus.blivet.isinstance", return_value=True):
                self.dbus_object.RemoveDevice(dbus_device.object_path)

        self.dbus_object._blivet.devicetree.recursive_remove.assert_called_once_with(dbus_device._device)
        self.dbus_object._blivet.reset_mock()

    def test_InitializeDisk(self):
        self.dbus_object._blivet.reset_mock()
        dbus_device = mock_dbus_device(22)
        with patch.object(self.dbus_object._manager, "get_object_by_path", return_value=dbus_device):
            with patch("blivet.dbus.blivet.isinstance", return_value=True):
                self.dbus_object.InitializeDisk(dbus_device.object_path)

        self.dbus_object._blivet.devicetree.recursive_remove.assert_called_once_with(dbus_device._device)
        self.dbus_object._blivet.initialize_disk.assert_called_once_with(dbus_device._device)
        self.dbus_object._blivet.reset_mock()

    def test_Commit(self):
        self.dbus_object._blivet.reset_mock()
        self.dbus_object.Commit()
        self.dbus_object._blivet.do_it.assert_called_once_with()
        self.dbus_object._blivet.reset_mock()

    def test_Factory(self):
        self.dbus_object._blivet.reset_mock()
        device_type = 1
        disks = ["/com/redhat/Blivet1/Devices/1", "/com/redhat/Blivet1/Devices/22"]
        size = 10 * 1024**3
        kwargs = {"device_type": device_type,
                  "size": size,
                  "disks": disks,
                  "fstype": "xfs",
                  "name": "testdevice",
                  "raid_level": "raid0"}
        with patch("blivet.dbus.blivet.isinstance", return_value=True):
            self.dbus_object.Factory(kwargs)
        self.dbus_object._blivet.factory_device.assert_called_once_with(**kwargs)
        self.dbus_object._blivet.reset_mock()


@patch.object(DBusObject, 'connection')
class DBusObjectTestCase(TestCase):
    @patch.object(DBusObject, "_init_dbus_object")
    @patch("blivet.dbus.blivet.callbacks")
    def setUp(self, *args):  # pylint: disable=unused-argument,arguments-differ
        self.obj = DBusObject(Mock(name="ObjectManager"))
        self.obj._manager.get_object_by_id.return_value = Mock(name="DBusObject", object_path="/an/object/path")

    def test_properties(self, *args):  # pylint: disable=unused-argument
        with self.assertRaises(NotImplementedError):
            _x = self.obj.properties

        with self.assertRaises(NotImplementedError):
            _x = self.obj.interface

        with self.assertRaises(NotImplementedError):
            _x = self.obj.object_path


@patch.object(DBusObject, 'connection')
@patch.object(DBusObject, 'add_to_connection')
@patch.object(DBusObject, 'remove_from_connection')
@patch("blivet.dbus.blivet.callbacks")
class DBusDeviceTestCase(DBusObjectTestCase):
    @patch.object(DBusObject, "_init_dbus_object")
    def setUp(self, *args):
        self._device_id = random.randint(0, 500)
        self._format_id = random.randint(501, 1000)
        self.obj = DBusDevice(Mock(name="StorageDevice", id=self._device_id,
                                   parents=[], children=[]),
                              Mock(name="ObjectManager"))
        self.obj._manager.get_object_by_id.return_value = Mock(name="DBusObject", object_path="/an/object/path")

    @patch('dbus.UInt64')
    def test_properties(self, *args):  # pylint: disable=unused-argument
        self.assertTrue(isinstance(self.obj.properties, dict))
        self.assertEqual(self.obj.interface, DEVICE_INTERFACE)
        self.assertEqual(self.obj.object_path, "%s/%d" % (DEVICE_OBJECT_PATH_BASE, self._device_id))
        self.obj.present = False
        self.assertEqual(self.obj.object_path, "%s/%d" % (DEVICE_REMOVED_OBJECT_PATH_BASE, self._device_id))
        self.obj.present = True
        self.assertEqual(self.obj.object_path, "%s/%d" % (DEVICE_OBJECT_PATH_BASE, self._device_id))


@patch.object(DBusObject, 'connection')
@patch.object(DBusObject, 'add_to_connection')
@patch.object(DBusObject, 'remove_from_connection')
@patch("blivet.dbus.blivet.callbacks")
class DBusFormatTestCase(DBusObjectTestCase):
    @patch.object(DBusObject, "_init_dbus_object")
    def setUp(self, *args):
        self._format_id = random.randint(0, 500)
        self.obj = DBusFormat(Mock(name="DeviceFormat", id=self._format_id),
                              Mock(name="ObjectManager"))
        self.obj._manager.get_object_by_id.return_value = Mock(name="DBusObject", object_path="/an/object/path")

    def test_properties(self, *args):  # pylint: disable=unused-argument
        self.assertTrue(isinstance(self.obj.properties, dict))
        self.assertEqual(self.obj.interface, FORMAT_INTERFACE)
        self.assertEqual(self.obj.object_path, "%s/%d" % (FORMAT_OBJECT_PATH_BASE, self._format_id))
        self.obj.present = False
        self.assertEqual(self.obj.object_path, "%s/%d" % (FORMAT_REMOVED_OBJECT_PATH_BASE, self._format_id))
        self.obj.present = True
        self.assertEqual(self.obj.object_path, "%s/%d" % (FORMAT_OBJECT_PATH_BASE, self._format_id))


@patch("blivet.dbus.blivet.callbacks")
class DBusActionTestCase(DBusObjectTestCase):
    @patch.object(DBusObject, "_init_dbus_object")
    def setUp(self, *args):
        self._id = random.randint(0, 500)
        self.obj = DBusAction(Mock(name="DeviceAction", id=self._id), Mock(name="ObjectManager"))
        self.obj._manager.get_object_by_id.return_value = Mock(name="DBusObject", object_path="/an/object/path")

    def test_properties(self, *args):  # pylint: disable=unused-argument
        self.assertTrue(isinstance(self.obj.properties, dict))
        self.assertEqual(self.obj.interface, ACTION_INTERFACE)
        self.assertEqual(self.obj.object_path, "%s/%d" % (ACTION_OBJECT_PATH_BASE, self._id))
