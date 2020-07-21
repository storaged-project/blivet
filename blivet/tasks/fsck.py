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

from six import add_metaclass

from ..errors import FSError
from .. import util

from . import availability
from . import fstask
from . import task

_UNKNOWN_RC_MSG = "Unknown return code: %d"


@add_metaclass(abc.ABCMeta)
class FSCK(task.BasicApplication, fstask.FSTask):

    """An abstract class that represents actions associated with
       checking consistency of a filesystem.
    """
    description = "fsck"

    options = abc.abstractproperty(
        doc="Options for invoking the application.")

    # IMPLEMENTATION methods

    @abc.abstractmethod
    def _error_message(self, rc):
        """ Error message corresponding to rc.

            :param int rc: the fsck program return code
            :returns: an error message corresponding to the code, or None
            :rtype: str or NoneType

            A return value of None indicates no error.
        """
        raise NotImplementedError()

    @property
    def _fsck_command(self):
        """The command to check the filesystem.

           :return: the command
           :rtype: list of str
        """
        return [str(self.ext)] + self.options + [self.fs.device]

    def do_task(self):
        """ Check the filesystem.

           :raises FSError: on failure
        """
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSError("\n".join(error_msgs))

        try:
            rc = util.run_program(self._fsck_command)
        except OSError as e:
            raise FSError("filesystem check failed: %s" % e)

        error_msg = self._error_message(rc)
        if error_msg is not None:
            hdr = "%(type)s filesystem check failure on %(device)s: " % \
                {"type": self.fs.type, "device": self.fs.device}

            raise FSError(hdr + error_msg)


class DosFSCK(FSCK):
    _fsck_errors = {1: "Recoverable errors have been detected or dosfsck has "
                    "discovered an internal inconsistency.",
                    2: "Usage error."}

    ext = availability.DOSFSCK_APP
    options = ["-n"]

    def _error_message(self, rc):
        if rc < 1:
            return None
        try:
            return self._fsck_errors[rc]
        except KeyError:
            return _UNKNOWN_RC_MSG % rc


class Ext2FSCK(FSCK):
    _fsck_errors = {4: "File system errors left uncorrected.",
                    8: "Operational error.",
                    16: "Usage or syntax error.",
                    32: "e2fsck cancelled by user request.",
                    128: "Shared library error."}

    ext = availability.E2FSCK_APP
    # "Force checking even if the file system seems clean." (we might get false results otherwise)
    # + "Automatically repair ("preen") the file system."
    options = ["-f", "-p"]

    def _error_message(self, rc):
        msgs = (self._fsck_errors[c] for c in self._fsck_errors.keys() if rc & c)
        return "\n".join(msgs) or None


class XFSCK(FSCK):
    _fsck_errors = {1: "Runtime error encountered during repair operation.",
                    2: "XFS repair was unable to proceed due to a dirty log."}

    ext = availability.XFSREPAIR_APP
    options = []

    def _error_message(self, rc):
        msgs = (self._fsck_errors[c] for c in self._fsck_errors.keys() if rc & c)
        return "\n".join(msgs) or None


class HFSPlusFSCK(FSCK):
    _fsck_errors = {3: "Quick check found a dirty filesystem; no repairs done.",
                    4: "Root filesystem was dirty. System should be rebooted.",
                    8: "Corrupt filesystem, repairs did not succeed.",
                    47: "Major error found; no repairs attempted."}
    ext = availability.FSCK_HFSPLUS_APP
    options = []

    def _error_message(self, rc):
        if rc < 1:
            return None
        try:
            return self._fsck_errors[rc]
        except KeyError:
            return _UNKNOWN_RC_MSG % rc


class NTFSFSCK(FSCK):
    ext = availability.NTFSRESIZE_APP
    options = ["-c"]

    def _error_message(self, rc):
        return _UNKNOWN_RC_MSG % (rc,) if rc != 0 else None


class F2FSFSCK(FSCK):
    ext = availability.FSCK_F2FS_APP
    options = ["-a"]

    def _error_message(self, rc):
        return _UNKNOWN_RC_MSG % (rc,) if rc != 0 else None


class UnimplementedFSCK(fstask.UnimplementedFSTask):
    pass
