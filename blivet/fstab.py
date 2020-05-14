import logging
import os

from libmount import Table, Fs


log = logging.getLogger("blivet.fstab")
FSTAB_PATH = "/etc/fstab"


def error_cb(table, filename, line):
    log.error("fstab parse error: line %d", line)
    return 1


def _get_table():
    table = Table()
    table.enable_comments(True)
    table.errcb = error_cb

    try:
        table.parse_fstab()
    except Exception:
        pass

    return table


def write_fstab(table, filename=None):
    if filename is None:
        filename = FSTAB_PATH

    if os.path.exists(filename):
        table.replace_file(filename)
    else:
        table.write_file(filename)


def remove_entry(device=None, mountpoint=None):
    table = _get_table()
    if device is not None:
        source = device.path
        if device.format.mountable and device.format.mountpoint:
            target = device.format.mountpoint

    if mountpoint is not None:
        target = mountpoint

    if target:
        fs = table.find_target(target)
        if fs:
            table.remove_fs(fs)

    if source:
        fs = table.find_source(source)
        if fs:
            table.remove_fs(fs)


def add_entry(device):
    if not (device.format.mountable or device.format.type == "swap"):
        return

    if device.format.mountable and not device.format.mountpoint:
        return

    if device.format.type == "swap":
        mountpoint = "swap"
    else:
        mountpoint = device.format.mountpoint

    table = _get_table()
    fs = Fs()
    fs.source = device.fstab_spec
    fs.target = mountpoint
    fs.fstype = getattr(device.format, "mount_type", device.format.type)
    fs.options = device.format.options or "defaults"
    #fs.freq
    #fs.passno
    table.add_fs(fs)


class FSTab:
    def __init__(self, filename=None):
        self._table = None
        self.filename = filename

        self.read_table()

    def read_table(self):
        if self.filename is not None:
            kwargs = dict(fstab=self.filename)
        else:
            kwargs = dict()

        self._table = Table()
        self._table.enable_comments(True)
        self._table.errcb = error_cb

        try:
            self._table.parse_fstab(**kwargs)
        except Exception:
            pass

    def write_fstab(self, filename=None):
        if filename is None:
            if self.filename:
                filename = self.filename
            else:
                filename = FSTAB_PATH

        if os.path.exists(filename):
            self._table.replace_file(filename)
        else:
            self._table.write_file(filename)

    def __iter__(self):
        return self

    def __next__(self):
        entry = self._table.next_fs()
        if entry is None:
            raise StopIteration
        return entry

    def remove_entry(self, device=None, mountpoint=None):
        if device is not None:
            source = device.path
            if device.format.mountable and device.format.mountpoint:
                target = device.format.mountpoint

        if mountpoint is not None:
            target = mountpoint

        if target:
            fs = self._table.find_target(target)
            if fs:
                self._table.remove_fs(fs)

        if source:
            fs = self._table.find_source(source)
            if fs:
                self._table.remove_fs(fs)

    def add_entry(self, device):
        if not (device.format.mountable or device.format.type == "swap"):
            return

        if device.format.mountable and not device.format.mountpoint:
            return

        if device.format.type == "swap":
            mountpoint = "swap"
        else:
            mountpoint = device.format.mountpoint

        fs = Fs()
        fs.source = device.fstab_spec
        fs.target = mountpoint
        fs.fstype = getattr(device.format, "mount_type", None) or device.format.type
        fs.options = device.format.options or "defaults"
        #fs.freq
        #fs.passno
        self._table.add_fs(fs)
        return fs
