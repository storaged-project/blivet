import sys

"""
Imports and functions needed for Python2 and Python3 compatiblity
"""

PY3 = sys.version_info[0] > 2

if PY3:
    long = int
    unicode = str
    xrange = range
    from os import statvfs
else:
    long = long
    unicode = unicode
    xrange = xrange
    import statvfs


def with_metaclass(meta, *bases):
    """
    The first argument is a metaclass and the remaining arguments
    are the base classes, you don't have to explicitly list `object`.

    Usage:
    >>>import abc
    >>>class MyClass(object, with_metaclass(abc.ABCMeta, object)):
    ...    pass

    Source: github.com/sympy/sympy

    """
    class metaclass(meta):
        __call__ = type.__call__
        __init__ = type.__init__

        def __new__(cls, name, this_bases, d):
            if this_bases is None:
                return type.__new__(cls, name, (), d)
            return meta(name, bases, d)
    return metaclass('NewBase', None, {})
