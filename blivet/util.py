import copy
import functools
import glob
import itertools
import os
import subprocess
import re
import sys
import tempfile
import uuid
import hashlib
import warnings
import abc
from decimal import Decimal
from contextlib import contextmanager
from functools import wraps
from collections import namedtuple
from enum import Enum

from .errors import DependencyError
from . import safe_dbus

import gi
gi.require_version("BlockDev", "3.0")

from gi.repository import BlockDev as blockdev

import logging
log = logging.getLogger("blivet")
program_log = logging.getLogger("program")
testdata_log = logging.getLogger("testdata")
console_log = logging.getLogger("blivet.console")

from threading import Lock
# this will get set to anaconda's program_log_lock in enable_installer_mode
program_log_lock = Lock()

try:
    import selinux
except ImportError:
    HAVE_SELINUX = False
else:
    HAVE_SELINUX = True


SYSTEMD_SERVICE = "org.freedesktop.systemd1"
SYSTEMD_MANAGER_PATH = "/org/freedesktop/systemd1"
SYSTEMD_MANAGER_IFACE = "org.freedesktop.systemd1.Manager"
VIRT_PROP_NAME = "Virtualization"


class Path(str):

    """ Path(path, root=None) provides a filesystem path object, which
        automatically normalizes slashes, assumes appends are what you
        always hoped os.path.join() was (but with out the weird slash
        games), and can easily handle paths with a root directory other
        than /
    """
    _root = None
    _path = None

    def __new__(cls, path, *args, **kwds):
        root = kwds.pop("root", None)
        obj = str.__new__(cls, path, *args, **kwds)
        obj._path = path
        obj._root = None
        if root is not None:
            obj.newroot(str(root))
        return obj

    @property
    def ondisk(self):
        """ Path.ondisk evaluates as the real filesystem path of the path,
            including the path's root in the data.
        """
        if self.root:
            return normalize_path_slashes(Path(self.root) + Path(self.path))
        else:
            return Path(self.path)

    @property
    def path(self):
        return self._path

    @property
    def normpath(self):
        return Path(os.path.normpath(str(self.path)), root=self.root)

    @property
    def realpath(self):
        rp = os.path.realpath(self.ondisk)
        return Path(rp, root=self.root)

    @property
    def root(self):
        return self._root

    def newroot(self, newroot=None):
        """ Change the root directory of this Path """
        if newroot is None:
            self._root = None
        else:
            self._root = normalize_path_slashes(newroot)
            if self.startswith(self._root):
                path = self._path[len(self._root):]
                self._path = normalize_path_slashes(path)
        return self

    def __str__(self):
        return str(self.path)

    def __repr__(self):
        return repr(str(self.path))

    def __getitem__(self, idx):
        ret = str(self)
        return ret.__getitem__(idx)

    def __add__(self, other):
        if isinstance(other, Path):
            if other.root is not None and other.root != "/":
                if self.root is None:
                    self._root = other.root
                elif other.root != self.root:
                    raise ValueError("roots <%s> and <%s> don't match." %
                                     (self.root, other.root))
            path = "%s/%s" % (self.path, other.path)
        else:
            path = "%s/%s" % (self.path, other)
        path = normalize_path_slashes(path)
        return Path(path, root=self.root)

    def __eq__(self, other):
        if isinstance(other, Path):
            return self.path == other.path
        else:
            return self.path == str(other)

    def __lt__(self, other):
        if isinstance(other, Path):
            return self.path < other.path
        else:
            return self.path < str(other)

    def __gt__(self, other):
        if isinstance(other, Path):
            return self.path > other.path
        else:
            return self.path > str(other)

    def startswith(self, other):
        return self._path.startswith(str(other))

    def glob(self):
        """ Similar to glob.glob(), except it takes the Path's root into
            account when globbing and returns path objects with the same
            root, so you don't have to think about that part.
        """

        testdata_log.debug("glob: %s", self.ondisk)
        if "None" in self.ondisk:
            log.error("glob: %s", self.ondisk)
            log.error("^^ Somehow \"None\" got logged and that's never right.")
        for g in glob.glob(self.ondisk):
            testdata_log.debug("glob match: %s", g)
            yield Path(g, root=self.root)

    def __hash__(self):
        return self._path.__hash__()


def _run_program(argv, root='/', stdin=None, env_prune=None, stderr_to_stdout=False, binary_output=False):
    if env_prune is None:
        env_prune = []

    def chroot():
        if root and root != '/':
            os.chroot(root)

    with program_log_lock:  # pylint: disable=not-context-manager
        program_log.info("Running... %s", " ".join(argv))

        env = os.environ.copy()
        env.update({"LC_ALL": "C",
                    "INSTALL_PATH": root})
        for var in env_prune:
            env.pop(var, None)

        if stderr_to_stdout:
            stderr_dir = subprocess.STDOUT
        else:
            stderr_dir = subprocess.PIPE
        try:
            proc = subprocess.Popen(argv,  # pylint: disable=subprocess-popen-preexec-fn
                                    stdin=stdin,
                                    stdout=subprocess.PIPE,
                                    stderr=stderr_dir,
                                    close_fds=True,
                                    preexec_fn=chroot, cwd=root, env=env)

            out, err = proc.communicate()
            if not binary_output:
                out = out.decode("utf-8")
            if out:
                if not stderr_to_stdout:
                    program_log.info("stdout:")
                for line in out.splitlines():
                    program_log.info("%s", line)

            if not stderr_to_stdout and err:
                program_log.info("stderr:")
                for line in err.splitlines():
                    program_log.info("%s", line)

        except OSError as e:
            program_log.error("Error running %s: %s", argv[0], e.strerror)
            raise

        program_log.debug("Return code: %d", proc.returncode)

    return (proc.returncode, out)


def run_program(*args, **kwargs):
    return _run_program(*args, **kwargs)[0]


def capture_output(*args, **kwargs):
    return _run_program(*args, **kwargs)[1]


def capture_output_binary(*args, **kwargs):
    kwargs["binary_output"] = True
    return _run_program(*args, **kwargs)[1]


def run_program_and_capture_output(*args, **kwargs):
    return _run_program(*args, **kwargs)


def run_program_and_capture_output_binary(*args, **kwargs):
    kwargs["binary_output"] = True
    return _run_program(*args, **kwargs)


def mount(device, mountpoint, fstype, options=None):
    if options is None:
        options = "defaults"

    mountpoint = os.path.normpath(mountpoint)
    if not os.path.isdir(mountpoint):
        makedirs(mountpoint)

    argv = ["mount", "-t", fstype, "-o", options, device, mountpoint]
    return run_program(argv)


def umount(mountpoint):
    return run_program(["umount", mountpoint])


def get_mount_paths(dev):
    """ Given a device node path, return a list of all active mountpoints.

        :param str dev: Device path
        :returns: A list of mountpoints or []
        :rtype: list
    """
    from .mounts import mounts_cache

    mount_paths = mounts_cache.get_mountpoints(dev)
    if mount_paths:
        log.debug("%s is mounted on %s", dev, ', '.join(mount_paths))
    return mount_paths


def get_mount_device(mountpoint):
    """ Given a mountpoint, return the device node path mounted there. """
    mountpoint = os.path.realpath(mountpoint)  # eliminate symlinks
    mount_device = None
    with open("/proc/mounts") as mounts:
        for mnt in mounts.readlines():
            try:
                (device, path, _rest) = mnt.split(None, 2)
            except ValueError:
                continue

            if path == mountpoint:
                mount_device = device
                break

    if mount_device and re.match(r'/dev/loop\d+$', mount_device):
        loop_name = os.path.basename(mount_device)
        try:
            info = blockdev.loop.info(loop_name)
        except blockdev.LoopError as e:
            log.warning("failed to get loop info for %s: %s", loop_name, str(e))
            return None
        mount_device = info.backing_file
        log.debug("found backing file %s for loop device %s", mount_device,
                  loop_name)

    if mount_device:
        log.debug("%s is mounted on %s", mount_device, mountpoint)

    return mount_device


def total_memory():
    """Return the amount of system RAM.

        Returns total system RAM in kB (given to us by /proc/meminfo).

        :rtype: :class:`~.size.Size`
    """
    # import locally to avoid a cycle with size importing util
    from .size import Size

    with open("/proc/meminfo", "r") as fobj:
        for line in fobj:
            if not line.startswith("MemTotal"):
                # we are only interested in the MemTotal: line
                continue

            fields = line.split()
            if len(fields) != 3:
                log.warning("unknown format for MemTotal line in /proc/meminfo: %s", line.rstrip())
                continue

            try:
                mem = Size("%s KiB" % fields[1])
            except ValueError:
                log.warning("invalid value of MemTotal /proc/meminfo: %s", fields[1])
                continue

            # Because /proc/meminfo only gives us the MemTotal (total physical RAM
            # minus the kernel binary code), we need to round this up. Assuming
            # every machine has the total RAM MiB number divisible by 128.
            bs = Size("128MiB")
            mem = (mem / bs + 1) * bs
            return mem

        raise RuntimeError("no valid line with MemTotal found in /proc/meminfo")


def available_memory():
    """ Return the amount of system RAM that is currently available.

        :rtype: :class:`~.size.Size`
    """
    # import locally to avoid a cycle with size importing util
    from .size import Size

    with open("/proc/meminfo") as lines:
        mems = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in lines)}

    if "MemAvailable" in mems.keys():
        return Size("%s KiB" % mems["MemAvailable"].split()[0])
    else:
        # MemAvailable is not present on linux < 3.14
        free = Size("%s KiB" % mems["MemFree"].split()[0])
        cached = Size("%s KiB" % mems["Cached"].split()[0])
        buffers = Size("%s KiB" % mems["Buffers"].split()[0])

        return (free + cached + buffers)


##
# sysfs functions
##


def normalize_path_slashes(path):
    """ Normalize the slashes in a filesystem path.
        Does not actually examine the filesystem in any way.
    """
    while "//" in path:
        path = path.replace("//", "/")
    return path


def join_paths(*paths):
    """ Joins filesystem paths without any consideration of slashes or
        whatnot and then normalizes repeated slashes.
    """
    if len(paths) == 1 and hasattr(paths[0], "__iter__"):
        return join_paths(*paths[0])
    return normalize_path_slashes('/'.join(paths))


def get_sysfs_attr(path, attr, root=None):
    if not attr:
        log.debug("get_sysfs_attr() called with attr=None")
        return None
    if not isinstance(path, Path):
        path = Path(path=path, root=root)
    elif root is not None:
        path.newroot(root)

    attribute = path + attr
    fullattr = os.path.realpath(attribute.ondisk)

    if not os.path.isfile(fullattr) and not os.path.islink(fullattr):
        log.warning("%s is not a valid attribute", attr)
        return None

    f = open(fullattr, "r", encoding="utf-8", errors="replace")
    data = f.read()
    f.close()
    sdata = "".join(["%02x" % (ord(x),) for x in data])
    testdata_log.debug("sysfs attr %s: %s", attribute, sdata)
    return data.strip()


def sysfs_readlink(path, link, root=None):
    if not link:
        log.debug("sysfs_readlink() called with link=None")
    if isinstance(path, Path):
        linkpath = path + link
    else:
        linkpath = Path(path, root=root) + link

    linkpath = Path(os.path.normpath(linkpath), root=linkpath.root)
    fullpath = os.path.normpath(linkpath.ondisk)

    if not os.path.islink(fullpath):
        log.warning("%s is not a valid symlink", linkpath)
        return None

    output = os.readlink(fullpath)
    testdata_log.debug("new sysfs link: \"%s\" -> \"%s\"", linkpath, output)
    return output


def get_sysfs_path_by_name(dev_node, class_name="block"):
    """ Return sysfs path for a given device.

        For a device node (e.g. /dev/vda2) get the respective sysfs path
        (e.g. /sys/class/block/vda2). This also has to work for device nodes
        that are in a subdirectory of /dev like '/dev/cciss/c0d0p1'.
     """
    dev_name = os.path.basename(dev_node)
    if dev_node.startswith("/dev/"):
        dev_name = dev_node[5:].replace("/", "!")
    sysfs_class_dir = "/sys/class/%s" % class_name
    dev_path = os.path.join(sysfs_class_dir, dev_name)
    if os.path.exists(dev_path):
        return dev_path
    else:
        raise RuntimeError("get_sysfs_path_by_name: Could not find sysfs path "
                           "for '%s' (it is not at '%s')" % (dev_node, dev_path))


def get_path_by_sysfs_path(sysfs_path, dev_type="block"):
    """ Return device path for a given device sysfs path. """

    dev = get_sysfs_attr(sysfs_path, "dev")
    if not dev or not os.path.exists("/dev/%s/%s" % (dev_type, dev)):
        raise RuntimeError("get_path_by_sysfs_path: Could not find device for %s" % sysfs_path)
    return os.path.realpath("/dev/%s/%s" % (dev_type, dev))


def get_cow_sysfs_path(dev_path, dev_sysfsPath):
    """ Return sysfs path of cow device for a given device.
    """

    cow_path = dev_path + "-cow"
    if not os.path.islink(cow_path):
        raise RuntimeError("get_cow_sysfs_path: Could not find cow device for %s" % dev_path)

    # dev path for cow devices is actually a link to a dm device (e.g. /dev/dm-X)
    # we need the 'dm-X' name for sysfs_path (e.g. /sys/devices/virtual/block/dm-X)
    # where first part is the same as in sysfs_path of the original device
    dm_name = os.path.basename(os.path.realpath(cow_path))
    cow_sysfsPath = os.path.join(os.path.split(dev_sysfsPath)[0], dm_name)

    return cow_sysfsPath

##
# SELinux functions
##


def match_path_context(path, mode=0):
    """ Return the default SELinux context for the given path. """
    if not HAVE_SELINUX:
        raise RuntimeError("SELinux python bindings not available")
    context = None
    try:
        context = selinux.matchpathcon(os.path.normpath(path), mode)[1]
    except OSError as e:
        log.info("failed to get default SELinux context for %s: %s", path, e)

    return context


def set_file_context(path, context, root=None):
    """ Set the SELinux file context of a file.

        Arguments:

            path        filename string
            context     context string

        Keyword Arguments:

            root        an optional chroot string

        Return Value:

            True if successful, False if not.
    """
    if not HAVE_SELINUX:
        raise RuntimeError("SELinux python bindings not available")
    if root is None:
        root = '/'

    full_path = os.path.normpath("%s/%s" % (root, path))
    if context is None or not os.access(full_path, os.F_OK):
        return False

    try:
        rc = (selinux.lsetfilecon(full_path, context) == 0)
    except OSError as e:
        log.info("failed to set SELinux context for %s: %s", full_path, e)
        rc = False

    return rc


def reset_file_context(path, root=None, mode=0):
    """ Restore the SELinux context of a file to its default value.

        Arguments:

            path        filename string

        Keyword Arguments:

            root        an optional chroot string
            mode        an optional mode to use

        Return Value:

            If successful, returns the file's new/default context.
    """
    if not HAVE_SELINUX:
        raise RuntimeError("SELinux python bindings not available")
    context = match_path_context(path, mode)
    if context:
        if set_file_context(path, context, root=root):
            return context

##
# Miscellaneous
##


def makedirs(path):
    if not os.path.isdir(path):
        os.makedirs(path, 0o755)


def lsmod():
    """ Returns list of names of all loaded modules. """
    with open("/proc/modules") as f:
        lines = f.readlines()
    return [l.split()[0] for l in lines]


def get_option_value(opt_name, options):
    """ Return the value of a named option in the specified options string. """
    for opt in options.split(","):
        if "=" not in opt:
            continue

        name, val = opt.split("=")
        if name == opt_name:
            return val.strip()


def numeric_type(num):
    """ Verify that a value is given as a numeric data type.

        Return the number if the type is sensible or raise ValueError
        if not.
    """
    # import locally to avoid a cycle with size importing util
    from .size import Size

    if num is None:
        num = 0
    elif not isinstance(num, (int, float, Size, Decimal)):
        raise ValueError("value (%s) must be either a number or None" % num)

    return num


def insert_colons(a_string):
    """ Insert colon between every second character.

        E.g. creates 'al:go:ri:th:ms' from 'algoritms'. Useful for formatting
        MAC addresses and wwids for output.
    """
    suffix = a_string[-2:]
    if len(a_string) > 2:
        return insert_colons(a_string[:-2]) + ':' + suffix
    else:
        return suffix


def sha256_file(filename):

    sha256 = hashlib.sha256()
    with open(filename, "rb") as f:

        block = f.read(65536)
        while block:
            sha256.update(block)
            block = f.read(65536)

    return sha256.hexdigest()


def read_file(filename, mode="r"):
    with open(filename, mode) as f:
        content = f.read()
    return content


class ObjectID(object):

    """This class is meant to be extended by other classes which require
       an ID which is preserved when an object copy is made.
       The value returned by the builtin function id() is not adequate:
       that value represents object identity so it is not in general
       preserved when the object is copied.

       The name of the identifier property is id, its type is int.

       The id is set during creation of the class instance to a new value
       which is unique for the object type. Subclasses can use self.id during
       __init__.
    """
    _newid_gen = functools.partial(next, itertools.count())

    def __new__(cls, *args, **kwargs):
        # pylint: disable=unused-argument
        self = super(ObjectID, cls).__new__(cls)
        self.id = self._newid_gen()  # pylint: disable=attribute-defined-outside-init,assignment-from-no-return
        return self


def canonicalize_UUID(a_uuid):
    """ Converts uuids to canonical form.

        :param str a_uuid: the UUID

        :returns: a canonicalized UUID
        :rtype: str

        mdadm's UUIDs are actual 128 bit uuids, but it formats them strangely.
        This converts the uuids to canonical form.
        Example:
            mdadm UUID: '3386ff85:f5012621:4a435f06:1eb47236'
        canonical UUID: '3386ff85-f501-2621-4a43-5f061eb47236'

        If the UUID is already in canonical form, the conversion
        is equivalent to the identity.
    """
    return str(uuid.UUID(a_uuid.replace(':', '')))


def compare(first, second):
    """ Compare two objects.

        :param first: first object to compare
        :param second: second object to compare
        :returns: 0 if first == second, 1 if first > second, -1 if first < second
        :rtype: int

        This method replaces Python 2 cmp() built-in-function.
    """

    if first is None and second is None:
        return 0

    elif first is None:
        return -1

    elif second is None:
        return 1

    else:
        return (first > second) - (first < second)


def dedup_list(alist):
    """Deduplicates the given list by removing duplicates while preserving the order"""
    seen = set()
    ret = []
    for item in alist:
        if item not in seen:
            ret.append(item)
        seen.add(item)
    return ret


##
# Convenience functions for examples and tests
##


def set_up_logging(log_dir="/tmp", log_prefix="blivet", console_logs=None):
    """ Configure the blivet logger to write out a log file.

        :keyword str log_dir: path to directory where log files are
        :keyword str log_prefix: prefix for log file names
        :keyword list console_logs: list of log names to output on the console
    """
    log.setLevel(logging.DEBUG)
    program_log.setLevel(logging.DEBUG)

    def make_handler(path, prefix, level):
        log_file = "%s/%s.log" % (path, prefix)
        log_file = os.path.realpath(log_file)
        handler = logging.FileHandler(log_file)
        handler.setLevel(level)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s/%(threadName)s: %(message)s")
        handler.setFormatter(formatter)
        return handler

    handler = make_handler(log_dir, log_prefix, logging.DEBUG)
    log.addHandler(handler)
    program_log.addHandler(handler)

    # capture python warnings in our logs
    warning_log = logging.getLogger("py.warnings")
    warning_log.addHandler(handler)

    if console_logs:
        set_up_console_log(log_names=console_logs)

    log.info("sys.argv = %s", sys.argv)


def set_up_console_log(log_names=None):
    log_names = log_names or []
    handler = logging.StreamHandler()
    console_log.setLevel(logging.DEBUG)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(threadName)s: %(message)s")
    handler.setFormatter(formatter)
    console_log.addHandler(handler)
    for name in log_names:
        logging.getLogger(name).addHandler(handler)


def create_sparse_tempfile(name, size):
    """ Create a temporary sparse file.

        :param str name: suffix for filename
        :param :class:`~.size.Size` size: the file size
        :returns: the path to the newly created file
    """
    (fd, path) = tempfile.mkstemp(prefix="blivet.", suffix="-%s" % name)
    os.close(fd)
    create_sparse_file(path, size)
    return path


def create_sparse_file(path, size):
    """ Create a sparse file.

        :param str path: the full path to the file
        :param :class:`~.size.Size` size: the size of the file
        :returns: None
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    os.ftruncate(fd, size)
    os.close(fd)


@contextmanager
def sparsetmpfile(name, size):
    """ Context manager that creates a sparse tempfile and then unlinks it.

        :param str name: suffix for filename
        :param :class:`~.size.Size` size: the file size

        Yields the path to the newly created file on __enter__.
    """
    path = create_sparse_tempfile(name, size)
    try:
        yield path
    finally:
        os.unlink(path)


def variable_copy(obj, memo, omit=None, shallow=None, duplicate=None):
    """ A configurable copy function. Any attributes not specified in omit,
        shallow, or duplicate are copied using copy.deepcopy().

        :param object obj: a python object to be copied.
        :param dict memo: a dictionary of already copied items
        :param omit: a list of names of attributes not to copy
        :type omit: iterable of str
        :param shallow: a list of names of attributes to shallow copy
        :type shallow: iterable of str
        :param duplicate: a list of names of attributes to duplicate
        :type duplicate: iterable of str

        Note that all attributes in duplicate must implement a duplicate()
        method that does what is expected of it. Attributes with type
        pyparted.Disk are known to do so.

        A shallow copy is implemented by calling copy.copy().
    """
    omit = omit or []
    shallow = shallow or []
    duplicate = duplicate or []

    new = obj.__class__.__new__(obj.__class__)
    memo[id(obj)] = new
    for (attr, value) in obj.__dict__.items():
        if attr in omit or value is None:
            setattr(new, attr, value)
        elif attr in shallow:
            setattr(new, attr, copy.copy(value))
        elif attr in duplicate:
            setattr(new, attr, value.duplicate())
        else:
            setattr(new, attr, copy.deepcopy(value, memo))

    return new


def get_current_entropy():
    with open("/proc/sys/kernel/random/entropy_avail", "r") as fobj:
        return int(fobj.readline())


def power_of_two(value):
    """ Checks whether value is a power of 2 greater than 1.

        :param any value: a value
        :returns: True if the value is a power of 2
        :rtype: bool
    """
    try:
        int_value = int(value)
    except (ValueError, TypeError):
        return False

    if int_value != value:
        return False

    value = int_value

    if value < 2:
        return False

    (q, r) = (value, 0)
    while q != 0:
        if r != 0:
            return False
        (q, r) = divmod(q, 2)

    return True


def indent(text, spaces=4):
    """ Indent text by a specified number of spaces.

        :param str text: the text to indent
        :keyword int spaces: the number of spaces to indent text

        It would be nice if we could use textwrap.indent for this but, since it
        does not exist in python2, I prefer to just use this.
    """
    if not text or not text.strip():
        return text

    indentation = " " * spaces
    indented = []
    for line in text.splitlines():
        indented.append("%s%s" % (indentation, line))

    return "\n".join(indented)


def _add_extra_doc_text(func, field=None, desc=None, field_unique=False):
    """ Add extra doc text to a function's docstring.

        :param :class:`function` func: the function
        :param str field: (sphinx) field to add to the doc text
        :param str desc: description to add in the given :param:`field`
        :param bool field_unique: whether the given :param:`field` should only
                                  appear in the doc text once (a new one won't
                                  be added if there already is an existing one)

        If your doctext is indented with something other than spaces the added
        doctext's indentation will probably not match. That'd be your fault.
    """

    base_text = func.__doc__
    if base_text is None:
        base_text = " "  # They contain leading and trailing spaces. *shrug*
    else:
        base_text = base_text[:-1]  # Trim the trailing space.

    if field_unique and field in base_text:
        # Don't add multiple fields
        return

    # Figure out the number of spaces to indent docstring text. We are looking
    # for the minimum indentation, not including the first line or empty lines.
    indent_spaces = None
    for l in base_text.splitlines()[1:]:
        if not l.strip():
            continue

        spaces = 0
        _l = l[:]
        while _l and _l.startswith(" "):
            spaces += 1
            _l = _l[1:]

        if indent_spaces is None or indent_spaces > spaces:
            indent_spaces = spaces

    if indent_spaces is None:
        indent_spaces = 0

    text = ""
    if not re.search(r'\n\s*$', base_text):
        # Make sure there's a newline after the last text.
        text = "\n"

    desc = desc or ""
    text += field + " " + desc
    func.__doc__ = base_text + "\n" + indent(text, indent_spaces)


#
# Deprecation decorator.
#
_DEPRECATION_MESSAGE = "will be removed in a future version."


def _default_deprecation_msg(func):
    return "%s %s" % (func.__name__, _DEPRECATION_MESSAGE)


_SPHINX_DEPRECATE = ".. deprecated::"
_DEPRECATION_INFO = """%(version)s
    %(message)s
"""


def _add_deprecation_doc_text(func, version=None, message=None):
    desc = _DEPRECATION_INFO % {"version": version, "message": message}
    _add_extra_doc_text(func, _SPHINX_DEPRECATE, desc, field_unique=True)


def deprecated(version, message):
    """ Decorator to deprecate a function or method via warning and docstring.

        :param str version: version in which the deprecation is effective
        :param str message: message suggesting a preferred alternative

        .. note::
            At the point this decorator gets applied to a method in a class the
            method is just a function. It becomes a method later.

        The docstring manipulation is performed only once for each decorated
        function/method, but the warning is issued every time the decorated
        function is called.
    """
    def deprecate_func(func):
        @wraps(func)
        def the_func(*args, **kwargs):
            """ Issue a deprecation warning for, then call, a function. """
            # Warnings look much better with default warning text than with
            # no text. The sphinx doesn't benefit from it, so don't use it
            # there.
            warn_msg = _default_deprecation_msg(func)
            if message:
                warn_msg += " %s" % message

            warnings.warn(warn_msg, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        _add_deprecation_doc_text(the_func, message=message, version=version)
        return the_func

    return deprecate_func


def default_namedtuple(name, fields, doc=""):
    """Create a namedtuple class

    The difference between a namedtuple class and this class is that default
    values may be specified for fields and fields with missing values on
    initialization being initialized to None.

    :param str name: name of the new class
    :param fields: field descriptions - an iterable of either "name" or ("name", default_value)
    :type fields: list of str or (str, object) objects
    :param str doc: the docstring for the new class (should at least describe the meanings and
                    types of fields)
    :returns: a new default namedtuple class
    :rtype: type

    """
    field_names = list()
    for field in fields:
        if isinstance(field, tuple):
            field_names.append(field[0])
        else:
            field_names.append(field)
    nt = namedtuple(name, field_names)

    class TheDefaultNamedTuple(nt):
        if doc:
            __doc__ = doc

        def __new__(cls, *args, **kwargs):
            args_list = list(args)
            sorted_kwargs = sorted(kwargs.keys(), key=field_names.index)
            for i in range(len(args), len(field_names)):
                if field_names[i] in sorted_kwargs:
                    args_list.append(kwargs[field_names[i]])
                elif isinstance(fields[i], tuple):
                    args_list.append(fields[i][1])
                else:
                    args_list.append(None)

            return nt.__new__(cls, *args_list)

    return TheDefaultNamedTuple


def requires_property(prop_name, val=True):
    """
    Function returning a decorator that can be used to guard methods and
    properties with evaluation of the given property.

    :param str prop_name: property to evaluate
    :param val: guard value of the :param:`prop_name`
    :type val: :class:`Object` (anything)
    """
    def guard(fn):
        @wraps(fn)
        def func(self, *args, **kwargs):
            if getattr(self, prop_name) == val:
                return fn(self, *args, **kwargs)
            else:
                raise ValueError("%s can only be accessed if %s evaluates to %s" % (fn.__name__, prop_name, val))
        return func
    return guard


class EvalMode(Enum):
    onetime = 1
    always = 2
    # TODO: no_sooner_than, if_changed,...


class DependencyGuard(object, metaclass=abc.ABCMeta):

    error_msg = abc.abstractproperty(doc="Error message to report when a dependency is missing")

    def __init__(self, exn_cls=DependencyError):
        self._exn_cls = exn_cls
        self._avail = None

    def check_avail(self, onetime=False):
        if self._avail is None or not onetime:
            self._avail = self._check_avail()
        return self._avail

    @abc.abstractmethod
    def _check_avail(self):
        raise NotImplementedError()

    def __call__(self, critical=False, eval_mode=EvalMode.always):
        def decorator(fn):
            @wraps(fn)
            def decorated(*args, **kwargs):
                just_onetime = eval_mode == EvalMode.onetime
                if self.check_avail(onetime=just_onetime):
                    return fn(*args, **kwargs)
                elif critical:
                    raise self._exn_cls(self.error_msg)
                else:
                    log.warning("Failed to call the %s method: %s", fn.__name__, self.error_msg)
                    return None
            return decorated
        return decorator


def detect_virt():
    """ Return True if we are running in a virtual machine. """
    try:
        vm = safe_dbus.get_property_sync(SYSTEMD_SERVICE, SYSTEMD_MANAGER_PATH,
                                         SYSTEMD_MANAGER_IFACE, VIRT_PROP_NAME)
    except (safe_dbus.DBusCallError, safe_dbus.DBusPropertyError):
        return False
    else:
        return vm[0] in ('qemu', 'kvm', 'xen', 'microsoft', 'amazon')


def natural_sort_key(device):
    """ Sorting key for devices which makes sure partitions are sorted in natural
        way, e.g. 'sda1, sda2, ..., sda10' and not like 'sda1, sda10, sda2, ...'
    """
    if device.type == "partition" and device.parted_partition and device.disk:
        part_num = getattr(device.parted_partition, "number", -1)
        return [device.disk.name, part_num]
    else:
        return [device.name, 0]


def get_kernel_module_parameter(module, parameter):
    """ Return the value of a given kernel module parameter

    :param str module: a kernel module
    :param str parameter: a module parameter
    :returns: the value of the given kernel module parameter or None
    :rtype: str
    """

    value = None

    parameter_path = os.path.join("/sys/module", module, "parameters", parameter)
    try:
        with open(parameter_path) as f:
            value = f.read().strip()
    except IOError as e:
        log.warning("Couldn't get the value of the parameter '%s' from the kernel module '%s': %s",
                    parameter, module, str(e))

    return value
