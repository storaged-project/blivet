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
        # new passphrase; used while working with new device
        self.__encryption_passphrase = None
        self.__save_passphrase = None
        # minimum entropy in bits required for LUKS format creation
        self.__min_entropy = 0
        # list of known passphrases
        self.__passphrases = []
        # dict of luks devices {device: passphrase}
        self.__luks_devs = {}
        # default pbkdf parameters for LUKS2 format creation
        self._pbkdf_args = None

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

    @property
    def luks_devs(self):
        return self.__luks_devs

    @luks_devs.setter
    def luks_devs(self, value):
        self.__luks_devs = value

    @property
    def pbkdf_args(self):
        return self._pbkdf_args

    @pbkdf_args.setter
    def pbkdf_args(self, value):
        self._pbkdf_args = value

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
            luks_data.luks_devs[device.format.uuid] = passphrase
            self.add_passphrase(passphrase)

    def reset(self, passphrase=None, luks_dict=None):
        self.clear_passphrases()
        self.add_passphrase(passphrase)
        self.luks_devs = {}
        if luks_dict and isinstance(luks_dict, dict):
            self.luks_devs = luks_dict
            self.add_passphrases([p for p in self.luks_devs.values() if p])

    @property
    def passphrases(self):
        return self.__passphrases


luks_data = LUKS_Data()
