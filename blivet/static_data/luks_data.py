# luks_data.py
# Backend code for populating a DeviceTree.
#
# Copyright (C) 2009-2016  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): Jan Pokorny <japokorn@redhat.com>
#


class LUKS_Data(object):
    """ Class to be used as a singleton.
        Maintains the LUKS data.
    """

    def __init__(self):
        """
            TODO - fix doc text
            :keyword __min_entropy: minimum entropy in bits required for
                                       LUKS format creation
            :type __min_entropy: int
        """
        self.__devs = None
        self.__encryption_passphrase = None
        self.__save_passphrase = None
        self.__min_entropy = 0
        self.__passphrases = []

    @property
    def devs(self):
        return self.__devs

    @devs.setter
    def devs(self, value):
        self.__devs = value

    @property
    def encryption_passphrase(self):
        return self.__encryption_passphrase

    @encryption_passphrase.setter
    def encryption_passphrase(self, value):
        self.__encryption_passphrase = value

    @property
    def min_entropy(self):
        return self.__min_entropy

    @min_entropy.setter
    def min_entropy(self, value):
        if value < 0:
            msg = "Invalid value for minimum required entropy: %s" % value
            raise ValueError(msg)
        self.__min_entropy = value

    def clear_passphrases(self):
        self.__passphrases = []

    def add_passphrase(self, passphrase):
        if passphrase:
            self.__passphrases.append(passphrase)

    def add_passphrases(self, passphrases):
        self.__passphrases.extend(passphrases)

    def save_passphrase(self, device):
        """ Save a device's LUKS passphrase in case of reset. """
        passphrase = device.format._LUKS__passphrase
        if passphrase:
            luks_data.devs[device.format.uuid] = passphrase
            self.add_passphrase(passphrase)

    @property
    def passphrases(self):
        return self. __passphrases


luks_data = LUKS_Data()
