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
import os

from six import add_metaclass

from ..errors import FSError
from .. import util

from . import availability
from . import task

@add_metaclass(abc.ABCMeta)
class FSSync(task.Task):
    """ An abstract class that represents syncing a filesystem. """

    description = "filesystem syncing"

    app_name = abc.abstractproperty(doc="The name of the syncing application.")

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
            return "application %s not available" % self._app()
        return None

    @property
    def unready(self):
        if not self.fs.status:
            return "filesystem has not been mounted"

        if not os.path.exists(self.fs.device):
            return "device does not exist"

        return False

    @property
    def unable(self):
        return False

    @property
    def dependsOn(self):
        return []

    @abc.abstractmethod
    def doTask(self):
        raise NotImplementedError()

class XFSSync(FSSync):
    """ Info application for XFS. """

    app_name = "xfs_freeze"

    def _freezeCommand(self):
        return [str(self._app()), "-f", self.fs.systemMountpoint]

    def _unfreezeCommand(self):
        return [str(self._app()), "-u", self.fs.systemMountpoint]

    def doTask(self, root="/"):
        # pylint: disable=arguments-differ
        error_msg = self.impossible
        if error_msg:
            raise FSError(error_msg)

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
