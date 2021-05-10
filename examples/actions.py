import os

import blivet
from blivet.size import Size
from blivet.util import set_up_logging, create_sparse_tempfile
from blivet.devices import PartitionDevice

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet (don't add system devices)

# create two disk image files on which to create new devices
disk1_file = create_sparse_tempfile("disk1", Size("100GiB"))
b.disk_images["disk1"] = disk1_file

b.reset()

try:
    disk1 = b.devicetree.get_device_by_name("disk1")

    fmt = blivet.formats.get_format("disklabel", device=disk1.path,
                                    label_type="msdos")
    ac = blivet.deviceaction.ActionCreateFormat(device=disk1, fmt=fmt)
    b.devicetree.actions.add(ac)

    # new 5 GiB partition on disk1
    dev = PartitionDevice(name="req%d" % b.next_id,
                          size=Size("5 GiB"), parents=[disk1])

    # low level actions API is usually hidden when using create_device() and format_device()
    # helper functions, working with actions is useful when offering undo/redo functionality
    ac = blivet.deviceaction.ActionCreateDevice(device=dev)
    b.devicetree.actions.add(ac)

    fmt = blivet.formats.get_format("ext4", device=dev.path)
    ac = blivet.deviceaction.ActionCreateFormat(device=dev, fmt=fmt)
    b.devicetree.actions.add(ac)

    # remove last action and format the partition to XFS instead
    b.devicetree.actions.remove(ac)

    fmt = blivet.formats.get_format("xfs", device=dev.path)
    ac = blivet.deviceaction.ActionCreateFormat(device=dev, fmt=fmt)
    b.devicetree.actions.add(ac)

    # now remove the format completely
    ac = blivet.deviceaction.ActionDestroyFormat(device=dev)
    b.devicetree.actions.add(ac)

    # remove redundant/obsolete actions, this will remove the last two actions:
    # we don't really need to create and immediately remove the filesystem
    b.devicetree.actions.prune()

    # print all currently scheduled actions
    for action in b.devicetree.actions.find():
        print(action)

finally:
    b.devicetree.teardown_disk_images()
    os.unlink(disk1_file)
