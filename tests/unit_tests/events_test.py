import time
from unittest import TestCase
from unittest.mock import patch, Mock

from blivet.events.manager import Event, EventManager


class FakeEventManager(EventManager):
    @property
    def enabled(self):
        return False

    def enable(self):
        pass

    def disable(self):
        pass

    def _create_event(self, *args, **kwargs):
        return Event(*args, **kwargs)


class EventManagerTest(TestCase):
    def testEventMask(self):
        handler_cb = Mock()
        with patch("blivet.events.manager.validate_cb", return_value=True):
            mgr = FakeEventManager(handler_cb=handler_cb)

        device = "sdc"
        action = "add"
        mgr.handle_event(action, device)
        time.sleep(1)
        self.assertEqual(handler_cb.call_count, 1)
        event = handler_cb.call_args[1]["event"]  # pylint: disable=unsubscriptable-object
        self.assertEqual(event.device, device)
        self.assertEqual(event.action, action)

        # mask matches device but not action -> event is handled
        handler_cb.reset_mock()
        mask = mgr.add_mask(device=device, action=action + 'x')
        mgr.handle_event(action, device)
        time.sleep(1)
        self.assertEqual(handler_cb.call_count, 1)
        event = handler_cb.call_args[1]["event"]  # pylint: disable=unsubscriptable-object
        self.assertEqual(event.device, device)
        self.assertEqual(event.action, action)

        # mask matches action but not device -> event is handled
        handler_cb.reset_mock()
        mask = mgr.add_mask(device=device + 'x', action=action)
        mgr.handle_event(action, device)
        time.sleep(1)
        self.assertEqual(handler_cb.call_count, 1)
        event = handler_cb.call_args[1]["event"]  # pylint: disable=unsubscriptable-object
        self.assertEqual(event.device, device)
        self.assertEqual(event.action, action)

        # mask matches device and action -> event is ignored
        handler_cb.reset_mock()
        mgr.remove_mask(mask)
        mask = mgr.add_mask(device=device, action=action)
        mgr.handle_event(action, device)
        time.sleep(1)
        self.assertEqual(handler_cb.call_count, 0)

        # device-only mask matches -> event is ignored
        handler_cb.reset_mock()
        mgr.remove_mask(mask)
        mask = mgr.add_mask(device=device)
        mgr.handle_event(action, device)
        time.sleep(1)
        self.assertEqual(handler_cb.call_count, 0)

        # action-only mask matches -> event is ignored
        handler_cb.reset_mock()
        mgr.remove_mask(mask)
        mask = mgr.add_mask(action=action)
        mgr.handle_event(action, device)
        time.sleep(1)
        self.assertEqual(handler_cb.call_count, 0)
        mgr.remove_mask(mask)
