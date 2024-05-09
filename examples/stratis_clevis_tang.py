import os
import sys

import blivet
from blivet.devices.stratis import StratisClevisConfig
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile


TANG_URL = None         # URL/IP and port of the Tang server
TANG_THUMBPRINT = None  # thumbprint for verifying the server or None to configure without verification


set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

if TANG_URL is None:
    print("Please set Tang server URL before running this example")
    sys.exit(1)

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

    # clevis configuration specification, TPM can be used by setting "pin" to "tpm2"
    clevis_info = StratisClevisConfig(pin="tang",
                                      tang_url=TANG_URL,
                                      tang_thumbprint=TANG_THUMBPRINT)
    pool = b.new_stratis_pool(name="stratis_pool",
                              parents=[bd, bd2],
                              encrypted=True, passphrase="secret",
                              clevis=clevis_info)
    b.create_device(pool)

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
