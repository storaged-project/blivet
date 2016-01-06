2.0
====

LVM RAID
---------

Blivet now recognizes and supports creation of new non-linear LVs. The segment
type is properly reported in the ``seg_type`` attribute of the
``LVMLogicalVolumeDevice`` objects and the ``seg_type`` constructor parameter
can be used to create new LVs with specific segment types. Please note that only
the *linear* (default), *striped*, *mirror* and *raidX* segment types are
supported so far. Also the ``LVMLogicalVolumeDevice`` class now inherits from
the ``RaidDevice`` mixin.

Added properties:

* ``LVMLogicalVolumeDevice``

  - ``is_raid_lv``, ``mirrored``

  -  ``data_vg_space_used``, ``metadata_vg_space_used`` - space used by the
     data/metadata part of the LV in its VG taking the RAID level (i.e. the
     number of mirrors) into account

* ``LVMPhysicalVolume``

  - ``free`` - free space in the PV (for all existing and non-existing PVs)


Removed properties:

* ``LVMLogicalVolumeDevice``

  - ``copies``
