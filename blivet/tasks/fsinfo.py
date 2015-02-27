# fsinfo.py
# Filesystem information gathering classes.
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

import abc
import os

from six import add_metaclass

from ..errors import FSError
from .. import util

from . import availability
from . import task

@add_metaclass(abc.ABCMeta)
class FSInfo(task.Task):
    """ An abstract class that represents an information gathering app. """

    description = "filesystem info"

    app_name = abc.abstractproperty(
       doc="The name of the filesystem information gathering application.")

    options = abc.abstractproperty(
       doc="Options for invoking the application.")

    @classmethod
    def _app(cls):
        return availability.Application(availability.Path(), cls.app_name)

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs

    @classmethod
    def available(cls):
        return cls._app().available

    @property
    def _unavailable(self):
        if not self._app().available:
            return "application %s not available." % self._app()

        return False

    @property
    def unready(self):
        if not self.fs.exists:
            return "filesystem has not been created"

        if not os.path.exists(self.fs.device):
            return "device does not exist"

        return False

    @property
    def unable(self):
        return False

    @property
    def dependsOn(self):
        return []

    def _infoCommand(self):
        """ Returns the command for reading filesystem information.

            :returns: a list of appropriate options
            :rtype: list of str
        """
        return [str(self._app())] + self.options + [self.fs.device]

    def doTask(self):
        """ Returns information from the command.

            :returns: a string representing the output of the command
            :rtype: str
            :raises FSError: if info cannot be obtained
        """
        error_msg = self.impossible
        if error_msg:
            raise FSError(error_msg)
        try:
            (rc, out) = util.run_program_and_capture_output(self._infoCommand())
            if rc:
                error_msg = "failed to gather fs info: %s" % rc
        except OSError as e:
            error_msg = "failed to gather fs info: %s" % e
        if error_msg:
            raise FSError(error_msg)
        return out

class Ext2FSInfo(FSInfo):
    app_name = "dumpe2fs"
    options = ["-h"]

class JFSInfo(FSInfo):
    app_name = "jfs_tune"
    options = ["-l"]

class NTFSInfo(FSInfo):
    app_name = "ntfsinfo"
    options = ["-m"]

class ReiserFSInfo(FSInfo):
    app_name = "debugreiserfs"
    options = []

class XFSInfo(FSInfo):
    app_name = "xfs_db"
    options = ["-c", "sb 0", "-c", "p dblocks", "-c", "p blocksize"]

class UnimplementedFSInfo(task.UnimplementedTask):

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs
