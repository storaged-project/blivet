DBus Interface
===============

New in blivet-2.2 is an experimental (see the :ref:`todo`) DBus interface. This
interface provides methods for examining blivet's ``DeviceTree``, creating
devices using blivet's ``DeviceFactory``, and removing devices.


The interface uses the bus name ``com.redhat.Blivet0``.


* com.redhat.Blivet0.Blivet

    * Methods

        * Reset()

            * Reset the model to match the running system.

        * Exit()

            * Stop the associated service.

        * ListDevices() -> ``'ao'``

            * List the devices in the current model.
            * Return a list of device object paths.

        * ResolveDevice(``'s'``) -> ``'o'``

            * Resolve a flexible device specification to a device object path.
            * Raise com.redhat.Blivet1.DeviceLookupFailed if no matching device was found.
            * Arguments

                * spec - device specification (eg: 'sda', 'LABEL=swap')

            * Return the object path of the matching device.

        * RemoveDevice(``'o'``)
            * Remove a device specified by object path.

        * InitializeDisk(``'o'``)
            * Create a disklabel on a disk specified by object path.

        * Factory(``'a{sv}'``) -> ``'o'``
            * Configure a non-existent device based on a top-down specification.
            * Return the object path to the configured device.
            * Optional Arguments

                * size (``'t'``) - Device target size in bytes.
                * disks (``'ao'``) - list of object paths of disks to use
                * device (``'o'``) - object path of already configured device to modify
                * name (``'s'``) - name of device (eg: 'testdata')
                * raid_level (``'s'``) - raid level as a string (eg: 'raid0')
                * encrypted (``'b'``) - encrypt device?
                * fstype (``'s'``) - file system type (eg: 'xfs', 'swap')
                * label (``'s'``) - file system label

                * container_name (``'s'``) - name of container device
                * container_size (``'t'``) - size of container device in bytes (omit for automatic sizing)
                * container_encrypted (``'b'``) - encrypt container device?
                * container_raid_level (``'s'``) - raid level as a string


        * Commit()
            * Commit all scheduled changes to disk.

    * Properties


* com.redhat.Blivet0.Device

    * Methods

        * Setup()

            * Active the device.

        * Teardown()

            * Deactivate the device.

    * Properties

        * Name (``'s'``) - The device's name (eg: 'sdb3')
        * Path (``'s'``) - Full device node path (eg: '/dev/mapper/fedora-root')
        * Type (``'s'``) - Device type (eg: 'lvmlv')
        * Size (``'t'``) - Device size in bytes.
        * ID (``'i'``) - Device ID. (used to formulate object path)
        * UUID (``'s'``) - Device UUID (not file system or other formatting UUID)
        * Status (``'b'``) - Is the device active and ready for use?
        * RaidLevel (``'s'``) - RAID level as a string (eg: 'raid1')
        * Parents (``'ao'``) - Object paths of devices on which this device resides.
        * Children (``'ao'``) - Object paths of devices that reside (in any part) on this device.
        * Format (``'o'``) - Object path for this device's formatting.


* com.redhat.Blivet0.Format

    * Methods

        * Setup()

            * Mount or otherwise activate the formatting.

        * Teardown()

            * Unmount or otherwise deactivate the formatting.

    * Properties

        * Device (``'s'``) - The full path to the device node. (eg: '/dev/mapper/fedora-root')
        * Type (``'s'``) - Format type. (eg: 'ext4')
        * ID (``'i'``) - A unique ID. (Used internally and to formulate object paths.)
        * UUID (``'s'``) - UUID associated with the formatting.
        * Label (``'s'``) - Label associated with the formatting.
        * Mountable (``'b'``) - Whether this formatting is something that can be mounted.
        * Mountpoint (``'s'``) - Mountpoint associated with this device/formatting.
        * Status (``'b'``) - Whether this formatting is current active or mounted.


* com.redhat.Blivet0.Action

    * Methods
    * Properties

        * Description (``'s'``) - Description of action. (eg: "[1] Destroy device partition sdb3 (id 7)")
        * Device (``'o'``) - Object path of device this action operates on.
        * Format (``'o'``) - Object path of formatting this action operates on.
        * Type (``'s'``) - Type of action. (eg: "Create Format")
        * ID (``'i'``) - A unique ID. (Used internally and to formulate object paths.)


.. _todo:

To Do List
----------

* testing
* PolicyKit integration
* implement signals
* show properties when introspecting
