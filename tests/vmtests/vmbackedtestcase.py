
import os
import unittest

from blivet import Blivet, udev


@unittest.skipUnless(os.environ.get("VM_ENVIRONMENT"), "vm only test")
@unittest.skipUnless(os.geteuid() == 0, "requires root access")
class VMBackedTestCase(unittest.TestCase):

    """ A class to encapsulate testing of blivet using block devices.

        The basic idea is you create some scratch block devices and then run
        some test code on them.

        :attr:`~.ImageBackedTestCase.disks` defines the set of disk images.

        :meth:`~.ImageBackedTestCase._set_up_storage` is where you specify the
        initial layout of the disks. It will be written to the disk images in
        :meth:`~.ImageBackedTestCase.set_up_storage`.

        You then write test methods as usual that use the disk images, which
        will be cleaned up and removed when each test method finishes.
    """

    initialize_disks = True  # Whether or not to create a disklabel on the disks.

    def set_up_disks(self):
        """ Create disk image files to build the test's storage on.

            If you are actually creating the disk image files here don't forget
            to set the initialize_disks flag so they get a fresh disklabel when
            clear_partitions gets called from create_storage later.
        """

    def _set_up_storage(self):
        """ Schedule creation of storage devices on the disk images.

            .. note::

                The disk images should already be in a populated devicetree.

        """

    def set_up_storage(self):
        """ Create a device stack on top of disk images for this test to run on.

            This will write the configuration to whatever disk images are
            defined in set_up_disks.
        """

        udev.ignored_device_names = [r'^zram']

        #
        # create disk images
        #
        self.set_up_disks()

        #
        # populate the devicetree
        #
        self.blivet.reset()

        if self.initialize_disks:
            for disk in self.blivet.disks:
                self.blivet.initialize_disk(disk)

        #
        # create the rest of the stack
        #
        self._set_up_storage()

        #
        # write configuration to disk images
        #
        self.blivet.do_it()

    def setUp(self):
        """ Do any setup required prior to running a test. """
        self.blivet = Blivet()

        self.addCleanup(self._clean_up)
        self.set_up_storage()

    def _clean_up(self):
        """ Clean up any resources that may have been set up for a test. """
        self.blivet.reset()

        # XXX The only reason for this may be lvmetad
        for disk in self.blivet.disks:
            self.blivet.recursive_remove(disk)

        try:
            self.blivet.do_it()
        except Exception:
            self.blivet.reset()
            raise
