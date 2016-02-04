2.0
====

A single class for all LVs
---------------------------

In order to be better prepared for supporting things like *lvconvert*, Blivet
now represents all LVs with a single class (keeping the name
``LVMLogicalVolumeDevice``).


Using the class
++++++++++++++++

In order to create LVs of various types, different values of the ``seg_type``
parameter need to be passed. For example, to create a thin pool, ``thin-pool``
segment type needs to be specified (optionally together with the
thin-pool-specific parameters like ``metadata_size``) . The same applies to thin
LVs and the ``thin`` segment type. To create a snapshot LV, one needs to specify
the ``origin`` LV or set the ``vorigin`` flag to ``True``. Internal LVs require
``parent_lv`` and ``int_type`` specifying the type of the internal LV.

To determine the type of some LV, the newly added ``is_thin_lv``,
``is_thin_pool``, ``is_snapshot_lv`` and ``is_internal_lv`` properties can be
used.


Implementation details
+++++++++++++++++++++++

To avoid having a single gigantic class with hundreds of lines of code, the
``LVMLogicalVolumeDevice`` class makes use of iheritance and "merges" together
the ``LVMLogicalVolumeBase`` class and mixins for specific types of LVs (thin
pool, thin LV,...) adding the type-specific methods and properties as well as
type-specific implementations of various methods. The ``@type_specific``
decorator makes sure that the right implementation of a method is called
whenever there is a type-specific one (for example thin pools are created in a
different way than good old linear LVs).

The code that is common to all LVs lives in the ``LVMLogicalVolumeBase`` class
together with properties that are required by this code. Type-specific code
lives in the particular mixin classes and the generic/fallback implementations
live in the (ultimate) ``LVMLogicalVolumeDevice`` class' methods decorated with
the ``@type_specific`` decorator.


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
