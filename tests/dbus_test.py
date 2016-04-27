import dbus
from unittest import TestCase
from unittest.mock import Mock, patch

from blivet import Blivet
from blivet.dbus.blivet import DBusBlivet
from blivet.dbus.blivet import DBusObject
from blivet.dbus.constants import BLIVET_INTERFACE


class UDevBlivetTestCase(TestCase):
    @patch.object(DBusObject, '__init__', return_value=None)
    def setUp(self, *args):  # pylint: disable=unused-argument
        self.dbus_object = DBusBlivet()
        self.dbus_object._blivet = Mock(spec=Blivet)

    def test_ListDevices(self):
        """ Verify that ListDevices returns what it should.

            It should return a dbus.Array w/ signature 's' containing the
            string representations of the contents of the underlying
            Blivet's devices property.
        """
        devices = ['a', 'b', 22, False]
        dbus_devices = dbus.Array((str(d) for d in devices), signature='s')
        self.dbus_object._blivet.devices = devices
        self.assertEqual(self.dbus_object.ListDevices(), dbus_devices)

        # now test the devices property for good measure. it should have the
        # same value.
        self.assertEqual(self.dbus_object.Get(BLIVET_INTERFACE, 'Devices'),
                         dbus_devices)
        self.dbus_object._blivet.devices = Mock()

    def test_Reset(self):
        """ Verify that Reset calls the underlying Blivet's reset method. """
        self.dbus_object._blivet.reset_mock()
        self.dbus_object.Reset()
        self.dbus_object._blivet.reset.assert_called_once_with()
        self.dbus_object._blivet.reset_mock()
