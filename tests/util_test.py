
import unittest
from decimal import Decimal

from blivet import util

class MiscTest(unittest.TestCase):

    # Disable this warning, which will only be triggered on python3.  For
    # python2, the default is False.
    longMessage = True      # pylint: disable=pointless-class-attribute-override

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
