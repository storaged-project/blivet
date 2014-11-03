#
# crypto.py
#
# Copyright (C) 2009  Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author(s): Dave Lehman <dlehman@redhat.com>
#            Martin Sivak <msivak@redhat.com>
#

import random
import time
from pycryptsetup import CryptSetup

from ..errors import CryptoError
from ..size import Size
from ..util import get_current_entropy

LUKS_METADATA_SIZE = Size("2 MiB")
MIN_CREATE_ENTROPY = 256 # bits

# Keep the character set size a power of two to make sure all characters are
# equally likely
GENERATED_PASSPHRASE_CHARSET = ("0123456789"
                                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                                "abcdefghijklmnopqrstuvwxyz"
                                "./")
# 20 chars * 6 bits per char = 120 "bits of security"
GENERATED_PASSPHRASE_LENGTH = 20

def generateBackupPassphrase():
    raw = [random.choice(GENERATED_PASSPHRASE_CHARSET) for _ in range(GENERATED_PASSPHRASE_LENGTH)]

    # Insert a '-' after every five char chunk for easier reading
    parts = []
    for i in range(0, GENERATED_PASSPHRASE_LENGTH, 5):
        parts.append(''.join(raw[i : i + 5]))
    return "-".join(parts)

yesDialog = lambda q: True
logFunc = lambda p, t: None
passwordDialog = lambda t: None

def is_luks(device):
    cs = CryptSetup(device=device, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)
    return cs.isLuks()

def luks_uuid(device):
    cs = CryptSetup(device=device, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)
    return cs.luksUUID()

def luks_status(name):
    """True means active, False means inactive (or non-existent)"""
    cs = CryptSetup(name=name, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)
    return cs.status()

def luks_format(device,
                passphrase=None,
                cipher=None, key_size=None, key_file=None,
                min_entropy=0):
    """
    Format device as LUKS with the specified parameters.

    :param str device: device to format
    :param str passphrase: passphrase to add to the new LUKS device
    :param str cipher: cipher mode to use
    :param int keysize: keysize to use
    :param str key_file: key file to use
    :param int min_entropy: minimum random data entropy level required for LUKS
                            format creation (0 means entropy level is not checked)

    note::
              If some minimum entropy is required (min_entropy > 0), the
              function waits for enough entropy to be gathered by the kernel
              which may potentially take very long time or even forever.
    """

    # pylint: disable=unused-argument
    if not passphrase:
        raise ValueError("luks_format requires passphrase")

    cs = CryptSetup(device=device, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)

    #None is not considered as default value and pycryptsetup doesn't accept it
    #so we need to filter out all Nones
    kwargs = {}

    # Split cipher designator to cipher name and cipher mode
    cipherType = None
    cipherMode = None
    if cipher:
        cparts = cipher.split("-")
        cipherType = "".join(cparts[0:1])
        cipherMode = "-".join(cparts[1:])

    if cipherType: kwargs["cipher"]  = cipherType
    if cipherMode: kwargs["cipherMode"]  = cipherMode
    if   key_size: kwargs["keysize"]  = key_size

    if min_entropy > 0:
        # min_entropy == 0 means "don't care"
        while get_current_entropy() < min_entropy:
            # wait for entropy to become high enough
            time.sleep(1)

    rc = cs.luksFormat(**kwargs)
    if rc:
        raise CryptoError("luks_format failed for '%s'" % device)

    # activate first keyslot
    cs.addKeyByVolumeKey(newPassphrase=passphrase)
    if rc:
        raise CryptoError("luks_add_key_by_volume_key failed for '%s'" % device)


def luks_open(device, name, passphrase=None, key_file=None):
    # pylint: disable=unused-argument
    if not passphrase:
        raise ValueError("luks_format requires passphrase")

    cs = CryptSetup(device=device, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)

    rc = cs.activate(passphrase=passphrase, name=name)
    if rc<0:
        raise CryptoError("luks_open failed for %s (%s) with errno %d" % (device, name, rc))

def luks_close(name):
    cs = CryptSetup(name=name, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)
    rc = cs.deactivate()

    if rc:
        raise CryptoError("luks_close failed for %s" % name)

def luks_add_key(device,
                 new_passphrase=None,
                 passphrase=None, key_file=None):
    # pylint: disable=unused-argument
    if not passphrase:
        raise ValueError("luks_add_key requires passphrase")

    cs = CryptSetup(device=device, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)
    rc = cs.addKeyByPassphrase(passphrase=passphrase, newPassphrase=new_passphrase)

    if rc<0:
        raise CryptoError("luks add key failed with errcode %d" % (rc,))

def luks_remove_key(device,
                    del_passphrase=None,
                    passphrase=None, key_file=None):
    # pylint: disable=unused-argument
    if not passphrase:
        raise ValueError("luks_remove_key requires passphrase")

    cs = CryptSetup(device=device, yesDialog=yesDialog, logFunc=logFunc, passwordDialog=passwordDialog)
    rc = cs.removePassphrase(passphrase = passphrase)

    if rc:
        raise CryptoError("luks remove key failed with errcode %d" % (rc,))
