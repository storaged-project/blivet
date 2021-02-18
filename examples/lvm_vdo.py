import os

import blivet
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create a disk image file on which to create new devices
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

    pv = b.new_partition(size=Size("50GiB"), fmt_type="lvmpv", parents=[disk1])
    b.create_device(pv)
    pv2 = b.new_partition(size=Size("50GiB"), fmt_type="lvmpv", parents=[disk2])
    b.create_device(pv2)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.do_partitioning(b)

    vg = b.new_vg(parents=[pv, pv2])
    b.create_device(vg)

    # create 80 GiB VDO pool
    # there can be only one VDO LV on the pool and these are created together
    # with one LVM call, we have 2 separate devices because there are two block
    # devices in the end and it allows to control the different "physical" size of
    # the pool and "logical" size of the VDO LV (which is usually bigger, accounting
    # for the saved space with deduplication and/or compression)
    pool = b.new_lv(size=Size("80GiB"), parents=[vg], name="vdopool", vdo_pool=True,
                    deduplication=True, compression=True)
    b.create_device(pool)

    # create the VDO LV with 400 GiB "virtual size" and ext4 filesystem on the VDO
    # pool
    lv = b.new_lv(size=Size("400GiB"), parents=[pool], name="vdolv", vdo_lv=True,
                  fmt_type="ext4")
    b.create_device(lv)

    print(b.devicetree)

    # write the new partitions to disk and format them as specified
    b.do_it()
    print(b.devicetree)
    input("Check the state and hit ENTER to trigger cleanup")
finally:
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
    os.unlink(disk2_file)
