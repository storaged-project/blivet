import abc

from six import add_metaclass

from .. import util
from ..errors import FSWriteUUIDError

from . import availability
from . import fstask
from . import task


@add_metaclass(abc.ABCMeta)
class FSWriteUUID(task.BasicApplication, fstask.FSTask):

    """ An abstract class that represents writing an UUID for a filesystem. """

    description = "write filesystem UUID"

    args = abc.abstractproperty(doc="arguments for writing a UUID")

    # IMPLEMENTATION methods

    @property
    def _set_command(self):
        """Get the command to set UUID of the filesystem.

           :return: the command
           :rtype: list of str
        """
        return [str(self.ext)] + self.args

    def do_task(self):
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSWriteUUIDError("\n".join(error_msgs))

        rc = util.run_program(self._set_command)
        if rc:
            msg = "setting UUID via {} failed".format(self._set_command)
            raise FSWriteUUIDError(msg)


class Ext2FSWriteUUID(FSWriteUUID):
    ext = availability.TUNE2FS_APP

    @property
    def args(self):
        return ["-U", self.fs.uuid, self.fs.device]


class JFSWriteUUID(FSWriteUUID):
    ext = availability.JFSTUNE_APP

    @property
    def args(self):
        return ["-U", self.fs.uuid, self.fs.device]


class NTFSWriteUUID(FSWriteUUID):
    ext = availability.NTFSLABEL_APP

    @property
    def args(self):
        return ["--new-serial=" + self.fs.uuid, self.fs.device]


class ReiserFSWriteUUID(FSWriteUUID):
    ext = availability.REISERFSTUNE_APP

    @property
    def args(self):
        return ["-u", self.fs.uuid, self.fs.device]


class XFSWriteUUID(FSWriteUUID):
    ext = availability.XFSADMIN_APP

    @property
    def args(self):
        return ["-U", self.fs.uuid, self.fs.device]


class UnimplementedFSWriteUUID(fstask.UnimplementedFSTask):
    pass
