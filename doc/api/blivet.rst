
blivet
=======

.. toctree::
   :hidden:
   :caption: Subpackages

   devices package <devices>
   events package <events>
   formats package <formats>


* :mod:`blivet.actionlist`
    * See 'actions' attribute in :ref:`DeviceTree <DeviceTreeAPI>`.

* :mod:`blivet.autopart`
    * :func:`~blivet.autopart.do_autopart`
    * :func:`~blivet.autopart.do_reqpart`
    * :func:`~blivet.autopart.swap_suggestion`

* :mod:`blivet.blivet`
    * :class:`~blivet.blivet.Blivet`
        * :attr:`~blivet.blivet.Blivet.btrfs_volumes`
        * :meth:`~blivet.blivet.Blivet.copy`
        * :meth:`~blivet.blivet.Blivet.create_device`
        * :meth:`~blivet.blivet.Blivet.default_fstype`
        * :meth:`~blivet.blivet.Blivet.destroy_device`
        * :attr:`~blivet.blivet.Blivet.devices`
        * :attr:`~blivet.blivet.Blivet.devicetree`
        * :attr:`~blivet.blivet.Blivet.disks`
        * :meth:`~blivet.blivet.Blivet.do_it`
        * :meth:`~blivet.blivet.Blivet.factory_device`
        * :meth:`~blivet.blivet.Blivet.file_system_free_space`
        * :meth:`~blivet.blivet.Blivet.format_device`
        * :meth:`~blivet.blivet.Blivet.get_free_space`
        * :meth:`~blivet.blivet.Blivet.get_fstype`
        * :meth:`~blivet.blivet.Blivet.initialize_disk`
        * :attr:`~blivet.blivet.Blivet.lvs`
        * :attr:`~blivet.blivet.Blivet.mdarrays`
        * :attr:`~blivet.blivet.Blivet.mdcontainers`
        * :attr:`~blivet.blivet.Blivet.mdmembers`
        * :attr:`~blivet.blivet.Blivet.mountpoints`
        * :attr:`~blivet.blivet.Blivet.names`
        * :meth:`~blivet.blivet.Blivet.new_btrfs`
        * :meth:`~blivet.blivet.Blivet.new_btrfs_sub_volume`
        * :meth:`~blivet.blivet.Blivet.new_lv`
        * :meth:`~blivet.blivet.Blivet.new_lv_from_lvs`
        * :meth:`~blivet.blivet.Blivet.new_mdarray`
        * :meth:`~blivet.blivet.Blivet.new_partition`
        * :meth:`~blivet.blivet.Blivet.new_stratis_filesystem`
        * :meth:`~blivet.blivet.Blivet.new_stratis_pool`
        * :meth:`~blivet.blivet.Blivet.new_tmp_fs`
        * :meth:`~blivet.blivet.Blivet.new_vg`
        * :attr:`~blivet.blivet.Blivet.partitioned`
        * :attr:`~blivet.blivet.Blivet.partitions`
        * :attr:`~blivet.blivet.Blivet.pvs`
        * :meth:`~blivet.blivet.Blivet.reset`
        * :meth:`~blivet.blivet.Blivet.reset_device`
        * :meth:`~blivet.blivet.Blivet.resize_device`
        * :attr:`~blivet.blivet.Blivet.root_device`
        * :meth:`~blivet.blivet.Blivet.safe_device_name`
        * :meth:`~blivet.blivet.Blivet.save_passphrase`
        * :meth:`~blivet.blivet.Blivet.set_default_fstype`
        * :meth:`~blivet.blivet.Blivet.shutdown`
        * :attr:`~blivet.blivet.Blivet.stratis_pools`
        * :meth:`~blivet.blivet.Blivet.suggest_container_name`
        * :meth:`~blivet.blivet.Blivet.suggest_device_name`
        * :attr:`~blivet.blivet.Blivet.swaps`
        * :attr:`~blivet.blivet.Blivet.thinlvs`
        * :attr:`~blivet.blivet.Blivet.thinpools`
        * :attr:`~blivet.blivet.Blivet.vgs`

* :mod:`blivet.deviceaction`
    * :class:`~blivet.deviceaction.ActionAddMember`
    * :class:`~blivet.deviceaction.ActionRemoveMember`
    * :class:`~blivet.deviceaction.ActionConfigureDevice`
    * :class:`~blivet.deviceaction.ActionConfigureFormat`
    * :class:`~blivet.deviceaction.ActionCreateDevice`
    * :class:`~blivet.deviceaction.ActionCreateFormat`
    * :class:`~blivet.deviceaction.ActionDestroyDevice`
    * :class:`~blivet.deviceaction.ActionDestroyFormat`
    * :class:`~blivet.deviceaction.ActionResizeDevice`
    * :class:`~blivet.deviceaction.ActionResizeFormat`

* :mod:`blivet.devicefactory`
    * :meth:`~blivet.devicefactory.DeviceFactory.configure`
    * :const:`~blivet.devicefactory.DEVICE_TYPE_MD`
    * :const:`~blivet.devicefactory.DEVICE_TYPE_PARTITION`
    * :const:`~blivet.devicefactory.DEVICE_TYPE_BTRFS`
    * :const:`~blivet.devicefactory.DEVICE_TYPE_DISK`
    * :const:`~blivet.devicefactory.DEVICE_TYPE_LVM_THINP`
    * :const:`~blivet.devicefactory.DEVICE_TYPE_LVM_VDO`
    * :const:`~blivet.devicefactory.DEVICE_TYPE_STRATIS`
    * :func:`~blivet.devicefactory.is_supported_device_type`
    * :func:`~blivet.devicefactory.get_device_factory`
    * :func:`~blivet.devicefactory.get_device_type`
    * :const:`~blivet.devicefactory.SIZE_POLICY_AUTO`
    * :const:`~blivet.devicefactory.SIZE_POLICY_MAX`

.. _DeviceTreeAPI:

* :mod:`blivet.devicetree`
    * :class:`~blivet.devicetree.DeviceTree`
        * :attr:`~blivet.devicetree.DeviceTreeBase.actions`
            * :meth:`~blivet.actionlist.ActionList.add`
            * :meth:`~blivet.actionlist.ActionList.find`
            * :meth:`~blivet.actionlist.ActionList.prune`
            * :meth:`~blivet.actionlist.ActionList.remove`
            * :meth:`~blivet.actionlist.ActionList.sort`
        * :meth:`~blivet.devicetree.DeviceTreeBase.cancel_disk_actions`
        * :attr:`~blivet.devicetree.DeviceTreeBase.devices`
        * :attr:`~blivet.devicetree.DeviceTreeBase.filesystems`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_dependent_devices`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_device_by_id`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_device_by_label`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_device_by_name`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_device_by_path`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_device_by_sysfs_path`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_device_by_uuid`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_disk_actions`
        * :meth:`~blivet.devicetree.DeviceTreeBase.get_related_disks`
        * :meth:`~blivet.populator.populator.PopulatorMixin.handle_device`
        * :meth:`~blivet.populator.populator.PopulatorMixin.handle_format`
        * :meth:`~blivet.devicetree.DeviceTreeBase.hide`
        * :attr:`~blivet.devicetree.DeviceTreeBase.labels`
        * :attr:`~blivet.devicetree.DeviceTreeBase.leaves`
        * :attr:`~blivet.devicetree.DeviceTreeBase.mountpoints`
        * :meth:`~blivet.populator.populator.PopulatorMixin.populate`
        * :meth:`~blivet.devicetree.DeviceTreeBase.recursive_remove`
        * :meth:`~blivet.devicetree.DeviceTreeBase.resolve_device`
        * :meth:`~blivet.devicetree.DeviceTreeBase.setup_all`
        * :meth:`~blivet.devicetree.DeviceTreeBase.teardown_all`
        * :meth:`~blivet.devicetree.DeviceTreeBase.unhide`
        * :attr:`~blivet.devicetree.DeviceTreeBase.uuids`

* :mod:`blivet.errors`
    * :class:`~blivet.errors.AlignmentError`
    * :class:`~blivet.errors.AvailabilityError`
    * :class:`~blivet.errors.BTRFSError`
    * :class:`~blivet.errors.BTRFSValueError`
    * :class:`~blivet.errors.CorruptGPTError`
    * :class:`~blivet.errors.DependencyError`
    * :class:`~blivet.errors.DeviceActionError`
    * :class:`~blivet.errors.DeviceCreateError`
    * :class:`~blivet.errors.DeviceDestroyError`
    * :class:`~blivet.errors.DeviceError`
    * :class:`~blivet.errors.DeviceFactoryError`
    * :class:`~blivet.errors.DeviceFormatError`
    * :class:`~blivet.errors.DeviceNotFoundError`
    * :class:`~blivet.errors.DeviceResizeError`
    * :class:`~blivet.errors.DeviceSetupError`
    * :class:`~blivet.errors.DeviceTeardownError`
    * :class:`~blivet.errors.DeviceTreeError`
    * :class:`~blivet.errors.DeviceUserDeniedFormatError`
    * :class:`~blivet.errors.DiskLabelCommitError`
    * :class:`~blivet.errors.DiskLabelError`
    * :class:`~blivet.errors.DiskLabelScanError`
    * :class:`~blivet.errors.DMError`
    * :class:`~blivet.errors.DMRaidMemberError`
    * :class:`~blivet.errors.DuplicateUUIDError`
    * :class:`~blivet.errors.DuplicateVGError`
    * :class:`~blivet.errors.EventHandlingError`
    * :class:`~blivet.errors.EventManagerError`
    * :class:`~blivet.errors.EventParamError`
    * :class:`~blivet.errors.FCoEError`
    * :class:`~blivet.errors.FormatCreateError`
    * :class:`~blivet.errors.FormatDestroyError`
    * :class:`~blivet.errors.FormatResizeError`
    * :class:`~blivet.errors.FormatSetupError`
    * :class:`~blivet.errors.FormatTeardownError`
    * :class:`~blivet.errors.FSError`
    * :class:`~blivet.errors.FSReadLabelError`
    * :class:`~blivet.errors.FSResizeError`
    * :class:`~blivet.errors.FSTabTypeMismatchError`
    * :class:`~blivet.errors.FSWriteLabelError`
    * :class:`~blivet.errors.InconsistentPVSectorSize`
    * :class:`~blivet.errors.IntegrityError`
    * :class:`~blivet.errors.InvalidDiskLabelError`
    * :class:`~blivet.errors.InvalidMultideviceSelection`
    * :class:`~blivet.errors.ISCSIError`
    * :class:`~blivet.errors.LUKSError`
    * :class:`~blivet.errors.MDMemberError`
    * :class:`~blivet.errors.MPathError`
    * :class:`~blivet.errors.MultipathMemberError`
    * :class:`~blivet.errors.NotEnoughFreeSpaceError`
    * :class:`~blivet.errors.NoDisksError`
    * :class:`~blivet.errors.NVMeError`
    * :class:`~blivet.errors.PhysicalVolumeError`
    * :class:`~blivet.errors.PartitioningError`
    * :class:`~blivet.errors.RaidError`
    * :class:`~blivet.errors.SinglePhysicalVolumeError`
    * :class:`~blivet.errors.SizePlacesError`
    * :class:`~blivet.errors.StorageError`
    * :class:`~blivet.errors.StratisError`
    * :class:`~blivet.errors.SwapSpaceError`
    * :class:`~blivet.errors.ThreadError`
    * :class:`~blivet.errors.UdevError`
    * :class:`~blivet.errors.UnrecognizedFSTabEntryError`
    * :class:`~blivet.errors.UnusableConfigurationError`

* :mod:`blivet.fcoe`
    * :data:`~blivet.fcoe.fcoe`
        * :meth:`~blivet.fcoe.FCoE.add_san`
        * :meth:`~blivet.fcoe.FCoE.startup`
    * :func:`~blivet.fcoe.has_fcoe`

* :mod:`blivet.flags`
    * :data:`~blivet.flags.flags`

* :mod:`blivet.iscsi`
    * :data:`~blivet.iscsi.iscsi`
        * :meth:`~blivet.iscsi.iSCSI.available`
        * :meth:`~blivet.iscsi.iSCSI.create_interfaces`
        * :meth:`~blivet.iscsi.iSCSI.delete_interfaces`
        * :meth:`~blivet.iscsi.iSCSI.discover`
        * :attr:`~blivet.iscsi.iSCSI.ifaces`
        * :attr:`~blivet.iscsi.iSCSI.initiator`
        * :attr:`~blivet.iscsi.iSCSI.initiator_set`
        * :meth:`~blivet.iscsi.iSCSI.log_into_node`
        * :attr:`~blivet.iscsi.iSCSI.mode`
        * :meth:`~blivet.iscsi.iSCSI.shutdown`
        * :meth:`~blivet.iscsi.iSCSI.startup`

* :mod:`blivet.partitioning`
    * :func:`~blivet.partitioning.do_partitioning`
    * :func:`~blivet.partitioning.grow_lvm`

* :mod:`blivet.populator`
    * See 'populate', 'handle_device', and 'handle_format' methods in :ref:`DeviceTree <DeviceTreeAPI>`.

* :mod:`blivet.size`
    * :const:`~blivet.size.B`
    * :const:`~blivet.size.EB`
    * :const:`~blivet.size.EiB`
    * :const:`~blivet.size.GB`
    * :const:`~blivet.size.GiB`
    * :const:`~blivet.size.KB`
    * :const:`~blivet.size.KiB`
    * :const:`~blivet.size.MB`
    * :const:`~blivet.size.MiB`
    * :const:`~blivet.size.PB`
    * :const:`~blivet.size.PiB`
    * :const:`~blivet.size.ROUND_DOWN`
    * :const:`~blivet.size.ROUND_UP`
    * :const:`~blivet.size.ROUND_DEFAULT`
    * :class:`~blivet.size.Size`
        * :meth:`~blivet.size.Size.convert_to`
        * :meth:`~blivet.size.Size.human_readable`
        * :meth:`~blivet.size.Size.round_to_nearest`
    * :const:`~blivet.size.TB`
    * :const:`~blivet.size.TiB`
    * :const:`~blivet.size.YB`
    * :const:`~blivet.size.YiB`
    * :const:`~blivet.size.ZB`
    * :const:`~blivet.size.ZiB`

* :mod:`blivet.util`
    * :func:`~blivet.util.set_up_logging`

* :mod:`blivet.zfcp`
    * :data:`~blivet.zfcp.zfcp`
        * :meth:`~blivet.zfcp.zFCP.add_fcp`
        * :meth:`~blivet.zfcp.zFCP.shutdown`
        * :meth:`~blivet.zfcp.zFCP.startup`
