import os


def pytest_ignore_collect(path, config):  # pylint: disable=unused-argument
    # we want to ignore symlinks in tests/devicelibs_test/edd_data/
    #  which cause pytest to end in an infinite loop
    if os.path.islink(path):
        return True
