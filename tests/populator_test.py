import os
import unittest
from blivet import Blivet
from blivet.flags import flags
from blivet import util
from blivet.size import Size
from blivet.osinstall import storageInitialize
try:
    from pyanaconda import kickstart
    pyanaconda_present = True
except ImportError:
    pyanaconda_present = False

@unittest.skipUnless(pyanaconda_present, "pyanaconda is missing")
class setupDiskImagesNonZeroSizeTestCase(unittest.TestCase):
    """
        Test if size of disk images is > 0. Related: rhbz#1252703.
        This test emulates how anaconda configures its storage.
    """

    disks = { "disk1": Size("2 GiB") }

    def setUp(self):
        self.blivet = Blivet()

        # anaconda first configures disk images
        for (name, size) in iter(self.disks.items()):
            path = util.create_sparse_tempfile(name, size)
            self.blivet.config.diskImages[name] = path

        # at this point the DMLinearDevice has correct size
        self.blivet.setupDiskImages()

        # emulates setting the anaconda flags which later update
        # blivet flags as the first thing to do in storageInitialize
        flags.image_install = True
        # no kickstart available
        ksdata = kickstart.AnacondaKSHandler([])
        # anaconda calls storageInitialize regardless of whether or not
        # this is an image install. Somewhere along the line this will
        # execute setupDiskImages() once more and the DMLinearDevice created
        # in this second execution has size 0
        storageInitialize(self.blivet, ksdata, [])

    def tearDown(self):
        self.blivet.reset()
        self.blivet.devicetree.teardownDiskImages()
        for fn in self.blivet.config.diskImages.values():
            if os.path.exists(fn):
                os.unlink(fn)

        flags.image_install = False

    def runTest(self):
        for d in self.blivet.devicetree.devices:
            self.assertTrue(d.size > 0)

if __name__ == "__main__":
    unittest.main()
