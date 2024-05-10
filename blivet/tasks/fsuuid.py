import abc

import gi
gi.require_version("BlockDev", "3.0")
from gi.repository import BlockDev


class FSUUID(object, metaclass=abc.ABCMeta):

    """An abstract class that represents filesystem actions for setting the
       UUID.
    """

    @classmethod
    @abc.abstractmethod
    def uuid_format_ok(cls, uuid):
        """Returns True if the given UUID is correctly formatted for
           this filesystem, otherwise False.

           :param str uuid: the UUID for this filesystem
           :rtype: bool
        """
        raise NotImplementedError

    # IMPLEMENTATION methods

    @classmethod
    def _check_rfc4122_uuid(cls, uuid):
        """Check whether the given UUID is correct according to RFC 4122 and
           return True if it's correct or False otherwise.

           :param str uuid: the UUID to check
           :rtype: bool
        """
        chunks = uuid.split('-')
        if len(chunks) != 5:
            return False
        chunklens = [len(chunk) for chunk in chunks
                     if all(char in "0123456789abcdef" for char in chunk)]
        return chunklens == [8, 4, 4, 4, 12]

    @classmethod
    def _blockdev_check_uuid(cls, fstype, uuid):
        try:
            BlockDev.fs.check_uuid(fstype, uuid)
        except BlockDev.FSError:
            return False
        else:
            return True


class Ext2FSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._blockdev_check_uuid("ext2", uuid)


class FATFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._blockdev_check_uuid("vfat", uuid)


class XFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._blockdev_check_uuid("xfs", uuid)


class HFSPlusUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._check_rfc4122_uuid(uuid)


class NTFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._blockdev_check_uuid("ntfs", uuid)
