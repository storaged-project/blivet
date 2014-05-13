import os

from common import print_devices

import blivet
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create two disk image files on which to create new devices
disk1_file = create_sparse_tempfile("disk1", Size("100GiB"))
b.config.diskImages["disk1"] = disk1_file
disk2_file = create_sparse_tempfile("disk2", Size("100GiB"))
b.config.diskImages["disk2"] = disk2_file

b.reset()

try:
    disk1 = b.devicetree.getDeviceByName("disk1")
    disk2 = b.devicetree.getDeviceByName("disk2")

    b.initializeDisk(disk1)
    b.initializeDisk(disk2)

    # new partition on either disk1 or disk2 with base size 10GiB and growth
    # up to a maximum size of 50GiB
    dev = b.newPartition(size=Size("10MiB"), maxsize=Size("50GiB"),
                         grow=True, parents=[disk1, disk2])
    b.createDevice(dev)

    # new partition on disk1 with base size 5GiB and unbounded growth and an
    # ext4 filesystem
    dev = b.newPartition(fmt_type="ext4", size=Size("5GiB"), grow=True,
                         parents=[disk1])
    b.createDevice(dev)

    # new partition on any suitable disk with a fixed size of 2GiB formatted
    # as swap space
    dev = b.newPartition(fmt_type="swap", size=Size("2GiB"))
    b.createDevice(dev)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.doPartitioning(b)
    print_devices(b)

    # write the new partitions to disk and format them as specified
    b.doIt()
    print_devices(b)
finally:
    b.devicetree.teardownDiskImages()
    os.unlink(disk1_file)
    os.unlink(disk2_file)
