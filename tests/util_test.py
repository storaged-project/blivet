
import unittest
from decimal import Decimal

from blivet import util


class MiscTest(unittest.TestCase):

    # Disable this warning, which will only be triggered on python3.  For
    # python2, the default is False.
    long_message = True      # pylint: disable=pointless-class-attribute-override

    def test_power_of_two(self):
        self.assertFalse(util.power_of_two(None))
        self.assertFalse(util.power_of_two("not a number"))
        self.assertFalse(util.power_of_two(Decimal("2.2")))
        self.assertFalse(util.power_of_two(-1))
        self.assertFalse(util.power_of_two(0))
        self.assertFalse(util.power_of_two(1))
        for i in range(1, 60, 5):
            self.assertTrue(util.power_of_two(2 ** i), msg=i)
            self.assertFalse(util.power_of_two(2 ** i + 1), msg=i)
            self.assertFalse(util.power_of_two(2 ** i - 1), msg=i)

class TestDefaultNamedtuple(unittest.TestCase):
    def test_default_namedtuple(self):
        TestTuple = util.default_namedtuple("TestTuple", ["x", "y", ("z", 5), "w"])
        dnt = TestTuple(1, 2, 3, 6)
        self.assertEqual(dnt.x, 1)
        self.assertEqual(dnt.y, 2)
        self.assertEqual(dnt.z, 3)
        self.assertEqual(dnt.w, 6)
        self.assertEqual(dnt, (1, 2, 3, 6))

        dnt = TestTuple(1, 2, 3, w=6)
        self.assertEqual(dnt.x, 1)
        self.assertEqual(dnt.y, 2)
        self.assertEqual(dnt.z, 3)
        self.assertEqual(dnt.w, 6)
        self.assertEqual(dnt, (1, 2, 3, 6))

        dnt = TestTuple(z=3, x=2, w=1, y=5)
        self.assertEqual(dnt, (2, 5, 3, 1))

        dnt = TestTuple()
        self.assertEqual(dnt, (None, None, 5, None))
