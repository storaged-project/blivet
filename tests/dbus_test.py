from collections import OrderedDict
import random
from unittest import TestCase
from unittest.mock import Mock, patch, sentinel

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


class UDevBlivetTestCase(TestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    @patch("blivet.dbus.blivet.callbacks")
    def setUp(self, *args):  # pylint: disable=unused-argument
        self.dbus_object = DBusBlivet(Mock(name="ObjectManager"))
        self.dbus_object._blivet = Mock()

    def test_ListDevices(self):
        """ Verify that ListDevices returns what it should.

            It should return a dbus.Array w/ signature 'o' containing the
            dbus object path of each device in the DBusBlivet.
        """
        object_paths = dbus.Array([sentinel.dev1, sentinel.dev2, sentinel.dev3], signature='o')
        dbus_devices = OrderedDict((p, Mock(object_path=p)) for p in object_paths)
        self.dbus_object._dbus_devices = dbus_devices
        self.assertEqual(self.dbus_object.ListDevices(), object_paths)

        # now test the devices property for good measure. it should have the
        # same value.
        self.assertEqual(self.dbus_object.Get(BLIVET_INTERFACE, 'Devices'), object_paths)
        self.dbus_object._blivet.devices = Mock()

    def test_Reset(self):
        """ Verify that Reset calls the underlying Blivet's reset method. """
        self.dbus_object._blivet.reset_mock()
        self.dbus_object._blivet.devices = []
        self.dbus_object.Reset()
        self.dbus_object._blivet.reset.assert_called_once_with()
        self.dbus_object._blivet.reset_mock()

    def test_RemoveDevice(self):
        self.dbus_object._blivet.reset_mock()
        object_path = '/com/redhat/Blivet1/Devices/23'
        device_mock = Mock("device 23")
        with patch.object(self.dbus_object, '_dbus_devices', new=dict()):
            self.dbus_object._dbus_devices[23] = device_mock
            self.dbus_object.RemoveDevice(object_path)

        self.dbus_object._blivet.devicetree.recursive_remove.assert_called_once_with(device_mock)
        self.dbus_object._blivet.reset_mock()

    def test_InitializeDisk(self):
        self.dbus_object._blivet.reset_mock()
        object_path = '/com/redhat/Blivet1/Devices/23'
        device_mock = Mock("device 23")
        with patch.object(self.dbus_object, '_dbus_devices', new=dict()):
            self.dbus_object._dbus_devices[23] = device_mock
            self.dbus_object.InitializeDisk(object_path)

        self.dbus_object._blivet.devicetree.recursive_remove.assert_called_once_with(device_mock)
        self.dbus_object._blivet.initialize_disk.assert_called_once_with(device_mock)
        self.dbus_object._blivet.reset_mock()


class DBusObjectTestCase(TestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    @patch("blivet.dbus.blivet.callbacks")
    def setUp(self, *args):  # pylint: disable=unused-argument
        self.obj = DBusObject()
        self.obj._manager.get_object_by_id.return_value = Mock(name="DBusObject", object_path="/an/object/path")

    def test_properties(self):
        with self.assertRaises(NotImplementedError):
            _x = self.obj.properties

        with self.assertRaises(NotImplementedError):
            _x = self.obj.interface

        with self.assertRaises(NotImplementedError):
            _x = self.obj.object_path


class DBusDeviceTestCase(DBusObjectTestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    @patch("blivet.dbus.blivet.callbacks")
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
        self.obj.removed = True
        self.assertEqual(self.obj.object_path, "%s/%d" % (DEVICE_REMOVED_OBJECT_PATH_BASE, self._device_id))
        self.obj.removed = False
        self.assertEqual(self.obj.object_path, "%s/%d" % (DEVICE_OBJECT_PATH_BASE, self._device_id))


class DBusFormatTestCase(DBusObjectTestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    @patch("blivet.dbus.blivet.callbacks")
    def setUp(self, *args):
        self._format_id = random.randint(0, 500)
        self.obj = DBusFormat(Mock(name="DeviceFormat", id=self._format_id),
                              Mock(name="ObjectManager"))
        self.obj._manager.get_object_by_id.return_value = Mock(name="DBusObject", object_path="/an/object/path")

    def test_properties(self, *args):  # pylint: disable=unused-argument
        self.assertTrue(isinstance(self.obj.properties, dict))
        self.assertEqual(self.obj.interface, FORMAT_INTERFACE)
        self.assertEqual(self.obj.object_path, "%s/%d" % (FORMAT_OBJECT_PATH_BASE, self._format_id))
        self.obj.removed = True
        self.assertEqual(self.obj.object_path, "%s/%d" % (FORMAT_REMOVED_OBJECT_PATH_BASE, self._format_id))
        self.obj.removed = False
        self.assertEqual(self.obj.object_path, "%s/%d" % (FORMAT_OBJECT_PATH_BASE, self._format_id))


class DBusActionTestCase(DBusObjectTestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    @patch("blivet.dbus.blivet.callbacks")
    def setUp(self, *args):
        self._id = random.randint(0, 500)
        self.obj = DBusAction(Mock(name="DeviceAction", id=self._id), Mock(name="ObjectManager"))
        self.obj._manager.get_object_by_id.return_value = Mock(name="DBusObject", object_path="/an/object/path")

    def test_properties(self, *args):  # pylint: disable=unused-argument
        self.assertTrue(isinstance(self.obj.properties, dict))
        self.assertEqual(self.obj.interface, ACTION_INTERFACE)
        self.assertEqual(self.obj.object_path, "%s/%d" % (ACTION_OBJECT_PATH_BASE, self._id))
