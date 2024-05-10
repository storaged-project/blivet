import unittest
from unittest.mock import patch

from blivet.nvme import nvme


class NVMeModuleTestCase(unittest.TestCase):

    host_nqn = "nqn.2014-08.org.nvmexpress:uuid:01234567-8900-abcd-efff-abcdabcdabcd"

    @patch("blivet.nvme.os")
    @patch("blivet.nvme.blockdev")
    def test_nvme_module(self, bd, os):
        self.assertIsNotNone(nvme)
        bd.nvme_get_host_nqn.return_value = self.host_nqn
        bd.nvme_get_host_id.return_value = None  # None = generate from host_nqn
        os.path.isdir.return_value = False

        # startup
        with patch.object(nvme, "write") as write:
            nvme.startup()
            write.assert_called_once_with("/", overwrite=False)

        self.assertTrue(nvme.started)
        self.assertEqual(nvme._hostnqn, self.host_nqn)
        self.assertEqual(nvme._hostid, "01234567-8900-abcd-efff-abcdabcdabcd")

        # write
        with patch("blivet.nvme.open") as op:
            nvme.write("/test")

            os.makedirs.assert_called_with("/test/etc/nvme/", 0o755)
            op.assert_any_call("/test/etc/nvme/hostnqn", "w")
            op.assert_any_call("/test/etc/nvme/hostid", "w")
