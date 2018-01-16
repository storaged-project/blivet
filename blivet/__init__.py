# __init__.py
#
# Copyright (C) 2009, 2010, 2011, 2012, 2013  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#                    Vratislav Podzimek <vpodzime@redhat.com>
#

__version__ = '1.20.4'

##
## Default stub values for installer-specific stuff that gets set up in
## enable_installer_mode.  These constants are only for use inside this file.
## For use in other blivet files, they must either be passed to the function
## in question or care must be taken so they are imported only after
## enable_installer_mode is called.
##
iutil = None
ROOT_PATH = '/'
_storageRoot = ROOT_PATH
_sysroot = ROOT_PATH
shortProductName = 'blivet'
ERROR_RAISE = 0

class ErrorHandler(object):
    def cb(self, exn):
        # pylint: disable=unused-argument
        return ERROR_RAISE

errorHandler = ErrorHandler()

get_bootloader = lambda: None

##
## end installer stubs
##

import sys
import importlib
import warnings

from . import util, arch
from .flags import flags

import logging
log = logging.getLogger("blivet")
program_log = logging.getLogger("program")
testdata_log = logging.getLogger("testdata")

# Tell the warnings module not to ignore DeprecationWarning, which it does by
# default since python-2.7.
warnings.simplefilter('module', DeprecationWarning)

# Enable logging of python warnings.
logging.captureWarnings(True)

# XXX: respect the level? Need to translate between C and Python log levels.
log_bd_message = lambda level, msg: program_log.info(msg)

import gi
gi.require_version("GLib", "2.0")
gi.require_version("BlockDev", "2.0")

# initialize the libblockdev library
from gi.repository import GLib
from gi.repository import BlockDev as blockdev
if arch.isS390():
    _REQUESTED_PLUGIN_NAMES = set(("lvm", "btrfs", "swap", "crypto", "loop", "mdraid", "mpath", "dm", "s390"))
else:
    _REQUESTED_PLUGIN_NAMES = set(("lvm", "btrfs", "swap", "crypto", "loop", "mdraid", "mpath", "dm"))

_requested_plugins = blockdev.plugin_specs_from_names(_REQUESTED_PLUGIN_NAMES)
try:
    succ_, avail_plugs = blockdev.try_reinit(require_plugins=_requested_plugins, reload=False, log_func=log_bd_message)
except GLib.GError as err:
    raise RuntimeError("Failed to intialize the libblockdev library: %s" % err)
else:
    avail_plugs = set(avail_plugs)

missing_plugs =  _REQUESTED_PLUGIN_NAMES - avail_plugs
for p in missing_plugs:
    log.info("Failed to load plugin %s", p)

def enable_installer_mode():
    """ Configure the module for use by anaconda (OS installer). """
    global iutil
    global ROOT_PATH
    global _storageRoot
    global _sysroot
    global shortProductName
    global get_bootloader
    global errorHandler
    global ERROR_RAISE

    from pyanaconda import iutil # pylint: disable=redefined-outer-name
    from pyanaconda.constants import shortProductName # pylint: disable=redefined-outer-name
    from pyanaconda.bootloader import get_bootloader # pylint: disable=redefined-outer-name
    from pyanaconda.errors import errorHandler # pylint: disable=redefined-outer-name
    from pyanaconda.errors import ERROR_RAISE # pylint: disable=redefined-outer-name

    if hasattr(iutil, 'getTargetPhysicalRoot'):
        # For anaconda versions > 21.43
        _storageRoot = iutil.getTargetPhysicalRoot() # pylint: disable=no-name-in-module
        _sysroot = iutil.getSysroot()
    else:
        # For prior anaconda versions
        from pyanaconda.constants import ROOT_PATH # pylint: disable=redefined-outer-name,no-name-in-module
        _storageRoot = _sysroot = ROOT_PATH

    from pyanaconda.anaconda_log import program_log_lock
    util.program_log_lock = program_log_lock

    flags.installer_mode = True

def getSysroot():
    """Returns the path to the target OS installation.

    For traditional installations, this is the same as the physical
    storage root.
    """
    return _sysroot

def getTargetPhysicalRoot():
    """Returns the path to the "physical" storage root.

    This may be distinct from the sysroot, which could be a
    chroot-type subdirectory of the physical root.  This is used for
    example by all OSTree-based installations.
    """
    return _storageRoot

def setSysroot(storageRoot, sysroot=None):
    """Change the OS root path.
       :param storageRoot: The root of physical storage
       :param sysroot: An optional chroot subdirectory of storageRoot
    """
    global _storageRoot
    global _sysroot
    _storageRoot = _sysroot = storageRoot
    if sysroot is not None:
        _sysroot = sysroot

class _LazyImportObject(object):
    """
    A simple class that uses sys.modules and importlib to implement a
    lazy-imported object. Once it is called (or instantiated) or an attribute of
    it is requested, the real object is imported and an appropriate method is
    called on it with all the passed arguments.

    """

    def __init__(self, name, real_mod):
        """
        Create a new instance of a lazy-imported object.

        :param str name: name of the real object/class
        :param str real_mod: the real module the real object lives in

        """

        self._name = name
        self._real_mod = real_mod

    def __call__(self, *args, **kwargs):
        mod = importlib.import_module(__package__+"."+self._real_mod)
        val = getattr(mod, self._name)
        sys.modules["%s.%s" % (__package__, self._name)] = val
        return val(*args, **kwargs)

    def __getattr__(self, attr):
        mod = importlib.import_module(__package__+"."+self._real_mod)
        val = getattr(mod, self._name)
        sys.modules["%s.%s" % (__package__, self._name)] = val
        return getattr(val, attr)

    def __dir__(self):
        mod = importlib.import_module(__package__+"."+self._real_mod)
        val = getattr(mod, self._name)
        sys.modules["%s.%s" % (__package__, self._name)] = val
        return dir(val)

# this way things like 'from blivet import Blivet' work without an overhead of
# importing of everything the Blivet class needs whenever anything from the
# 'blivet' package is imported (e.g. the 'arch' module)
Blivet = _LazyImportObject("Blivet", "blivet")
