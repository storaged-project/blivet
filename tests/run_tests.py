#!/usr/bin/python3

from __future__ import print_function

import os
import six
import sys
import argparse
import unittest


def _get_tests_from_suite(test_suite, extracted_tests):
    """ Extract tests from the test suite """
    # 'tests' we get from 'unittest.defaultTestLoader.discover' are "wrapped"
    # in multiple 'unittest.suite.TestSuite' classes/lists so we need to "unpack"
    # the individual test cases
    for test_case in test_suite:
        if isinstance(test_case, unittest.suite.TestSuite):
            _get_tests_from_suite(test_case, extracted_tests)

        if isinstance(test_case, unittest.TestCase):
            extracted_tests.add(test_case)

    return extracted_tests


if __name__ == '__main__':
    testdir = os.path.abspath(os.path.dirname(__file__))
    projdir = os.path.abspath(os.path.normpath(os.path.join(testdir, '..')))

    loader = unittest.defaultTestLoader
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
        test_cases = loader.loadTestsFromNames(args.testname)
    else:
        test_cases = loader.discover(start_dir=testdir, pattern='*_test*.py')

    tests = set()
    tests = _get_tests_from_suite(test_cases, tests)
    tests = sorted(tests, key=lambda test: test.id())

    for test in tests:
        suite.addTest(test)

    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if result.wasSuccessful():
        sys.exit(0)
    else:
        sys.exit(1)
