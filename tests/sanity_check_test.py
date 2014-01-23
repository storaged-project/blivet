#!/usr/bin/python
#
# tests/sanity_check_test.py
#
# Tests on blivet's sanityCheck method.
#
# Copyright (C) 2014  Red Hat, Inc.
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
# Red Hat Author(s): Anne Mulhern <amulhern@redhat.com>

import unittest

import blivet
from blivet import devices
from blivet import formats

class LUKSKeyTestCase(unittest.TestCase):

    def testNoKey(self):
        errors = []
        b = blivet.Blivet()
        b.createDevice(devices.LUKSDevice("name",
           format=formats.luks.LUKS(),
           parents=[]))
        errors += b._verifyLUKSDevicesHaveKey()
        self.assertNotEqual(errors, [])

    def testWithKey(self):
        errors = []
        b = blivet.Blivet()
        b.createDevice(devices.LUKSDevice("name",
           format=formats.luks.LUKS(passphrase="open"),
           parents=[]))
        errors += b._verifyLUKSDevicesHaveKey()
        self.assertEqual(errors, [])

def suite():
    return unittest.TestLoader().loadTestsFromTestCase(LUKSKeyTestCase)

if __name__ == "__main__":
    unittest.main()
