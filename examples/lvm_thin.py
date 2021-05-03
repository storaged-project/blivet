import os

import blivet
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create a disk image file on which to create new devices
disk1_file = create_sparse_tempfile("disk1", Size("100GiB"))
b.disk_images["disk1"] = disk1_file

b.reset()

try:
    disk1 = b.devicetree.get_device_by_name("disk1")

    b.initialize_disk(disk1)

    pv = b.new_partition(size=Size("50GiB"), fmt_type="lvmpv")
    b.create_device(pv)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.do_partitioning(b)

    vg = b.new_vg(parents=[pv])
    b.create_device(vg)

    # new 40 GiB thin pool
    pool = b.new_lv(thin_pool=True, size=Size("40 GiB"), parents=[vg])
    b.create_device(pool)

    # new 20 GiB thin lv
    thinlv = b.new_lv(thin_volume=True, size=Size("20 GiB"), parents=[pool],
                      fmt_type="ext4")
    b.create_device(thinlv)

    # new snapshot of the thin volume we just created
    snap = b.new_lv(name=thinlv.name + "_snapshot", parents=[pool], origin=thinlv,
                    seg_type="thin")
    b.create_device(snap)

    # write the new partitions to disk and format them as specified
    b.do_it()
    print(b.devicetree)
finally:
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
