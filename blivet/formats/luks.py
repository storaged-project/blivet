# luks.py
# Device format classes for anaconda's storage configuration module.
#
# Copyright (C) 2009  Red Hat, Inc.
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
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#

import gi
gi.require_version("BlockDev", "2.0")

from gi.repository import BlockDev as blockdev

import os

from ..storage_log import log_method_call
from ..errors import LUKSError
from ..devicelibs import crypto
from . import DeviceFormat, register_device_format
from ..flags import flags
from ..i18n import _, N_
from ..tasks import availability, lukstasks
from ..size import Size, KiB
from ..static_data import luks_data

import logging
log = logging.getLogger("blivet")


class LUKS2PBKDFArgs(object):
    """ PBKDF arguments for LUKS 2 format """

    def __init__(self, type=None, max_memory_kb=0, iterations=0, time_ms=0, hash_fn=None):  # pylint: disable=redefined-builtin
        self.type = type
        self.max_memory_kb = max_memory_kb
        self.iterations = iterations
        self.time_ms = time_ms
        self.hash_fn = hash_fn


class LUKS(DeviceFormat):

    """ LUKS """
    _type = "luks"
    _name = N_("LUKS")
    _locked_name = N_("Encrypted")
    _udev_types = ["crypto_LUKS"]
    _formattable = True                 # can be formatted
    _linux_native = True                 # for clearpart
    _packages = ["cryptsetup"]          # required packages
    _min_size = crypto.LUKS_METADATA_SIZE
    _max_size = Size("16 EiB")
    _plugin = availability.BLOCKDEV_CRYPTO_PLUGIN

    _size_info_class = lukstasks.LUKSSize
    _resize_class = lukstasks.LUKSResize
    _resizable = True

    def __init__(self, **kwargs):
        """
            :keyword device: the path to the underlying device
            :keyword uuid: the LUKS UUID
            :keyword exists: indicates whether this is an existing format
            :type exists: bool
            :keyword name: the name of the mapped device
            :keyword passphrase: device passphrase
            :type passphrase: str
            :keyword key_file: path to a file containing a key
            :type key_file: str
            :keyword cipher: cipher mode
            :type cipher: str
            :keyword key_size: key size in bits
            :type key_size: int
            :keyword escrow_cert: certificate (contents) to use for key escrow
            :type escrow_cert: str
            :keyword add_backup_passphrase: generate a backup passphrase?
            :type add_backup_passphrase: bool.
            :keyword min_luks_entropy: minimum entropy in bits required for
                                       format creation
            :type min_luks_entropy: int
            :keyword luks_version: luks format version ("luks1" or "luks2")
            :type luks_version: str
            :keyword pbkdf_args: optional arguments for LUKS2 key derivation function
                                 (for non-existent format only)
            :type pbkdf_args: :class:`LUKS2PBKDFArgs`
            :keyword luks_sector_size: encryption sector size (use only with LUKS version 2)
            :type luks_sector_size: int

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        self._size_info = self._size_info_class(self)
        self._resize = self._resize_class(self)

        self.cipher = kwargs.get("cipher")
        self.key_size = kwargs.get("key_size") or 0
        self.map_name = kwargs.get("name")
        self.luks_version = kwargs.get("luks_version") or crypto.DEFAULT_LUKS_VERSION

        if not self.exists and self.luks_version not in crypto.LUKS_VERSIONS.keys():
            raise ValueError("Unknown or unsupported LUKS version '%s'" % self.luks_version)

        if not self.exists:
            if not self.cipher:
                self.cipher = "aes-xts-plain64"
            if not self.key_size and "xts" in self.cipher:
                # default to the max (512 bits) for xts
                self.key_size = 512

        # FIXME: these should both be lists, but managing them will be a pain
        self.__passphrase = kwargs.get("passphrase")
        self._key_file = kwargs.get("key_file")
        self.escrow_cert = kwargs.get("escrow_cert")
        self.add_backup_passphrase = kwargs.get("add_backup_passphrase", False)
        self.min_luks_entropy = kwargs.get("min_luks_entropy")

        if self.min_luks_entropy is None:
            self.min_luks_entropy = luks_data.min_entropy

        if not self.map_name and self.exists and self.uuid:
            self.map_name = "luks-%s" % self.uuid
        elif not self.map_name and self.device:
            self.map_name = "luks-%s" % os.path.basename(self.device)

        if flags.auto_dev_updates and self._resize.available:
            # if you want current/min size you have to call update_size_info
            self.update_size_info()

        # add the discard option for newly created LUKS formats if requested
        # (e.g. during the installation -- see rhbz#1421596)
        if not self.exists and flags.discard_new:
            if not self.options:
                self.options = "discard"
            elif "discard" not in self.options:
                self.options += ",discard"

        self.pbkdf_args = kwargs.get("pbkdf_args")
        if self.pbkdf_args:
            if self.luks_version != "luks2":
                raise ValueError("PBKDF arguments are valid only for LUKS version 2.")
            if self.pbkdf_args.time_ms and self.pbkdf_args.iterations:
                log.warning("Both iterations and time_ms specified for PBKDF, number of iterations will be ignored.")
            if self.pbkdf_args.type == "pbkdf2" and self.pbkdf_args.max_memory_kb:
                log.warning("Memory limit is not used for pbkdf2 and it will be ignored.")

        self.luks_sector_size = kwargs.get("luks_sector_size") or 0
        if self.luks_sector_size and self.luks_version != "luks2":
            raise ValueError("Sector size argument is valid only for LUKS version 2.")

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        if self.__passphrase:
            passphrase = "(set)"
        else:
            passphrase = "(not set)"
        s += ("  cipher = %(cipher)s  key_size = %(key_size)s"
              "  map_name = %(map_name)s\n version = %(luks_version)s"
              "  key_file = %(key_file)s  passphrase = %(passphrase)s\n"
              "  escrow_cert = %(escrow_cert)s  add_backup = %(backup)s" %
              {"cipher": self.cipher, "key_size": self.key_size,
               "map_name": self.map_name, "luks_version": self.luks_version,
               "key_file": self._key_file, "passphrase": passphrase,
               "escrow_cert": self.escrow_cert, "backup": self.add_backup_passphrase})
        return s

    @property
    def dict(self):
        d = super(LUKS, self).dict
        d.update({"cipher": self.cipher, "key_size": self.key_size,
                  "map_name": self.map_name, "version": self.luks_version,
                  "has_key": self.has_key, "escrow_cert": self.escrow_cert,
                  "backup": self.add_backup_passphrase})
        return d

    @property
    def name(self):
        # for existing locked devices, show "Encrypted" instead of LUKS
        if self.has_key or not self.exists:
            name = _(self._name)
        else:
            name = "%s (%s)" % (_(self._locked_name), _(self._name))
        return name

    def _set_passphrase(self, passphrase):
        """ Set the passphrase used to access this device. """
        self.__passphrase = passphrase

    passphrase = property(fset=_set_passphrase)

    @property
    def has_key(self):
        return ((self.__passphrase not in ["", None]) or
                (self._key_file and os.access(self._key_file, os.R_OK)))

    @property
    def formattable(self):
        return super(LUKS, self).formattable and self._plugin.available

    @property
    def supported(self):
        return super(LUKS, self).supported and self._plugin.available

    @property
    def controllable(self):
        return super(LUKS, self).controllable and self._plugin.available

    @property
    def configured(self):
        """ To be ready we need a key or passphrase and a map name. """
        return self.has_key and self.map_name

    @property
    def status(self):
        if not self.exists or not self.map_name:
            return False
        return os.path.exists("/dev/mapper/%s" % self.map_name)

    def update_size_info(self):
        """ Update this format's current size. """

        self._resizable = False

        if not self.status:
            return

        try:
            self._size = self._size_info.do_task()
        except LUKSError as e:
            log.warning("Failed to obtain current size for device %s: %s", self.device, e)
        else:
            self._resizable = True

    def _pre_setup(self, **kwargs):
        if not self.configured:
            raise LUKSError("luks device not configured")

        return super(LUKS, self)._pre_setup(**kwargs)

    def _setup(self, **kwargs):
        log_method_call(self, device=self.device, map_name=self.map_name,
                        type=self.type, status=self.status)
        try:
            blockdev.crypto.luks_open(self.device, self.map_name,
                                      passphrase=self.__passphrase,
                                      key_file=self._key_file)
        except blockdev.CryptoError as e:
            raise LUKSError(e)

    def _teardown(self, **kwargs):
        """ Close, or tear down, the format. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        log.debug("unmapping %s", self.map_name)
        blockdev.crypto.luks_close(self.map_name)

    def _pre_resize(self):
        if self.luks_version == "luks2" and not self.has_key:
            raise LUKSError("Passphrase or key needs to be set before resizing LUKS2 format.")

        super(LUKS, self)._pre_resize()

    def _pre_create(self, **kwargs):
        super(LUKS, self)._pre_create(**kwargs)
        self.map_name = None
        if not self.has_key:
            raise LUKSError("luks device has no key/passphrase")

    def _create(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        super(LUKS, self)._create(**kwargs)  # set up the event sync

        if not self.pbkdf_args and self.luks_version == "luks2":
            if luks_data.pbkdf_args:
                self.pbkdf_args = luks_data.pbkdf_args
            else:
                mem_limit = crypto.calculate_luks2_max_memory()
                if mem_limit:
                    self.pbkdf_args = LUKS2PBKDFArgs(max_memory_kb=int(mem_limit.convert_to(KiB)))
                    luks_data.pbkdf_args = self.pbkdf_args
                    log.info("PBKDF arguments for LUKS2 not specified, using defaults with memory limit %s", mem_limit)

        if self.pbkdf_args:
            pbkdf = blockdev.CryptoLUKSPBKDF(type=self.pbkdf_args.type,
                                             hash=self.pbkdf_args.hash_fn,
                                             max_memory_kb=self.pbkdf_args.max_memory_kb,
                                             iterations=self.pbkdf_args.iterations,
                                             time_ms=self.pbkdf_args.time_ms)
            extra = blockdev.CryptoLUKSExtra(pbkdf=pbkdf,
                                             sector_size=self.luks_sector_size)
        else:
            if self.luks_sector_size:
                extra = blockdev.CryptoLUKSExtra(sector_size=self.luks_sector_size)
            else:
                extra = None

        blockdev.crypto.luks_format(self.device,
                                    passphrase=self.__passphrase,
                                    key_file=self._key_file,
                                    cipher=self.cipher,
                                    key_size=self.key_size,
                                    min_entropy=self.min_luks_entropy,
                                    luks_version=crypto.LUKS_VERSIONS[self.luks_version],
                                    extra=extra)

    def _post_create(self, **kwargs):
        super(LUKS, self)._post_create(**kwargs)
        self.uuid = blockdev.crypto.luks_uuid(self.device)
        if not self.map_name:
            self.map_name = "luks-%s" % self.uuid

    @property
    def destroyable(self):
        return self._plugin.available

    @property
    def key_file(self):
        """ Path to key file to be used in /etc/crypttab """
        return self._key_file

    def add_passphrase(self, passphrase):
        """ Add a new passphrase.

            Add the specified passphrase to an available key slot in the
            LUKS header.
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self.exists:
            raise LUKSError("format has not been created")

        blockdev.crypto.luks_add_key(self.device,
                                     pass_=self.__passphrase,
                                     key_file=self._key_file,
                                     npass=passphrase)

    def remove_passphrase(self):
        """
        Remove the saved passphrase (and possibly key file) from the LUKS
        header.

        """

        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self.exists:
            raise LUKSError("format has not been created")

        blockdev.crypto.luks_remove_key(self.device,
                                        pass_=self.__passphrase,
                                        key_file=self._key_file)

    def escrow(self, directory, backup_passphrase):
        log.debug("escrow: escrow_volume start for %s", self.device)
        blockdev.crypto.escrow_device(self.device, self.__passphrase, self.escrow_cert,
                                      directory, backup_passphrase)
        log.debug("escrow: escrow_volume done for %s", repr(self.device))

    def populate_ksdata(self, data):
        super(LUKS, self).populate_ksdata(data)
        data.luks_version = self.luks_version

        if self.pbkdf_args:
            data.pbkdf = self.pbkdf_args.type
            data.pbkdf_memory = self.pbkdf_args.max_memory_kb
            data.pbkdf_iterations = self.pbkdf_args.iterations
            data.pbkdf_time = self.pbkdf_args.time_ms


register_device_format(LUKS)


class Integrity(DeviceFormat):

    """ DM integrity format """
    _type = "integrity"
    _name = N_("DM Integrity")
    _udev_types = ["DM_integrity"]
    _supported = False                 # is supported
    _formattable = False               # can be formatted
    _linux_native = True               # for clearpart
    _resizable = False                 # can be resized
    _packages = ["cryptsetup"]         # required packages
    _plugin = availability.BLOCKDEV_CRYPTO_PLUGIN

    def __init__(self, **kwargs):
        """
            :keyword device: the path to the underlying device
            :keyword uuid: the LUKS UUID
            :keyword exists: indicates whether this is an existing format
            :type exists: bool
            :keyword name: the name of the mapped device

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        self.map_name = kwargs.get("name")

    @property
    def status(self):
        if not self.exists or not self.map_name:
            return False
        return os.path.exists("/dev/mapper/%s" % self.map_name)

    def _teardown(self, **kwargs):
        """ Close, or tear down, the format. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        log.debug("unmapping %s", self.map_name)

        # it's safe to use luks_close here, it uses crypt_deactivate which works
        # for all devices supported by cryptsetup
        blockdev.crypto.luks_close(self.map_name)


register_device_format(Integrity)
