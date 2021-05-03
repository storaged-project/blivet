import os

import blivet
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile
from blivet.devices import LUKSDevice

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

    # new lv with base size 5GiB and unbounded growth and an ext4 filesystem
    dev = b.new_lv(fmt_type="ext4", size=Size("5GiB"), grow=True,
                   parents=[vg], name="unbounded")
    b.create_device(dev)

    # new lv with base size 5GiB and growth up to 15GiB and an ext4 filesystem
    dev = b.new_lv(fmt_type="ext4", size=Size("5GiB"), grow=True,
                   maxsize=Size("15GiB"), parents=[vg], name="bounded")
    b.create_device(dev)

    # new lv with a fixed size of 2GiB formatted as swap space
    dev = b.new_lv(fmt_type="swap", size=Size("2GiB"), parents=[vg])
    b.create_device(dev)

    # new LUKS encrypted lv with fixed size of 10GiB and ext4 filesystem
    dev = b.new_lv(fmt_type="luks", fmt_args={"passphrase": "12345"},
                   size=Size("10GiB"), parents=[vg], name="encrypted")
    b.create_device(dev)

    luks_dev = LUKSDevice(name="luks-%s" % dev.name,
                          size=dev.size, parents=[dev])
    b.create_device(luks_dev)

    luks_fmt = blivet.formats.get_format(fmt_type="ext4", device=luks_dev.path)
    b.format_device(luks_dev, luks_fmt)

    # allocate the growable lvs
    blivet.partitioning.grow_lvm(b)
    print(b.devicetree)

    # write the new partitions to disk and format them as specified
    b.do_it()
    print(b.devicetree)
finally:
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
