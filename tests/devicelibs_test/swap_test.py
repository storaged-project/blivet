#!/usr/bin/python
import unittest

import blivet.devicelibs.swap as swap
from blivet.errors import SwapError

from tests import loopbackedtestcase

class SwapTestCase(loopbackedtestcase.LoopBackedTestCase):

    def testSwap(self):
        _LOOP_DEV0 = self.loopDevices[0]
        _LOOP_DEV1 = self.loopDevices[1]


        ##
        ## mkswap
        ##
        # pass
        self.assertEqual(swap.mkswap(_LOOP_DEV0, "swap"), None)

        # fail
        with self.assertRaises(SwapError):
            swap.mkswap("/not/existing/device")

        ##
        ## swapon
        ##
        # pass
        self.assertEqual(swap.swapon(_LOOP_DEV0, 1), None)

        # fail
        with self.assertRaises(SwapError):
            swap.swapon("/not/existing/device")
        # not a swap partition
        with self.assertRaises(SwapError):
            swap.swapon(_LOOP_DEV1)

        # pass
        # make another swap
        self.assertEqual(swap.mkswap(_LOOP_DEV1, "another-swap"), None)
        self.assertEqual(swap.swapon(_LOOP_DEV1), None)

        ##
        ## swapstatus
        ##
        # pass
        self.assertEqual(swap.swapstatus(_LOOP_DEV0), True)
        self.assertEqual(swap.swapstatus(_LOOP_DEV1), True)

        # does not fail
        self.assertEqual(swap.swapstatus("/not/existing/device"), False)

        ##
        ## swapoff
        ##
        # pass
        self.assertEqual(swap.swapoff(_LOOP_DEV1), None)

        # check status
        self.assertEqual(swap.swapstatus(_LOOP_DEV0), True)
        self.assertEqual(swap.swapstatus(_LOOP_DEV1), False)

        self.assertEqual(swap.swapoff(_LOOP_DEV0), None)

        # fail
        with self.assertRaises(SwapError):
            swap.swapoff("/not/existing/device")
        # already off
        with self.assertRaises(SwapError):
            swap.swapoff(_LOOP_DEV0)

if __name__ == "__main__":
    unittest.main()
