from collections import OrderedDict
import random
from unittest import TestCase
from unittest.mock import Mock, patch, sentinel

import dbus

from blivet import Blivet
from blivet.dbus.blivet import DBusBlivet
from blivet.dbus.device import DBusDevice
from blivet.dbus.object import DBusObject
from blivet.dbus.constants import BLIVET_INTERFACE, DEVICE_INTERFACE


class UDevBlivetTestCase(TestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    @patch("blivet.dbus.blivet.callbacks")
    def setUp(self, *args):  # pylint: disable=unused-argument
        self.dbus_object = DBusBlivet(Mock(name="ObjectManager"))
        self.dbus_object._blivet = Mock(spec=Blivet)

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


class DBusObjectTestCase(TestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    @patch("blivet.dbus.blivet.callbacks")
    def setUp(self, *args):  # pylint: disable=unused-argument
        self.obj = DBusObject()

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
        self.obj = DBusDevice(Mock(name="StorageDevice", id=self._device_id,
                                   parents=[], children=[]))

    @patch('dbus.UInt64')
    def test_properties(self, *args):  # pylint: disable=unused-argument
        self.assertTrue(isinstance(self.obj.properties, dict))
        self.assertEqual(self.obj.interface, DEVICE_INTERFACE)
        self.assertEqual(self.obj.object_path,
                         self.obj.get_object_path_by_id(self._device_id))
