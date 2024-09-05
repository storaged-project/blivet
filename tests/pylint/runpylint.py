#!/usr/bin/python3

import atexit
import shutil
import sys
import tempfile
import os

from censorship import CensorshipConfig, CensorshipLinter, FalsePositive


class BlivetLintConfig(CensorshipConfig):
    def __init__(self):
        super().__init__()

        current_dir = os.path.dirname(os.path.realpath(__file__))

        self.pylintrc_path = os.path.join(current_dir, "pylintrc")

        self.false_positives = [
            FalsePositive(r"Instance of 'int' has no .* member"),
            FalsePositive(r"Method 'do_task' is abstract in class 'Task' but is not overridden"),
            FalsePositive(r"Method 'do_task' is abstract in class 'UnimplementedTask' but is not overridden"),
            FalsePositive(r"No value for argument 'member_count' in unbound method call$"),
            FalsePositive(r"No value for argument 'smallest_member_size' in unbound method call$"),
            FalsePositive(r"Bad option value '(subprocess-popen-preexec-fn|try-except-raise|environment-modify|arguments-renamed|redundant-u-string-prefix|possibly-used-before-assignment)'"),
            FalsePositive(r"Instance of '(Action.*Device|Action.*Format|Action.*Member|Device|DeviceAction|DeviceFormat|Event|ObjectID|PartitionDevice|StorageDevice|BTRFS.*Device|LoopDevice)' has no 'id' member$"),
            FalsePositive(r"Instance of 'GError' has no 'message' member"),  # overriding currently broken local pylint disable
            FalsePositive(r"No name '.*' in module 'libmount'"),
            FalsePositive(r"Unknown option value for 'disable', expected a valid pylint message and got 'possibly-used-before-assignment'")
        ]

    def _files(self):
        srcdir = os.environ.get("top_srcdir", os.getcwd())

        retval = self._get_py_paths(srcdir)

        return sorted(retval)

    def _get_py_paths(self, directory):
        retval = []

        for (root, _dirnames, files) in os.walk(directory):

            # skip scanning of already added python modules
            skip = False
            for i in retval:
                if root.startswith(i):
                    skip = True
                    break

            if skip:
                continue

            if "__init__.py" in files:
                retval.append(root)
                continue

            for f in files:
                try:
                    with open(root + "/" + f) as fo:
                        lines = fo.readlines()
                except UnicodeDecodeError:
                    # If we couldn't open this file, just skip it.  It wasn't
                    # going to be valid python anyway.
                    continue

                # Test any file that either ends in .py or contains #!/usr/bin/python
                # in the first line.
                if f.endswith(".py") or (lines and str(lines[0]).startswith("#!/usr/bin/python")):
                    retval.append(root + "/" + f)

        return retval

    @property
    def check_paths(self):
        return self._files()


def setup_environment():
    # We need top_builddir to be set so we know where to put the pylint analysis
    # stuff.  Usually this will be set up if we are run via "make test" but if
    # not, hope that we are at least being run out of the right directory.
    builddir = os.environ.get("top_builddir", os.getcwd())

    # XDG_RUNTIME_DIR is "required" to be set, so make one up in case something
    # actually tries to do something with it.
    if "XDG_RUNTIME_DIR" not in os.environ:
        d = tempfile.mkdtemp()
        os.environ["XDG_RUNTIME_DIR"] = d  # pylint: disable=environment-modify
        atexit.register(_del_xdg_runtime_dir)

    # Unset TERM so that things that use readline don't output terminal garbage.
    if "TERM" in os.environ:
        os.environ.pop("TERM")  # pylint: disable=environment-modify

    # Don't try to connect to the accessibility socket.
    os.environ["NO_AT_BRIDGE"] = "1"  # pylint: disable=environment-modify

    # Force the GDK backend to X11.  Otherwise if no display can be found, Gdk
    # tries every backend type, which includes "broadway", which prints an error
    # and keeps changing the content of said error.
    os.environ["GDK_BACKEND"] = "x11"  # pylint: disable=environment-modify

    # Save analysis data in the pylint directory.
    os.environ["PYLINTHOME"] = builddir + "/tests/pylint/.pylint.d"  # pylint: disable=environment-modify
    if not os.path.exists(os.environ["PYLINTHOME"]):
        os.mkdir(os.environ["PYLINTHOME"])


def _del_xdg_runtime_dir():
    shutil.rmtree(os.environ["XDG_RUNTIME_DIR"])


if __name__ == "__main__":
    setup_environment()
    conf = BlivetLintConfig()
    linter = CensorshipLinter(conf)
    rc = linter.run()
    sys.exit(rc)
