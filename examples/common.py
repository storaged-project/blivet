import logging

def set_up_logging():
    """ Configure the blivet logger to use /tmp/blivet.log as its log file. """
    blivet_log = logging.getLogger("blivet")
    blivet_log.setLevel(logging.DEBUG)
    program_log = logging.getLogger("program")
    program_log.setLevel(logging.DEBUG)
    handler = logging.FileHandler("/tmp/blivet.log")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    blivet_log.addHandler(handler)
    program_log.addHandler(handler)

def print_devices(b):
    for device in sorted(b.devices, key=lambda d: len(d.ancestors)):
        print device    # this is a blivet.devices.StorageDevice instance

    print

def create_sparse_file(b, name, size):
    """ Create a sparse file for use as a disk image. """
    import blivet
    import tempfile

    (_fd, path) = tempfile.mkstemp(prefix="blivet.", suffix="-image-%s" % name)

    file_device = blivet.devices.SparseFileDevice(path, size=size)
    file_device.create()
    return path

def tear_down_disk_images(b):
    """ Tear down any disk image stacks. """
    b.devicetree.teardownAll()
    for (name, _path) in b.config.diskImages.items():
        dm_device = b.devicetree.getDeviceByName(name)
        if not dm_device:
            continue

        dm_device.deactivate()
        loop_device = dm_device.parents[0]
        loop_device.teardown()
