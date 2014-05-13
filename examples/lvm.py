import os

from common import print_devices

import blivet
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create a disk image file on which to create new devices
disk1_file = create_sparse_tempfile("disk1", Size("100GiB"))
b.config.diskImages["disk1"] = disk1_file

b.reset()

try:
    disk1 = b.devicetree.getDeviceByName("disk1")

    b.initializeDisk(disk1)

    pv = b.newPartition(size=Size("50GiB"), fmt_type="lvmpv")
    b.createDevice(pv)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.doPartitioning(b)

    vg = b.newVG(parents=[pv])
    b.createDevice(vg)

    # new lv with base size 5GiB and unbounded growth and an ext4 filesystem
    dev = b.newLV(fmt_type="ext4", size=Size("5GiB"), grow=True,
                  parents=[vg], name="unbounded")
    b.createDevice(dev)

    # new lv with base size 5GiB and growth up to 15GiB and an ext4 filesystem
    dev = b.newLV(fmt_type="ext4", size=Size("5GiB"), grow=True,
                  maxsize=Size("15GiB"), parents=[vg], name="bounded")
    b.createDevice(dev)

    # new lv with a fixed size of 2GiB formatted as swap space
    dev = b.newLV(fmt_type="swap", size=Size("2GiB"), parents=[vg])
    b.createDevice(dev)

    # allocate the growable lvs
    blivet.partitioning.growLVM(b)
    print_devices(b)

    # write the new partitions to disk and format them as specified
    b.doIt()
    print_devices(b)
finally:
    b.devicetree.teardownDiskImages()
    os.unlink(disk1_file)
