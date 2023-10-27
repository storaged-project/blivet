formats
========

* :func:`~blivet.formats.get_format`

.. _DeviceFormatAPI:

* :class:`~blivet.formats.DeviceFormat`
    * :attr:`~blivet.formats.DeviceFormat.controllable`
    * :attr:`~blivet.formats.DeviceFormat.current_size`
    * :attr:`~blivet.formats.DeviceFormat.destroyable`
    * :attr:`~blivet.formats.DeviceFormat.device`
    * :meth:`~blivet.formats.DeviceFormat.do_resize`
    * :attr:`~blivet.formats.DeviceFormat.exists`
    * :attr:`~blivet.formats.DeviceFormat.formattable`
    * :attr:`~blivet.formats.DeviceFormat.hidden`
    * :attr:`~blivet.formats.DeviceFormat.name`
    * :attr:`~blivet.formats.DeviceFormat.label`
    * :attr:`~blivet.formats.DeviceFormat.label_format_ok`
    * :attr:`~blivet.formats.DeviceFormat.labeling`
    * :attr:`~blivet.formats.DeviceFormat.linux_native`
    * :attr:`~blivet.formats.DeviceFormat.max_size`
    * :attr:`~blivet.formats.DeviceFormat.min_size`
    * :attr:`~blivet.formats.DeviceFormat.mountable`
    * :attr:`~blivet.formats.DeviceFormat.options`
    * :attr:`~blivet.formats.DeviceFormat.packages`
    * :attr:`~blivet.formats.DeviceFormat.resizable`
    * :meth:`~blivet.formats.DeviceFormat.setup`
    * :attr:`~blivet.formats.DeviceFormat.size`
    * :attr:`~blivet.formats.DeviceFormat.target_size`
    * :meth:`~blivet.formats.DeviceFormat.teardown`
    * :attr:`~blivet.formats.DeviceFormat.status`
    * :attr:`~blivet.formats.DeviceFormat.supported`
    * :attr:`~blivet.formats.DeviceFormat.type`
    * :attr:`~blivet.formats.DeviceFormat.update_size_info`
    * :attr:`~blivet.formats.DeviceFormat.uuid`

* :mod:`~blivet.formats.biosboot`
    * :class:`~blivet.formats.biosboot.BIOSBoot` (see :ref:`inherited public API <DeviceFormatAPI>`)

* :mod:`~blivet.formats.disklabel`
    * :class:`~blivet.formats.disklabel.DiskLabel` (see :ref:`inherited public API <DeviceFormatAPI>`)
        * :attr:`~blivet.formats.disklabel.DiskLabel.label_type`
        * :attr:`~blivet.formats.disklabel.DiskLabel.sector_size`
        * :meth:`~blivet.formats.disklabel.DiskLabel.get_alignment`
        * :meth:`~blivet.formats.disklabel.DiskLabel.get_end_alignment`
        * :meth:`~blivet.formats.disklabel.DiskLabel.get_minimal_alignment`
        * :meth:`~blivet.formats.disklabel.DiskLabel.get_optimal_alignment`

* :mod:`~blivet.formats.dmraid`
    * :class:`~blivet.formats.dmraid.DMRaidMember` (see :ref:`inherited public API <DeviceFormatAPI>`)

.. _FSAPI:

* :mod:`~blivet.formats.fs`
    * :class:`~blivet.formats.fs.FS` (see :ref:`inherited public API <DeviceFormatAPI>`)
        * :meth:`~blivet.formats.fs.FS.do_check`
        * :attr:`~blivet.formats.fs.FS.mountpoint`
        * :attr:`~blivet.formats.fs.FS.system_mountpoint`
        * :meth:`~blivet.formats.fs.FS.write_label`

    * :class:`~blivet.formats.fs.BindFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.BTRFS` (see :ref:`inherited public API <FSAPI>`)
        * :attr:`~blivet.formats.fs.BTRFS.container_uuid`
    * :class:`~blivet.formats.fs.DevPtsFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.EFIFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.EFIVarFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.Ext2FS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.Ext3FS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.Ext4FS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.ExFATFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.FATFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.F2FS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.GFS2` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.HFSPlus` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.Iso9660FS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.UDFFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.MacEFIFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.NFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.NFSv4` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.NoDevFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.NTFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.ProcFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.SELinuxFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.SysFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.TmpFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.USBFS` (see :ref:`inherited public API <FSAPI>`)
    * :class:`~blivet.formats.fs.XFS` (see :ref:`inherited public API <FSAPI>`)

* :mod:`~blivet.formats.luks`
    * :class:`~blivet.formats.luks.LUKS` (see :ref:`inherited public API <DeviceFormatAPI>`)
        * :meth:`~blivet.formats.luks.LUKS.add_passphrase`
        * :attr:`~blivet.formats.luks.LUKS.configured`
        * :attr:`~blivet.formats.luks.LUKS.has_key`
        * :meth:`~blivet.formats.luks.LUKS.map_name`
        * :meth:`~blivet.formats.luks.LUKS.remove_passphrase`
    * :class:`~blivet.formats.luks.Integrity` (see :ref:`inherited public API <DeviceFormatAPI>`)
        * :meth:`~blivet.formats.luks.Integrity.algorithm`
        * :meth:`~blivet.formats.luks.Integrity.map_name`

* :mod:`~blivet.formats.lvmpv`
    * :class:`~blivet.formats.lvmpv.LVMPhysicalVolume` (see :ref:`inherited public API <DeviceFormatAPI>`)
        * :attr:`~blivet.formats.lvmpv.LVMPhysicalVolume.container_uuid`

* :mod:`~blivet.formats.mdraid`
    * :class:`~blivet.formats.mdraid.MDRaidMember` (see :ref:`inherited public API <DeviceFormatAPI>`)
        * :attr:`~blivet.formats.mdraid.MDRaidMember.container_uuid`

* :mod:`~blivet.formats.multipath`
    * :class:`~blivet.formats.multipath.MultipathMember` (see :ref:`inherited public API <DeviceFormatAPI>`)

* :mod:`~blivet.formats.prepboot`
    * :class:`~blivet.formats.prepboot.PPCPRePBoot` (see :ref:`inherited public API <DeviceFormatAPI>`)

* :mod:`~blivet.formats.stratis`
    * :class:`~blivet.formats.stratis.StratisBlockdev` (see :ref:`inherited public API <DeviceFormatAPI>`)
        * :attr:`~blivet.formats.stratis.StratisBlockdev.has_key`
        * :meth:`~blivet.formats.stratis.StratisBlockdev.unlock_pool`

* :mod:`~blivet.formats.swap`
    * :class:`~blivet.formats.swap.SwapSpace` (see :ref:`inherited public API <DeviceFormatAPI>`)
