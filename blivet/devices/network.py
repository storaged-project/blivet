# devices/network.py
#
# Copyright (C) 2009-2014  Red Hat, Inc.
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
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from .lib import Tags


class NetworkStorageDevice(object):

    """ Virtual base class for network backed storage devices """

    def __init__(self, host_address=None, nic=None):
        """ Note this class is only to be used as a baseclass and then only with
            multiple inheritance. The only correct use is:
            class MyStorageDevice(StorageDevice, NetworkStorageDevice):

            The sole purpose of this class is to:
            1) Be able to check if a StorageDevice is network backed
               (using isinstance).
            2) To be able to get the host address of the host (server) backing
               the storage *or* the NIC through which the storage is connected

            :keyword host_address: host address of the backing server
            :type host_address: str
            :keyword nic: NIC to which the block device is bound
            :type nic: str
        """
        self.host_address = host_address
        self.nic = nic

        self.tags.add(Tags.remote)  # pylint: disable=no-member
