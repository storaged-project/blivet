#!/usr/bin/python3

from __future__ import print_function

import os
import six
import sys
import argparse
import unittest


if __name__ == '__main__':
    testdir = os.path.abspath(os.path.dirname(__file__))
    projdir = os.path.abspath(os.path.normpath(os.path.join(testdir, '..')))

    suite = unittest.TestSuite()

    if 'PYTHONPATH' not in os.environ:
        os.environ['PYTHONPATH'] = projdir  # pylint: disable=environment-modify

        try:
            pyver = 'python3' if six.PY3 else 'python'
            os.execv(sys.executable, [pyver] + sys.argv)
        except OSError as e:
            print('Failed re-exec with a new PYTHONPATH: %s' % str(e))
            sys.exit(1)

    argparser = argparse.ArgumentParser(description="Blivet test suite")
    argparser.add_argument("testname", nargs="*",
                           help="name of test class or method (e. g. 'devices_test' or 'formats_test.fs_test.Ext2FSTestCase'")
    args = argparser.parse_args()

    testdir = os.path.abspath(os.path.dirname(__file__))

    import blivet
    print("Running tests with Blivet %s from %s" % (blivet.__version__,
                                                    os.path.abspath(os.path.dirname(blivet.__file__))),
          file=sys.stderr)

    if args.testname:
        for n in args.testname:
            suite.addTests(unittest.TestLoader().loadTestsFromName(n))
    else:
        # Load all files in this directory whose name ends with '_test.py'
        for test_cases in unittest.defaultTestLoader.discover(testdir, pattern="*_test.py"):
            suite.addTest(test_cases)

    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if result.wasSuccessful():
        sys.exit(0)
    else:
        sys.exit(1)
