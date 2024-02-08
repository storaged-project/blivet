# pylint: skip-file
import os
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch
from decimal import Decimal
from textwrap import dedent
from io import StringIO

from blivet import errors
from blivet import util
from blivet.size import Size


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
            t.bad_news  # pylint: disable=pointless-statement


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
        _guard = TestDependencyGuard()
        with self.assertLogs("blivet", level="WARNING") as cm:
            self.assertEqual(self._test_dependency_guard_non_critical(), None)
        self.assertTrue(TestDependencyGuard.error_msg in "\n".join(cm.output))

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


class GetKernelModuleParameterTestCase(unittest.TestCase):

    def test_nonexisting_kernel_module(self):
        self.assertIsNone(util.get_kernel_module_parameter("unknown_module", "unknown_parameter"))

    def test_get_kernel_module_parameter_value(self):
        with mock.patch('blivet.util.open', mock.mock_open(read_data='value\n')):
            value = util.get_kernel_module_parameter("module", "parameter")
        self.assertEqual(value, "value")


class MemoryTests(unittest.TestCase):

    MEMINFO = dedent(
        """MemTotal:       32526648 kB
           MemFree:         8196560 kB
           MemAvailable:   21189232 kB
           Buffers:            4012 kB
           Cached:         13974708 kB
           SwapCached:            0 kB
           Active:          4934172 kB
           Inactive:       17128972 kB
           Active(anon):       7184 kB
           Inactive(anon):  9202192 kB
           Active(file):    4926988 kB
           Inactive(file):  7926780 kB
           Unevictable:     1009932 kB
           Mlocked:             152 kB
           SwapTotal:       8388604 kB
           SwapFree:        8388604 kB
           Zswap:                 0 kB
           Zswapped:              0 kB
           Dirty:              4508 kB
           Writeback:             0 kB
           AnonPages:       9094440 kB
           Mapped:          1224920 kB
           Shmem:           1124952 kB
           KReclaimable:     605048 kB
           Slab:             969324 kB
           SReclaimable:     605048 kB
           SUnreclaim:       364276 kB
           KernelStack:       36672 kB
           PageTables:        85696 kB
           NFS_Unstable:          0 kB
           Bounce:                0 kB
           WritebackTmp:          0 kB
           CommitLimit:    24651928 kB
           Committed_AS:   19177064 kB
           VmallocTotal:   34359738367 kB
           VmallocUsed:      102060 kB
           VmallocChunk:          0 kB
           Percpu:            11392 kB
           HardwareCorrupted:     0 kB
           AnonHugePages:         0 kB
           ShmemHugePages:        0 kB
           ShmemPmdMapped:        0 kB
           FileHugePages:         0 kB
           FilePmdMapped:         0 kB
           CmaTotal:              0 kB
           CmaFree:               0 kB
           HugePages_Total:       0
           HugePages_Free:        0
           HugePages_Rsvd:        0
           HugePages_Surp:        0
           Hugepagesize:       2048 kB
           Hugetlb:               0 kB
           DirectMap4k:      829716 kB
           DirectMap2M:    27138048 kB
           DirectMap1G:     6291456 kB
        """
    )

    @patch("blivet.util.open")
    def test_total_memory_real(self, open_mock):
        """Test total_memory with real data"""
        open_mock.return_value = StringIO(self.MEMINFO)
        assert util.total_memory() == Size("32657720.0 KiB")
        open_mock.assert_called_once_with("/proc/meminfo", "r")

    @patch("blivet.util.open")
    def test_total_memory_missing(self, open_mock):
        """Test total_memory with missing value"""
        missing = self.MEMINFO.replace("MemTotal", "Nonsense")
        open_mock.return_value = StringIO(missing)
        with self.assertRaises(RuntimeError):
            util.total_memory()
        open_mock.assert_called_once_with("/proc/meminfo", "r")

    @patch("blivet.util.open")
    def test_total_memory_not_number(self, open_mock):
        """Test total_memory with bad format"""
        missing = self.MEMINFO.replace(
            "MemTotal:       32526648 kB",
            "MemTotal:       nonsense kB"
        )
        open_mock.return_value = StringIO(missing)
        with self.assertRaises(RuntimeError):
            util.total_memory()

        malformed = self.MEMINFO.replace(
            "MemTotal:       32526648 kB",
            "MemTotal:       32526648 kB as of right now"
        )
        open_mock.return_value = StringIO(malformed)
        with self.assertRaises(RuntimeError):
            util.total_memory()

    @patch("blivet.util.open")
    def test_total_memory_calculations(self, open_mock):
        """Test total_memory calculates correctly."""
        open_mock.return_value = StringIO("MemTotal: 1024 kB")
        assert util.total_memory() == Size("132096.0 KiB")

        open_mock.return_value = StringIO("MemTotal: 65536 kB")
        assert util.total_memory() == Size("196608.0 KiB")

        open_mock.return_value = StringIO("MemTotal: 10000000 kB")
        assert util.total_memory() == Size("10131072.0 KiB")
