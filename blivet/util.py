import abc
import copy
import functools
import itertools
import os
import shutil
import selinux
import subprocess
import re
import six
import sys
import tempfile
import uuid
from decimal import Decimal
from contextlib import contextmanager
from distutils import spawn

from .errors import DependencyError
from .size import Size

import logging
log = logging.getLogger("blivet")
program_log = logging.getLogger("program")

from threading import Lock
# this will get set to anaconda's program_log_lock in enable_installer_mode
program_log_lock = Lock()


def _run_program(argv, root='/', stdin=None, env_prune=None):
    if env_prune is None:
        env_prune = []

    def chroot():
        if root and root != '/':
            os.chroot(root)

    with program_log_lock:
        program_log.info("Running... %s", " ".join(argv))

        env = os.environ.copy()
        env.update({"LC_ALL": "C",
                    "INSTALL_PATH": root})
        for var in env_prune:
            env.pop(var, None)

        # Try to find absolute path of the executable so we prevent possible
        # deadlock on strerror called from fork from thread (rhbz#1411407)
        if not argv[0].startswith('/') and (not root or root == '/'):
            exec_path = spawn.find_executable(argv[0])
            if exec_path != None:
                argv[0] = exec_path

        try:
            proc = subprocess.Popen(argv,
                                    stdin=stdin,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    close_fds=True,
                                    preexec_fn=chroot, cwd=root, env=env)

            out = proc.communicate()[0]
            if out:
                for line in out.splitlines():
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

def run_program_and_capture_output(*args, **kwargs):
    return _run_program(*args, **kwargs)

def mount(device, mountpoint, fstype, options=None):
    if options is None:
        options = "defaults"

    mountpoint = os.path.normpath(mountpoint)
    if not os.path.exists(mountpoint):
        makedirs(mountpoint)

    argv = ["mount", "-t", fstype, "-o", options, device, mountpoint]
    try:
        rc = run_program(argv)
    except OSError:
        raise

    return rc

def umount(mountpoint):
    try:
        rc = run_program(["umount", mountpoint])
    except OSError:
        raise

    return rc

def get_mount_paths(dev):
    """ Given a device node path, return a list of all active mountpoints. """
    mounts = open("/proc/mounts").readlines()
    mount_paths = []
    for mnt in mounts:
        try:
            (device, path, _rest) = mnt.split(None, 2)
        except ValueError:
            continue

        if dev == device:
            mount_paths.append(path)

    if mount_paths:
        log.debug("%s is mounted on %s", dev, ', '.join(mount_paths))
    return mount_paths

def get_mount_device(mountpoint):
    """ Given a mountpoint, return the device node path mounted there. """
    mountpoint = os.path.realpath(mountpoint)  # eliminate symlinks
    mounts = open("/proc/mounts").readlines()
    mount_device = None
    for mnt in mounts:
        try:
            (device, path, _rest) = mnt.split(None, 2)
        except ValueError:
            continue

        if path == mountpoint:
            mount_device = device
            break

    if mount_device and re.match(r'/dev/loop\d+$', mount_device):
        from blivet.devicelibs import loop
        loop_name = os.path.basename(mount_device)
        mount_device = loop.get_backing_file(loop_name)
        log.debug("found backing file %s for loop device %s", mount_device,
                                                              loop_name)

    if mount_device:
        log.debug("%s is mounted on %s", mount_device, mountpoint)

    return mount_device

def total_memory():
    """ Return the amount of system RAM.

        :rtype: :class:`~.size.Size`
    """
    lines = open("/proc/meminfo").readlines()
    for line in lines:
        if line.startswith("MemTotal:"):
            mem = Size("%s KiB" % line.split()[1])

    # Because /proc/meminfo only gives us the MemTotal (total physical RAM
    # minus the kernel binary code), we need to round this up. Assuming
    # every machine has the total RAM MiB number divisible by 128. */
    bs = Size("128MiB")
    mem = (mem / bs + 1) * bs
    return mem

##
## sysfs functions
##
def notify_kernel(path, action="change"):
    """ Signal the kernel that the specified device has changed.

        Exceptions raised: ValueError, IOError
    """
    log.debug("notifying kernel of '%s' event on device %s", action, path)
    path = os.path.join(path, "uevent")
    if not path.startswith("/sys/") or not os.access(path, os.W_OK):
        log.debug("sysfs path '%s' invalid", path)
        raise ValueError("invalid sysfs path")

    f = open(path, "a")
    f.write("%s\n" % action)
    f.close()

def get_sysfs_attr(path, attr):
    if not attr:
        log.debug("get_sysfs_attr() called with attr=None")
        return None

    attribute = "%s/%s" % (path, attr)
    attribute = os.path.realpath(attribute)

    if not os.path.isfile(attribute) and not os.path.islink(attribute):
        log.warning("%s is not a valid attribute", attr)
        return None

    return open(attribute, "r").read().strip()

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

##
## SELinux functions
##
def match_path_context(path):
    """ Return the default SELinux context for the given path. """
    context = None
    try:
        context = selinux.matchpathcon(os.path.normpath(path), 0)[1]
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

def reset_file_context(path, root=None):
    """ Restore the SELinux context of a file to its default value.

        Arguments:

            path        filename string

        Keyword Arguments:

            root        an optional chroot string

        Return Value:

            If successful, returns the file's new/default context.
    """
    context = match_path_context(path)
    if context:
        if set_file_context(path, context, root=root):
            return context

##
## Miscellaneous
##
def find_program_in_path(prog, raise_on_error=False):
    for d in os.environ["PATH"].split(os.pathsep):
        full = os.path.join(d, prog)
        if os.access(full, os.X_OK):
            return full

    if raise_on_error:
        raise RuntimeError("Unable to locate a needed executable: '%s'" % prog)

def makedirs(path):
    if not os.path.isdir(path):
        os.makedirs(path, 0o755)

def copy_to_system(source):
    # do the import now because enable_installer_mode() has finally been called.
    from . import getSysroot

    if not os.access(source, os.R_OK):
        log.info("copy_to_system: source '%s' does not exist.", source)
        return False

    target = getSysroot() + source
    target_dir = os.path.dirname(target)
    log.debug("copy_to_system: '%s' -> '%s'.", source, target)
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir)
    shutil.copy(source, target)
    return True

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
    if num is None:
        num = 0
    elif not isinstance(num, (int, long, float, Size, Decimal)):
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
        self = super(ObjectID, cls).__new__(cls, *args, **kwargs)
        self.id = self._newid_gen() # pylint: disable=attribute-defined-outside-init
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

##
## Convenience functions for examples and tests
##
def set_up_logging(log_file='/tmp/blivet.log'):
    """ Configure the blivet logger to write out a log file.

        :keyword str log_file: path to the log file (default: /tmp/blivet.log)
    """
    log.setLevel(logging.DEBUG)
    program_log.setLevel(logging.DEBUG)
    handler = logging.FileHandler(log_file)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    log.addHandler(handler)
    program_log.addHandler(handler)
    log.info("sys.argv = %s", sys.argv)

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
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC)
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

        Note that all atrributes in duplicate must implement a duplicate()
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
        if attr in omit or value == None:
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


class EvalMode(object):
    onetime = 1
    always = 2


@six.add_metaclass(abc.ABCMeta)
class DependencyGuard(object):

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
            @functools.wraps(fn)
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
