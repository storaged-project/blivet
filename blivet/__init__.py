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

__version__ = '3.3.0'

import sys
import importlib
import warnings
import syslog

from . import util, arch

import logging
log = logging.getLogger("blivet")
program_log = logging.getLogger("program")
testdata_log = logging.getLogger("testdata")

# Tell the warnings module not to ignore DeprecationWarning, which it does by
# default since python-2.7.
warnings.simplefilter('module', DeprecationWarning)

# Enable logging of python warnings.
logging.captureWarnings(True)

# "translation" between syslog log levels (used by libblockdev) and python log levels
LOG_LEVELS = {syslog.LOG_EMERG: logging.CRITICAL, syslog.LOG_ALERT: logging.CRITICAL,
              syslog.LOG_CRIT: logging.CRITICAL, syslog.LOG_ERR: logging.ERROR,
              syslog.LOG_WARNING: logging.WARNING, syslog.LOG_NOTICE: logging.INFO,
              syslog.LOG_INFO: logging.INFO, syslog.LOG_DEBUG: logging.DEBUG}


def log_bd_message(level, msg):
    # only log <= info for libblockdev, debug contains debug messages
    # from cryptsetup and we don't want to put these into program.log
    if level <= syslog.LOG_INFO and level in LOG_LEVELS.keys():
        program_log.log(LOG_LEVELS[level], msg)


import gi
gi.require_version("GLib", "2.0")
gi.require_version("BlockDev", "2.0")

# initialize the libblockdev library
from gi.repository import GLib
from gi.repository import BlockDev as blockdev
if arch.is_s390():
    _REQUESTED_PLUGIN_NAMES = set(("lvm", "btrfs", "swap", "crypto", "loop", "mdraid", "mpath", "dm", "s390", "nvdimm"))
else:
    _REQUESTED_PLUGIN_NAMES = set(("lvm", "btrfs", "swap", "crypto", "loop", "mdraid", "mpath", "dm", "nvdimm"))

_requested_plugins = blockdev.plugin_specs_from_names(_REQUESTED_PLUGIN_NAMES)
try:
    # do not check for dependencies during libblockdev initializtion, do runtime
    # checks instead
    blockdev.switch_init_checks(False)
    succ_, avail_plugs = blockdev.try_reinit(require_plugins=_requested_plugins, reload=False, log_func=log_bd_message)
except GLib.GError as err:
    raise RuntimeError("Failed to initialize the libblockdev library: %s" % err)
else:
    avail_plugs = set(avail_plugs)

missing_plugs = _REQUESTED_PLUGIN_NAMES - avail_plugs
for p in missing_plugs:
    log.info("Failed to load plugin %s", p)


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
        mod = importlib.import_module(__package__ + "." + self._real_mod)
        val = getattr(mod, self._name)
        sys.modules["%s.%s" % (__package__, self._name)] = val
        return val(*args, **kwargs)

    def __getattr__(self, attr):
        mod = importlib.import_module(__package__ + "." + self._real_mod)
        val = getattr(mod, self._name)
        sys.modules["%s.%s" % (__package__, self._name)] = val
        return getattr(val, attr)

    def __dir__(self):
        mod = importlib.import_module(__package__ + "." + self._real_mod)
        val = getattr(mod, self._name)
        sys.modules["%s.%s" % (__package__, self._name)] = val
        return dir(val)


# this way things like 'from blivet import Blivet' work without an overhead of
# importing of everything the Blivet class needs whenever anything from the
# 'blivet' package is imported (e.g. the 'arch' module)
Blivet = _LazyImportObject("Blivet", "blivet")
