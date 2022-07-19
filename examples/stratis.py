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

    bd = b.new_partition(size=Size("50GiB"), fmt_type="stratis", parents=[disk1])
    b.create_device(bd)
    bd2 = b.new_partition(size=Size("50GiB"), fmt_type="stratis", parents=[disk2])
    b.create_device(bd2)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.do_partitioning(b)

    pool = b.new_stratis_pool(name="stratis_pool", parents=[bd, bd2])
    b.create_device(pool)

    # # encrypted stratis pool can be created by adding "encrypted" and "passphrase"
    # # keywords, only the entire pool can be encrypted:
    # pool = b.new_stratis_pool(name="stratis_pool", parents=[bd, bd2], encrypted=True, passphrase="secret")
    # b.create_device(pool)

    fs = b.new_stratis_filesystem(name="stratis_filesystem", parents=[pool])
    b.create_device(fs)

    print(b.devicetree)

    # write the new partitions to disk and format them as specified
    b.do_it()
    print(b.devicetree)
    input("Check the state and hit ENTER to trigger cleanup")
finally:
    b.devicetree.recursive_remove(pool)
    b.do_it()
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
    os.unlink(disk2_file)
