import test_compat  # pylint: disable=unused-import

import os
from six.moves.mock import Mock, patch, sentinel  # pylint: disable=no-name-in-module,import-error
import unittest

import libmount

from blivet.formats import get_format
from blivet.fstab import FSTab


class FSTabTestCase(unittest.TestCase):
    def test_init(self):
        with patch.object(FSTab, 'read_table') as read_table:
            tb = FSTab()
            read_table.assert_called_once_with()

    def test_read_table(self):
        with patch('blivet.fstab.Table') as tblcls:
            tb = FSTab()

            tblcls.reset_mock()
            tb.read_table()
            tblcls.assert_called_once_with()
            tb._table.parse_fstab.assert_called_once_with()

            fn = '/etc/alttab'
            tb = FSTab(filename=fn)
            tblcls.reset_mock()
            tb.read_table()
            tblcls.assert_called_once_with()
            tb._table.parse_fstab.assert_called_once_with(fstab=fn)

        # given a non-existent path to the fstab, assert that there are no entries
        fn = '/etc/alttab'
        tb = FSTab(filename=fn)
        self.assertIsNone(next(tb, None))

    def test_write_fstab(self):
        with patch('blivet.fstab.Table') as tblcls:
            tb = FSTab()

            tb.write_fstab()
            tb._table.replace_file.assert_called_once_with('/etc/fstab')

            tblcls.reset_mock()
            fn = '/etc/alttab'
            self.assertFalse(os.path.exists(fn))
            tb.write_fstab(filename=fn)
            tb._table.write_file.assert_called_once_with(fn)

            fn2 = '/etc/alttab2'
            tb = FSTab(filename=fn2)
            tblcls.reset_mock()
            self.assertFalse(os.path.exists(fn2))
            tb.write_fstab()
            tb._table.write_file.assert_called_once_with(fn2)

            tblcls.reset_mock()
            self.assertFalse(os.path.exists(fn))
            tb.write_fstab(filename=fn)
            tb._table.write_file.assert_called_once_with(fn)

    def test_add_entry(self):
        fn = '/etc/alttab'
        tb = FSTab(filename=fn)
        self.assertIsNone(next(tb, None))

        dev1 = Mock(name='dev1')
        dev1.fstab_spec = 'LABEL=dev`'
        dev1.format = get_format("xfs")

        # refuse to add fs entry w/o mountpoint
        fs = tb.add_entry(dev1)
        self.assertIsNone(fs)
        self.assertEqual(len(list(tb)), 0)

        # add it w/ mountpoint
        dev1.format.mountpoint = '/opt/dev1'
        fs = tb.add_entry(dev1)
        self.assertEqual(len(list(tb)), 1)
        self.assertEqual(fs.source, dev1.fstab_spec)
        self.assertEqual(fs.target, dev1.format.mountpoint)
        self.assertEqual(fs.fstype, dev1.format.type)
        self.assertEqual(fs.options, dev1.format.options or "defaults")

        # add swap entry
        dev2 = Mock(name='dev2')
        dev2.fstab_spec = 'LABEL=dev2`'
        dev2.format = get_format("swap", options="pri=1,discard=pages,nofail")
        fs = tb.add_entry(dev2)

        self.assertEqual(len(list(tb)), 2)
        self.assertEqual(fs.source, dev2.fstab_spec)
        self.assertEqual(fs.target, "swap")
        self.assertEqual(fs.fstype, dev2.format.type)
        self.assertEqual(fs.options, dev2.format.options or "defaults")

    def test_remove_entry(self):
        pass
