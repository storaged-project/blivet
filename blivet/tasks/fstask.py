# fstask.py
# Superclass for filesystem tasks.
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

from . import task


@add_metaclass(abc.ABCMeta)
class FSTask(task.Task):

    """ An abstract class that encapsulates the fact that all FSTasks
        have a single master object: the filesystem that they belong to.
    """
    description = "parent of all filesystem tasks"

    def __init__(self, an_fs):
        """ Initializer.

            :param FS an_fs: a filesystem object
        """
        self.fs = an_fs


class UnimplementedFSTask(FSTask, task.UnimplementedTask):

    """ A convenience class for unimplemented filesystem tasks.
        Useful in the usual case where an Unimplemented task has
        no special methods that it is required to implement.
    """
