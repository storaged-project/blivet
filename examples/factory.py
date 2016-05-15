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
    disk1.format = blivet.formats.get_format("disklabel", device=disk1.path)
    disk2.format = blivet.formats.get_format("disklabel", device=disk2.path)

    # create an lv named data in a vg named testvg
    device = b.factory_device(blivet.devicefactory.DEVICE_TYPE_LVM,
                              Size("50GiB"), disks=[disk1, disk2],
                              fstype="xfs", mountpoint="/data")
    print(b.devicetree)

    # change testvg to have an md RAID1 pv instead of partition pvs
    device = b.factory_device(blivet.devicefactory.DEVICE_TYPE_LVM,
                              Size("50GiB"), disks=[disk1, disk2],
                              fstype="xfs", mountpoint="/data",
                              container_raid_level="raid1",
                              device=device)
    print(b.devicetree)

    b.do_it()
    print(b.devicetree)
finally:
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
    os.unlink(disk2_file)
