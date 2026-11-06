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
gi.require_version("BlockDev", "3.0")

from gi.repository import BlockDev as blockdev, GLib

import os

from ..storage_log import log_method_call
from ..errors import LUKSError, IntegrityError, BitLockerError, FormatDestroyError
from ..devicelibs import crypto
from . import DeviceFormat, register_device_format
from ..flags import flags
from ..i18n import _, N_
from ..tasks import availability, lukstasks
from ..size import Size, KiB
from ..static_data import luks_data
from .. import arch, udev

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
            :keyword subsystem: LUKS subsystem
            :type subsystem: str
            :keyword opal_admin_passphrase: OPAL admin passphrase
            :type opal_admin_passphrase: str
            :keyword zkey_key_type: secure-key type (None uses the zkey default)
            :keyword zkey_apqns: list of crypto adapters in card.domain notation
            :keyword zkey_keybits: clear-key size in bits (0 uses the zkey default)
            :keyword zkey_sector_size: PAES sector size (0 uses luks_sector_size or the zkey default;
                                       nonzero values must agree with luks_sector_size)
            :keyword zkey_dummy_passphrase: generate and enroll a repository dummy passphrase
            :keyword zkey_name: repository key name (must not already exist)

            .. note::

                The 'device' kwarg is required for existing formats. For non-
                existent formats, it is only necessary that the :attr:`device`
                attribute be set before the :meth:`create` method runs. Note
                that you can specify the device at the last moment by specifying
                it via the 'device' kwarg to the :meth:`create` method.

            .. note::

                Setting passphrase and key file kwargs is considered deprecated, the new
                API to set "keyslot contexts" should be used instead: see the `contexts`
                property and the `crypto.KeyslotContextList` class.
                This new API allows setting multiple passphrases and or key files for the
                LUKS device and will allow using more types of LUKS key slots (kernel keyring,
                TPM, FIDO etc.) in the future. Setting multiple contexts for a non-existing LUKS
                format means all the specified passphrases and key files will be used when
                creating the format: specifying two passphrase contexts and one key file context
                will mean the new LUKS format will be created with three key slots.
                For existing LUKS devices if you set multiple contexts, only the highest priority
                context (by default the first passphrase context) will be used when activating the
                LUKS device.
        """
        log_method_call(self, **kwargs)
        DeviceFormat.__init__(self, **kwargs)

        self._size_info = self._size_info_class(self)
        self._resize = self._resize_class(self)

        self.cipher = kwargs.get("cipher")
        self.key_size = kwargs.get("key_size") or 0
        self.map_name = kwargs.get("name")
        self.luks_version = kwargs.get("luks_version") or crypto.DEFAULT_LUKS_VERSION

        self.label = kwargs.get("label") or None
        self.subsystem = kwargs.get("subsystem") or None

        self.is_opal = self.luks_version in crypto.OPAL_TYPES.keys()
        self.pervasive = crypto.is_paes_cipher(self.cipher)
        self.zkey_key_type = kwargs.get("zkey_key_type")
        self.zkey_apqns = kwargs.get("zkey_apqns")
        self.zkey_keybits = kwargs.get("zkey_keybits") or 0
        self.zkey_sector_size = kwargs.get("zkey_sector_size") or 0
        self.zkey_dummy_passphrase = kwargs.get("zkey_dummy_passphrase", False)
        self._zkey_name = kwargs.get("zkey_name")
        self._paes_format_created = False

        if self.pervasive and not self.exists:
            if self.luks_version != "luks2" or self.is_opal:
                raise LUKSError("Pervasive encryption requires LUKS2 without OPAL")
            if not arch.is_s390():
                raise LUKSError("Pervasive encryption requires IBM Z")
            if not availability.BLOCKDEV_S390_PLUGIN_PAES.available:
                raise LUKSError("Pervasive encryption is not available: %s" %
                                ",".join(availability.BLOCKDEV_S390_PLUGIN_PAES.availability_errors))

        if self.luks_version.startswith("luks2"):
            self._header_size = crypto.LUKS2_METADATA_SIZE
        else:
            self._header_size = crypto.LUKS1_METADATA_SIZE
        self._min_size = self._header_size

        if not self.exists and self.luks_version not in list(crypto.LUKS_VERSIONS.keys()) + list(crypto.OPAL_TYPES.keys()):
            raise ValueError("Unknown or unsupported LUKS version '%s'" % self.luks_version)

        if not self.exists:
            if not self.cipher:
                self.cipher = "aes-xts-plain64"
            if not self.key_size and "xts" in self.cipher and not self.pervasive:
                # default to the max (512 bits) for xts
                self.key_size = 512

        self._contexts = crypto.KeyslotContextList()

        passphrase = kwargs.get("passphrase", None)
        if passphrase:
            self.contexts.add_passphrase(passphrase=passphrase, priority=100)
        keyfile = kwargs.get("key_file", None)
        if keyfile:
            self.contexts.add_keyfile(keyfile=keyfile, priority=50)

        self.escrow_cert = kwargs.get("escrow_cert")
        self.add_backup_passphrase = kwargs.get("add_backup_passphrase", False)
        if self.escrow_cert and not availability.BLOCKDEV_CRYPTO_PLUGIN_ESCROW.available:
            raise LUKSError("Escrow certificate is not fully supported: %s" % ",".join(availability.BLOCKDEV_CRYPTO_PLUGIN_ESCROW.availability_errors))

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
        if self.pervasive:
            self._validate_paes_sector_size()

        self.__opal_admin_passphrase = kwargs.get("opal_admin_passphrase")

    def __repr__(self):
        s = DeviceFormat.__repr__(self)
        if self.contexts:
            passphrase = "(set)"
        else:
            passphrase = "(not set)"
        s += ("  cipher = %(cipher)s  key_size = %(key_size)s"
              "  map_name = %(map_name)s\n version = %(luks_version)s"
              "  passphrase = %(passphrase)s (total contexts: %(total_contexts)s)\n"
              "  escrow_cert = %(escrow_cert)s  add_backup = %(backup)s\n"
              "  label = %(label)s  subsystem = %(subsystem)s" %
              {"cipher": self.cipher, "key_size": self.key_size,
               "map_name": self.map_name, "luks_version": self.luks_version,
               "passphrase": passphrase, "total_contexts": len(self.contexts),
               "escrow_cert": self.escrow_cert, "backup": self.add_backup_passphrase,
               "label": self.label, "subsystem": self.subsystem})
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

    @property
    def contexts(self):
        """ Passphrases and key files set for this LUKS format. For non-existing LUKS formats
            these will be added as key slots when creating the format, for existing LUKS formats
            at least one context needs to be set to be able to activate the format.
        """
        return self._contexts

    def _set_passphrase(self, passphrase):
        """ Set the passphrase used to access this device. """
        if not passphrase:
            # fallback to keep this API backward compatible --> setting passphrase
            # to "None" will remove ALL passphrase contexts
            self.contexts.clear_contexts(ctype="passphrase")
        else:
            self.contexts.add_passphrase(passphrase=passphrase, priority=100)

    passphrase = property(fset=_set_passphrase)

    def _set_opal_admin_passphrase(self, opal_admin_passphrase):
        """ Set the OPAL admin passphrase for this device. """
        self.__opal_admin_passphrase = opal_admin_passphrase

    opal_admin_passphrase = property(fset=_set_opal_admin_passphrase)

    @property
    def has_key(self):
        return bool(self.contexts) and self.contexts.valid

    @property
    def packages(self):
        packages = super(LUKS, self).packages[:]
        if self.pervasive:
            packages.append("s390utils-base")
        return packages

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

    @property
    def resizable(self):
        if self.is_opal:
            return False
        return super(LUKS, self).resizable

    @property
    def protected(self):
        if self.is_opal and self.exists:
            # cannot remove LUKS HW-OPAL without admin password
            return True
        return False

    def labeling(self):
        return self.luks_version == "luks2"

    def relabels(self):
        return self.luks_version == "luks2"

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

        # passphrase is preferred for open
        if not self.contexts:
            raise LUKSError("Passphrase or key file must be set for LUKS setup")

        try:
            blockdev.crypto.luks_open(self.device, self.map_name,
                                      context=self.contexts.get_context()._context)
        except blockdev.CryptoError as e:
            raise LUKSError(e)

    def _teardown(self, **kwargs):
        """ Close, or tear down, the format. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        log.debug("unmapping %s", self.map_name)

        try:
            blockdev.crypto.luks_close(self.map_name)
        except blockdev.CryptoError as e:
            raise LUKSError(e)

        udev.settle()

    # pylint: disable=unused-argument
    def _pre_destroy(self, **kwargs):
        if self.is_opal:
            raise LUKSError("HW-OPAL LUKS devices cannot be destroyed.")
        super(LUKS, self)._pre_destroy()
        if self.pervasive and not self.uuid:
            # The by-UUID link can disappear as soon as the signature is wiped.
            # Remember the UUID even for formats constructed without discovery.
            try:
                self.uuid = blockdev.crypto.luks_info(self.device).uuid
            except blockdev.CryptoError as e:
                log.debug("Failed to read PAES UUID before destroying %s: %s", self.device, e)

    def _post_destroy(self, **kwargs):
        # Keep the repository key if wiping the volume failed.
        super(LUKS, self)._post_destroy(**kwargs)
        if self.pervasive:
            try:
                # Re-read associations even for a cached key: it may have been
                # shared with other volumes since this format was discovered.
                info = crypto.find_secure_key_for_volume(self.device, uuid=self.uuid)
                if info:
                    own_volumes = [volume for volume in info.volumes or []
                                   if crypto.secure_key_volume_matches(volume, self.device, self.uuid)]
                    other_volumes = [volume for volume in info.volumes or [] if volume not in own_volumes]
                    if other_volumes:
                        crypto.change_secure_key_volumes(info.name, own_volumes, remove=True)
                        log.info("Keeping shared secure key %s for other volumes: %s",
                                 info.name, ", ".join(other_volumes))
                    else:
                        crypto.remove_secure_key(info.name)
                    self._zkey_name = None
            except (blockdev.BlockDevError, GLib.Error, OSError, AttributeError, LUKSError) as e:
                log.warning("Failed to remove secure key for %s: %s", self.device, e)

    def _pre_resize(self):
        if self.luks_version == "luks2" and not self.has_key:
            raise LUKSError("Passphrase or key needs to be set before resizing LUKS2 format.")

        if self.is_opal:
            raise LUKSError("HW-OPAL LUKS devices cannot be resized.")

        super(LUKS, self)._pre_resize()

    def _pre_create(self, **kwargs):
        super(LUKS, self)._pre_create(**kwargs)
        if not self.pervasive:
            self.map_name = None
        elif not self.map_name:
            self.map_name = "luks-%s" % os.path.basename(self.device)
        if not self.has_key:
            raise LUKSError("luks device has no key/passphrase")

    def _create(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        super(LUKS, self)._create(**kwargs)  # set up the event sync

        original_zkey_name = self._zkey_name
        original_uuid = self.uuid
        self._paes_format_created = False
        volume_key = None
        dummy_context = None
        if self.pervasive:
            volume_key, dummy_context = self._prepare_secure_key()

        try:
            self._create_luks(volume_key, dummy_context)
        except Exception:
            if volume_key is not None:
                if self._paes_format_created:
                    try:
                        self._destroy()
                        self.uuid = original_uuid
                    except (FormatDestroyError, blockdev.BlockDevError, GLib.Error, OSError) as e:
                        # Do not discard the repository key for a surviving header.
                        # Leave a usable object so callers can explicitly destroy it.
                        self.exists = True
                        log.warning("Failed to wipe partially created PAES volume %s; keeping secure key %s: %s",
                                    self.device, self._zkey_name, e)
                if not self.exists:
                    try:
                        crypto.remove_secure_key(self._zkey_name)
                        self._zkey_name = original_zkey_name
                    except (blockdev.BlockDevError, GLib.Error, OSError, AttributeError) as e:
                        log.warning("Failed to remove secure key %s after LUKS creation failed: %s", self._zkey_name, e)
            raise

    def _create_luks(self, volume_key=None, dummy_context=None):
        """Format the volume, add keyslots, and initialize PAES verification."""
        if not self.pbkdf_args and self.luks_version.startswith("luks2"):
            if luks_data.pbkdf_args:
                self.pbkdf_args = luks_data.pbkdf_args
            else:
                # argon is not used with FIPS so we don't need to adjust the memory when in FIPS mode
                if not crypto.is_fips_enabled():
                    mem_limit = crypto.calculate_luks2_max_memory()
                    if mem_limit:
                        self.pbkdf_args = LUKS2PBKDFArgs(max_memory_kb=int(mem_limit.convert_to(KiB)))
                        luks_data.pbkdf_args = self.pbkdf_args
                        log.info("PBKDF arguments for LUKS2 not specified, using defaults with memory limit %s", mem_limit)

        if not self.pervasive and not self.luks_sector_size and self.luks_version.startswith("luks2"):
            self.luks_sector_size = crypto.get_optimal_luks_sector_size(self.device)

        if self.pbkdf_args:
            pbkdf = blockdev.CryptoLUKSPBKDF(type=self.pbkdf_args.type,
                                             hash=self.pbkdf_args.hash_fn,
                                             max_memory_kb=self.pbkdf_args.max_memory_kb,
                                             iterations=self.pbkdf_args.iterations,
                                             time_ms=self.pbkdf_args.time_ms)
            extra = blockdev.CryptoLUKSExtra(pbkdf=pbkdf,
                                             sector_size=self.luks_sector_size,
                                             label=self.label,
                                             subsystem=self.subsystem)
        else:
            if self.luks_sector_size or self.label or self.subsystem:
                extra = blockdev.CryptoLUKSExtra(sector_size=self.luks_sector_size,
                                                 label=self.label,
                                                 subsystem=self.subsystem)
            else:
                extra = None

        if not self.contexts:
            raise LUKSError("Passphrase or key file must be set for LUKS create")

        # sort contexts by priority and use the highest priority for format
        context = self.contexts.get_context()
        if self.pervasive:
            context = self.contexts.get_context("passphrase")

        if self.is_opal:
            if not self.__opal_admin_passphrase:
                raise LUKSError("OPAL admin passphrase must be specified when creating LUKS HW-OPAL format")
            opal_context = blockdev.CryptoKeyslotContext(passphrase=self.__opal_admin_passphrase)

        try:
            if self.pervasive:
                blockdev.crypto.luks_format_volume_key(self.device,
                                                       context=context._context,
                                                       volume_key=volume_key._context,
                                                       cipher=self.cipher,
                                                       key_size=self.key_size,
                                                       min_entropy=self.min_luks_entropy,
                                                       luks_version=crypto.LUKS_VERSIONS[self.luks_version],
                                                       extra=extra)
                self._paes_format_created = True
            elif self.is_opal:
                blockdev.crypto.opal_format(self.device,
                                            context=context._context,
                                            cipher=self.cipher if self.luks_version == "luks2-hw-opal" else None,
                                            key_size=self.key_size if self.luks_version == "luks2-hw-opal" else 0,
                                            min_entropy=self.min_luks_entropy,
                                            opal_context=opal_context,
                                            hw_encryption=crypto.OPAL_TYPES[self.luks_version],
                                            extra=extra)
            else:
                blockdev.crypto.luks_format(self.device,
                                            context=context._context,
                                            cipher=self.cipher,
                                            key_size=self.key_size,
                                            min_entropy=self.min_luks_entropy,
                                            luks_version=crypto.LUKS_VERSIONS[self.luks_version],
                                            extra=extra)
        except blockdev.CryptoError as e:
            raise LUKSError(e)

        if len(self.contexts) > 1:
            all_contexts = self.contexts.get_contexts()
            # we have more contexts specified, let's add all of them
            for cxt in all_contexts:
                if cxt == context:
                    # skip the context already added by format above
                    continue
                try:
                    blockdev.crypto.luks_add_key(self.device, context._context, cxt._context)
                except blockdev.CryptoError as e:
                    raise LUKSError(e)

        if dummy_context is not None:
            try:
                blockdev.crypto.luks_add_key(self.device, context._context, dummy_context._context)
            except blockdev.CryptoError as e:
                raise LUKSError("Failed to enroll PAES dummy passphrase: %s" % e)

        if self.pervasive:
            try:
                crypto.set_verification_pattern(self.device, self.contexts.get_context("passphrase")._passphrase)
            except (blockdev.BlockDevError, GLib.Error, OSError) as e:
                raise LUKSError("Failed to set PAES verification pattern: %s" % e)
            try:
                self.uuid = blockdev.crypto.luks_info(self.device).uuid
                if not self.uuid:
                    raise LUKSError("New PAES volume has no LUKS UUID")
                # cryptsetup's udev change event creates the UUID link needed by
                # zkey. Never persist a kernel name which may identify a different
                # disk after reboot/device enumeration changes.
                udev.settle()
                crypto.change_secure_key_volumes(self._zkey_name,
                                                 ["%s:%s" % (crypto.luks_uuid_path(self.uuid), self.map_name)])
            except (blockdev.BlockDevError, GLib.Error, OSError, LUKSError) as e:
                raise LUKSError("Failed to associate PAES secure key with LUKS UUID: %s" % e)

    def _validate_paes_sector_size(self):
        if self.zkey_sector_size and self.luks_sector_size and self.zkey_sector_size != self.luks_sector_size:
            raise LUKSError("PAES zkey_sector_size and luks_sector_size must agree")

    def _prepare_secure_key(self):
        """Generate a new key and return volume-key and optional dummy-keyfile contexts."""
        if not self.contexts.get_context("passphrase"):
            raise LUKSError("Pervasive encryption creation requires a passphrase")
        if not all(context.valid for context in self.contexts.get_contexts()):
            raise LUKSError("All PAES keyslot contexts must be valid before creating the volume")
        self._validate_paes_sector_size()
        original_zkey_name = self._zkey_name
        try:
            keys = blockdev.s390.zkey_list(None)
            if crypto.find_secure_key_for_volume(self.device):
                raise LUKSError("A secure key is already associated with %s" % self.device)
            names = {key.name for key in keys}
            name = self._zkey_name
            if name and name in names:
                raise LUKSError("Secure key '%s' already exists" % name)
            if not name:
                base = "blivet-%s" % os.path.basename(self.device)
                name = base
                suffix = 1
                while name in names:
                    name = "%s-%d" % (base, suffix)
                    suffix += 1
            info = crypto.generate_secure_key(name, self.zkey_key_type, self.zkey_keybits,
                                              ["%s:%s" % (self.device, self.map_name)], self.zkey_apqns,
                                              self.zkey_sector_size or self.luks_sector_size, self.zkey_dummy_passphrase)
            self._zkey_name = info.name
            try:
                key = crypto.read_secure_key(info.key_file_name)
                if not key or len(key) != info.secure_key_size:
                    raise LUKSError("Secure-key size does not match repository metadata")
                context = crypto.KeyslotContext(volume_key=key)
                dummy_context = None
                if self.zkey_dummy_passphrase:
                    if not info.dummy_passphrase:
                        raise LUKSError("Generated secure key has no dummy passphrase file")
                    dummy_context = crypto.KeyslotContext(keyfile=info.dummy_passphrase)
                    if not dummy_context.valid:
                        raise LUKSError("Generated dummy passphrase file is not readable")
            except (OSError, ValueError, blockdev.BlockDevError, GLib.Error, LUKSError):
                try:
                    crypto.remove_secure_key(self._zkey_name)
                    self._zkey_name = original_zkey_name
                except (blockdev.BlockDevError, GLib.Error) as e:
                    log.warning("Failed to remove secure key %s: %s", self._zkey_name, e)
                raise
            self.key_size = info.secure_key_size * 8
            self.luks_sector_size = info.sector_size
            return context, dummy_context
        except (blockdev.BlockDevError, GLib.Error, OSError, ValueError) as e:
            raise LUKSError("Failed to prepare PAES secure key: %s" % e)

    def _post_create(self, **kwargs):
        super(LUKS, self)._post_create(**kwargs)

        if self.luks_version == "luks2" and flags.discard_new:
            try:
                blockdev.crypto.luks_set_persistent_flags(self.device,
                                                          blockdev.CryptoLUKSPersistentFlags.ALLOW_DISCARDS)
            except blockdev.CryptoError as e:
                raise LUKSError("Failed to set allow discards flag for newly created LUKS format: %s" % str(e))
            except AttributeError:
                log.warning("Cannot set allow discards flag: not supported")

        try:
            info = blockdev.crypto.luks_info(self.device)
        except blockdev.CryptoError as e:
            raise LUKSError("Failed to get UUID for the newly created LUKS device %s: %s" % (self.device, str(e)))
        else:
            self.uuid = info.uuid

        if not self.map_name:
            self.map_name = "luks-%s" % self.uuid

    @property
    def destroyable(self):
        if self.is_opal:
            return False
        return self._plugin.available

    @property
    def key_file(self):
        """ Path to key file to be used in /etc/crypttab """
        # sort contexts by priority and get the highest priority keyfile context
        context = self.contexts.get_context(ctype="keyfile")
        if not context:
            return None
        else:
            return context._key_file

    @key_file.setter
    def key_file(self, keyfile):
        if not keyfile:
            # fallback to keep this API backward compatible --> setting keyfile
            # to "None" will remove ALL keyfile contexts
            self.contexts.clear_contexts(ctype="keyfile")
        else:
            self.contexts.add_keyfile(keyfile=keyfile, priority=50)

    def add_passphrase(self, passphrase):
        """ Add a new passphrase.

            Add the specified passphrase to an available key slot in the
            LUKS header.
        """
        pwcontext = crypto.KeyslotContext(passphrase=passphrase)
        return self.add_key(pwcontext)

    def add_key(self, ncontext):
        """ Add a new key to an existing LUKS device.

            Add the specified context (passphrase, key file...) to an available key slot in the
            LUKS header.

            :param ncontext: new context to add the LUKS format
            :type ncontext: :class:`~.crypto.KeyslotContext` object

            .. note:: The LUKS format must have at least one valid context set to be able
                      to add a new key.
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self.exists:
            raise LUKSError("format has not been created")

        if not self.contexts:
            raise LUKSError("luks device not configured")

        context = self.contexts.get_context()
        try:
            blockdev.crypto.luks_add_key(self.device, context._context, ncontext._context)
        except blockdev.CryptoError as e:
            raise LUKSError(e)

        self.contexts.add_context(ncontext)

    def remove_passphrase(self, passphrase):
        """ Remove specified passphrase from this device.

            .. note:: Key slot associated with the provided passphrase will be removed from
                      this format even if it is the last active key slot!
        """
        context = crypto.KeyslotContext(passphrase=passphrase)
        return self.remove_key(context)

    def remove_key(self, context):
        """ Remove a key from an existing LUKS device.

            :param context: existing context to be removed from the LUKS format
            :type context: :class:`~.crypto.KeyslotContext` object

            .. note:: Key slot specified by @context will be removed from this format
                      even if it is the last active key slot!
        """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        if not self.exists:
            raise LUKSError("format has not been created")

        try:
            blockdev.crypto.luks_remove_key(self.device, context=context._context)
        except blockdev.CryptoError as e:
            raise LUKSError(e)

        self.contexts.remove_context(context)

    def label_format_ok(self, label):
        """Return True if the label has an acceptable format for this
           format. None, which represents accepting the default for this
           device, is always acceptable.

           :param label: A possible label
           :type label: str or None
        """
        return label is None or len(label) < 48

    def write_label(self, dry_run=False):
        """ Create a label for this format.

            :raises: LUKSError

            If self.label is None, this means accept the default, so raise
            an LUKSError in this case.

            Raises a LUKSError if the label can not be set.
        """

        if self.luks_version != "luks2":
            raise LUKSError("label can be set only for luks2")

        if not dry_run:
            if not self.exists:
                raise LUKSError("format has not been created")

            if not os.path.exists(self.device):
                raise LUKSError("device does not exist")

            if self.label is None:
                raise LUKSError("makes no sense to write a label when accepting default label")

            if not self.label_format_ok(self.label):
                raise LUKSError("bad label format for labelling")

            try:
                blockdev.crypto.luks_set_label(self.device, self.label)
            except blockdev.CryptoError as e:
                raise LUKSError(e)

    def escrow(self, directory, backup_passphrase):
        log.debug("escrow: escrow_volume start for %s", self.device)

        # get the highest priority passphrase context
        context = self.contexts.get_context(ctype="passphrase")

        try:
            blockdev.crypto.escrow_device(self.device, context._passphrase, self.escrow_cert,
                                          directory,
                                          backup_passphrase if self.add_backup_passphrase else None)
        except blockdev.CryptoError as e:
            raise LUKSError(e)

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
    _formattable = True                # can be formatted
    _linux_native = True               # for clearpart
    _resizable = False                 # can be resized
    _packages = ["cryptsetup"]         # required packages
    _plugin = availability.BLOCKDEV_CRYPTO_PLUGIN_INTEGRITY

    def __init__(self, **kwargs):
        """
            :keyword device: the path to the underlying device
            :keyword exists: indicates whether this is an existing format
            :type exists: bool
            :keyword name: the name of the mapped device
            :keyword algorithm: integrity algorithm (HMAC is not supported)
            :keyword sector_size: integrity sector size
            :type sector_size: int

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
        self.algorithm = kwargs.get("algorithm", crypto.DEFAULT_INTEGRITY_ALGORITHM)
        self.sector_size = kwargs.get("sector_size", 0)

        if not self.map_name and self.device:
            self.map_name = "integrity-%s" % os.path.basename(self.device)

    @property
    def formattable(self):
        return super(Integrity, self).formattable and self._plugin.available

    @property
    def status(self):
        if not self.exists or not self.map_name:
            return False
        return os.path.exists("/dev/mapper/%s" % self.map_name)

    def _pre_setup(self, **kwargs):
        if not self._plugin.available:
            raise IntegrityError("Integrity devices not fully supported: %s" % ",".join(self._plugin.availability_errors))

        return super(Integrity, self)._pre_setup(**kwargs)

    def _setup(self, **kwargs):
        log_method_call(self, device=self.device, map_name=self.map_name,
                        type=self.type, status=self.status)
        try:
            blockdev.crypto.integrity_open(self.device, self.map_name, self.algorithm)
        except blockdev.CryptoError as e:
            raise IntegrityError(e)

    def _pre_create(self, **kwargs):
        if not self.formattable:
            raise IntegrityError("Integrity devices not fully supported: %s" % ",".join(self._plugin.availability_errors))

        return super(Integrity, self)._pre_create(**kwargs)

    def _create(self, **kwargs):
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        super(Integrity, self)._create(**kwargs)  # set up the event sync

        if self.sector_size:
            extra = blockdev.CryptoIntegrityExtra(sector_size=self.sector_size)
        else:
            extra = None

        try:
            blockdev.crypto.integrity_format(self.device,
                                             self.algorithm,
                                             extra=extra)
        except blockdev.CryptoError as e:
            raise IntegrityError(e)

    def _teardown(self, **kwargs):
        """ Close, or tear down, the format. """
        log_method_call(self, device=self.device,
                        type=self.type, status=self.status)
        log.debug("unmapping %s", self.map_name)

        # it's safe to use luks_close here, it uses crypt_deactivate which works
        # for all devices supported by cryptsetup
        try:
            blockdev.crypto.luks_close(self.map_name)
        except blockdev.CryptoError as e:
            raise IntegrityError(e)

        udev.settle()


register_device_format(Integrity)


class BitLocker(DeviceFormat):

    """ BitLocker format """
    _type = "bitlocker"
    _name = N_("BitLocker")
    _udev_types = ["BitLocker"]
    _supported = False                 # is supported
    _formattable = False               # can be formatted
    _linux_native = False              # for clearpart
    _resizable = False                 # can be resized
    _packages = ["cryptsetup"]         # required packages
    _plugin = availability.BLOCKDEV_CRYPTO_PLUGIN_BITLK

    def __init__(self, **kwargs):
        """
            :keyword device: the path to the underlying device
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
        try:
            blockdev.crypto.luks_close(self.map_name)
        except blockdev.CryptoError as e:
            raise BitLockerError(e)

        udev.settle()


register_device_format(BitLocker)
