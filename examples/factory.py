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
from blivet.size import Size

b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create two disk image files on which to create new devices
disk1_file = create_sparse_file(b, "disk1", Size(en_spec="100GiB"))
b.config.diskImages["disk1"] = disk1_file
disk2_file = create_sparse_file(b, "disk2", Size(en_spec="100GiB"))
b.config.diskImages["disk2"] = disk2_file

b.reset()

try:
    disk1 = b.devicetree.getDeviceByName("disk1")
    disk2 = b.devicetree.getDeviceByName("disk2")
    disk1.format = blivet.formats.getFormat("disklabel", device=disk1.path)
    disk2.format = blivet.formats.getFormat("disklabel", device=disk2.path)

    # create an lv named data in a vg named testvg
    device = b.factoryDevice(blivet.devicefactory.DEVICE_TYPE_LVM,
                             Size(en_spec="50GiB"), disks=[disk1, disk2],
                             fstype="xfs", mountpoint="/data")
    print_devices(b)

    # change testvg to have an md RAID1 pv instead of partition pvs
    device = b.factoryDevice(blivet.devicefactory.DEVICE_TYPE_LVM,
                             Size(en_spec="50GiB"), disks=[disk1, disk2],
                             fstype="xfs", mountpoint="/data",
                             container_raid_level="raid1",
                             device=device)
    print_devices(b)

    b.devicetree.processActions()
    print_devices(b)
finally:
    tear_down_disk_images(b)
    os.unlink(disk1_file)
    os.unlink(disk2_file)
