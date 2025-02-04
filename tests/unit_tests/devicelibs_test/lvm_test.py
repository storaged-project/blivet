import unittest
from unittest.mock import patch, mock_open

import blivet.devicelibs.lvm as lvm


class LVMTestCase(unittest.TestCase):

    def test_lvm_autoactivation(self):
        localconf = "global { event_activation = 0 }"

        with patch("builtins.open", mock_open(read_data=localconf)):
            # already disabled
            with self.assertRaises(RuntimeError):
                lvm.disable_lvm_autoactivation()

        localconf = ""
        with patch("builtins.open", mock_open(read_data=localconf)) as m:
            lvm.disable_lvm_autoactivation()
            m.assert_called_with("/etc/lvm/lvmlocal.conf", "a")
            handle = m()
            handle.write.assert_called_once_with("global { event_activation = 0 }")

        localconf = "test\ntest"
        with patch("builtins.open", mock_open(read_data=localconf)) as m:
            # not disabled
            with self.assertRaises(RuntimeError):
                lvm.reenable_lvm_autoactivation()

        localconf = "# global { event_activation = 0 }"
        with patch("builtins.open", mock_open(read_data=localconf)) as m:
            # not disabled
            with self.assertRaises(RuntimeError):
                lvm.reenable_lvm_autoactivation()

        localconf = "test\nglobal { event_activation = 0 }"
        with patch("builtins.open", mock_open(read_data=localconf)) as m:
            lvm.reenable_lvm_autoactivation()
            m.assert_called_with("/etc/lvm/lvmlocal.conf", "w+")
            handle = m()
            handle.write.assert_called_once_with("test\n")
