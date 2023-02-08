devices
========


* :mod:`~blivet.devices.btrfs`
    * :class:`~blivet.devices.btrfs.BTRFSSubVolumeDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.btrfs.BTRFSSubVolumeDevice.vol_id`
        * :attr:`~blivet.devices.btrfs.BTRFSSubVolumeDevice.volume`

    * :class:`~blivet.devices.btrfs.BTRFSVolumeDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.btrfs.BTRFSVolumeDevice.data_level`
        * :attr:`~blivet.devices.btrfs.BTRFSVolumeDevice.default_subvolume`
        * :attr:`~blivet.devices.btrfs.BTRFSVolumeDevice.members`
        * :attr:`~blivet.devices.btrfs.BTRFSVolumeDevice.metadata_level`

* :mod:`~blivet.devices.disk`
    * :class:`~blivet.devices.disk.DiskDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.storage.StorageDevice.model`
        * :attr:`~blivet.devices.storage.StorageDevice.vendor`
        * :attr:`~blivet.devices.storage.DiskDevice.wwn`

* :mod:`~blivet.devices.file`
    * :class:`~blivet.devices.file.DirectoryDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
    * :class:`~blivet.devices.file.FileDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
    * :class:`~blivet.devices.file.SparseFileDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)

* :mod:`~blivet.devices.loop`
    * :class:`~blivet.devices.loop.LoopDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)

* :mod:`~blivet.devices.luks`
    * :class:`~blivet.devices.luks.LUKSDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.dm.DMDevice.map_name`
    * :class:`~blivet.devices.luks.IntegrityDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.dm.DMDevice.map_name`

* :mod:`~blivet.devices.lvm`
    * :class:`~blivet.devices.lvm.LVMCache`
        * :attr:`~blivet.devices.lvm.LVMCache.backing_device_name`
        * :attr:`~blivet.devices.lvm.LVMCache.cache_device_name`
        * :attr:`~blivet.devices.lvm.LVMCache.exists`
        * :attr:`~blivet.devices.lvm.LVMCache.md_size`
        * :attr:`~blivet.devices.lvm.LVMCache.mode`
        * :attr:`~blivet.devices.lvm.LVMCache.size`
        * :attr:`~blivet.devices.lvm.LVMCache.stats`

    * :class:`~blivet.devices.lvm.LVMWriteCache`
        * :attr:`~blivet.devices.lvm.LVMWriteCache.backing_device_name`
        * :attr:`~blivet.devices.lvm.LVMWriteCache.cache_device_name`
        * :attr:`~blivet.devices.lvm.LVMWriteCache.exists`
        * :attr:`~blivet.devices.lvm.LVMWriteCache.size`

    * :class:`~blivet.devices.lvm.LVMCacheRequest`
        * :attr:`~blivet.devices.lvm.LVMCacheRequest.fast_devs`
        * :attr:`~blivet.devices.lvm.LVMCacheRequest.pv_space_requests`
        * :attr:`~blivet.devices.lvm.LVMCacheRequest.mode`

    * :class:`~blivet.devices.lvm.LVMLogicalVolumeDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.lvm.LVMLogicalVolumeBase.cache`
        * :attr:`~blivet.devices.lvm.LVMLogicalVolumeBase.cached`
        * :attr:`~blivet.devices.lvm.LVMInternalLogicalVolumeMixin.is_internal_lv`
        * :attr:`~blivet.devices.lvm.LVMLogicalVolumeBase.is_raid_lv`
        * :attr:`~blivet.devices.lvm.LVMSnapshotMixin.is_snapshot_lv`
        * :attr:`~blivet.devices.lvm.LVMThinLogicalVolumeMixin.is_thin_lv`
        * :attr:`~blivet.devices.lvm.LVMThinPoolMixin.is_thin_pool`
        * :attr:`~blivet.devices.lvm.LVMVDOLogicalVolumeMixin.is_vdo_lv`
        * :attr:`~blivet.devices.lvm.LVMVDOPoolMixin.is_vdo_pool`
        * :attr:`~blivet.devices.lvm.LVMCachePoolMixin.is_cache_pool`
        * :attr:`~blivet.devices.dm.DMDevice.map_name`
        * :attr:`~blivet.devices.lvm.LVMLogicalVolumeBase.metadata_size`
        * :attr:`~blivet.devices.lvm.LVMLogicalVolumeDevice.vg`

    * :class:`~blivet.devices.lvm.LVMVolumeGroupDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.cached_lvs`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.complete`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.extents`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.free_extents`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.free_space`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.lvs`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.pv_free_info`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.thinlvs`
        * :attr:`~blivet.devices.lvm.LVMVolumeGroupDevice.thinpools`

.. _MDRaidArrayDeviceAPI:

* :mod:`~blivet.devices.md`
    * :class:`~blivet.devices.md.MDRaidArrayDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.md.MDRaidArrayDevice.complete`
        * :attr:`~blivet.devices.md.MDRaidArrayDevice.degraded`
        * :attr:`~blivet.devices.md.MDRaidArrayDevice.level`
        * :attr:`~blivet.devices.md.MDRaidArrayDevice.member_devices`
        * :meth:`~blivet.devices.md.MDRaidArrayDevice.member_status`
        * :attr:`~blivet.devices.md.MDRaidArrayDevice.members`
        * :attr:`~blivet.devices.md.MDRaidArrayDevice.spares`
        * :attr:`~blivet.devices.md.MDRaidArrayDevice.total_devices`

* :mod:`~blivet.devices.nfs`
    * :class:`~blivet.devices.nfs.NFSDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)

* :mod:`~blivet.devices.optical`
    * :class:`~blivet.devices.optical.OpticalDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)

* :mod:`~blivet.devices.partition`
    * :class:`~blivet.devices.partition.PartitionDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.partition.PartitionDevice.bootable`
        * :attr:`~blivet.devices.partition.PartitionDevice.is_extended`
        * :attr:`~blivet.devices.partition.PartitionDevice.is_logical`
        * :attr:`~blivet.devices.partition.PartitionDevice.is_primary`

.. _StorageDeviceAPI:

* :mod:`~blivet.devices.storage`
    * :class:`~blivet.devices.storage.StorageDevice`
        * :meth:`~blivet.devices.storage.StorageDevice.align_target_size`
        * :attr:`~blivet.devices.device.Device.ancestors`
        * :attr:`~blivet.devices.storage.StorageDevice.children`
        * :attr:`~blivet.devices.storage.StorageDevice.current_size`
        * :meth:`~blivet.devices.device.Device.depends_on`
        * :attr:`~blivet.devices.storage.StorageDevice.direct`
        * :attr:`~blivet.devices.storage.StorageDevice.disks`
        * :attr:`~blivet.devices.storage.StorageDevice.encrypted`
        * :attr:`~blivet.devices.storage.StorageDevice.exists`
        * :attr:`~blivet.devices.storage.StorageDevice.format`
        * :attr:`~blivet.devices.storage.StorageDevice.format_immutable`
        * :attr:`~blivet.devices.storage.StorageDevice.fstab_spec`
        * :attr:`~blivet.devices.storage.StorageDevice.is_disk`
        * :attr:`~blivet.devices.device.Device.is_leaf`
        * :attr:`~blivet.devices.storage.StorageDevice.max_size`
        * :attr:`~blivet.devices.storage.StorageDevice.min_size`
        * :attr:`~blivet.devices.storage.StorageDevice.name`
        * :attr:`~blivet.devices.storage.StorageDevice.parents`
        * :attr:`~blivet.devices.storage.StorageDevice.partitionable`
        * :attr:`~blivet.devices.storage.StorageDevice.partitioned`
        * :attr:`~blivet.devices.storage.StorageDevice.path`
        * :attr:`~blivet.devices.storage.StorageDevice.protected`
        * :attr:`~blivet.devices.storage.StorageDevice.raw_device`
        * :attr:`~blivet.devices.storage.StorageDevice.read_only`
        * :attr:`~blivet.devices.storage.StorageDevice.resizable`
        * :meth:`~blivet.devices.storage.StorageDevice.resize`
        * :meth:`~blivet.devices.storage.StorageDevice.setup`
        * :attr:`~blivet.devices.storage.StorageDevice.size`
        * :attr:`~blivet.devices.storage.StorageDevice.status`
        * :attr:`~blivet.devices.storage.StorageDevice.sysfs_path`
        * :attr:`~blivet.devices.device.Device.tags`
        * :attr:`~blivet.devices.storage.StorageDevice.target_size`
        * :meth:`~blivet.devices.storage.StorageDevice.teardown`
        * :attr:`~blivet.devices.storage.StorageDevice.uuid`

* :mod:`~blivet.devices.stratis`
    * :class:`~blivet.devices.stratis.StratisPoolDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
        * :attr:`~blivet.devices.stratis.StratisPoolDevice.encrypted`
    * :class:`~blivet.devices.stratis.StratisFilesystemDevice` (see :ref:`inherited public API <StorageDeviceAPI>`)
