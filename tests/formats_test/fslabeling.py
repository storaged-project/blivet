#!/usr/bin/python

import abc

from tests import loopbackedtestcase
from blivet.errors import FSError

class LabelingAsRoot(loopbackedtestcase.LoopBackedTestCase):
    """Tests various aspects of labeling a filesystem where there
       is no easy way to read the filesystem's label once it has been
       set and where the filesystem can not be relabeled.
    """
    __metaclass__ = abc.ABCMeta

    _fs_class = abc.abstractproperty(
       doc="The class of the filesystem being tested on.")

    _invalid_label = abc.abstractproperty(
       doc="A label which is invalid for this filesystem.")

    def __init__(self, methodName='runTest'):
        super(LabelingAsRoot, self).__init__(methodName=methodName, deviceSpec=[102400])

    def setUp(self):
        an_fs = self._fs_class()
        if not an_fs.utilsAvailable:
            self.skipTest("utilities unavailable for filesystem %s" % an_fs.name)
        super(LabelingAsRoot, self).setUp()

    def testLabeling(self):
        """A sequence of tests of filesystem labeling.

           * create the filesystem when passing an invalid label
           * raise an exception when reading the filesystem
           * raise an exception when relabeling the filesystem
        """
        an_fs = self._fs_class(device=self.loopDevices[0], label=self._invalid_label)
        self.assertIsNone(an_fs.create())

        with self.assertRaisesRegexp(FSError, "no application to read label"):
            an_fs.readLabel()

        an_fs.label = "an fs"
        with self.assertRaisesRegexp(FSError, "no application to set label for filesystem"):
            an_fs.writeLabel()

    def testCreating(self):
        """Create the filesystem when passing a valid label """
        an_fs = self._fs_class(device=self.loopDevices[0], label="start")
        self.assertIsNone(an_fs.create())

    def testCreatingNone(self):
        """Create the filesystem when passing None
           (indicates filesystem default)
        """
        an_fs = self._fs_class(device=self.loopDevices[0], label=None)
        self.assertIsNone(an_fs.create())

    def testCreatingEmpty(self):
        """Create the filesystem when passing the empty label."""
        an_fs = self._fs_class(device=self.loopDevices[0], label="")
        self.assertIsNone(an_fs.create())

class LabelingWithRelabeling(LabelingAsRoot):
    """Tests labeling where it is possible to relabel.
    """

    def testLabeling(self):
        """A sequence of tests of filesystem labeling.

           * create the filesystem when passing an invalid label
           * raise an exception when reading the filesystem
           * relabel the filesystem with a valid label
           * relabel the filesystem with an empty label
           * raise an exception when relabeling when None is specified
           * raise an exception when relabeling with an invalid label
        """
        an_fs = self._fs_class(device=self.loopDevices[0], label=self._invalid_label)
        self.assertIsNone(an_fs.create())

        with self.assertRaisesRegexp(FSError, "no application to read label"):
            an_fs.readLabel()

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.writeLabel())

        an_fs.label = ""
        self.assertIsNone(an_fs.writeLabel())

        an_fs.label = None
        with self.assertRaisesRegexp(FSError, "default label"):
            an_fs.writeLabel()

        an_fs.label = self._invalid_label
        with self.assertRaisesRegexp(FSError, "bad label format"):
            an_fs.writeLabel()

class CompleteLabelingAsRoot(LabelingAsRoot):
    """Tests where it is possible to read the label and to relabel
       an existing filesystem.
    """

    def testLabeling(self):
        """A sequence of tests of filesystem labeling.

           * create the filesystem when passing an invalid label
             and verify that the filesystem has the default label
           * relabel the filesystem with a valid label
             and verify that the filesystem has that label
           * relabel the filesystem with an empty label
             and verify that the filesystem has that label
           * raise an exception when relabeling when None is specified
           * raise an exception when relabeling with an invalid label
        """
        an_fs = self._fs_class(device=self.loopDevices[0], label=self._invalid_label)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.default_label)

        an_fs.label = "an_fs"
        if an_fs.labelFormatOK(an_fs.label):
            self.assertIsNone(an_fs.writeLabel())
            self.assertEqual(an_fs.readLabel(), an_fs.label)
        else:
            self.assertRaisesRegexp(FSError, "bad label format", an_fs.writeLabel)

        an_fs.label = ""
        self.assertIsNone(an_fs.writeLabel())
        self.assertEqual(an_fs.readLabel(), an_fs.label)

        an_fs.label = None
        with self.assertRaisesRegexp(FSError, "default label"):
            an_fs.writeLabel()

        an_fs.label = "root___filesystem"
        with self.assertRaisesRegexp(FSError, "bad label format"):
            an_fs.writeLabel()

    def testCreating(self):
        """Create the filesystem when passing a valid label.
           Verify that the filesystem has that label.
        """
        an_fs = self._fs_class(device=self.loopDevices[0], label="start")
        self.assertIsNone(an_fs.create())
        if an_fs.labelFormatOK(an_fs.label):
            self.assertEqual(an_fs.readLabel(), "start")

    def testCreatingNone(self):
        """Create a filesystem with the label None.
           Verify that the filesystem has the default label.
        """
        an_fs = self._fs_class(device=self.loopDevices[0], label=None)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), an_fs._labelfs.default_label)

    def testCreatingEmpty(self):
        """Create a filesystem with an empty label.
           Verify that the filesystem has the empty label.
        """
        an_fs = self._fs_class(device=self.loopDevices[0], label="")
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.readLabel(), "")
