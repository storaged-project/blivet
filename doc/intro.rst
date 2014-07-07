Introduction to Blivet
======================

Blivet is a python module for system storage configuration.

The main thing that blivet offers is the ability to model a series of changes
without necessarily commiting any of the changes to disk. You can schedule an
arbitrarily large series of changes (called 'actions'), seeing the effects of
each (within the :class:`~.devicetree.DeviceTree` instance) as it is scheduled.
Nothing is written to disk, however, until you execute the actions.

Building Blocks
===============

Individual block devices are represented by the various subclasses of
:class:`~.devices.StorageDevice`, while the formatting of the data they contain
is represented by the various subclasses of :class:`~.formats.DeviceFormat`.
The hierarchy of devices is represented by :class:`~.devicetree.DeviceTree`.

:class:`~.devices.DiskDevice`, :class:`~.devices.PartitionDevice`,
:class:`~.devices.LVMLogicalVolumeDevice`, and
:class:`~.devices.MDRaidArrayDevice` are some of the most important examples of
:class:`~.devices.StorageDevice` subclasses.

Some examples of :class:`~.formats.DeviceFormat` subclasses include
:class:`~.formats.swap.SwapSpace`, :class:`~.formats.disklabel.DiskLabel`,
and subclasses of :class:`~.formats.fs.FS` such as :class:`~.formats.fs.Ext4FS`
and :class:`~.formats.fs.XFS`.

Every :class:`~.devices.StorageDevice` instance has a :attr:`~.devices.StorageDevice.format` that contains an instance of some :class:`~.formats.DeviceFormat`
subclass -- even if it is "blank" or "unformatted" (in which case it is an instance of :class:`~.formats.DeviceFormat` itself).

Every :class:`~.formats.DeviceFormat` has a
:attr:`~.formats.DeviceFormat.device` attribute that is a string representing
the path to the device node for the block device containing the formatting.
:class:`~.devices.StorageDevice` and :class:`~.formats.DeviceFormat` can
represent either existent or non-existent devices and formatting.

:class:`~.devices.StorageDevice` and :class:`~.formats.DeviceFormat` share a similar API, which consists of methods to control existing devices/formats
(:meth:`~.devices.StorageDevice.setup`,
:meth:`~.devices.StorageDevice.teardown`), methods to create or modify
devices/formats (:meth:`~.devices.StorageDevice.create`,
:meth:`~.devices.StorageDevice.destroy`, :meth:`~.devices.StorageDevice.resize`)
, and attributes to store critical data
(:attr:`~.devices.StorageDevice.status`, :attr:`~.devices.StorageDevice.exists`)
. Some useful attributes of :class:`~.devices.StorageDevice` that are not found
in :class:`~.formats.DeviceFormat` include
:attr:`~.devices.Device.parents`, :attr:`~.devices.Device.isleaf`,
:attr:`~.devices.Device.ancestors`, and :attr:`~.devices.StorageDevice.disks`.

:class:`~.devicetree.DeviceTree` provides
:attr:`~.devicetree.DeviceTree.devices` which is a list of
:class:`~.devices.StorageDevice` instances representing the current state of the
system as configured within blivet. It also provides some methods for looking up
devices (:meth:`~.devicetree.DeviceTree.getDeviceByName`), for listing devices
that build upon a device (:meth:`~.devicetree.DeviceTree.getDependentDevices`),
and for listing direct descendants of a given device
(:meth:`~.devicetree.DeviceTree.getChildren`).

Getting Started
===============

First Steps
-----------

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

    sda3 = b.devicetree.getDeviceByName("sda3")
    b.destroyDevice(sda3)   # schedules actions to destroy format and device

At this point, the StorageDevice representing sda3 is no longer in the tree.
That means you could allocate a new partition from the newly free space if you
wanted to (via blivet, that is, since there is not actually any free space on
the physical disk yet -- you haven't commited the changes). If you now ran the
following line::

    sda3 = b.devicetree.getDeviceByName("sda3")

sda3 would be None since that device has been removed from the tree.

When you are ready to commit your changes to disk, here's how::

    b.doIt()

That's it. Now you have actually removed /dev/sda3 from the disk.

Here's an alternative approach that uses the lower-level
:class:`~.devicetree.DeviceTree` class directly::

    import blivet
    dt = blivet.devicetree.DeviceTree()
    dt.populate()
    sda3 = dt.getDeviceByName("sda3")
    action1 = ActionDestroyFormat(sda3)
    action2 = ActionDestroyDevice(sda3)
    dt.registerAction(action1)
    dt.registerAction(action2)
    dt.processActions()

Here's the Blivet approach again for comparison::

    import blivet
    b = blivet.Blivet() # contains a DeviceTree instance
    b.reset()   # calls DeviceTree.populate()
    sda3 = b.devicetree.getDeviceByName("sda3")
    b.destroyDevice(sda3)   # schedules actions to destroy format and device
    b.doIt()    # calls DeviceTree.processActions()


Scheduling a Series of Actions
------------------------------

Start out as before::

    import blivet
    from blivet.size import Size
    b = blivet.Blivet()
    b.reset()
    sda3 = b.devicetree.getDeviceByName("sda3")

Now we're going to wipe the existing formatting from sda3::

    b.destroyFormat(sda3)

Now let's assume sda3 is larger than 10GiB and resize it to that size::

    b.resizeDevice(sda3, Size("10 GiB"))

And then let's create a new ext4 filesystem there::

    new_fmt = blivet.formats.getFormat("ext4", device=sda3.path)
    b.formatDevice(sda3, new_fmt)

If you want to commit the whole set of changes in one shot, it's easy::

    b.doIt()

Now you can mount the new filesystem at the directory "/mnt/test"::

    sda3.format.setup(mountpoint="/mnt/test")

Once you're finished, unmount it as follows::

    sda3.format.teardown()


Disk Partitions
---------------

Disk partitions are a little bit tricky in that they require an extra step to
actually allocate the partitions from free space on the disk(s). What that
means is deciding exactly which sectors on which disk the new partition will
occupy. Blivet offers some powerful means for deciding for you where to place
the partitions, but it also allows you to specify an exact start and end
sector on a specific disk if that's how you want to do it. Here's an example
of letting Blivet handle the details of creating a partition of minimum size
10GiB on either sdb or sdc that is also growable to a maximum size of 20GiB::

    sdb = b.devicetree.getDeviceByName("sdb")
    sdc = b.devicetree.getDeviceByName("sdc")
    new_part = b.newPartition(size=Size("10 GiB"), grow=True,
                              maxsize=Size("20 GiB"),
                              parents=[sdb, sdc])
    b.createDevice(new_part)
    blivet.partitioning.doPartitioning(b)

Now you could see where it ended up::

    print("partition %s of size %s on disk %s" % (new_part.name,
                                                     new_part.size,
                                                     new_part.disk.name))

From here, everything is the same as it was in the first examples. All that's
left is to execute the scheduled action::

    b.doIt()    # or b.devicetree.processActions()

Backing up, let's see how it looks if you want to specify the start and end
sectors. If you specify a start sector you have to also specify a single disk
from which to allocate the partition::

    new_part = b.newPartition(start=2048, end=204802048, parents=[sdb])

All the rest is the same as the previous partitioning example.
