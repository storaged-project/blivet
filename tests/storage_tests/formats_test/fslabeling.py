
import abc

from . import loopbackedtestcase
from blivet.errors import FSError, FSReadLabelError
from blivet.size import Size


class LabelingAsRoot(loopbackedtestcase.LoopBackedTestCase, metaclass=abc.ABCMeta):

    """Tests various aspects of labeling a filesystem where there
       is no easy way to read the filesystem's label once it has been
       set and where the filesystem can not be relabeled.
    """

    _fs_class = abc.abstractproperty(
        doc="The class of the filesystem being tested on.")

    _invalid_label = abc.abstractproperty(
        doc="A label which is invalid for this filesystem.")

    _DEVICE_SIZE = Size("100 MiB")

    def __init__(self, methodName='run_test'):
        super(LabelingAsRoot, self).__init__(methodName=methodName, device_spec=[self._DEVICE_SIZE])

    def setUp(self):
        an_fs = self._fs_class()
        if not an_fs.formattable:
            self.skipTest("can not create filesystem %s" % an_fs.name)
        if not an_fs.labeling():
            self.skipTest("can not label filesystem %s" % an_fs.name)
        super(LabelingAsRoot, self).setUp()

    def test_labeling(self):
        """A sequence of tests of filesystem labeling.

           * create the filesystem when passing an invalid label
           * raise an exception when reading the filesystem
           * raise an exception when relabeling the filesystem
        """
        an_fs = self._fs_class(device=self.loop_devices[0], label=self._invalid_label)
        if an_fs._readlabel.availability_errors or not an_fs.relabels():
            self.skipTest("can not read or write label for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())

        with self.assertRaises(FSReadLabelError):
            an_fs.read_label()

        an_fs.label = "an fs"
        with self.assertRaises(FSError):
            an_fs.write_label()

    def test_creating(self):
        """Create the filesystem when passing a valid label """
        an_fs = self._fs_class(device=self.loop_devices[0], label="start")
        self.assertIsNone(an_fs.create())

    def test_creating_none(self):
        """Create the filesystem when passing None
           (indicates filesystem default)
        """
        an_fs = self._fs_class(device=self.loop_devices[0], label=None)
        self.assertIsNone(an_fs.create())

    def test_creating_empty(self):
        """Create the filesystem when passing the empty label."""
        an_fs = self._fs_class(device=self.loop_devices[0], label="")
        self.assertIsNone(an_fs.create())


class LabelingWithRelabeling(LabelingAsRoot):

    """Tests labeling where it is possible to relabel.
    """

    def test_labeling(self):
        """A sequence of tests of filesystem labeling.

           * create the filesystem when passing an invalid label
           * raise an exception when reading the filesystem
           * relabel the filesystem with a valid label
           * relabel the filesystem with an empty label
           * raise an exception when relabeling when None is specified
           * raise an exception when relabeling with an invalid label
        """
        an_fs = self._fs_class(device=self.loop_devices[0], label=self._invalid_label)
        if an_fs._readlabel.availability_errors or not an_fs.relabels():
            self.skipTest("can not read or write label for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())

        with self.assertRaises(FSReadLabelError):
            an_fs.read_label()

        an_fs.label = "an fs"
        self.assertIsNone(an_fs.write_label())

        an_fs.label = ""
        self.assertIsNone(an_fs.write_label())

        an_fs.label = None
        with self.assertRaisesRegex(FSError, "default label"):
            an_fs.write_label()

        an_fs.label = self._invalid_label
        with self.assertRaisesRegex(FSError, "bad label format"):
            an_fs.write_label()


class CompleteLabelingAsRoot(LabelingAsRoot):

    """Tests where it is possible to read the label and to relabel
       an existing filesystem.
    """

    def test_labeling(self):
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
        an_fs = self._fs_class(device=self.loop_devices[0], label=self._invalid_label)
        if an_fs._readlabel.availability_errors or not an_fs.relabels():
            self.skipTest("can not read or write label for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.read_label(), self._default_label)

        an_fs.label = "an_fs"
        self.assertIsNone(an_fs.write_label())
        if an_fs.type in ("vfat", "efi"):
            self.assertEqual(an_fs.read_label(), an_fs.label.upper())
        else:
            self.assertEqual(an_fs.read_label(), an_fs.label)

        an_fs.label = ""
        self.assertIsNone(an_fs.write_label())
        self.assertEqual(an_fs.read_label(), an_fs.label)

        an_fs.label = None
        with self.assertRaisesRegex(FSError, "default label"):
            an_fs.write_label()

        an_fs.label = "n" * 129
        with self.assertRaisesRegex(FSError, "bad label format"):
            an_fs.write_label()

    def test_creating(self):
        """Create the filesystem when passing a valid label.
           Verify that the filesystem has that label.
        """
        an_fs = self._fs_class(device=self.loop_devices[0], label="start")
        if an_fs._readlabel.availability_errors:
            self.skipTest("can not read label for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())
        if an_fs.type in ("vfat", "efi"):
            self.assertEqual(an_fs.read_label(), "START")
        else:
            self.assertEqual(an_fs.read_label(), "start")

    def test_creating_none(self):
        """Create a filesystem with the label None.
           Verify that the filesystem has the default label.
        """
        an_fs = self._fs_class(device=self.loop_devices[0], label=None)
        if an_fs._readlabel.availability_errors:
            self.skipTest("can not read label for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.read_label(), self._default_label)

    def test_creating_empty(self):
        """Create a filesystem with an empty label.
           Verify that the filesystem has the empty label.
        """
        an_fs = self._fs_class(device=self.loop_devices[0], label="")
        if an_fs._readlabel.availability_errors:
            self.skipTest("can not read label for filesystem %s" % an_fs.name)
        self.assertIsNone(an_fs.create())
        self.assertEqual(an_fs.read_label(), "")
