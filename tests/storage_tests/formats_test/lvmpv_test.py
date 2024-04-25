from blivet.formats.lvmpv import LVMPhysicalVolume

from blivet.size import Size

from . import loopbackedtestcase


class LVMPVTestCase(loopbackedtestcase.LoopBackedTestCase):

    def __init__(self, methodName='run_test'):
        super(LVMPVTestCase, self).__init__(methodName=methodName, device_spec=[Size("100 MiB")])
        self.fmt = LVMPhysicalVolume()

    def test_size(self):
        self.fmt.device = self.loop_devices[0]

        # create the format
        self.fmt.create()
        self.addCleanup(self._pvremove)

        # without update_size_info size should be 0
        self.assertEqual(self.fmt.current_size, Size(0))

        # get current size
        self.fmt.update_size_info()
        self.assertGreater(self.fmt.current_size, Size(0))

    def test_resize(self):
        self.fmt.device = self.loop_devices[0]

        # create the format
        self.fmt.create()
        self.addCleanup(self._pvremove)

        # get current size to make format resizable
        self.assertFalse(self.fmt.resizable)
        self.fmt.update_size_info()
        self.assertTrue(self.fmt.resizable)

        # save the pv maximum size
        maxpvsize = self.fmt.current_size

        # resize the format
        new_size = Size("50 MiB")
        self.fmt.target_size = new_size
        self.fmt.do_resize()

        # get current size
        self.fmt.update_size_info()
        self.assertEqual(self.fmt.current_size, new_size)

        # Test growing PV to fill all available space on the device
        self.fmt.grow_to_fill = True
        self.fmt.do_resize()

        self.fmt.update_size_info()
        self.assertEqual(self.fmt.current_size, maxpvsize)

    def _pvremove(self):
        self.fmt._destroy()
