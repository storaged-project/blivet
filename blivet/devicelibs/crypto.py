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

import os
import random
import time
from pycryptsetup import CryptSetup

from ..errors import CryptoError
from ..size import Size
from ..util import get_current_entropy, run_program

LUKS_METADATA_SIZE = Size("2 MiB")
MIN_CREATE_ENTROPY = 256

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
    parts = [''.join(raw[i : i + 5]) for i in range(0, GENERATED_PASSPHRASE_LENGTH, 5)]
    return "-".join(parts)

yesDialog = lambda q: True
logFunc = lambda p, t: None

def is_luks(device):
    cs = CryptSetup(yesDialog=yesDialog, logFunc=logFunc)
    return cs.isLuks(device)

def luks_uuid(device):
    cs = CryptSetup(yesDialog=yesDialog, logFunc=logFunc)
    return cs.luksUUID(device).strip()

def luks_status(name):
    """True means active, False means inactive (or non-existent)"""
    cs = CryptSetup(yesDialog=yesDialog, logFunc=logFunc)
    return cs.luksStatus(name)!=0

def luks_format(device,
                passphrase=None, key_file=None,
                cipher=None, key_size=None,
                min_entropy=0):

    if not passphrase:
        raise ValueError("luks_format requires passphrase")

    cs = CryptSetup(yesDialog=yesDialog, logFunc=logFunc)
    key_file_unlink = False

    key_file = cs.prepare_passphrase_file(passphrase)
    key_file_unlink = True

    #None is not considered as default value and pycryptsetup doesn't accept it
    #so we need to filter out all Nones
    kwargs = {}
    kwargs["device"] = device
    if   cipher: kwargs["cipher"]  = cipher
    if key_file: kwargs["keyfile"] = key_file
    if key_size: kwargs["keysize"] = key_size

    if min_entropy > 0:
        # min_entropy == 0 means "don't care"
        while get_current_entropy() < min_entropy:
            # wait for entropy to become high enough
            time.sleep(1)

    rc = cs.luksFormat(**kwargs)
    if key_file_unlink: os.unlink(key_file)

    if rc:
        raise CryptoError("luks_format failed for '%s'" % device)

def luks_open(device, name, passphrase=None, key_file=None):
    # pylint: disable=unused-argument
    if not passphrase:
        raise ValueError("luks_open requires a passphrase")

    cs = CryptSetup(yesDialog=yesDialog, logFunc=logFunc)
    key_file_unlink = False

    key_file = cs.prepare_passphrase_file(passphrase)
    key_file_unlink = True

    rc = cs.luksOpen(device=device, name=name, keyfile=key_file)
    if key_file_unlink: os.unlink(key_file)
    if rc:
        raise CryptoError("luks_open failed for %s (%s)" % (device, name))

def luks_close(name):
    cs = CryptSetup(yesDialog=yesDialog, logFunc=logFunc)
    rc = cs.luksClose(name)
    if rc:
        raise CryptoError("luks_close failed for %s" % name)

def luks_add_key(device,
                 new_passphrase=None, new_key_file=None,
                 passphrase=None, key_file=None):
    # pylint: disable=unused-argument
    if not passphrase:
        raise ValueError("luks_add_key requires a passphrase")

    params = ["-q"]

    p = os.pipe()
    os.write(p[1], "%s\n" % passphrase)

    params.extend(["luksAddKey", device])

    if new_passphrase:
        os.write(p[1], "%s\n" % new_passphrase)
    elif new_key_file and os.path.isfile(new_key_file):
        params.append("%s" % new_key_file)
    else:
        raise CryptoError("luks_add_key requires either a passphrase or a key file to add")

    os.close(p[1])

    rc = run_program(["cryptsetup"] + params, stdin=p[0], stderr_to_stdout=True)

    os.close(p[0])
    if rc:
        raise CryptoError("luks add key failed with errcode %d" % (rc,))

def luks_remove_key(device,
                    del_passphrase=None, del_key_file=None,
                    passphrase=None, key_file=None):
    # pylint: disable=unused-argument
    if not passphrase:
        raise ValueError("luks_remove_key requires a passphrase")

    params = []

    p = os.pipe()
    if del_passphrase: #the first question is about the key we want to remove
        os.write(p[1], "%s\n" % del_passphrase)

    os.write(p[1], "%s\n" % passphrase)

    params.extend(["luksRemoveKey", device])

    if del_passphrase:
        pass
    elif del_key_file and os.path.isfile(del_key_file):
        params.append("%s" % del_key_file)
    else:
        raise CryptoError("luks_remove_key requires either a passphrase or a key file to remove")

    os.close(p[1])

    rc = run_program(["cryptsetup"] + params, stdin=p[0], stderr_to_stdout=True)

    os.close(p[0])
    if rc:
        raise CryptoError("luks_remove_key failed with errcode %d" % (rc,))


