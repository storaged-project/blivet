# gpt_test.py
# GPT partitioning helpers test suite
#
# Copyright (C) Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#

import unittest
from uuid import UUID
from unittest import mock

from blivet.devicelibs import gpt
from blivet.errors import GPTVolUUIDError


class GPTTestCase(unittest.TestCase):

    def test_uuid_for_vol_arch_less(self):
        uuid = gpt.gpt_part_uuid_for_volume(gpt.GPT_VOL_SRV)
        self.assertEqual(uuid, UUID("3b8f8425-20e0-4f3b-907f-1a25a76f98e8"))

    @mock.patch("blivet.devicelibs.gpt.get_arch", return_value="ppc64")
    def test_uuid_for_vol_arch_implicit(self, mock_get_arch):
        uuid = gpt.gpt_part_uuid_for_volume(gpt.GPT_VOL_ARCH_USR_VERITY)
        mock_get_arch.assert_called_once()
        self.assertEqual(uuid, UUID("bdb528a5-a259-475f-a87d-da53fa736a07"))

    def test_uuid_for_vol_arch_explicit(self):
        uuid = gpt.gpt_part_uuid_for_volume(gpt.GPT_VOL_ARCH_USR_VERITY,
                                            arch="s390")
        self.assertEqual(uuid, UUID("b663c618-e7bc-4d6d-90aa-11b756bb1797"))

    def test_uuid_for_vol_arch_unknown(self):
        with self.assertRaises(GPTVolUUIDError):
            gpt.gpt_part_uuid_for_volume(gpt.GPT_VOL_ARCH_USR_VERITY,
                                         arch="nope")

    def test_uuid_for_vol_unknown(self):
        with self.assertRaises(GPTVolUUIDError):
            gpt.gpt_part_uuid_for_volume("nope")

    def test_uuid_for_path_arch_less(self):
        uuid = gpt.gpt_part_uuid_for_mountpoint("/home")
        self.assertEqual(uuid, UUID("933ac7e1-2eb4-4f13-b844-0e14e2aef915"))

    @mock.patch("blivet.devicelibs.gpt.get_arch", return_value="ppc64")
    def test_uuid_for_path_arch_implicit(self, mock_get_arch):
        uuid = gpt.gpt_part_uuid_for_mountpoint("/")
        mock_get_arch.assert_called_once()
        self.assertEqual(uuid, UUID("912ade1d-a839-4913-8964-a10eee08fbd2"))

    def test_uuid_for_path_arch_explicit(self):
        uuid = gpt.gpt_part_uuid_for_mountpoint("/",
                                                arch="s390")
        self.assertEqual(uuid, UUID("08a7acea-624c-4a20-91e8-6e0fa67d23f9"))

    def test_uuid_for_path_unknown(self):
        uuid = gpt.gpt_part_uuid_for_mountpoint("/nope")
        self.assertEqual(uuid, None)
