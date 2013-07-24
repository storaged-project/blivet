import logging
import sys
import os

from common import set_up_logging
from common import create_sparse_file
from common import tear_down_disk_images
from common import print_devices

# doing this before importing blivet gets the logging from format class
# registrations and other stuff triggered by the import
set_up_logging()
blivet_log = logging.getLogger("blivet")
blivet_log.info(sys.argv[0])

import blivet

b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create two disk image files on which to create new devices
disk1_file = create_sparse_file(b, "disk1", 100000)
b.config.diskImages["disk1"] = disk1_file
disk2_file = create_sparse_file(b, "disk2", 100000)
b.config.diskImages["disk2"] = disk2_file

b.reset()

try:
    disk1 = b.devicetree.getDeviceByName("disk1")
    disk2 = b.devicetree.getDeviceByName("disk2")

    b.initializeDisk(disk1)
    b.initializeDisk(disk2)

    # new partition on either disk1 or disk2 with base size 10000 MiB and growth
    # up to a maximum size of 50000 MiB
    dev = b.newPartition(size=10000, grow=True, maxsize=50000,
                         parents=[disk1, disk2])
    b.createDevice(dev)

    # new partition on disk1 with base size 5000 MiB and unbounded growth and an
    # ext4 filesystem
    dev = b.newPartition(fmt_type="ext4", size=5000, grow=True, parents=[disk1])
    b.createDevice(dev)

    # new partition on any suitable disk with a fixed size of 2000 MiB formatted
    # as swap space
    dev = b.newPartition(fmt_type="swap", size=2000)
    b.createDevice(dev)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.doPartitioning(b)
    print_devices(b)

    # write the new partitions to disk and format them as specified
    b.doIt()
    print_devices(b)
finally:
    tear_down_disk_images(b)
    os.unlink(disk1_file)
    os.unlink(disk2_file)
