
import unittest

from blivet.threads import StorageEventSynchronizer, StorageEventBase, \
                           StorageEventSynchronizerSet
from blivet.threads import KEY_ABSENT, KEY_PRESENT

from blivet.event import Event, EventQueue

class StorageEventSynchronizerTest(unittest.TestCase):
    def _testEventSyncReset(self, sync):
        """ Test correct operation of reset method. """
        # reset should clear any active flag and validation dict
        sync.reset()
        self.assertEqual(sync.active, False)
        self.assertEqual(sync._validate, dict())

    def _testEventSyncFlags(self, sync):
        """ Test correct operation of flags. """
        self.assertEqual(sync.active, False)

        # active property is True when any flag is True
        sync.changing = True
        self.assertEqual(sync.active, True)

        # only one flag can be set at a time
        with self.assertRaises(RuntimeError):
            sync.starting = True

        # reset should clear any active flag and validation dict
        self._testEventSyncReset(sync)

    def _testEventSyncValidation(self, sync):
        """ Test validation of event info. """
        # Set up some fake event information to validate.
        info = {"key1": 22, "key2": 'x'}

        # key3 is not present, so this should fail
        sync.info_update(key1=22, key2=KEY_PRESENT, key3=KEY_PRESENT)
        self.assertEqual(sync.validate(info), False)

        # if we don't specify key3 at all, it should pass
        sync.info_remove("key3")
        self.assertEqual(sync.validate(info), True)

        # now we specify that key3 must be absent, which should also pass
        sync.info_update(key3=KEY_ABSENT)
        self.assertEqual(sync.validate(info), True)

        # reset should clear any active flag and validation dict
        self._testEventSyncReset(sync)

    def testEventSyncBase(self):
        """ Test the StorageEventBase class. """
        sync = StorageEventBase()
        self._testEventSyncFlags(sync)
        self._testEventSyncValidation(sync)

    def testEventSync(self):
        """ Test the StorageEventSynchronizer class. """
        sync = StorageEventSynchronizer()
        self.assertEqual(sync.passthrough, False)
        self._testEventSyncFlags(sync)
        self._testEventSyncValidation(sync)

    def testEventSyncSet(self):
        """ Test the StorageEventSynchronizerSet class. """
        ss_list = []
        # pylint: disable=unused-variable
        for _i in range(3):
            ss_list.append(StorageEventSynchronizer())

        sync = StorageEventSynchronizerSet(ss_list)
        self._testEventSyncFlags(sync)
        self._testEventSyncValidation(sync)

class FakeEvent(Event):
    @property
    def device(self):
        return self.info

class EventQueueTest(unittest.TestCase):
    def testEventQueue(self):
        q = EventQueue()

        # should be initially empty
        self.assertEqual(list(q), [])

        e1 = FakeEvent('add', 'sdc')
        q.enqueue(e1)
        self.assertEqual(list(q), [e1])

        e2 = FakeEvent('add', 'sdd')
        q.enqueue(e2)
        self.assertEqual(list(q), [e1, e2])

        e1d = q.dequeue()
        self.assertEqual(e1d, e1)
        self.assertEqual(list(q), [e2])

        q.blacklist_add(device='sdc', action='change', count=1)
        e3 = FakeEvent('change', 'sdc')

        # should get enqueued since it isn't a blacklist match (action)
        e4 = FakeEvent('add', 'sdc')
        q.enqueue(e4)
        self.assertEqual(list(q), [e2, e4])

        # should get enqueued since it isn't a blacklist match (device)
        e5 = FakeEvent('change', 'sde')
        q.enqueue(e5)
        self.assertEqual(list(q), [e2, e4, e5])

        # enqueuing e3 should be a no-op
        q.enqueue(e3)
        self.assertEqual(list(q), [e2, e4, e5])

        # now that the blacklist was hit once, enqueuing e3 should work normally
        q.enqueue(e3)
        self.assertEqual(list(q), [e2, e4, e5, e3])

        # omitting device or action should mean "any device" or "any action",
        # respectively
        q.blacklist_add(device='sdc', count=2)
        q.enqueue(e1)
        self.assertEqual(list(q), [e2, e4, e5, e3])
        q.enqueue(e1)
        self.assertEqual(list(q), [e2, e4, e5, e3])
        # the blacklist entry should be dropped after being hit twice
        q.enqueue(e1)
        self.assertEqual(list(q), [e2, e4, e5, e3, e1])

        q.blacklist_add(action='remove', count=1)
        e6 = FakeEvent('remove', 'sdd2')
        # enqueue will be a no-op since event.action == "remove"
        q.enqueue(e6)
        self.assertEqual(list(q), [e2, e4, e5, e3, e1])
        # now the blacklist entry should be removed since it was hit once,
        # making the next enqueue work as expected (no blacklist)
        q.enqueue(e6)
        self.assertEqual(list(q), [e2, e4, e5, e3, e1, e6])

        # shorten the queue to save some typing below
        _ignoreme = q.dequeue()
        _ignoreme = q.dequeue()
        _ignoreme = q.dequeue()
        _ignoreme = q.dequeue()
        self.assertEqual(list(q), [e1, e6])

        # blacklist entries with a count of zero are permanent
        e7 = FakeEvent('add', 'sdg')
        q.blacklist_add(device='sdg', action='add', count=0)
        for _i in range(300):
            q.enqueue(e7)
            self.assertEqual(list(q), [e1, e6])

if __name__ == "__main__":
    unittest.main()

