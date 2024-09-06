#!/usr/bin/python3

from __future__ import print_function

import argparse
import csv
import dbus
import os
import pdb
import re
import subprocess
import sys
import traceback
import unittest
import yaml


SKIP_CONFIG = 'skip.yml'


def run_command(command, cmd_input=None):
    res = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, stdin=subprocess.PIPE)

    out, err = res.communicate(input=cmd_input)
    return (res.returncode, out.decode().strip(), err.decode().strip())


def get_version_from_lsb():
    ret, out, err = run_command("lsb_release -rs")
    if ret != 0:
        raise RuntimeError("Cannot get distro version from lsb_release output: '%s %s'" % (out, err))

    return out.split(".")[0]


def get_version_from_pretty_name(pretty_name):
    """ Try to get distro and version from 'OperatingSystemPrettyName'
        hostname property.

        It should look like this:
         - "Debian GNU/Linux 9 (stretch)"
         - "Fedora 27 (Workstation Edition)"
         - "CentOS Linux 7 (Core)"

        So just return first word as distro and first number as version.
    """
    distro = pretty_name.split()[0].lower()
    match = re.search(r"\d+", pretty_name)
    if match is not None:
        version = match.group(0)
    else:
        version = get_version_from_lsb()

    return (distro, version)


def get_version_from_cpe(cpe):
    """ Try to get distro and version from 'OperatingSystemCPEName'
        hostname property.

        It should look like this:
         - "cpe:/o:fedoraproject:fedora:39"
         - "cpe:/o:redhat:enterprise_linux:7.3:GA:server
    """
    # 2nd to 4th fields from e.g. "cpe:/o:fedoraproject:fedora:25" or "cpe:/o:redhat:enterprise_linux:7.3:GA:server"
    _project, distro, version = tuple(cpe.split(":")[2:5])
    version = str(int(float(version)))
    return (distro, version)


def get_version_from_dbus():
    """ Try to get distro and version from dbus
    """

    bus = dbus.SystemBus()

    # get information about the distribution from systemd (hostname1)
    sys_info = bus.get_object("org.freedesktop.hostname1", "/org/freedesktop/hostname1")

    cpe = str(sys_info.Get("org.freedesktop.hostname1", "OperatingSystemCPEName", dbus_interface=dbus.PROPERTIES_IFACE))
    if cpe:
        return get_version_from_cpe(cpe)

    pretty_name = str(sys_info.Get("org.freedesktop.hostname1", "OperatingSystemPrettyName", dbus_interface=dbus.PROPERTIES_IFACE))
    if pretty_name:
        return get_version_from_pretty_name(pretty_name)

    raise RuntimeError("Failed to get distro and version from DBus")


def get_version_from_os():
    """ Try to get distro and version from /etc/os-release
    """
    if not os.path.isfile("/etc/os-release"):
        raise RuntimeError("/etc/os-release does not exist")

    with open('/etc/os-release') as csvfile:
        reader = csv.reader(csvfile, delimiter='=')
        release = dict(reader)

    if 'CPE_NAME' in release.keys():
        return get_version_from_cpe(release['CPE_NAME'])
    elif 'PRETTY_NAME' in release.keys():
        return get_version_from_cpe(release['PRETTY_NAME'])
    elif 'ID' in release.keys() and 'VERSION_ID' in release.keys():
        return (release['ID'], release['VERSION_ID'])

    raise RuntimeError("Failed to get distro and version from /etc/os-release")


def get_version():
    try:
        return get_version_from_dbus()
    except Exception as err:  # pylint: disable=broad-except
        print(err)

    try:
        return get_version_from_os()
    except Exception as err:  # pylint: disable=broad-except
        print(err)

    raise RuntimeError("Failed to get distro and version")


def _should_skip(distro=None, version=None, arch=None, reason=None):  # pylint: disable=unused-argument
    # all these can be lists or a single value, so convert everything to list
    if distro is not None and type(distro) is not list:
        distro = [distro]
    if version is not None and type(version) is not list:
        version = [version]
    if arch is not None and type(arch) is not list:
        arch = [arch]

    # DISTRO, VERSION and ARCH variables are set in main, we don't need to
    # call hostnamectl etc. for every test run
    if ((distro is None or DISTRO in distro) and (version is None or VERSION in version) and  # pylint: disable=used-before-assignment,possibly-used-before-assignment
       (arch is None or ARCH in arch)):  # pylint: disable=used-before-assignment,possibly-used-before-assignment
        return True

    return False


def _parse_skip_config(config):
    with open(config) as f:
        data = f.read()
    parsed = yaml.load(data, Loader=yaml.SafeLoader)

    skipped_tests = dict()
    if parsed is None:
        # empty skip.yml
        return skipped_tests

    for entry in parsed:
        for skip in entry["skip_on"]:
            if _should_skip(**skip):
                skipped_tests[entry["test"]] = skip["reason"]

    return skipped_tests


def _split_test_id(tid):
    # test.id() looks like 'crypto_test.CryptoTestResize.test_luks2_resize'
    # and we want to print 'test_luks2_resize (crypto_test.CryptoTestResize)'
    tdesc = tid.split(".")
    tname = tdesc[-1]
    tmodule = ".".join(tdesc[:-1])

    return tname, tmodule


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


class DebugTestResult(unittest.TextTestResult):

    def addError(self, test, err):  # pylint: disable=redefined-outer-name
        traceback.print_exception(*err)
        pdb.post_mortem(err[2])
        super(DebugTestResult, self).addError(test, err)

    def addFailure(self, test, err):  # pylint: disable=redefined-outer-name
        traceback.print_exception(*err)
        pdb.post_mortem(err[2])
        super(DebugTestResult, self).addFailure(test, err)


if __name__ == '__main__':
    testdir = os.path.abspath(os.path.dirname(__file__))
    projdir = os.path.abspath(os.path.normpath(os.path.join(testdir, '..')))

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()

    if 'PYTHONPATH' not in os.environ:
        os.environ['PYTHONPATH'] = projdir  # pylint: disable=environment-modify

        try:
            os.execv(sys.executable, ['python3'] + sys.argv)
        except OSError as e:
            print('Failed re-exec with a new PYTHONPATH: %s' % str(e))
            sys.exit(1)

    argparser = argparse.ArgumentParser(description="Blivet test suite")
    argparser.add_argument("testname", nargs="*",
                           help="name of test class or method (e. g. 'devices_test' or 'formats_test.fs_test.Ext2FSTestCase'")
    argparser.add_argument("-p", "--pdb", dest="pdb", help="run pdb after a failed test", action="store_true")
    argparser.add_argument("-s", "--stop", dest="stop", help="stop executing after first failed test", action="store_true")
    args = argparser.parse_args()

    testdir = os.path.abspath(os.path.dirname(__file__))

    import blivet
    print("Running tests with Blivet %s from %s" % (blivet.__version__,
                                                    os.path.abspath(os.path.dirname(blivet.__file__))),
          file=sys.stderr)

    # get distro and arch here so we don't have to do this for every test
    DISTRO, VERSION = get_version()
    ARCH = os.uname()[-1]

    # get list of tests to skip from the config file
    skipping = _parse_skip_config(os.path.join(testdir, SKIP_CONFIG))

    if args.testname:
        test_cases = loader.loadTestsFromNames(args.testname)
    else:
        test_cases = loader.discover(start_dir=testdir, pattern='*_test*.py')

    tests = set()
    tests = _get_tests_from_suite(test_cases, tests)
    tests = sorted(tests, key=lambda test: test.id())

    for test in tests:
        test_id = test.id()

        # check if the test is in the list of tests to skip
        skip_id = next((test_pattern for test_pattern in skipping.keys() if re.search(test_pattern, test_id)), None)
        if skip_id:
            test_name, test_module = _split_test_id(test_id)
            reason_str = "not supported on this distribution in this version and arch: %s" % skipping[skip_id]
            print("%s (%s)\n%s ... skipped '%s'" % (test_name, test_module,
                                                    test._testMethodDoc, reason_str),
                  file=sys.stderr)
            continue

        suite.addTest(test)

    if args.pdb:
        runner = unittest.TextTestRunner(verbosity=2, failfast=args.stop, resultclass=DebugTestResult)
    else:
        runner = unittest.TextTestRunner(verbosity=2, failfast=args.stop)

    result = runner.run(suite)

    if result.wasSuccessful():
        sys.exit(0)
    else:
        sys.exit(1)
