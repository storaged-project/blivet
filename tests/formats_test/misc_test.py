#!/usr/bin/python
import unittest

from blivet.formats import device_formats
import blivet.formats.fs as fs

class MethodsTestCase(unittest.TestCase):
    """Test some methods that do not require actual images."""

    def setUp(self):
        self.fs = {}
        for k, v  in device_formats.items():
            if issubclass(v, fs.FS) and not issubclass(v, fs.NFS):
                self.fs[k] = v(device="/dev")


    def testGetLabelArgs(self):
        self.longMessage = True

        # ReiserFS is currently backwards, needs the label after the l flag
        for k, v in [(k, v) for k, v in self.fs.items() if isinstance(v, fs.ReiserFS)]:
            self.assertEqual(v._getLabelArgs("myfs"), ["-l", "/dev", "myfs"], msg=k)

        # JFS is backward as well
        for k, v in [(k, v) for k, v in self.fs.items() if isinstance(v, fs.JFS)]:
            self.assertEqual(v._getLabelArgs("myfs"), ["-L", "/dev", "myfs"], msg=k)

        #XFS uses a -L label
        for k, v in [(k, v) for k, v in self.fs.items() if isinstance(v, fs.XFS)]:
            self.assertEqual(v._getLabelArgs("myfs"), ["-L", "myfs", "/dev"], msg=k)


        # All NoDeviceFSs ignore the device argument passed and set device
        # to the fs type
        for k, v in [(k, v) for k, v in self.fs.items() if isinstance(v, fs.NoDevFS)]:
            self.assertEqual(v._getLabelArgs("myfs"), [v.type, "myfs"], msg=k)

        for k, v in [(k, v) for k, v in self.fs.items() if not (isinstance(v, fs.NoDevFS) or isinstance(v, fs.ReiserFS) or isinstance(v, fs.XFS) or isinstance(v, fs.JFS))]:
            self.assertEqual(v._getLabelArgs("myfs"), ["/dev", "myfs"], msg=k)

def suite():
    suite1 = unittest.TestLoader().loadTestsFromTestCase(MethodsTestCase)
    return unittest.TestSuite(suite1)


if __name__ == "__main__":
    unittest.main()
