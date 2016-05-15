import os

import blivet
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create two disk image files on which to create new devices
disk1_file = create_sparse_tempfile("disk1", Size("100GiB"))
b.disk_images["disk1"] = disk1_file
disk2_file = create_sparse_tempfile("disk2", Size("100GiB"))
b.disk_images["disk2"] = disk2_file

b.reset()

try:
    disk1 = b.devicetree.get_device_by_name("disk1")
    disk2 = b.devicetree.get_device_by_name("disk2")

    b.initialize_disk(disk1)
    b.initialize_disk(disk2)

    # new partition on either disk1 or disk2 with base size 10GiB and growth
    # up to a maximum size of 50GiB
    dev = b.new_partition(size=Size("10MiB"), maxsize=Size("50GiB"),
                          grow=True, parents=[disk1, disk2])
    b.create_device(dev)

    # new partition on disk1 with base size 5GiB and unbounded growth and an
    # ext4 filesystem
    dev = b.new_partition(fmt_type="ext4", size=Size("5GiB"), grow=True,
                          parents=[disk1])
    b.create_device(dev)

    # new partition on any suitable disk with a fixed size of 2GiB formatted
    # as swap space
    dev = b.new_partition(fmt_type="swap", size=Size("2GiB"))
    b.create_device(dev)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.do_partitioning(b)
    print(b.devicetree)

    # write the new partitions to disk and format them as specified
    b.do_it()
    print(b.devicetree)
finally:
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
    os.unlink(disk2_file)
