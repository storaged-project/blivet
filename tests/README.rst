Testing Blivet
==============

Note: The test suite documented here is available only from the git repository
not as part of any installable packages.

In order to execute blivet's test suite from inside the source directory execute
the command::

    make test

There are three separate test suites available:

- *Unit tests* located in the `unit_tests` folder. These tests don't require
  root privileges to run and don't use any existing block devices.
  These tests can be run separately using `make unit-test`.
- *Storage tests* located in the `storage_tests` folder. These tests require
  root privileges and create block devices to run tests on. These tests can
  be run separately using `make storage-test`.
- *VM tests* located in the `vmtests` folder. These test are not run by
  default and require a special virtual machine to run in.

Tests descending from :class:`~.imagebackedtestcase.ImageBackedTestCase` or
:class:`~.loopbackedtestcase.LoopBackedTestCase` require root access on the
system and will be skipped if you're running as non-root user.
Tests descending from :class:`~.imagebackedtestcase.ImageBackedTestCase` will
also be skipped if the environment variable JENKINS_HOME is not defined. If
you'd like to execute them use the following commands (as root)::

    # export JENKINS_HOME=`pwd`
    # make test

To execute the Pylint code analysis tool run::

    make check

Running Pylint doesn't require root privileges but requires Python3 due to usage
of pocket-lint.

It is also possible to generate test coverage reports using the Python coverage
tool. To do that execute::

    make coverage

It is also possible to check all external links in the documentation for
integrity. To do this::

    cd doc/
    make linkcheck

Test Suite Architecture
------------------------

Blivet's test suite relies on several base classes listed below. All test cases
inherit from them.

- :class:`unittest.TestCase` - the standard unit test class in Python.
  Used for tests which don't touch disk space;


- :class:`~tests.storagetestcase.StorageTestCase` - intended as a base class for
  higher-level tests. Most of what it does is stub out operations that touch
  disks. Currently it is only used in
  :class:`~tests.action_test.DeviceActionTestCase`;


- :class:`~tests.loopbackedtestcase.LoopBackedTestCase` and
  :class:`~tests.imagebackedtestcase.ImageBackedTestCase` - both classes
  represent actual storage space.
  :class:`~tests.imagebackedtestcase.ImageBackedTestCase` uses the same stacks
  as anaconda disk image installations. These mimic normal disks more closely
  than using loop devices directly. Usually
  :class:`~tests.loopbackedtestcase.LoopBackedTestCase` is used for stacks of
  limited depth (eg: md array with two loop members) and
  :class:`~tests.imagebackedtestcase.ImageBackedTestCase` for stacks of greater
  or arbitrary depth.


In order to get a high level view of how test classes inherit from each other
you can generate an inheritance diagram::

    PYTHONPATH=.:tests/ python3-pyreverse -p "Blivet_Tests" -o svg -SkAmy tests/
