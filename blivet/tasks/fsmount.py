# fsmount.py
# Filesystem mounting classes.
#
# Copyright (C) 2015  Red Hat, Inc.
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
# Red Hat Author(s): Anne Mulhern <amulhern@redhat.com>

import os

from ..errors import FSError
from ..flags import flags
from .. import util
from ..formats import fslib

from . import availability
from . import task

class FSMount(task.BasicApplication):
    """An abstract class that represents filesystem mounting actions. """
    description = "mount a filesystem"

    options = ["defaults"]
    # type argument to pass to mount, if different from filesystem type
    fstype = None

    ext = availability.MOUNT_APP

    def __init__(self, an_fs):
        self.fs = an_fs

    # TASK methods

    @property
    def _availabilityErrors(self):
        errors = super(FSMount, self)._availabilityErrors

        canmount = (self.mountType in fslib.kernel_filesystems) or \
                   (os.access("/sbin/mount.%s" % (self.mountType,), os.X_OK))

        # Still consider the filesystem type mountable if there exists
        # an appropriate filesystem driver in the kernel modules directory.
        if not canmount:
            modpath = os.path.realpath(os.path.join("/lib/modules", os.uname()[2]))
            if os.path.isdir(modpath):
                modname = "%s.ko" % self.mountType
                for _root, _dirs, files in os.walk(modpath):
                    if any(x.startswith(modname) for x in files):
                        canmount = True
                        break

        if not canmount:
            errors.append("mounting filesystem %s is not supported" % self.mountType)
        return errors

    # IMPLEMENTATION methods

    @property
    def mountType(self):
        """ Mount type string to pass to mount command.

            :returns: mount type string
            :rtype: str
        """
        return self.fstype or self.fs._type

    def _modifyOptions(self, options):
        """ Any mandatory options can be added in this method.

            :param str options: an option string
            :returns: a modified option string
            :rtype: str
        """
        return options

    def mountOptions(self, options):
        """ The options used for mounting.

           :param options: mount options
           :type options: str or None
           :returns: the options used by the task
           :rtype: str
        """
        if not options or not isinstance(options, str):
            options = self.fs.mountopts or ",".join(self.options)

        return self._modifyOptions(options)

    def doTask(self, mountpoint, options=None):
        """Create the format on the device and label if possible and desired.

           :param str mountpoint: mountpoint that overrides self.mountpoint
           :param options: mount options
           :type options: str or None
        """
        # pylint: disable=arguments-differ
        error_msgs = self.availabilityErrors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        try:
            rc = util.mount(self.fs.device, mountpoint,
                            fstype=self.mountType,
                            options=self.mountOptions(options))
        except OSError as e:
            raise FSError("mount failed: %s" % e)

        if rc:
            raise FSError("mount failed: %s" % rc)

class AppleBootstrapFSMount(FSMount):
    fstype = "hfs"

class BindFSMount(FSMount):

    @property
    def _availabilityErrors(self):
        errors = []
        if not self.ext.available:
            errors.append("application %s is not available" % self.ext)

        return errors

    def _modifyOptions(self, options):
        return ",".join(["bind", options])

class DevPtsFSMount(FSMount):
    options = ["gid=5", "mode=620"]

class FATFSMount(FSMount):
    options = ["umask=0077", "shortname=winnt"]

class EFIFSMount(FATFSMount):
    fstype = "vfat"

class HFSPlusMount(FSMount):
    fstype = "hfsplus"

class Iso9660FSMount(FSMount):
    options = ["ro"]

class NoDevFSMount(FSMount):

    @property
    def mountType(self):
        return self.fs.device

class NFSMount(FSMount):

    def _availabilityErrors(self):
        return ["nfs filesystem can't be mounted"]

class NTFSMount(FSMount):
    options = ["default", "ro"]

class SELinuxFSMount(NoDevFSMount):

    @property
    def _availabilityErrors(self):
        errors = super(SELinuxFSMount, self)._availabilityErrors
        if not flags.selinux:
            errors.append("selinux not enabled")
        return errors

class TmpFSMount(NoDevFSMount):

    def _modifyOptions(self, options):
        # This duplicates some code in fs.TmpFS._getOptions.
        # There seems to be no way around that.
        if self.fs._accept_default_size:
            size_opt = None
        else:
            size_opt = self.fs._sizeOption(self.fs._size)
        return ",".join(o for o in (options, size_opt) if o)

    @property
    def _availabilityErrors(self):
        errors = []
        if not self.ext.available:
            errors.append("application %s is not available" % self.ext)

        return errors
