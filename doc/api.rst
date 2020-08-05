Public API
=============

API Specification
------------------

This should be considered an exhaustive listing of blivet's public API.
Anything not listed should be considered unstable and subject to change
between minor releases.

.. toctree::
   :includehidden:

   blivet package <api/blivet>


Explanation
""""""""""""

In general, anything listed is public and anything not listed is not public.
There are a couple of strange situations that deserve explanation:

* :mod:`blivet.devicetree`
    * :class:`~blivet.devicetree.DeviceTree`
        * :attr:`~blivet.devicetree.DeviceTreeBase.actions`
            * :meth:`~blivet.actionlist.ActionList.add`
            * :meth:`~blivet.actionlist.ActionList.find`
            * :meth:`~blivet.actionlist.ActionList.prune`
            * :meth:`~blivet.actionlist.ActionList.remove`
            * :meth:`~blivet.actionlist.ActionList.sort`
        * :meth:`~blivet.devicetree.DeviceTreeBase.cancel_disk_actions`

1. The class DeviceTree itself is listed, which means the constructor
   interface is considered to be stable.
2. DeviceTree has an 'actions' attribute that is an instance of class
   ActionList. ActionList's constructor isn't public, but the methods and
   attributes listed under the 'actions' attribute are.
3. DeviceTree has a 'cancel_disk_actions' method which is public.

* :mod:`blivet.iscsi`
    * :data:`~blivet.iscsi.iscsi`
        * :meth:`~blivet.iscsi.iSCSI.available`
        * :meth:`~blivet.iscsi.iSCSI.create_interfaces`

1. The module blivet.iscsi contains a module-level 'iscsi' attribute, which
   is public.
2. The class iSCSI is not public. You shouldn't create instances of it.
   Instead, you should use the existing instance at blivet.iscsi.iscsi.
3. The 'available' and 'create_interfaces' methods of the iSCSI class are
   public. The above example is incomplete, but if it were complete it would
   mean that the only public members of the iSCSI class are the 'available'
   and 'create_interfaces' methods.
