# fsck.py
# Filesystem check functionality.
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

from ..i18n import _, N_

from ..errors import FSError
from .. import util

from . import availability
from . import task

_UNKNOWN_RC_MSG = N_("Unknown return code: %d")

@add_metaclass(abc.ABCMeta)
class FSCK(task.Task):
    """An abstract class that represents actions associated with
       checking consistency of a filesystem.
    """
    description = "fsck"

    app_name = abc.abstractproperty(
       doc="The name of the filesystem labeling application.")

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

    # TASK methods

    @classmethod
    def available(cls):
        return cls._app().available

    @property
    def unavailable(self):
        if not self._app().available:
            return "application %s is not available" % self._app()

        return False

    @property
    def unready(self):
        if not self.fs.exists:
            return "filesystem has not been created"

        if not os.path.exists(self.fs.device):
            return "device %s does not exist" % self.fs.device.name

        return False

    @property
    def unable(self):
        return False

    # IMPLEMENTATION methods

    @abc.abstractmethod
    def _errorMessage(self, rc):
        """ Error message corresponding to rc.

            :param int rc: the fsck program return code
            :returns: an error message corresponding to the code, or None
            :rtype: str or NoneType

            A return value of None indicates no error.
        """
        raise NotImplementedError()

    @property
    def _fsckCommand(self):
        """The command to check the filesystem.

           :return: the command
           :rtype: list of str
        """
        return [str(self._app())] + self.options + [self.fs.device]

    def doTask(self):
        """ Check the filesystem.

           :raises FSError: on failure
        """
        error_msg = self.impossible
        if error_msg:
            raise FSError(error_msg)

        try:
            rc = util.run_program(self._fsckCommand)
        except OSError as e:
            raise FSError("filesystem check failed: %s" % e)

        error_msg = self._errorMessage(rc)
        if error_msg is not None:
            hdr = _("%(type)s filesystem check failure on %(device)s: ") % \
                    {"type": self.fs.type, "device": self.fs.device}

            raise FSError(hdr + error_msg)


class DosFSCK(FSCK):
    _fsckErrors = {1: N_("Recoverable errors have been detected or dosfsck has "
                        "discovered an internal inconsistency."),
                   2: N_("Usage error.")}

    app_name = "dosfsck"
    options = ["-n"]

    def _errorMessage(self, rc):
        if rc < 1:
            return None
        try:
            return _(self._fsckErrors[rc])
        except KeyError:
            return _UNKNOWN_RC_MSG % rc


class Ext2FSCK(FSCK):
    _fsckErrors = {4: N_("File system errors left uncorrected."),
                   8: N_("Operational error."),
                   16: N_("Usage or syntax error."),
                   32: N_("e2fsck cancelled by user request."),
                   128: N_("Shared library error.")}

    app_name = "e2fsck"
    options = ["-f", "-p", "-C", "0"]

    def _errorMessage(self, rc):
        msgs = (_(self._fsckErrors[c]) for c in self._fsckErrors.keys() if rc & c)
        return "\n".join(msgs).strip() or None

class HFSPlusFSCK(FSCK):
    app_name = "fsck.hfsplus"
    options = []

    def _errorMessage(self, rc):
        # pylint: disable=unused-argument
        return None

class NTFSFSCK(FSCK):
    app_name = "ntfsresize"
    options = ["-c"]

    def _errorMessage(self, rc):
        return _UNKNOWN_RC_MSG % (rc,) if rc != 0 else None
