import os

from libmount import Table, Fs, MNT_ITER_FORWARD
from libmount import Error as LibmountException

def parser_errcb(tb, fname, line):
    print("{:s}:{:d}: parse error".format(fname, line))
    return 1

class FSTabManager():
    """ Read, write and modify fstab file """

    def __init__(self, src_file=None, dest_file=None):
        self._table = Table()   # Space for parsed fstab contents

        self.src_file = src_file

        self.dest_file = dest_file
        if dest_file is None:
            dest_file = self.src_file

        if self.src_file is not None:
            #self.read(self.src_file)
            self.read("/home/japokorn/myroot/fstab_copy")

    def _get_containing_device(self, path, devicetree):
        """ Return the device that a path resides on. """
        if not os.path.exists(path):
            return None

        st = os.stat(path)
        major = os.major(st.st_dev)
        minor = os.minor(st.st_dev)
        link = "/sys/dev/block/%s:%s" % (major, minor)
        if not os.path.exists(link):
            return None

        try:
            device_name = os.path.basename(os.readlink(link))
        except Exception:  # pylint: disable=broad-except
            log_exception_info(fmt_str="failed to find device name for path %s", fmt_args=[path])
            return None

        if device_name.startswith("dm-"):
            # have I told you lately that I love you, device-mapper?
            # (code and comment copied from anaconda, kept for entertaining purposes)
            device_name = blockdev.dm.name_from_node(device_name)

        return devicetree.get_device_by_name(device_name)

    def read(self, src_file=None):
        # Read fstab file

        # Reset table
        self._table = Table()
        self._table.enable_comments(True)

        # resolve which file to read
        if src_file is None:
            if self._src_file is None:
                # No parameter given, no internal value
                return
        else:
            self._src_file = src_file

        self._table.errcb = parser_errcb
        self._table.parse_fstab(self._src_file)

    def get_device(self, blivet, spec, file, vfstype, mntops, freq="0", passno="0"):
        # Parse an fstab entry for a device, return the corresponding device.

        # TODO make sure imports do not need some extra logic
        from blivet.formats import get_format
        from blivet.devices import DirectoryDevice, FileDevice, NoDevice

        # no sense in doing any legwork for a noauto entry
        if "noauto" in mntops.split(","):
            raise ValueError("Unrecognized fstab entry value 'noauto'")

        # find device in the tree
        device = blivet.devicetree.resolve_device(spec, options=mntops)

        if device:
            # fall through to the bottom of this block
            pass
        elif ":" in spec and vfstype.startswith("nfs"):
            # NFS -- preserve but otherwise ignore
            device = NFSDevice(spec,
                               fmt=get_format(vfstype,
                                              exists=True,
                                              device=spec))
        elif spec.startswith("/") and vfstype == "swap":
            # swap file
            device = FileDevice(spec,
                                parents=self._get_containing_device(spec, blivet.devicetree),
                                fmt=get_format(vfstype,
                                               device=spec,
                                               exists=True),
                                exists=True)
        elif vfstype == "bind" or "bind" in mntops:
            # bind mount... set vfstype so later comparison won't
            # turn up false positives
            vfstype = "bind"

            # This is probably not going to do anything useful, so we'll
            # make sure to try again from FSSet.mount_filesystems. The bind
            # mount targets should be accessible by the time we try to do
            # the bind mount from there.
            parents = self._get_containing_device(spec, blivet.devicetree)
            device = DirectoryDevice(spec, parents=parents, exists=True)
            device.format = get_format("bind",
                                       device=device.path,
                                       exists=True)
        elif file in ("/proc", "/sys", "/dev/shm", "/dev/pts",
                      "/sys/fs/selinux", "/proc/bus/usb", "/sys/firmware/efi/efivars"):
            # drop these now -- we'll recreate later
            return None
        else:
            # nodev filesystem -- preserve or drop completely?
            fmt = get_format(vfstype)
            fmt_class = get_device_format_class("nodev")
            if spec == "none" or \
               (fmt_class and isinstance(fmt, fmt_class)):
                device = NoDevice(fmt=fmt)

        if device is None:
            log.error("failed to resolve %s (%s) from fstab", spec,
                      vfstype)
            raise ValueError()

        device.setup()
        fmt = get_format(vfstype, device=device.path, exists=True)
        if vfstype != "auto" and None in (device.format.type, fmt.type):
            log.info("Unrecognized filesystem type for %s (%s)",
                     device.name, vfstype)
            device.teardown()
            raise ValueError()

        # make sure, if we're using a device from the tree, that
        # the device's format we found matches what's in the fstab
        ftype = getattr(fmt, "mount_type", fmt.type)
        dtype = getattr(device.format, "mount_type", device.format.type)
        if hasattr(fmt, "test_mount") and vfstype != "auto" and ftype != dtype:
            log.info("fstab says %s at %s is %s", dtype, file, ftype)
            if fmt.test_mount():     # pylint: disable=no-member
                device.format = fmt
            else:
                device.teardown()
                raise ValueError(_(
                    "There is an entry in your /etc/fstab file that contains "
                    "an invalid or incorrect file system type. The file says that "
                    "{detected_type} at {mount_point} is {fstab_type}.").format(
                    detected_type=dtype,
                    mount_point=file,
                    fstab_type=ftype
                ))

        del ftype
        del dtype

        if hasattr(device.format, "mountpoint"):
            device.format.mountpoint = file

        device.format.options = mntops

        return device

    def from_device(self, device):
        """ return list of fstab options obtained from device """
        spec = getattr(device, 'fstab_spec', None)

        file = None
        if device.format.mountable:
            file = device.format.mountpoint
        if device.format.type == 'swap':
            file = 'swap'

        vfstype = device.format.type
        mntops = None

        return spec, file, vfstype, mntops

    def add_entry(self, spec, file, vfstype, mntops, freq=None, passno=None, comment=None):
        # Default mount options
        if mntops is None:
            mntops = 'defaults'

        # Whether the fs should be dumped by dump(8), defaults to 0 
        if freq is None:
            freq = 0

        # Order of fsck run at boot time. '/' should have 1, other 2, defaults to 0
        if passno is None:
            if file is None:
                file = ''
            if file == '/':
                passno = 1
            elif file.startswith('/boot'):
                passno = 2
            else:
                passno = 0

        entry = Fs()

        entry.source = spec
        entry.target = file
        entry.fstype = vfstype
        entry.append_options(mntops)
        entry.freq = freq
        entry.passno = passno

        if comment is not None:
            # add '# ' at the start of any comment line and newline to the end of comment
            modif_comment = '# ' + comment.replace('\n', '\n# ') + '\n'
            entry.comment = modif_comment

        self._table.add_fs(entry)

    def remove_entry(self, spec, file, vfstype, mntops):
        fs = self.find(spec, file, vfstype, mntops)
        if fs:
            self._table.remove_fs(fs)

    def write(self, dest_file = None):
        if dest_file is None:
            dest_file = self.dest_file

        if os.path.exists(dest_file):
            self._table.replace_file(dest_file)
        else:
            # write will fail if underlying directories do not exist
            self._table.write_file(dest_file)

    def find(self, spec, file, vfstype, mntops):
        # TODO add find_pair if both spec and file are given

        entry = None
        if spec is not None:
            try:
                entry = self._table.find_source(spec, MNT_ITER_FORWARD)
            except LibmountException:
                entry = None

        if file is not None:
            try:
                entry = self._table.find_target(file)
            except LibmountException:
                entry = None
        return entry

    def update(self, devices):
        # remove entries not tied to any device

        fstab_entries = []
        entry = self._table.next_fs()
        while entry:
            fstab_entries.append(entry)
            entry = self._table.next_fs()

        for device in devices:
            args = self.from_device(device)
            entry = self.find(*args)

            # remove from the list if found
            try:
                fstab_entries.remove(entry)
            except ValueError:
                pass

        # add new entries based on devices not in the table
        for device in devices:
            # if mountable the device should be in the fstab
            if device.format.mountable:
                args = self.from_device(device)
                found = self.find(*args)
                if found is None:
                    self.add_entry(*args)
                elif found.target != device.format.mountpoint:
                    # TODO will it replace it or create a new one?
                    self.add_entry(args[0], device.format.mountpoint, args[2], args[3])
