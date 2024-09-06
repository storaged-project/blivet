# fstab.py
# Fstab management.
#
# Copyright (C) 2023  Red Hat, Inc.
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

import os

try:
    from libmount import Table, Fs, MNT_ITER_FORWARD
    from libmount import Error as LibmountException
except ModuleNotFoundError:
    HAVE_LIBMOUNT = False
else:
    HAVE_LIBMOUNT = True

import logging
log = logging.getLogger("blivet")


class FSTabOptions(object):
    """ User preferred fstab settings object intended to be attached to device.format.
        Set variables override otherwise automatically obtained values put into fstab.
    """

    def __init__(self):
        self.freq = None
        self.passno = None

        # preferred spec identification type; default "UUID"
        # possible values: None, "UUID", "LABEL", "PARTLABEL", "PARTUUID", "PATH"
        self.spec_type = None

        # list of fstab options to be used
        self.mntops = []


class FSTabEntry(object):
    """ One processed line of fstab
    """

    def __init__(self, spec=None, file=None, vfstype=None, mntops=None,
                 freq=None, passno=None, comment=None, *, entry=None):

        # Note: "*" in arguments means that every following parameter can be used
        # only with its key (e.g. "FSTabEntry(entry=Fs())")

        if entry is None:
            self._entry = Fs()
        else:
            self._entry = entry

        if spec is not None:
            self.spec = spec
        if file is not None:
            self.file = file
        if vfstype is not None:
            self.vfstype = vfstype
        if mntops is not None:
            self.mntops = mntops
        if freq is not None:
            self.freq = freq
        if passno is not None:
            self.passno = passno
        if comment is not None:
            self.comment = comment

        self._none_to_empty()

    def __repr__(self):
        _comment = ""
        if self._entry.comment not in ("", None):
            _comment = "%s\n" % self._entry.comment
        _line = "%s\t%s\t%s\t%s\t%s\t%s\t" % (self._entry.source, self._entry.target, self._entry.fstype,
                                              self._entry.options, self._entry.freq, self._entry.passno)
        return _comment + _line

    def __eq__(self, other):
        if not isinstance(other, FSTabEntry):
            return False

        if self._entry.source != other._entry.source:
            return False

        if self._entry.target != other._entry.target:
            return False

        if self._entry.fstype != other._entry.fstype:
            return False

        if self._entry.options != other._entry.options:
            return False

        if self._entry.freq != other._entry.freq:
            return False

        if self._entry.passno != other._entry.passno:
            return False

        return True

    def _none_to_empty(self):
        """ Workaround function that internally replaces all None values with empty strings.
            Reason: While libmount.Fs() initializes with parameters set to None, it does not
            allow to store None as a valid value, blocking all value resets.
        """

        affected_params = [self._entry.source,
                           self._entry.target,
                           self._entry.fstype,
                           self._entry.options,
                           self._entry.comment]

        for param in affected_params:
            if param is None:
                param = ""

    @property
    def entry(self):
        return self._entry

    @entry.setter
    def entry(self, value):
        """ Setter for the whole internal entry value

            :param value: fstab entry
            :type value: :class: `libmount.Fs`
        """
        self._entry = value

    @property
    def spec(self):
        return self._entry.source if self._entry.source != "" else None

    @spec.setter
    def spec(self, value):
        self._entry.source = value if value is not None else ""

    @property
    def file(self):
        return self._entry.target if self._entry.target != "" else None

    @file.setter
    def file(self, value):
        self._entry.target = value if value is not None else ""

    @property
    def vfstype(self):
        return self._entry.fstype if self._entry.fstype != "" else None

    @vfstype.setter
    def vfstype(self, value):
        self._entry.fstype = value if value is not None else ""

    @property
    def mntops(self):
        """ Return mount options

            :returns: list of mount options or None when not set
            :rtype: list of str
        """

        if self._entry.options == "":
            return None

        return self._entry.options.split(',')

    def get_raw_mntops(self):
        """ Return mount options

            :returns: comma separated string of mount options or None when not set
            :rtype: str
        """

        return self._entry.options if self._entry.options != "" else None

    @mntops.setter
    def mntops(self, values):
        """ Set new mount options from the list of strings

            :param values: mount options (see man fstab(5) fs_mntops)
            :type values: list of str
        """

        # libmount.Fs() internally stores options as a comma separated string
        if values is None:
            self._entry.options = ""
        else:
            self._entry.options = ','.join([x for x in values if x != ""])

    def mntops_add(self, values):
        """ Append new mount options to already existing ones

            :param values: mount options (see man fstab(5) fs_mntops)
            :type values: list of str
        """

        self._entry.append_options(','.join([x for x in values if x != ""]))

    @property
    def freq(self):
        return self._entry.freq

    @freq.setter
    def freq(self, value):
        self._entry.freq = value

    @property
    def passno(self):
        return self._entry.passno

    @passno.setter
    def passno(self, value):
        if value not in [None, 0, 1, 2]:
            raise ValueError("fstab field passno must be 0, 1 or 2 (got '%s')" % value)
        self._entry.passno = value

    @property
    def comment(self):
        return self._entry.comment if self._entry.comment != "" else None

    @comment.setter
    def comment(self, value):
        if value is None:
            self._entry.comment = ""
            return
        self._entry.comment = value

    def is_valid(self):
        """ Verify that this instance has enough data for valid fstab entry

            :returns: False if any of the listed values is not set; otherwise True
            :rtype: bool
        """
        items = [self.spec, self.file, self.vfstype, self.mntops, self.freq, self.passno]

        # (Property getters replace empty strings with None)
        return not any(x is None for x in items)


class FSTabManagerIterator(object):
    """ Iterator class for FSTabManager
        Iteration over libmount Table entries is weird - only one iterator can run at a time.
        This class purpose is to mitigate that.
    """

    def __init__(self, fstab):
        # To avoid messing up the libmount Table iterator which is singleton,
        # set up independent entry list
        entry = fstab._table.next_fs()
        self.entries = []
        while entry:
            self.entries.append(entry)
            entry = fstab._table.next_fs()
        self.cur_index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.cur_index < len(self.entries):
            self.cur_index += 1
            return FSTabEntry(entry=self.entries[self.cur_index - 1])
        raise StopIteration


class FSTabManager(object):
    """ Read, write and modify fstab file.
        This class is meant to work even without blivet.
        However some of its methods require blivet and will not function without it.
    """

    def __init__(self, src_file=None, dest_file=None):
        """ Initialize internal table; load the file if specified

            :keyword src_file: Path to fstab file which will be read
            :type src_file: str
            :keyword dest_file: Path to file which will be overwritten with results
            :type src_file: str
        """

        self._table = Table()   # Space for parsed fstab contents
        self._table.enable_comments(True)

        self.src_file = src_file
        self.dest_file = dest_file

        # preferred spec identification type; default "UUID"
        # possible values: None, "UUID", "LABEL", "PARTLABEL", "PARTUUID", "PATH"
        self.spec_type = None

        if self.src_file is not None:
            # self.read() will raise an exception in case of invalid fstab path.
            # This can interrupt object initialization thus preventing even setting read path
            # to something else.
            # This suppresses the exception.
            if os.path.isfile(self.src_file):
                self.read()
            else:
                # Acceptable at this point, but notify the user
                log.info("Fstab file '%s' does not exist, setting fstab read path to None", self.src_file)
                self.src_file = None

    def __deepcopy__(self, memo):
        clone = FSTabManager(src_file=self.src_file, dest_file=self.dest_file)
        clone._table = Table()
        clone._table.enable_comments(True)

        # Two special variables for the first and last comment. When assigning None to them, libmount fails.
        # Notice that we are copying the value from the instance of the same type.
        if self._table.intro_comment is not None:
            clone._table.intro_comment = self._table.intro_comment
        if self._table.trailing_comment is not None:
            clone._table.trailing_comment = self._table.trailing_comment

        entry = self._table.next_fs()
        entries = []
        while entry:
            entries.append(entry)
            entry = self._table.next_fs()

        for entry in entries:
            new_entry = self._copy_fs_entry(entry)
            clone._table.add_fs(new_entry)

        return clone

    def __str__(self):
        entry = self._table.next_fs()
        entries_str = ""
        while entry:
            entries_str += repr(FSTabEntry(entry=entry)) + '\n'
            entry = self._table.next_fs()
        return entries_str

    def __iter__(self):
        return FSTabManagerIterator(self)

    def _copy_fs_entry(self, entry):
        """ Create copy of libmount.Fs()
        """
        # Nope, it has to be done like this. Oh well...
        new_entry = Fs()
        new_entry.source = entry.source
        new_entry.target = entry.target
        new_entry.fstype = entry.fstype
        new_entry.append_options(entry.options)
        new_entry.freq = entry.freq
        new_entry.passno = entry.passno
        if entry.comment is not None:
            new_entry.comment = entry.comment
        return new_entry

    def _parser_errcb(self, tb, fname, line):  # pylint: disable=unused-argument
        """ Libmount interface error reporting function
        """
        log.error("Fstab parse error '%s:%s'", fname, line)
        return 1

    def entry_from_device(self, device):
        """ Generate FSTabEntry object based on given blivet Device

            :keyword device: device to process
            :type device: :class: `blivet.devices.StorageDevice`
            :returns: fstab entry object based on device
            :rtype: :class: `FSTabEntry`
        """

        entry = FSTabEntry()

        entry.file = None
        if device.format.mountable:
            entry.file = device.format.mountpoint
        elif device.format.type == "swap":
            entry.file = "swap"
        else:
            raise ValueError("""cannot generate fstab entry from device '%s' because
                                it is neither mountable nor swap type""" % device.format.name)

        entry.spec = self._get_spec(device)
        if entry.spec is None:
            entry.spec = getattr(device, "fstab_spec", None)

        if hasattr(device.format, "mount_type") and device.format.mount_type is not None:
            entry.vfstype = device.format.mount_type
        else:
            entry.vfstype = device.format.type

        return entry

    def entry_from_action(self, action):
        """ Generate FSTabEntry object based on given blivet Action

            :keyword action: action to process
            :type action: :class: `blivet.deviceaction.DeviceAction`
            :returns: fstab entry object based on device processed by action
            :rtype: :class: `FSTabEntry`
        """

        if not action.is_format:
            raise ValueError("""cannot generate fstab entry from action '%s' because
                                its type is not 'format'""" % action)

        fmt = action.format
        if action.is_destroy:
            fmt = action.orig_format
        if action.is_create:
            fmt = action.device.format

        entry = FSTabEntry()

        entry.file = None
        if fmt.mountable:
            entry.file = fmt.mountpoint
        elif fmt.type == "swap":
            entry.file = "swap"
        else:
            raise ValueError("""cannot generate fstab entry from action '%s' because
                                it is neither mountable nor swap type""" % action)

        entry.spec = self._get_spec(action.device)
        if entry.spec is None:
            entry.spec = getattr(action.device, "fstab_spec", None)

        if hasattr(action.device.format, "mount_type") and action.device.format.mount_type is not None:
            entry.vfstype = action.device.format.mount_type
        else:
            entry.vfstype = action.device.format.type

        return entry

    def read(self):
        """ Read the fstab file from path stored in self.src_file. Resets currently loaded table contents.
        """

        # Reset table
        self._table = Table()
        self._table.enable_comments(True)

        # resolve which file to read
        if self.src_file is None:
            return

        self._table.errcb = self._parser_errcb

        if not os.path.isfile(self.src_file):
            raise FileNotFoundError("Fstab file '%s' does not exist" % self.src_file)

        self._table.parse_fstab(self.src_file)

    def find_device(self, devicetree, spec=None, mntops=None, blkid_tab=None, crypt_tab=None, *, entry=None):
        """ Find a blivet device, based on spec or entry. Mount options can be used to refine the search.
            If both entry and spec/mntops are given, spec/mntops are prioritized over entry values.

            :param devicetree: populated blivet.Devicetree instance
            :type devicetree: :class: `blivet.Devicetree`
            :keyword spec: searched device specs (see man fstab(5) fs_spec)
            :type spec: str
            :keyword mntops: list of mount option strings (see man fstab(5) fs_mntops)
            :type mnops: list
            :keyword blkid_tab: Blkidtab object
            :type blkid_tab: :class: `BlkidTab`
            :keyword crypt_tab: Crypttab object
            :type crypt_tab: :class: `CryptTab`
            :keyword entry: fstab entry with its spec (and mntops) filled as an alternative input type
            :type: :class: `FSTabEntry`
            :returns: found device or None
            :rtype: :class: `~.devices.StorageDevice` or None
        """

        _spec = spec or (entry.spec if entry is not None else None)
        _mntops = mntops or (entry.mntops if entry is not None else None)
        _mntops_str = ",".join(_mntops) if mntops is not None else None

        return devicetree.resolve_device(_spec, options=_mntops_str, blkid_tab=blkid_tab, crypt_tab=crypt_tab)

    def get_device(self, devicetree, spec=None, file=None, vfstype=None,
                   mntops=None, blkid_tab=None, crypt_tab=None, *, entry=None):
        """ Parse an fstab entry for a device and return the corresponding device from the devicetree.
            If not found, try to create a new device based on given values.
            Raises UnrecognizedFSTabError in case of invalid or incomplete data.

            :param devicetree: populated blivet.Devicetree instance
            :type devicetree: :class: `blivet.Devicetree`
            :keyword spec: searched device specs (see man fstab(5) fs_spec)
            :type spec: str
            :keyword mntops: list of mount option strings (see man fstab(5) fs_mntops)
            :type mnops: list
            :keyword blkid_tab: Blkidtab object
            :type blkid_tab: :class: `BlkidTab`
            :keyword crypt_tab: Crypttab object
            :type crypt_tab: :class: `CryptTab`
            :keyword entry: fstab entry with its values filled as an alternative input type
            :type: :class: `FSTabEntry`
            :returns: found device
            :rtype: :class: `~.devices.StorageDevice`
        """

        from blivet.formats import get_format
        from blivet.devices import DirectoryDevice, FileDevice
        from blivet.errors import UnrecognizedFSTabEntryError

        _spec = spec or (entry.spec if entry is not None else None)
        _mntops = mntops or (entry.mntops if entry is not None else None)
        _mntops_str = ",".join(_mntops) if mntops is not None else None

        # find device in the tree
        device = devicetree.resolve_device(_spec, options=_mntops_str, blkid_tab=blkid_tab, crypt_tab=crypt_tab)

        if device is None:
            if vfstype == "swap":
                # swap file
                device = FileDevice(_spec,
                                    parents=devicetree.resolve_device(_spec),
                                    fmt=get_format(vfstype, device=_spec, exists=True),
                                    exists=True)
            elif vfstype == "bind" or (_mntops is not None and "bind" in _mntops):
                # bind mount... set vfstype so later comparison won't
                # turn up false positives
                vfstype = "bind"

                parents = devicetree.resolve_device(_spec)
                device = DirectoryDevice(_spec, parents=parents, exists=True)
                device.format = get_format("bind", device=device.path, exists=True)

        if device is None:
            raise UnrecognizedFSTabEntryError("Could not resolve entry %s %s" % (_spec, vfstype))

        fmt = get_format(vfstype, device=device.path, exists=True)
        if vfstype != "auto" and None in (device.format.type, fmt.type):
            raise UnrecognizedFSTabEntryError("Unrecognized filesystem type for %s: '%s'" % (_spec, vfstype))

        if hasattr(device.format, "mountpoint"):
            device.format.mountpoint = file

        device.format.options = _mntops

        return device

    def add_entry(self, spec=None, file=None, vfstype=None, mntops=None,
                  freq=None, passno=None, comment=None, *, entry=None):
        """ Add a new entry into the table
            If both entry and other values are given, these values are prioritized over entry values.
            If mntops/freq/passno is not set uses their respective default values.

            :keyword spec: device specs (see man fstab(5) fs_spec)
            :type spec: str
            :keyword file: device mount path (see man fstab(5) fs_file)
            :type file: str
            :keyword vfstype: device file system type (see man fstab(5) fs_vfstype)
            :type vfstype: str
            :keyword mntops: list of mount option strings (see man fstab(5) fs_mntops)
            :type mnops: list
            :keyword freq: whether to dump the filesystem (see man fstab(5) fs_freq)
            :type freq: int
            :keyword passno: fsck order or disable fsck if 0 (see man fstab(5) fs_passno)
            :type passno: int
            :keyword comment: multiline comment added to fstab before entry; each line will be prefixed with "# "
            :type comment: str
            :keyword entry: fstab entry as an alternative input type
            :type: :class: `FSTabEntry`
        """

        # Default mount options
        if mntops is None:
            mntops = ['defaults']

        # Use existing FSTabEntry or create a new one
        _entry = entry or FSTabEntry()

        if spec is not None:
            _entry.spec = spec

        if file is not None:
            _entry.file = file

        if vfstype is not None:
            _entry.vfstype = vfstype

        if mntops is not None:
            _entry.mntops = mntops
        if _entry.mntops is None:
            _entry.mntops = ['defaults']

        if freq is not None:
            # Whether the fs should be dumped by dump(8) (default: 0, i.e. no)
            _entry.freq = freq
        elif _entry.freq is None:
            _entry.freq = 0

        if passno is not None:
            _entry.passno = passno
        elif _entry.passno is None:
            # 'passno' represents order of fsck run at the boot time (default: 0, i.e. disabled).
            # '/' should have 1, other checked should have 2
            if _entry.file == '/':
                _entry.passno = 1
            elif _entry.file.startswith('/boot'):
                _entry.passno = 2
            else:
                _entry.passno = 0

        if comment is not None:
            # Add '# ' at the start of any comment line and newline to the end of comment.
            # Has to be done here since libmount won't do it.
            modif_comment = '# ' + comment.replace('\n', '\n# ') + '\n'
            _entry.comment = modif_comment

        self._table.add_fs(_entry.entry)

    def remove_entry(self, spec=None, file=None, *, entry=None):
        """ Find and remove entry from fstab based on spec/file.
            If both entry and spec/file are given, spec/file are prioritized over entry values.

            :keyword spec: device specs (see man fstab(5) fs_spec)
            :type spec: str
            :keyword file: device mount path (see man fstab(5) fs_file)
            :type file: str
            :keyword entry: fstab entry as an alternative input type
            :type: :class: `FSTabEntry`
        """

        fs = self.find_entry(spec, file, entry=entry)
        if fs:
            self._table.remove_fs(fs.entry)
        else:
            raise ValueError("Cannot remove entry (%s) from fstab, because it is not there" % entry)

    def write(self, dest_file=None):
        """ Commit the self._table into the self._dest_file. Setting dest_file parameter overrides
            writing path with its value.

            :keyword dest_file: When set, writes fstab to the path specified in it
            :type dest_file: str
        """

        if dest_file is None:
            dest_file = self.dest_file
        if dest_file is None:
            log.info("Fstab path for writing was not specified")
            return

        # Output sanity check to prevent saving an incomplete file entries
        # since libmount happily inserts incomplete lines into the fstab.
        # Invalid lines should be skipped, but the whole table is written at once.
        # Also the incomplete lines need to be preserved in the object.
        # Conclusion: Create the second table, prune invalid/incomplete lines and write it.

        clean_table = Table()
        clean_table.enable_comments(True)

        # Two special variables for the first and last comment. When assigning None libmount fails.
        # Notice that we are copying the value from the same type instance.
        if self._table.intro_comment is not None:
            clean_table.intro_comment = self._table.intro_comment
        if self._table.trailing_comment is not None:
            clean_table.trailing_comment = self._table.trailing_comment

        entry = self._table.next_fs()
        while entry:
            if FSTabEntry(entry=entry).is_valid():
                new_entry = self._copy_fs_entry(entry)
                clean_table.add_fs(new_entry)
            else:
                log.warning("Fstab entry: '%s' is incomplete, it will not be written into the file", entry)
            entry = self._table.next_fs()

        if os.path.exists(dest_file):
            clean_table.replace_file(dest_file)
        else:
            try:
                clean_table.write_file(dest_file)
            except Exception as e:  # pylint: disable=broad-except
                # libmount throws general Exception if underlying directories do not exist. Okay...
                if str(e) == "No such file or directory":
                    log.info("Underlying directory of fstab '%s' does not exist. creating...", dest_file)
                    os.makedirs(os.path.split(dest_file)[0])
                else:
                    raise

    def find_entry(self, spec=None, file=None, *, entry=None):
        """ Return the line of loaded fstab with given spec and/or file.
            If both entry and spec/file are given, spec/file are prioritized over entry values.

            :keyword spec: searched device specs (see man fstab(5) fs_spec)
            :type spec: str
            :keyword file: device mount path (see man fstab(5) fs_file)
            :type file: str
            :keyword entry: fstab entry as an alternative input type
            :type: :class: `FSTabEntry`
            :returns: found fstab entry object
            :rtype: :class: `FSTabEntry` or None
        """

        _spec = spec or (entry.spec if entry is not None else None)
        _file = file or (entry.file if entry is not None else None)

        found_entry = None

        if _spec is not None and _file is not None:
            try:
                found_entry = self._table.find_pair(_spec, _file, MNT_ITER_FORWARD)
            except LibmountException:
                return None
            return FSTabEntry(entry=found_entry)

        if _spec is not None:
            try:
                found_entry = self._table.find_source(_spec, MNT_ITER_FORWARD)
            except LibmountException:
                return None
            return FSTabEntry(entry=found_entry)

        if file is not None:
            try:
                found_entry = self._table.find_target(file, MNT_ITER_FORWARD)
            except LibmountException:
                return None
            return FSTabEntry(entry=found_entry)

        return None

    def _get_spec(self, device):
        """ Resolve which device spec should be used and return it in a form accepted by fstab.
            Returns None if desired spec was not found
        """

        # Use device specific spec type if it is set
        # Use "globally" set (on FSTabManager level) spec type otherwise

        spec = None

        if hasattr(device.format, 'fstab') and device.format.fstab.spec_type:
            spec_type = device.format.fstab.spec_type
        else:
            spec_type = self.spec_type

        if spec_type == "LABEL" and device.format.label:
            spec = "LABEL=%s" % device.format.label
        elif spec_type == "PARTUUID" and device.uuid:
            spec = "PARTUUID=%s" % device.uuid
        elif spec_type == "PARTLABEL" and device.format.name:
            spec = "PARTLABEL=%s" % device.format.name
        elif spec_type == "PATH":
            spec = device.path
        elif device.format.uuid:
            # default choice
            spec = "UUID=%s" % device.format.uuid
        else:
            # if everything else failed, let blivet decide
            return None

        return spec

    def update(self, action, bae_entry):
        """ Update fstab based on action type and device. Does not commit changes to a file.

            :param action: just executed blivet action
            :type action: :class: `~.deviceaction.DeviceAction`
            :param bae_entry: fstab entry based on action.device before action.execute was called
            :type bae_entry: :class: `FSTabEntry` or None
        """

        if not action._applied:
            return

        if action.is_destroy and bae_entry is not None:
            # remove destroyed device from the fstab
            self.remove_entry(entry=bae_entry)
            return

        if action.is_create and action.is_device and action.device.type == "luks/dm-crypt":
            # when creating luks format, two actions are made. Device creation
            # does not have UUID assigned yet, so we skip that one
            return

        if action.is_create and action.is_format and action.device.format.mountable:
            # add the device to the fstab
            # make sure it is not already present there
            try:
                entry = self.entry_from_device(action.device)
            except ValueError:
                # this device should not be at fstab
                found = None
                entry = None
            else:
                found = self.find_entry(entry=entry)

            # get correct spec type to use (if None, the one already present in entry is used)
            spec = self._get_spec(action.device)

            if found is None and action.device.format.mountpoint is not None:
                # device is not present in fstab and has a defined mountpoint => add it
                self.add_entry(spec=spec,
                               file=action.device.format.mountpoint,
                               mntops=action.device.format.fstab.mntops,
                               freq=action.device.format.fstab.freq,
                               passno=action.device.format.fstab.passno,
                               entry=entry)
            elif found and found.spec != spec and action.device.format.mountpoint is not None:
                # allow change of spec of existing devices
                self.remove_entry(entry=found)
                self.add_entry(spec=spec,
                               mntops=action.device.format.fstab.mntops,
                               freq=action.device.format.fstab.freq,
                               passno=action.device.format.fstab.passno,
                               entry=found)
            elif found and found.file != action.device.format.mountpoint and action.device.format.mountpoint is not None:
                # device already exists in fstab but with a different mountpoint => add it
                self.add_entry(spec=spec,
                               file=action.device.format.mountpoint,
                               mntops=action.device.format.fstab.mntops,
                               freq=action.device.format.fstab.freq,
                               passno=action.device.format.fstab.passno,
                               entry=found)
            return

        if action.is_configure and action.is_format and bae_entry is not None:
            # Handle change of the mountpoint:
            # Change its value if it is defined, remove the fstab entry if it is None

            # get correct spec type to use (if None, the one already present in entry is used)
            spec = self._get_spec(action.device)

            if action.device.format.mountpoint is not None and bae_entry.file != action.device.format.mountpoint:
                self.remove_entry(entry=bae_entry)
                self.add_entry(spec=spec,
                               file=action.device.format.mountpoint,
                               mntops=action.device.format.fstab.mntops,
                               freq=action.device.format.fstab.freq,
                               passno=action.device.format.fstab.passno,
                               entry=bae_entry)
            elif action.device.format.mountpoint is None:
                self.remove_entry(entry=bae_entry)
