from ..errors import FSWriteUUIDError

from . import availability
from . import fstask
from . import task

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSWriteUUID(task.BasicApplication, fstask.FSTask):
    """ An abstract class that represents writing an UUID for a filesystem. """

    description = "write filesystem UUID"
    fstype = None

    # IMPLEMENTATION methods

    def do_task(self):  # pylint: disable=arguments-differ
        error_msgs = self.availability_errors
        if error_msgs:
            raise FSWriteUUIDError("\n".join(error_msgs))

        try:
            BlockDev.fs.set_uuid(self.fs.device, self.fs.uuid, self.fstype)
        except BlockDev.FSError as e:
            raise FSWriteUUIDError(str(e))


class Ext2FSWriteUUID(FSWriteUUID):
    fstype = "ext2"
    ext = availability.BLOCKDEV_EXT_UUID


class NTFSWriteUUID(FSWriteUUID):
    fstype = "ntfs"
    ext = availability.BLOCKDEV_NTFS_UUID


class XFSWriteUUID(FSWriteUUID):
    fstype = "xfs"
    ext = availability.BLOCKDEV_XFS_UUID


class UnimplementedFSWriteUUID(fstask.UnimplementedFSTask):
    pass
