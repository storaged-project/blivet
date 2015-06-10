# lukstasks.py
# Tasks for a LUKS format.
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

from .. import util

from ..errors import LUKSError
from ..size import Size

from . import availability
from . import task

class LUKSSize(task.BasicApplication):
    """ Obtain information about the size of a LUKS format. """

    # Note that this task currently makes use of lsblk. It must
    # parse the output of lsblk --list and use the mapName of the device
    # to identify the correct entry. Ideally, it would be possible
    # to get the information by specifying the device using the mapName,
    # but lsblk won't cooperate, reporting that the luks devices is not
    # a block device instead.

    ext = availability.LSBLK_APP

    description = "size of a luks device"

    def __init__(self, a_luks):
        """ Initializer.

            :param :class:`~.formats.luks.LUKS` a_luks: a LUKS format object
        """
        self.luks = a_luks

    @property
    def _sizeCommand(self):
        """ Returns the command for reading luks format size.

            :returns: a list consisting of the appropriate command
            :rtype: list of str
        """
        return [
           str(self.ext),
           '--list',
           '--noheadings',
           '--bytes',
           '--output=NAME,SIZE'
        ]

    def _extractSize(self, tab):
        """ Extract size information from blkid output.

            :param str tab: tabular information for blkid
            :rtype: :class:`~.size.Size`
            :raises :class:`~.errors.LUKSError`: if size cannot be obtained

            Expects tab to be in name, value lines, where the value is
            the size in bytes.
        """
        for line in tab.strip().split('\n'):
            name, size = line.split()
            if name == self.luks.mapName:
                return Size(int(size))
        raise LUKSError("Could not extract size from blkid output for %s" % self.luks.mapName)

    def doTask(self):
        """ Returns the size of the luks format.

            :returns: the size of the luks format
            :rtype: :class:`~.size.Size`
            :raises :class:`~.errors.LUKSError`: if size cannot be obtained
        """
        error_msgs = self.availabilityErrors
        if error_msgs:
            raise LUKSError("\n".join(error_msgs))

        error_msg = None
        try:
            (rc, out) = util.run_program_and_capture_output(self._sizeCommand)
            if rc:
                error_msg = "failed to gather luks size info: %s" % rc
        except OSError as e:
            error_msg = "failed to gather luks size info: %s" % e
        if error_msg:
            raise LUKSError(error_msg)
        return self._extractSize(out)
