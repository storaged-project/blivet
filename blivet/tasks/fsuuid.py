import abc

from six import add_metaclass


@add_metaclass(abc.ABCMeta)
class FSUUID(object):

    """An abstract class that represents filesystem actions for setting the
       UUID.
    """

    @abc.abstractmethod
    def uuid_format_ok(self, uuid):
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


class Ext2FSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._check_rfc4122_uuid(uuid)


class FATFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        if len(uuid) != 9 or uuid[4] != '-':
            return False
        return all(char in "0123456789ABCDEF"
                   for char in (uuid[:4] + uuid[5:]))


class JFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._check_rfc4122_uuid(uuid)


class ReiserFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._check_rfc4122_uuid(uuid)


class XFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._check_rfc4122_uuid(uuid)


class HFSPlusUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        return cls._check_rfc4122_uuid(uuid)


class NTFSUUID(FSUUID):
    @classmethod
    def uuid_format_ok(cls, uuid):
        if len(uuid) != 16:
            return False
        return all(char in "0123456789ABCDEF" for char in uuid)
