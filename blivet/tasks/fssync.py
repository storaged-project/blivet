# fssync.py
# Filesystem syncing classes.
#
# Copyright (C) 2014  Red Hat, Inc.
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

from six import add_metaclass

from ..errors import FSError
from .. import util

from . import availability
from . import task

@add_metaclass(abc.ABCMeta)
class FSSync(task.BasicApplication):
    """ An abstract class that represents syncing a filesystem. """

    description = "filesystem syncing"

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs

    @abc.abstractmethod
    def doTask(self):
        raise NotImplementedError()

class XFSSync(FSSync):
    """ Info application for XFS. """

    ext = availability.application("xfs_freeze")

    def _freezeCommand(self):
        return [str(self.ext), "-f", self.fs.systemMountpoint]

    def _unfreezeCommand(self):
        return [str(self.ext), "-u", self.fs.systemMountpoint]

    def doTask(self, root="/"):
        # pylint: disable=arguments-differ
        error_msgs = self.availabilityErrors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        error_msg = None
        try:
            rc = util.run_program(self._freezeCommand(), root=root)
        except OSError as e:
            error_msg = "failed to sync filesytem: %s" % e
        error_msg = error_msg or rc

        try:
            rc = util.run_program(self._unfreezeCommand(), root=root)
        except OSError as e:
            error_msg = error_msg or "failed to sync filesystem: %s" % e
        error_msg = error_msg or rc

        if error_msg:
            raise FSError(error_msg)

class UnimplementedFSSync(task.UnimplementedTask):

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs
