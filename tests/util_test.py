# pylint: skip-file
import test_compat

from six.moves import mock
import os
import six
import tempfile
import unittest
from decimal import Decimal

from blivet import errors
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

    def test_dedup_list(self):
        # no duplicates, no change
        self.assertEqual([1, 2, 3, 4], util.dedup_list([1, 2, 3, 4]))
        # empty list no issue
        self.assertEqual([], util.dedup_list([]))

        # real deduplication
        self.assertEqual([1, 2, 3, 4, 5, 6], util.dedup_list([1, 2, 3, 4, 2, 2, 2, 1, 3, 5, 3, 6, 6, 2, 3, 1, 5]))

    def test_detect_virt(self):
        in_virt = not util.run_program(["systemd-detect-virt", "--vm"])
        self.assertEqual(util.detect_virt(), in_virt)


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


class Test(object):
    def __init__(self, s):
        self._s = s

    @property
    def s(self):
        return self._s

    @property
    def ok(self):
        return True

    @property
    def nok(self):
        return False

    @util.requires_property("s", "hi")
    def say_hi(self):
        return self.s + ", guys!"

    @property
    @util.requires_property("s", "hi")
    def hi(self):
        return self.s

    @property
    @util.requires_property("ok")
    def good_news(self):
        return "Everything okay!"

    @property
    @util.requires_property("nok")
    def bad_news(self):
        return "Nothing okay!"


class TestRequiresProperty(unittest.TestCase):
    def test_requires_property(self):
        t = Test("hi")

        self.assertEqual(t.s, "hi")
        self.assertEqual(t.say_hi(), "hi, guys!")
        self.assertEqual(t.hi, "hi")

        t = Test("hello")
        self.assertEqual(t.s, "hello")
        with self.assertRaises(ValueError):
            t.say_hi()
        with self.assertRaises(ValueError):
            t.hi()

        self.assertEqual(t.good_news, "Everything okay!")

        with self.assertRaises(ValueError):
            t.bad_news


class TestDependencyGuard(util.DependencyGuard):
    error_msg = "test dep not satisfied"

    def _check_avail(self):
        return False


_requires_something = TestDependencyGuard()


class DependencyGuardTestCase(unittest.TestCase):
    @_requires_something(critical=True)
    def _test_dependency_guard_critical(self):
        return True

    @_requires_something(critical=False)
    def _test_dependency_guard_non_critical(self):
        return True

    def test_dependency_guard(self):
        guard = TestDependencyGuard()
        if six.PY3:
            with self.assertLogs("blivet", level="WARNING") as cm:
                self.assertEqual(self._test_dependency_guard_non_critical(), None)
            self.assertTrue(TestDependencyGuard.error_msg in "\n".join(cm.output))
        else:
            self.assertEqual(self._test_dependency_guard_non_critical(), None)

        with self.assertRaises(errors.DependencyError):
            self._test_dependency_guard_critical()

        with mock.patch.object(_requires_something, '_check_avail', return_value=True):
            self.assertEqual(self._test_dependency_guard_non_critical(), True)
            self.assertEqual(self._test_dependency_guard_critical(), True)


class GetSysfsAttrTestCase(unittest.TestCase):

    def test_get_sysfs_attr(self):

        with tempfile.TemporaryDirectory() as sysfs:
            model_file = os.path.join(sysfs, "model")
            with open(model_file, "w") as f:
                f.write("test model\n")

            model = util.get_sysfs_attr(sysfs, "model")
            self.assertEqual(model, "test model")

            # now with some invalid byte in the model
            with open(model_file, "wb") as f:
                f.write(b"test model\xef\n")

            # the unicode replacement character (U+FFFD) should be used instead
            model = util.get_sysfs_attr(sysfs, "model")
            self.assertEqual(model, "test model\ufffd")
