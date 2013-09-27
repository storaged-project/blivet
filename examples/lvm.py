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

# create a disk image file on which to create new devices
disk1_file = create_sparse_file(b, "disk1", Size(spec="100GB"))
b.config.diskImages["disk1"] = disk1_file

b.reset()

try:
    disk1 = b.devicetree.getDeviceByName("disk1")

    b.initializeDisk(disk1)

    pv = b.newPartition(size=Size(spec="50GB"), fmt_type="lvmpv")
    b.createDevice(pv)

    # allocate the partitions (decide where and on which disks they'll reside)
    blivet.partitioning.doPartitioning(b)

    vg = b.newVG(parents=[pv])
    b.createDevice(vg)

    # new lv with base size 5GB and unbounded growth and an ext4 filesystem
    dev = b.newLV(fmt_type="ext4", size=Size(spec="5GB"), grow=True,
                  parents=[vg], name="unbounded")
    b.createDevice(dev)

    # new lv with base size 5GB and growth up to 15GB and an ext4 filesystem
    dev = b.newLV(fmt_type="ext4", size=Size(spec="5GB"), grow=True,
                  maxsize=Size(spec="15GB"), parents=[vg], name="bounded")
    b.createDevice(dev)

    # new lv with a fixed size of 2GB formatted as swap space
    dev = b.newLV(fmt_type="swap", size=Size(spec="2GB"), parents=[vg])
    b.createDevice(dev)

    # allocate the growable lvs
    blivet.partitioning.growLVM(b)
    print_devices(b)

    # write the new partitions to disk and format them as specified
    b.doIt()
    print_devices(b)
finally:
    tear_down_disk_images(b)
    os.unlink(disk1_file)
