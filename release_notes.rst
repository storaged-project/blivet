2.0.0
======

* `PEP8 compatibility`_
* `LVM RAID`_
* `Thread safety`_
* `Handling of external storage events`_
* `LUKS resize`_
* `A single class for all LVs`_
* `Revamped code to populate the device tree`_
* `Changed Size implementation`_
* `API Stability`_
* `Removed`_
* `Moved`_


Removed
--------

The following were deprecated and have been removed.

* ``DeviceTree.get_devices_by_serial`` (use a list comprehension)

    For example, this::

        devs = devicetree.get_devices_by_serial(serial)

    could be accomplished like this::

        devs = [d for d in devicetree.devices if d.serial == serial]


* ``DeviceTree.get_devices_by_type`` (use a list comprehension)
* ``DeviceTree.get_devices_by_instance`` (use a list comprehension)
* ``BTRFSVolumeDevice.create_subvolumes``
* ``MDRaidArrayDevice.devices`` (use ``MDRaidArrayDevice.members``)
* ``MDBiosRaidArrayDevice.devices`` (use ``MDBiosRaidArrayDevice.members``)


Moved
------

* ``DeviceTree.register_action`` (use ``DeviceTree.actions.add``)
* ``DeviceTree.cancel_action`` (use ``DeviceTree.actions.remove``)
* ``DeviceTree.find_actions`` (use ``DeviceTree.actions.find``)
* ``DeviceTree.prune_actions`` (use ``DeviceTree.actions.prune``)
* ``DeviceTree.sort_actions`` (use ``DeviceTree.actions.sort``)
* ``DeviceTree.process_actions`` (use ``DeviceTree.actions.process``)
* ``DeviceTree.get_children`` (use ``Device.children``)


API Stability
--------------

A complete public API specification can be found in the documentation,
which is available in the source tree at ``doc/api.rst`` and ``doc/api/``.

Beginning with version 2.0.0 the blivet project will be using semantic
versioning -- actually, we will be using a variation developed by the
OpenStack project which incorporates support for Python PEP440:
http://docs.openstack.org/developer/pbr/semver.html


LUKS resize
------------

Blivet now supports resize of block devices encrypted using LUKS, including
the ``Blivet.resize_device`` method.


Handling of external storage events
------------------------------------

Blivet now has the ability to listen for uevents on block devices and adjust to
externally-initiated changes. Event handling is not enabled by default. For an
example of how to enable this feature, see ``examples/uevents.py``. Most of the
code related to event handling is in the new ``blivet.events`` package. The
main pieces are ``blivet.events.manager.event_manager`` (an instance of
``blivet.events.manager.UdevEventManager``), ``blivet.events.manager.Event``,
and ``blivet.events.handler.EventHandlerMixin`` (a mixin class that augments
``DeviceTree``).


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


Devices know their children
----------------------------

Instances of ``blivet.device.Device`` now have a list of their direct
descendants: ``Device.children``. Accordingly, ``DeviceTree.get_children`` has
been removed.


Thread safety
--------------

Blivet now uses a global reentrant lock to ensure thread-safety within the
``Blivet``, ``DeviceTree``, ``Device``, and ``DeviceFormat`` classes.


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


Revamped code to populate the device tree
------------------------------------------

``blivet.populator.Populator`` has been rewritten to improve maintainability.
Most of the code that does type-specific handling for devices or formatting has
been moved into individual helper classes under ``blivet.populator.helpers``.
The populator class itself has been rewritten as a mixin
(``blivet.populator.PopulatorMixin``) that augments ``DeviceTree``.


PEP8 compatibility
-------------------

All code in blivet now conforms to
`PEP8 <https://www.python.org/dev/peps/pep-0008/>`_. As a result, all non-class
names in the ``camelCase`` style have been renamed to the
``lower_case_with_underscores`` style. This applies to methods within classes,
but not to the names of the classes themselves -- they still use ``CamelCase``.


Changed Size implementation
---------------------------

The ``Size`` class now inherits from the ``bytesize.Size`` class provided by the
*libbytesize* library. There should be no difference in behaviour except for
potential speed-up and the ``human_readable()`` method having different
parameters. It now accepts the ``min_unit``, ``max_places`` and ``xlate``
parameters described in the documentation.
