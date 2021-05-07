LVM VDO support
===============

Support for creating LVM VDO devices has been added in Blivet 3.4.

These devices are similar to LVM thinly provisioned volumes, but there are some special steps
and limitations when creating these devices which this document describes.

LVM VDO in Blivet
-----------------

LVM VDO devices are represented by two ``LVMLogicalVolumeDevice`` devices:

- VDO Pool logical volume with type 'lvmvdopool'
- VDO logical volume with type 'lvmvdolv' which is the child of the VDO Pool device

Existing LVM VDO setup in Blivet:

    existing 20 GiB disk vdb (265) with existing msdos disklabel
      existing 20 GiB partition vdb1 (275) with existing lvmpv
        existing 20 GiB lvmvg data (284)
          existing 10 GiB lvmvdopool data-vdopool (288)
            existing 50 GiB lvmvdolv data-vdolv (295)

When creating LVM VDO setup using Blivet these two devices must be created together as these
are created by a single LVM command.

It currently isn't possible to create additional VDO logical volumes in the pool. It is however
possible to create multiple VDO pools in a single volume group.

Deduplication and compression are properties of the VDO pool. Size specified for the VDO pool
volume will be used as the "physical" size for the pool and size specified for the VDO logical volume
will be used as the "virtual" size for the VDO volume.

When creating format, it must be created on the VDO logical volume. For filesystems with discard
support, no discard option will be automatically added when calling the ``mkfs`` command
(e.g. ``-K`` for ``mkfs.xfs``).

Example for creating a *80 GiB* VDO pool with *400 GiB* VDO logical volume with an *ext4* format with
both deduplication and compression enabled:

    pool = b.new_lv(size=Size("80GiB"), parents=[vg], name="vdopool", vdo_pool=True,
                    deduplication=True, compression=True)
    b.create_device(pool)

    lv = b.new_lv(size=Size("400GiB"), parents=[pool], name="vdolv", vdo_lv=True,
                  fmt_type="ext4")
    b.create_device(lv)

When removing existing LVM VDO devices, both devices must be removed from the devicetree and the VDO
logical volume must be removed first (``recursive_remove`` can be used to automate these two steps).

Managing of existing LVM VDO devices is currently not supported.


LVM VDO in Devicefactory
------------------------

For the top-down specified creation using device factories a new ``LVMVDOFactory`` factory has been
added. Factory device in this case is the VDO logical volume and is again automatically created
together with the VDO pool.

Example of creating a new LVM VDO setup using the ``devicefactory`` module:

    factory = blivet.devicefactory.LVMVDOFactory(b, size=Size("5 GiB"), virtual_size=Size("50 GiB"),
                                                 disks=disks, fstype="xfs",
                                                 container_name="data",
                                                 pool_name="myvdopool",
                                                 compression=True, deduplication=True)
    factory.configure()
    factory.device

        LVMLogicalVolumeDevice instance (0x7f14d17422b0) --
            name = data-00  status = False  id = 528
            children = []
            parents = ['non-existent 5 GiB lvmvdopool data-myvdopool (519)']
            ...

``size`` in this case sets the pool (physical) size, the VDO logical volume size can be specified
with ``virtual_size`` (if not specified it will be same as the pool size). Name for the VDO volume
can be specified using the ``name`` keyword argument. ``pool_name`` argument is optional and
a unique name will be generated if omitted. Both ``compression`` and ``deduplication`` default to
``True`` (enabled) if not specified.

This factory can create only a single VDO logical volume in a single VDO pool but additional VDO pools
can be added by repeating the steps to create the first one.
