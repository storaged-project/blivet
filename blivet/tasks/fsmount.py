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
from . import fstask
from . import task


class FSMount(task.BasicApplication, fstask.FSTask):

    """An abstract class that represents filesystem mounting actions. """
    description = "mount a filesystem"

    options = ["defaults"]
    # type argument to pass to mount, if different from filesystem type
    fstype = None

    ext = availability.MOUNT_APP

    # TASK methods

    @property
    def _has_driver(self):
        """ Is there a filesystem driver in the kernel modules directory. """
        modpath = os.path.realpath(os.path.join("/lib/modules", os.uname()[2]))
        if os.path.isdir(modpath):
            modname = "%s.ko" % self.mount_type
            for _root, _dirs, files in os.walk(modpath):
                if any(x.startswith(modname) for x in files):
                    return True
        return False

    @property
    def _can_mount(self):
        return (self.mount_type in fslib.kernel_filesystems) or \
            (os.access("/sbin/mount.%s" % (self.mount_type,), os.X_OK)) or \
            self._has_driver

    @property
    def _availability_errors(self):
        errors = super(FSMount, self)._availability_errors

        if not self._can_mount:
            errors.append("mounting filesystem %s is not supported" % self.mount_type)
        return errors

    # IMPLEMENTATION methods

    @property
    def mount_type(self):
        """ Mount type string to pass to mount command.

            :returns: mount type string
            :rtype: str
        """
        return self.fstype or self.fs._type

    def _modify_options(self, options):
        """ Any mandatory options can be added in this method.

            :param str options: an option string
            :returns: a modified option string
            :rtype: str
        """
        return options

    def mount_options(self, options):
        """ The options used for mounting.

           :param options: mount options
           :type options: str or NoneType
           :returns: the options used by the task
           :rtype: str
        """
        if not options or not isinstance(options, str):
            options = self.fs.mountopts or ",".join(self.options)

        return self._modify_options(options)

    def do_task(self, mountpoint, options=None):
        """Create the format on the device and label if possible and desired.

           :param str mountpoint: mountpoint that overrides self.mountpoint
           :param options: mount options
           :type options: str or None
        """
        # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        try:
            rc = util.mount(self.fs.device, mountpoint,
                            fstype=self.mount_type,
                            options=self.mount_options(options))
        except OSError as e:
            raise FSError("mount failed: %s" % e)

        if rc:
            raise FSError("mount failed: %s" % rc)


class AppleBootstrapFSMount(FSMount):
    fstype = "hfs"


class BindFSMount(FSMount):

    @property
    def _availability_errors(self):
        errors = []
        if not self.ext.available:
            errors.append("application %s is not available" % self.ext)

        return errors

    def _modify_options(self, options):
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
    def mount_type(self):
        return self.fs.device


class NFSMount(FSMount):

    @property
    def _availability_errors(self):
        return ["nfs filesystem can't be mounted"]


class NTFSMount(FSMount):
    options = ["default", "ro"]


class SELinuxFSMount(NoDevFSMount):

    @property
    def _availability_errors(self):
        errors = super(SELinuxFSMount, self)._availability_errors
        if not flags.selinux:
            errors.append("selinux not enabled")
        return errors


class TmpFSMount(NoDevFSMount):

    def _modify_options(self, options):
        # This duplicates some code in fs.TmpFS._get_options.
        # There seems to be no way around that.
        if self.fs._accept_default_size:
            size_opt = None
        else:
            size_opt = self.fs._size_option(self.fs._size)
        return ",".join(o for o in (options, size_opt) if o)

    @property
    def _availability_errors(self):
        errors = []
        if not self.ext.available:
            errors.append("application %s is not available" % self.ext)

        return errors
