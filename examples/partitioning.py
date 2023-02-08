import os

import blivet
from uuid import UUID
from blivet.devices import LUKSDevice
from blivet.size import Size
from blivet.flags import flags
from blivet import formats
from blivet.formats import disklabel
from blivet.util import set_up_logging, create_sparse_tempfile

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create two disk image files on which to create new devices
disk1_file = create_sparse_tempfile("disk1", Size("100GiB"))
b.disk_images["disk1"] = disk1_file
disk2_file = create_sparse_tempfile("disk2", Size("100GiB"))
b.disk_images["disk2"] = disk2_file

b.reset()

disklabel.DiskLabel.set_default_label_type("gpt")
flags.gpt_discoverable_partitions = True

try:
    disk1 = b.devicetree.get_device_by_name("disk1")
    disk2 = b.devicetree.get_device_by_name("disk2")

    b.initialize_disk(disk1)
    b.initialize_disk(disk2)

    # new partition on either disk1 or disk2 with base size 10GiB and growth
    # up to a maximum size of 50GiB
    root = b.new_partition(size=Size("10MiB"), maxsize=Size("50GiB"),
                           grow=True, parents=[disk1, disk2],
                           mountpoint="/")
    b.create_device(root)

    # new partition on disk1 with base size 5GiB and unbounded growth and an
    # ext4 filesystem
    home = b.new_partition(fmt_type="ext4", size=Size("5GiB"), grow=True,
                           parents=[disk1], mountpoint="/home")
    b.create_device(home)

    var = b.new_partition(fmt_type="luks",
                          fmt_args={
                              "passphrase": "123456",
                          }, size=Size("200MiB"),
                          parents=[disk2],
                          mountpoint="/var")
    b.create_device(var)

    varenc = LUKSDevice(
        name="luks-user", size=var.size, parents=var)
    b.create_device(varenc)

    varfs = formats.get_format(
        fmt_type="ext4", device=varenc.path, mountpoint="/usr")
    b.format_device(varenc, varfs)

    # new partition on any suitable disk with a fixed size of 2GiB formatted
    # as swap space
    swap = b.new_partition(fmt_type="swap", size=Size("2GiB"))
    b.create_device(swap)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.do_partitioning(b)
    print(b.devicetree)

    # write the new partitions to disk and format them as specified
    b.do_it()
    print(b.devicetree)

    print("/ assigned GUID %s" % UUID(bytes=root.parted_partition.type_uuid))
    print("/home assigned GUID %s" % UUID(bytes=home.parted_partition.type_uuid))
    print("/var assigned GUID %s" % UUID(bytes=var.parted_partition.type_uuid))
    print("<swap> assigned GUID %s" % UUID(bytes=swap.parted_partition.type_uuid))

finally:
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
    os.unlink(disk2_file)
