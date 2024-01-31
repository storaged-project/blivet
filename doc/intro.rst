Introduction to Blivet
======================

Blivet is a python module for system storage configuration.

The main thing that blivet offers is the ability to model a series of changes
without necessarily committing any of the changes to disk. You can schedule an
arbitrarily large series of changes (called 'actions'), seeing the effects of
each (within the :class:`~.devicetree.DeviceTree` instance) as it is scheduled.
Nothing is written to disk, however, until you execute the actions.

Building Blocks
---------------

Individual block devices are represented by the various subclasses of
:class:`~.devices.storage.StorageDevice`, while the formatting of the data they contain
is represented by the various subclasses of :class:`~.formats.DeviceFormat`.
The hierarchy of devices is represented by :class:`~.devicetree.DeviceTree`.

:class:`~.devices.disk.DiskDevice`, :class:`~.devices.partition.PartitionDevice`,
:class:`~.devices.lvm.LVMLogicalVolumeDevice`, and
:class:`~.devices.md.MDRaidArrayDevice` are some of the most important examples of
:class:`~.devices.storage.StorageDevice` subclasses.

Some examples of :class:`~.formats.DeviceFormat` subclasses include
:class:`~.formats.swap.SwapSpace`, :class:`~.formats.disklabel.DiskLabel`,
and subclasses of :class:`~.formats.fs.FS` such as :class:`~.formats.fs.Ext4FS`
and :class:`~.formats.fs.XFS`.

Every :class:`~.devices.storage.StorageDevice` instance has a :attr:`~.devices.storage.StorageDevice.format` that contains an instance of some :class:`~.formats.DeviceFormat`
subclass -- even if it is "blank" or "unformatted" (in which case it is an instance of :class:`~.formats.DeviceFormat` itself).

Every :class:`~.formats.DeviceFormat` has a
:attr:`~.formats.DeviceFormat.device` attribute that is a string representing
the path to the device node for the block device containing the formatting.
:class:`~.devices.storage.StorageDevice` and :class:`~.formats.DeviceFormat` can
represent either existent or non-existent devices and formatting.

:class:`~.devices.storage.StorageDevice` and :class:`~.formats.DeviceFormat` share a similar API, which consists of methods to control existing devices/formats
(:meth:`~.devices.storage.StorageDevice.setup`,
:meth:`~.devices.storage.StorageDevice.teardown`), methods to create or modify
devices/formats (:meth:`~.devices.storage.StorageDevice.create`,
:meth:`~.devices.storage.StorageDevice.destroy`, :meth:`~.devices.storage.StorageDevice.resize`)
, and attributes to store critical data
(:attr:`~.devices.storage.StorageDevice.status`, :attr:`~.devices.storage.StorageDevice.exists`)
. Some useful attributes of :class:`~.devices.storage.StorageDevice` that are not found
in :class:`~.formats.DeviceFormat` include
:attr:`~.devices.device.Device.parents`, :attr:`~.devices.device.Device.isleaf`,
:attr:`~.devices.device.Device.ancestors`, and :attr:`~.devices.storage.StorageDevice.disks`.

:class:`~.devicetree.DeviceTree` provides
:attr:`~.devicetree.DeviceTreeBase.devices` which is a list of
:class:`~.devices.storage.StorageDevice` instances representing the current state of the
system as configured within blivet. It also provides some methods for looking up
devices (:meth:`~.devicetree.DeviceTreeBase.get_device_by_name`) and for listing devices
that build upon a device (:meth:`~.devicetree.DeviceTreeBase.get_dependent_devices`).

Getting Started
---------------

First Steps
^^^^^^^^^^^

First, create an instance of the :class:`~.Blivet` class::

    import blivet
    b = blivet.Blivet()

Next, scan the system's storage configuration and store it in the tree::

    b.reset()

Now, you can do some simple things like listing the devices::

    for device in b.devices:
        print(device)

To make changes to the configuration you'll schedule actions, but
:class:`~.Blivet` provides some convenience methods to hide the details. Here's an example of removing partition '/dev/sda3'::

    sda3 = b.devicetree.get_device_by_name("sda3")
    b.destroy_device(sda3)   # schedules actions to destroy format and device

At this point, the StorageDevice representing sda3 is no longer in the tree.
That means you could allocate a new partition from the newly free space if you
wanted to (via blivet, that is, since there is not actually any free space on
the physical disk yet -- you haven't committed the changes). If you now ran the
following line::

    sda3 = b.devicetree.get_device_by_name("sda3")

sda3 would be None since that device has been removed from the tree.

When you are ready to commit your changes to disk, here's how::

    b.do_it()

That's it. Now you have actually removed /dev/sda3 from the disk.

Here's an alternative approach that uses the lower-level
:class:`~.devicetree.DeviceTree` class directly::

    import blivet
    dt = blivet.devicetree.DeviceTree()
    dt.populate()
    sda3 = dt.get_device_by_name("sda3")
    action1 = ActionDestroyFormat(sda3)
    action2 = ActionDestroyDevice(sda3)
    dt.actions.add(action1)
    dt.actions.add(action2)
    dt.actions.process()

Here's the Blivet approach again for comparison::

    import blivet
    b = blivet.Blivet() # contains a DeviceTree instance
    b.reset()   # calls DeviceTree.populate()
    sda3 = b.devicetree.get_device_by_name("sda3")
    b.destroy_device(sda3)   # schedules actions to destroy format and device
    b.do_it()    # calls DeviceTree.actions.process()


Scheduling a Series of Actions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Start out as before::

    import blivet
    from blivet.size import Size
    b = blivet.Blivet()
    b.reset()
    sda3 = b.devicetree.get_device_by_name("sda3")

Now let's assume sda3 is larger than 10GiB and resize it to that size::

    b.resize_device(sda3, Size("10 GiB"))

And then let's create a new ext4 filesystem there::

    new_fmt = blivet.formats.get_format("ext4", device=sda3.path)
    b.format_device(sda3, new_fmt)

If you want to commit the whole set of changes in one shot, it's easy::

    b.do_it()

Now you can mount the new filesystem at the directory "/mnt/test"::

    sda3.format.setup(mountpoint="/mnt/test")

Once you're finished, unmount it as follows::

    sda3.format.teardown()


Disk Partitions
^^^^^^^^^^^^^^^

Disk partitions are a little bit tricky in that they require an extra step to
actually allocate the partitions from free space on the disk(s). What that
means is deciding exactly which sectors on which disk the new partition will
occupy. Blivet offers some powerful means for deciding for you where to place
the partitions, but it also allows you to specify an exact start and end
sector on a specific disk if that's how you want to do it. Here's an example
of letting Blivet handle the details of creating a partition of minimum size
10GiB on either sdb or sdc that is also growable to a maximum size of 20GiB::

    sdb = b.devicetree.get_device_by_name("sdb")
    sdc = b.devicetree.get_device_by_name("sdc")
    new_part = b.new_partition(size=Size("10 GiB"), grow=True,
                               maxsize=Size("20 GiB"),
                               parents=[sdb, sdc])
    b.create_device(new_part)
    blivet.partitioning.do_partitioning(b)

Now you could see where it ended up::

    print("partition %s of size %s on disk %s" % (new_part.name,
                                                     new_part.size,
                                                     new_part.disk.name))

From here, everything is the same as it was in the first examples. All that's
left is to execute the scheduled action::

    b.do_it()    # or b.devicetree.process_actions()

Backing up, let's see how it looks if you want to specify the start and end
sectors. If you specify a start sector you have to also specify a single disk
from which to allocate the partition::

    new_part = b.new_partition(start=2048, end=204802048, parents=[sdb])

All the rest is the same as the previous partitioning example.
