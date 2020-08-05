
import unittest
from blivet.devices import ParentList
from blivet.devices import Device


class ParentListTestCase(unittest.TestCase):

    def test_parent_list(self):
        items = list(range(5))
        length = len(items)
        pl = ParentList(items=items)
        self.assertEqual(len(pl), length)
        self.assertEqual(list(pl), items)

        self.assertEqual(hasattr(pl, "index"), False)
        self.assertEqual(hasattr(pl, "insert"), False)
        self.assertEqual(hasattr(pl, "pop"), False)

        self.assertEqual(pl[:], pl.items)

        with self.assertRaises(TypeError):
            pl[2] = 99  # pylint: disable=unsupported-assignment-operation

        newval = 99
        self.assertEqual(99 in pl, False)
        pl.append(newval)
        length += 1
        self.assertEqual(len(pl), length)
        self.assertEqual(newval in pl, True)

        val = 3
        self.assertEqual(val in pl, True)
        pl.remove(val)
        length -= 1
        self.assertEqual(len(pl), length)
        self.assertEqual(val in pl, False)

        #
        # verify that add/remove functions work as expected
        #
        def pre_add(item):
            if item > 32:
                raise ValueError("only numbers less than 32 are allowed")

        def pre_remove(item):
            # pylint: disable=unused-argument
            if len(pl) - 1 < 3:
                raise RuntimeError("list can never have fewer than 3 items")

        pl = ParentList(items=items, appendfunc=pre_add, removefunc=pre_remove)

        with self.assertRaises(ValueError):
            pl.append(33)

        pl.remove(4)
        pl.remove(3)
        with self.assertRaises(RuntimeError):
            pl.remove(2)

    def test_device_parents(self):
        """ Verify that Device.parents functions as expected. """
        dev1 = Device("dev1", [])
        self.assertEqual(len(dev1.parents), 0)
        self.assertIsInstance(dev1.parents, ParentList)
        dev2 = Device("dev2")
        dev3 = Device("dev3", [dev1])
        self.assertEqual(len(dev3.parents), 1)
        dev3.parents.remove(dev1)
        self.assertEqual(len(dev3.parents), 0)
        dev3.parents.append(dev1)
        self.assertEqual(len(dev3.parents), 1)
        dev3.parents.append(dev2)
        self.assertEqual(len(dev3.parents), 2)

        dev3.parents = [dev1, dev2]
        self.assertEqual(len(dev3.parents), 2)

        dev3.parents = []
        self.assertEqual(len(dev3.parents), 0)
