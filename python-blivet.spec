Summary:  A python module for system storage configuration
Name: python-blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 1.3
Release: 1%{?dist}
Epoch: 1
License: LGPLv2+
Group: System Environment/Libraries
%define realname blivet
Source0: http://github.com/dwlehman/blivet/archive/%{realname}-%{version}.tar.gz
%global with_python3 1

# Versions of required components (done so we make sure the buildrequires
# match the requires versions of things).
%define pykickstartver 1.99.22
%define pocketlintver 0.4
%define partedver 1.8.1
%define pypartedver 3.10.3
%define e2fsver 1.41.0
%define utillinuxver 2.15.1
%define libblockdevver 0.10

BuildArch: noarch
BuildRequires: gettext
BuildRequires: python-setuptools
BuildRequires: python3-pocketlint >= %{pocketlintver}

%if 0%{with_python3}
BuildRequires: python3-devel python3-setuptools
%endif

Requires: python
Requires: python-six
Requires: python-kickstart >= %{pykickstartver}
Requires: util-linux >= %{utillinuxver}
Requires: python-pyudev
Requires: parted >= %{partedver}
Requires: pyparted >= %{pypartedver}
Requires: e2fsprogs >= %{e2fsver}
Requires: lsof
Requires: libselinux-python
Requires: libblockdev >= %{libblockdevver}
Requires: libselinux-python
Requires: rpm-python

%description
The python-blivet package is a python module for examining and modifying
storage configuration.

%if 0%{with_python3}
%package -n python3-%{realname}
Summary: A python3 package for examining and modifying storage configuration.
Requires: python3
Requires: python3-six
Requires: python3-kickstart
Requires: python3-pyudev
Requires: parted >= %{partedver}
Requires: python3-pyparted >= %{pypartedver}
Requires: libselinux-python3
Requires: libblockdev >= %{libblockdevver}
Requires: util-linux >= %{utillinuxver}
Requires: e2fsprogs >= %{e2fsver}
Requires: lsof
Requires: rpm-python3

%description -n python3-%{realname}
The python3-%{realname} is a python3 package for examining and modifying storage
configuration.
%endif

%prep
%setup -q -n %{realname}-%{version}

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif

%build
make

%install
rm -rf %{buildroot}
make DESTDIR=%{buildroot} install
%find_lang %{realname}

%if 0%{?with_python3}
pushd %{py3dir}
make PYTHON=%{__python3} DESTDIR=%{buildroot} install
popd
%endif

%files -f %{realname}.lang
%defattr(-,root,root,-)
%license COPYING
%doc README ChangeLog examples
%{python_sitelib}/*

%if 0%{?with_python3}
%files -n python3-%{realname}
%license COPYING
%doc README ChangeLog examples
%{python3_sitelib}/*
%endif

%changelog
* Wed Apr 22 2015 Brian C. Lane <bcl@redhat.com> - 1.3-1
- fix conf.py pylint errors (bcl)
- Fix BlockDev import in populator.py (bcl)
- Prevent pylint from going crazy because of libblockdev's ErrorProxy
  (vpodzime)
- Make use of the new libblockdev error reporting (vpodzime)
- Add libselinux-python to package dependencies (#1211834) (vtrefny)
- Introduce a new doReqPartition method that is similar to doAutoPartition.
  (clumens)
- Merge pull request #81 from mulkieran/master-mount-options (mulkieran)
- Merge pull request #66 from vpodzime/master-py3_final (martin.kolman)
- Encode input for os.write() (mkolman)
- Build the python3-blivet subpackage (vpodzime)
- Do not modify dict while iterating over its values (vpodzime)
- Do not try to compare strings and Nones when sorting mountpoints (vpodzime)
- Always return strings from regular capture output run functions (mkolman)
- Do not use variable from an inner comprehension in tests (vpodzime)
- Implement and test Python 3 division for the Size class (vpodzime)
- Replace python 2 build-in-function cmp() with custom method (vtrefny)
- Do not rely on __sub__ being implemented as __add__ (-1)* (vpodzime)
- Transform our compare functions into key functions and use these instead
  (vpodzime)
- Fix the size_test to stop using byte strings (vpodzime)
- Do not define unit strings as byte strings (vpodzime)
- Do not pass context to Decimal numeric operations (vpodzime)
- Don't call object's (as a class) __new__ with extra arguments (vpodzime)
- Make translation to lowerASCII Python[23]-compatible (vpodzime)
- Replace __import__ call with importlib.import_module (vpodzime)
- In FS._postSetup() check the mountpoint options that were actually used.
  (amulhern)
- Add kwargs to unmount and move mountpoint check into _preSetup (bcl)
- Do not try importing hidden/backup files as formats (vpodzime)
- Add back DeviceTree's support for saving LUKS passphrases (vpodzime)
- Do not try to stat FileDevice's path if it doesn't exist (vpodzime)
- Merge pull request #76 from dwlehman/unusable-storage-branch (dlehman)
- Add error handling around storageInitialize for unusable setups. (dlehman)
- Include suggestions in error classes for unusable storage configurations.
  (dlehman)
- Use partially corrupt gpt disklabels. (dlehman)
- Consolidate common code in DeviceFormat class methods. (dlehman)
- Update get_mount_paths to use mountsCache (bcl)
- Add multiple mountpoint handling to MountsCache (bcl)
- Remove obsolete FIXME from FS.status (bcl)
- Check to see if mountpoint is already mounted (bcl)
- Add isMountpoint to MountsCache (bcl)
- Add ability to unmount specific mountpoints (bcl)
- Fix pylint errors for six.moves import (vtrefny)
- Merge pull request #72 from vojtechtrefny/picklable-size (vpodzime)
- Merge pull request #74 from mulkieran/master-trivia (mulkieran)
- Fix two instances where check_equal() returned True incorrectly. (amulhern)
- Fix typo in 66f2ddb11e85ec6f48535d670dd6f24cb60cbe55. (amulhern)
- Make sure installer_mode is reset to original value. (amulhern)
- Test for Size pickling support (vtrefny)
- Pickling support for Size. (vtrefny)
- Disable pylint bad-super-call in MDRaidArrayDevice.updateSize. (dlehman)
- Merge pull request #68 from dwlehman/parted-device-branch (dlehman)
- Require reallocation after changing an allocated partition's size. (dlehman)
- Move mediaPresent out of Device and into StorageDevice. (dlehman)
- Don't use parted.Device to obtain size info. (dlehman)
- Merge pull request #70 from mulkieran/master-1208536 (mulkieran)
- Prepend /sys to sysfs path for udev lookup (#1208536) (amulhern)
- Fall back on mdadm info if udev info is missing for the array (#1208536)
  (amulhern)
- Catch DeviceError as well as ValueError (#1208536) (amulhern)
- Make an MDContainerDevice if that is the right model (#1208536) (amulhern)
- Change raid variable name to raid_items (#1208536) (amulhern)
- Fix swapped args to processActions. (dlehman)
- Merge pull request #63 from dwlehman/disk-selection-branch (dlehman)
- Use VGname-LVname as key for LVinfo cache (vpodzime)
- Add back DeviceTree's methods and properties used from the outside (vpodzime)
- Wrap keys() with a list so that the dictionary can be changed (martin.kolman)
- Add a method to list disks related by lvm/md/btrfs container membership.
  (dlehman)
- Make getDependentDevices work with hidden devices. (dlehman)

* Fri Mar 27 2015 Brian C. Lane <bcl@redhat.com> - 1.2-1
- Fix pylint unused variable warnings (vtrefny)
- Add test for mountpoints (vtrefny)
- Replace _mountpoint with systemMountpoint in other modules (vtrefny)
- New method to handle nodev filesystems (vtrefny)
- Add dynamic mountpoint detection support (vtrefny)
- New method to compute md5 hash of file (vtrefny)
- Add information about subvolume to BTRFS format (vtrefny)
- Don't specify priority in fstab if -1 (default) is used (#1203709) (vpodzime)
- Catch GLib.GError in places where we catch StorageError (#1202505) (vpodzime)
- slave_dev is undefined here, use slave_devices[0] instead. (clumens)
- Clean out the mock chroot before attempting to run the rest of the test.
  (clumens)
- Move recursiveRemove from Blivet to DeviceTree. (dlehman)
- Factor out adding of sysfs slave (parent) devices into its own method.
  (dlehman)
- Add a __str__ method to DeviceTree. (dlehman)
- Allow changing the names of existing devices. (dlehman)
- Remove redundant block for adding fwraid member disks. (dlehman)
- Return a device from addUdevLVDevice if possible. (dlehman)
- Pass a sysfs path to MultipathDevice constructor from Populator. (dlehman)
- Resolve md names in udev info. (dlehman)
- LVMVolumeGroupDevice format should be marked as immutable. (dlehman)
- Don't catch and re-raise device create exceptions as DeviceCreateError.
  (dlehman)
- Call superclass _preCreate from BTRFSVolumeDevice._preCreate. (dlehman)
- Move code that populates the device tree into a new class and module.
  (dlehman)
- Move action list management into a separate class and module. (dlehman)
- Put an __init__.py in devices_tests directory. (amulhern)
- Require the Python 2 version of pykickstart (#1202255) (vpodzime)
- Use Size method to perform a Size operation (#1200812) (amulhern)
- Extend Size.roundToNearest to allow Size units (#1200812) (amulhern)
- Move code that populates the device tree into a new class and module.
  (dlehman)
- Move action list management into a separate class and module. (dlehman)
- Remove a pointless override. (amulhern)
- Display the name of the overridden ancestor in error message. (amulhern)
- Check for simple function calls in pointless overrides. (amulhern)
- Simplify supported methods in FS.py. (amulhern)
- Make hidden property use superclass method where possible. (amulhern)
- Simplify some methods in DeviceFormat class. (amulhern)
- Do supercall in BTRFSVolumeDevice.formatImmutable. (amulhern)
- Add a comment to supported property. (amulhern)
- Get rid of some very old commented out code. (amulhern)
- Put all mock results into the top-level source dir. (clumens)
- Spell TestCase.teardown correctly as tearDown(). (amulhern)
- Make testMount() check return value of util.mount(). (amulhern)
- Remove unused fs_configs. (amulhern)
- Remove side-effects from mountType property. (amulhern)
- Do not make the mountpoint directory in fs.FS.mount(). (amulhern)
- Mount should not be satisfied with anything less than a directory. (amulhern)
- Do not return doFormat() value. (amulhern)
- Put previously removed mountExistingSystem() into osinstall.py. (amulhern)
- Revert "Revive the mountExistingSystem() function and all it needs"
  (amulhern)
- Make sure the device is setup before formatting it (#1196397) (bcl)
- Use %%d format string for every value that should be an integer decimal.
  (amulhern)
- Robustify PartitionDevice._wipe() method. (amulhern)
- Fix up scientific notation _parseSpec() tests. (amulhern)
- Make size._parseSpec a public method. (amulhern)
- Simplify StorageDevice.disks. (amulhern)
- Simplify StorageDevice.growable. (amulhern)
- Simplify and correct StorageDevice.packages property. (amulhern)
- Remove services infrastructure from devices and formats. (amulhern)
- Split devices tests out into a separate directory. (amulhern)
- Fix dd wipe call. (exclusion)
- Add a script to rebase and merge pull requests (dshea)
- Add pylint false positive to list of pylint false positives. (amulhern)
- Change all instances of GLib.Error to GLib.GError. (amulhern)
- Sort pylint-false-positives using sort's default options with LC_ALL=C.
  (amulhern)
- Add ability to match scientific notation in strings. (amulhern)

* Fri Mar 06 2015 Brian C. Lane <bcl@redhat.com> - 1.1-1
- Add scratch, scratch-bumpver and rc-release targets. (bcl)
- Add --newrelease to makebumpver (bcl)
- Add po-empty make target (bcl)
- Revive the mountExistingSystem() function and all it needs (vpodzime)
- Switch translations to use Zanata (bcl)
- Set EFIFS._check to True so that it gets correct fspassno (#1077917)
  (amulhern)
- Use format string and arguments for logging function (vpodzime)
- Merge pull request #28 from vpodzime/master-libblockdev (vratislav.podzimek)
- Do not restrict MDRaidArrayDevice's memberDevices to type int (vpodzime)
- Adapt better to libblockdev's md_examine data (vpodzime)
- Set TmpFS._resizable to False. (amulhern)
- Add an additional test for TmpFS. (amulhern)
- Override NoDevFS.notifyKernel() so that it does nothing. (amulhern)
- Add TmpFS._resizefsUnit and use appropriately. (amulhern)
- Rewrite TmpFS class definition. (amulhern)
- Add TmpFS._getExistingSize() method. (amulhern)
- Make _getExistingSize() method more generally useful. (amulhern)
- Remove _getExistingSize() methods with body pass. (amulhern)
- Tidy up the definition of the device property throughout formats package.
  (amulhern)
- Add a test to check properties of device paths assigned to formats.
  (amulhern)
- Set TmpFSDevice object's _formatImmutable attribute to True. (amulhern)
- Remove no longer needed requires (vpodzime)
- Filter out pylint's "No name 'GLib' in module 'gi.repository'" messages
  (vpodzime)
- Add a static method providing list of available PE sizes (vpodzime)
- Use BlockDev's crypto plugin to do LUKS escrow (vpodzime)
- Use BlockDev's DM plugin to work with DM RAID sets (vpodzime)
- Use BlockDev's DM plugin for DM map existence testing (vpodzime)
- Remove tests for the removed devicelibs functions (vpodzime)
- Set and refresh BlockDev's global LVM config if needed (vpodzime)
- Use BlockDev's LVM plugin instead of devicelibs/lvm.py (vpodzime)
- Use BlockDev's BTRFS plugin instead of devicelibs/btrfs.py (vpodzime)
- Use the BlockDev's DM plugin instead of devicelibs/dm.py (vpodzime)
- Use BlockDev's crypto plugin instead of devicelibs/crypto.py (vpodzime)
- Use BlockDev's loop plugin instead of devicelibs/loop.py (vpodzime)
- Use BlockDev's MD plugin instead of devicelibs/mdraid.py (vpodzime)
- Use BlockDev's swap plugin instead of devicelibs/swap.py (vpodzime)
- Use BlockDev's mpath plugin instead of devicelibs/mpath.py (vpodzime)
- First little step towards libblockdev (vpodzime)
- Move the Blivet class into its own module (vpodzime)
- Use a safer method to get a dm partition's disk name. (dlehman)
- Be more careful about overwriting device.originalFormat. (#1192004) (dlehman)

* Fri Feb 13 2015 David Lehman <dlehman@redhat.com> - 1.0-1
- Move autopart and installation-specific code outside of __init__.py
  (vpodzime)
- Convert _parseUnits to public function (vtrefny)
- LVMFactory: raise exception when adding LV to full fixed size VG (#1170660)
  (vtrefny)
- Do not unhide devices with hidden parents (#1158643) (vtrefny)

* Fri Feb 06 2015 Brian C. Lane <bcl@redhat.com> - 0.76-1
- Revert "Switch to temporary transifex project" (bcl)
- Check parent/container type for thin volumes and normal volumes. (dlehman)
- drop useless entries from formatByDefault exceptlist (awilliam)
- Fix import of devicelibs.raid in platform.py (vpodzime)
- Use %%license in python-blivet.spec (bcl)
- Fix import of FALLBACK_DEFAULT_PART_SIZE (vpodzime)
- Make implicit partitions smaller if real requests don't fit anywhere
  (vpodzime)
- Use list comprehension instead of filter+lambda in makebumpver (amulhern)
- Revert "Try to deactivate lvm on corrupted gpt disks." (dlehman)
- Virtualize options property methods in DeviceFormat.options definition.
  (amulhern)
- Do not redefine size property in TmpFS. (amulhern)
- Do not set self.exists to True in TmpFS.__init__(). (amulhern)
- Simplify NoDevFS.type. (amulhern)
- Set format's mountpoint if it has the mountpoint attribute. (amulhern)
- Do not bother to set device.format.mountopts. (amulhern)
- Tighten up FS.mountable(). (amulhern)
- Simplify FS._getOptions(). (amulhern)
- Simplify setting options variable. (amulhern)
- Be less eager about processing all lines in /proc/meminfo. (amulhern)
- Make error message more useful. (amulhern)
- Add a tiny test for TmpFS. (amulhern)
- More fixes for alignment-related partition allocation failures. (dlehman)
- Do not mix stdout and stderr when running utilities unless requested
  (vpodzime)
- Define the _device, _label and _options attributes in constructor (vpodzime)
- Get rid of the has_lvm function (vpodzime)
- Do not create lambda over and over in a cycle (vpodzime)
- Disable pylint check for cached LVM data in more places (vpodzime)
- Fix issue where too many mpath luns crashes installer (#1181336) (rmarshall)
- Allow user-specified values for data alignment of new lvm pvs. (#1178705)
  (dlehman)
- Let LVM determine alignment for PV data areas. (#962961) (dlehman)
- Raise UnusableConfigurationError when unusable configuration is detected.
  (dlehman)
- Don't raise an exception for failure to scan an ignored disk. (dlehman)
- Try to deactivate lvm on corrupted gpt disks. (dlehman)
- Remove an unused and outdated constant (vpodzime)
- Relax the blivet device name requirements (#1183061) (dshea)

* Fri Jan 16 2015 Brian C. Lane <bcl@redhat.com> - 0.75-1
- Switch to temporary transifex project (bcl)
- Add docstrings to the methods in loop.py (bcl)
- get_loop_name should return an empty name if it isn't found (#980510) (bcl)
- Use dict() instead of dict comprehension. (riehecky)
- Fix the pylint errors in the examples directory. (amulhern)
- Add __init__ file to examples directory. (amulhern)

* Fri Jan 09 2015 Brian C. Lane <bcl@redhat.com> - 0.74-1
- Use _resizefsUnit in resizeArgs() method implementations. (amulhern)
- Do not supply a default implementation for the resizeArgs() method.
  (amulhern)
- Use convertTo in humanReadable(). (amulhern)
- Change convertTo() and roundToNearest() so each takes a units specifier.
  (amulhern)
- Do not even pretend that ReiserFS is resizable. (amulhern)
- Get whole unit tuple in loop when searching for correct units. (amulhern)
- Make _parseUnits() return a unit constant, rather than a number. (amulhern)
- Add unitStr() method. (amulhern)
- Make _Prefix entries named constants. (amulhern)
- Hoist _BINARY_FACTOR * min_value calculation out of loop. (amulhern)
- Comment _prefixTestHelper() and eliminate some redundancies. (amulhern)
- Eliminate redundant test. (amulhern)
- Avoid using Size constant in FileDevice._create(). (amulhern)
- Do not compare the same two values twice. (amulhern)
- Make possiblePhysicalExtents() a bit more direct. (amulhern)
- Get rid of unnecessary use of long. (amulhern)
- Use _netdev mount option as needed. (#1166509) (dlehman)
- Don't crash when a free region is too small for an aligned partition.
  (dlehman)
- Multiple loops shouldn't be fatal (#980510) (bcl)
- If allowing degraded array, attempt to start it (#1090009) (amulhern)
- Add a method that looks at DEVNAME (#1090009) (amulhern)
- Add mdrun method to just start, not assemble, an array. (#1090009) (amulhern)
- Change allow_degraded_mdraid flag to allow_imperfect_devices (#1090009)
  (amulhern)
- Remove needsFSCheck() and what only it depends on. (amulhern)
- Remove allowDirty parameter and code that depends on it. (amulhern)
- Eliminate dirtyCB parameter from mountExistingSystem() params. (amulhern)
- Use correct package for FSError. (amulhern)

* Fri Dec 19 2014 Brian C. Lane <bcl@redhat.com> - 0.73-1
- Mountpoint detection for removable devices (vtrefny)
- Fix adding partition after ActionDestroyDevice canceling (vtrefny)
- Avoid exception when aligned start and end are crossed over (exclusion)
- Substitute simple value for single element array. (amulhern)
- Change _matchNames so that it is less restrictive (amulhern)
- Change MDRaidArrayDevice to MDBiosRaidArrayDevice. (amulhern)
- Factor out MDRaidArrayDevice w/ type in ("mdcontainer", "mdbiosraidarray")
  (amulhern)
- Make it possible for NTFS to recognize the label it reads. (amulhern)
- Make unnecessarily verbose properties into simple class attributes.
  (amulhern)
- Change the generic badly formatted label to one that's bad for all.
  (amulhern)
- Don't make overridden values actual properties. (amulhern)
- Check the status of the format being mounted. (amulhern)

* Thu Dec 04 2014 Brian C. Lane <bcl@redhat.com> - 0.72-1
- Add a bunch of simple tests for filesystem formats. (amulhern)
- Get rid of long() related code. (amulhern)
- Add another check for resizable in FS.doResize() (amulhern)
- Simplify FS.free(). (amulhern)
- Make an early exit if self._existingSizeFields is [] (amulhern)
- Change "Aggregate block size:" to "Physical block size:" for JFS. (amulhern)
- Split output from infofs program for size on whitespace. (amulhern)
- Simplify _getSize() and currentSize(). (amulhern)
- Check resizable when assigning a new target size. (amulhern)
- Make default exists value a boolean in DeviceFormat.__init__. (amulhern)
- Remove pointless overrides. (amulhern)
- Add a simple pylint checker for pointless overrides. (amulhern)
- Run dosfsck in non-interactive mode (#1167959) (bcl)

* Fri Nov 21 2014 Brian C. Lane <bcl@redhat.com> - 0.71-1
- Remove redundant import. (amulhern)
- Change inclusion to equality. (amulhern)
- Round filesystem target size to whole resize tool units. (#1163410) (dlehman)
- New method to round a Size to a whole number of a specified unit. (dlehman)
- Fix units for fs min size padding. (dlehman)
- Disable resize operations on filesystems whose current size is unknown.
  (dlehman)
- Run fsck before obtaining minimum filesystem size. (#1162215) (dlehman)
- Fix setupDiskImages when the devices are already in the tree. (dlehman)
- Make logging a little less verbose and more useful in FS.mount() (amulhern)
- Make selinux test less precise. (amulhern)
- Do not translate empty strings, gettext translates them into system
  information (vtrefny)
- Add a tearDown method to StorageTestCase. (dlehman)
- Remove pointless assignment to _formattable in Iso9660FS. (amulhern)
- Remove BTRFS._resizeArgs() (amulhern)
- Add more arguments to mpathconf (#1154347) (dshea)
- Check the minimum member size for BtrfsVolumeDevices. (amulhern)
- Get rid of FS._getRandomUUID() method. (amulhern)
- Eliminate TmpFS.minSize() (amulhern)
- Don't run selinux context tests when selinux is disabled. (dlehman)
- Temporarily disable a test that isn't working. (dlehman)
- Pass a path (not a name) to devicePathToName. (dlehman)
- devicePathToName should default to returning a basename. (dlehman)
- Fix test that guards forcible removal of dm partition nodes. (dlehman)
- Device status can never be True for non-existent devices. (#1156058)
  (dlehman)
- Use super to get much-needed MRO magic in constructor. (#1158968) (dlehman)

* Thu Nov 06 2014 Brian C. Lane <bcl@redhat.com> - 0.70-1
- Add a method that determines whether a number is an exact power of 2.
  (amulhern)
- Put size values in Size universe eagerly. (amulhern)
- Update minSize method headers. (amulhern)
- Remove _minSize assignment to 0 where it's inherited from superclass.
  (amulhern)
- Make _minInstanceSize, a source of minSize() value, always a Size. (amulhern)
- Fix int * Size operation and add tests (#1158792) (bcl)
- getArch should return ppc64 or ppc64le (#1159271) (bcl)
- Pack data for the wait_for_entropy callback (vpodzime)
- Allow the wait_for_entropy callback enforce continue (vpodzime)

* Tue Nov 04 2014 Brian C. Lane <bcl@redhat.com> - 0.69-1
- Increase max depth of sphinx toc to show subpackage names. (dlehman)
- Temporarily disable the md devicetree tests due to mdadm issues. (dlehman)
- Add ability to set a default fstype for the boot partition (#1112697) (bcl)
- Pass a list of string items to log_method_return. (sbueno+anaconda)
- Require resize target sizes to yield aligned partitions. (#1120964) (dlehman)
- Split out code to determine max unaligned partition size to a property.
  (dlehman)
- Allow generating aligned geometry for arbitrary target size. (dlehman)
- Align end sector in the appropriate direction for resize. (#1120964)
  (dlehman)
- Specify ntfs resize target in bytes. (#1120964) (dlehman)
- Check new target size against min size and max size. (dlehman)
- Add a number of new tests. (amulhern)
- Add xlate parameter to humanReadable(). (amulhern)
- Rewrite _parseSpec() and convertTo() (amulhern)
- Make _lowerASCII() python 3 compatible and add a method header. (amulhern)
- Use b"", not u"", for _EMPTY_PREFIX. (amulhern)
- Strip lvm WARNING: lines from output (#1157864) (bcl)
- Add testing for MDRaidArrayDevice.mdadmFormatUUID (#1155151) (amulhern)
- Give mdadm format uuids to the outside world (#1155151) (amulhern)
- Make logSize, metaDataSize, and chunkSize always consistently Size objects.
  (amulhern)

* Wed Oct 22 2014 Brian C. Lane <bcl@redhat.com> - 0.68-1
- Only write label if there is a label AND labeling application. (amulhern)
- Handle unicode strings in Size spec parsing. (dshea)
- Fix typo in getting Thin Pool profile's name (vpodzime)
- Don't try to get no profile's name (#1151458) (vpodzime)
- Change signature of DiskLabel.addPartition to be more useful. (dlehman)
- Remove unused fallback code from DiskLabel. (dlehman)
- Let udev settle between writing partition flags and formatting. (#1109244)
  (dlehman)
- Set _partedDevice attribute before calling device constructor (#1150147)
  (amulhern)
- Fixed wrong Runtime Error raise in _preProcessActions (vtrefny)
- Set sysfsPath attribute before calling Device constructor (#1150147)
  (amulhern)
- Return all translated strings as unicode (#1144314) (dshea)
- Force __str__ to return str. (dshea)
- Use the i18n module instead of creating new gettext methods (dshea)
- Take care when checking relationship of parent and child UUIDs (#1151649)
  (amulhern)
- Further abstract loopbackedtestcase on block_size. (amulhern)
- Update tests to bring into line w/ previous commit (#1150147) (amulhern)
- Abstract ContainerDevice member format check into a method (#1150147)
  (amulhern)
- Register DeviceFormat class (#1150147) (amulhern)
- Don't append btrfs mount options to None (#1150872) (dshea)
- Convert int to str before passing it to run_program (#1151129) (amulhern)

* Thu Oct 09 2014 Brian C. Lane <bcl@redhat.com> - 0.67-1
- Don't pass --disable-overwrite to tx pull. (dlehman)
- Avoid unneccesarily tripping raid-level member count checks. (dlehman)
- Allow toggling encryption of raid container members. (#1148373) (dlehman)
- Include the new blivet.devices submodule in the built package. (clumens)
- Add a few test for setting dataLevel and metaDataLevel in BTRFS (amulhern)
- Add dataLevel and metaDataLevel attributes for testing. (amulhern)
- Add isleaf and direct to _state_functions (amulhern)
- Refactor setup of _state_functions into __init__() methods (amulhern)
- Move getting the attribute into the check methods. (amulhern)
- Adjust detection of exceptions raised. (amulhern)
- Update test setup so that it obeys RAID level requirements. (amulhern)
- Use new RaidDevice class in appropriate Device subclasses. (amulhern)
- Add new RaidDevice class for handling RAID aspects of devices. (amulhern)
- Do not set parents attribute if parents param is bad. (amulhern)

* Wed Oct 08 2014 Brian C. Lane <bcl@redhat.com> - 0.66-1
- Organize installer block device name blacklist. (#1148923) (dlehman)
- Add likely to be raised exceptions to catch block (#1150174) (amulhern)
- Canonicalize MD_UUID* values in udev.py (#1147087) (amulhern)
- Split up devices.py. (dlehman)
- Fix some pylint errors introduced in recent commits. (dlehman)
- Return early when setting new size for non-existent partition. (dlehman)
- Raise an exception when we find orphan partitions. (dlehman)
- Fall back to parted to detect dasd disklabels. (dlehman)
- Omit pylint false positive (amulhern)
- Revert "pylint hack" (amulhern)
- Remove unused import (amulhern)
- Remove unused import (amulhern)
- pylint hack (amulhern)
- Make sure autopart requests fit in somewhere (#978266) (vpodzime)
- Work with free region sizes instead of parted.Geometry objects (vpodzime)
- Check that we have big enough free space for the partition request (vpodzime)
- Allow specifying thin pool profiles (vpodzime)
- Allow specifying minimum entropy when creating LUKS (vpodzime)
- Allow user code provide callbacks for various actions/events (vpodzime)
- Change default min_value from 10 to 1 in humanReadable() (amulhern)
- Rewrite of Size.humanReadable() method (amulhern)
- Factor out commonalities in xlated_*_prefix() methods. (amulhern)
- Use named constants for binary and decimal factors. (amulhern)
- Use UPPER_CASE for constants (amulhern)

* Tue Sep 30 2014 Brian C. Lane <bcl@redhat.com> - 0.65-1
- Remove a problematic remnant of singlePV. (dlehman)
- Remove all traces of singlePV. (sbueno+anaconda)
- Change the default /boot part on s390x to not be lvm. (sbueno+anaconda)
- Remove redundant check for parents in Blivet.newBTRFS. (dlehman)
- Use Decimal for math in Size.convertTo. (dlehman)
- Filter out free regions too small for alignment of partitions. (dlehman)
- Disable LVM autobackup when doing image installs (#1066004) (wwoods)
- Add attribute 'flags.lvm_metadata_backup' (wwoods)
- lvm_test: refactoring + minor fix (wwoods)
- devicelibs.lvm: refactor _getConfigArgs()/lvm() (wwoods)
- devicelibs.lvm: fix pvmove(src, dest=DESTPATH) (wwoods)
- Only pad for md metadata if pvs use multiple disks. (dlehman)
- Align free regions used for partition growing calculations. (dlehman)
- Try to align end sector up when aligning new partitions. (dlehman)
- Remove obsolete conversion of size to float. (dlehman)
- Honor size specified for explicit extended partition requests. (dlehman)
- Honor zerombr regardless of clearpart setting. (dlehman)
- Fix treatment of percent as lvm lv size spec. (dlehman)
- Change variable keyword (#1075671) (amulhern)
- Remove unused import (#1075671) (amulhern)
- Don't mix target and discovery credentials (#1037564) (mkolman)
- Make sure /boot/efi is metadata 1.0 if it's on mdraid. (pjones)
- iscsi: fix root argument being overriden by local variable (#1144463)
  (rvykydal)
- iscsi: add iscsi singleton back (#1144463) (rvykydal)

* Fri Sep 19 2014 Brian C. Lane <bcl@redhat.com> - 0.64-1
- Fix pylint errors from recent btrfs commits. (dlehman)
- Only cancel actions on disks related to the one we are hiding. (dlehman)
- Cancel actions before hiding descendent devices. (dlehman)
- Improve handling of device removals/additions from the devicetree. (dlehman)
- The first format destroy action should obsolete any others. (dlehman)
- Do not allow modification or removal of protected devices. (dlehman)
- Propagate mount options for btrfs members to all volumes/subvolumes.
  (dlehman)
- Properly identify dm devices even when udev info is incomplete. (dlehman)
- Do not mount btrfs to list subvolumes outside installer_mode. (dlehman)
- Reset default subvolume prior to removing the default subvolume. (dlehman)
- Increase max size for btrfs to 16 EiB. (#1114435) (dlehman)
- Improve adjustment for removal of a subvol in BTRFSFactory. (dlehman)
- Set dummy mountpoint in ksdata for lvm thin pools. (dlehman)
- Add an epoch to blivet. (sbueno+anaconda)
- Check if device has enough members when setting RAID level (#1019685)
  (amulhern)
- Add BTRFSValueError error and use in btrfs related code (#1019685) (amulhern)
- iscsi: mount partitions in initramfs for root on iscsi (#740106) (rvykydal)
- Remove poolMetaData (#1021505) (amulhern)
- Revert "Allow use of a single path if multipath activation fails. (#1054806)"
  (vpodzime)
- Add a release make target (bcl)
- Prefer ID_SERIAL over ID_SERIAL_SHORT (#1138254) (vpodzime)
- Allow use of a single path if multipath activation fails. (#1054806)
  (dlehman)

* Wed Sep 10 2014 Brian C. Lane <bcl@redhat.com> - 0.63-1
- Update makebumpver to include flags on first request (bcl)
- Condense and comment some devicelibs.dasd methods (#1070115) (amulhern)
- Add a test file for DASD handling (#1070115) (amulhern)
- Pylint inspired cleanup (#1070115) (amulhern)
- Add a property for read-only devices. (dshea)
- Get rid of misleading comment (#1066721) (amulhern)
- Allow user code creating free space snapshot (vpodzime)
- Add two functions to enable manual addition of ECKD DASDs. (sbueno+anaconda)
- Make prefering leaves the default in getDeviceByPath (#1122081) (amulhern)
- Make _filterDevices() return a generator consistently (#1122081) (amulhern)
- Split string of symlinks into array of strings (#1136214) (amulhern)
- Don't put "Linux" in a root's name if it's already there. (clumens)

* Thu Aug 28 2014 Brian C. Lane <bcl@redhat.com> - 0.62-1
- Mock pyudev since libudev will not be on the builders. (dlehman)
- Update selinux tests for default context of mounts under /tmp. (dlehman)
- Clean up mocking done by udev tests when finished. (dlehman)
- Remove unused lvm and md activation code. (dlehman)
- Bypass size getter when mocking new devices. (dlehman)
- Simplify udev.device_get_uuid. (dlehman)
- Don't pass md array UUID as member format UUID. (dlehman)
- Update md name when lookup relied on UUID. (dlehman)
- Remove an obsolete block related to unpredictable md device names. (dlehman)
- Get md member and array UUIDs for format ctor from udev. (dlehman)
- Look in udev data for md member UUID. (dlehman)
- Remove some unused multipath-specific functions from blivet.udev. (dlehman)
- Adapt multipath detection code to external pyudev module. (dlehman)
- Keep lvm and md metadata separate from udev info. (dlehman)
- Replace our pyudev with the package python-pyudev. (dlehman)
- Add a bunch of tests for mdadd. (amulhern)
- Make has_redundancy() a method rather than a property and revise mdadd.
  (amulhern)
- Omit unnecessary class hierarchy related boilerplate. (amulhern)
- Add a test for activation. (amulhern)
- Add a test for mddetail on containers. (amulhern)
- Still attempt to destroy even if remove failed. (amulhern)
- Use long messages for unittest errors. (amulhern)
- Fix mdnominate error message. (amulhern)
- Cosmetic changes for the swapSuggestion function (vpodzime)
- Break once metadata value is found. (amulhern)
- Fix issues reported by pyflakes (vpodzime)
- Remove tests for the sanityCheck (vpodzime)
- Move _verifyLUKSDevicesHaveKey and its exception to anaconda (vpodzime)
- Remove sanityCheck functions from blivet sources (vpodzime)
- Remove an unused closure function (vpodzime)
- Remove two methods that are never called (vpodzime)
- Add some tests for blivet.partitioning.addPartition. (dlehman)
- Add a couple of tests for blivet.partitioning.DiskChunk. (dlehman)
- Add a DiskFile class for testing partitioning code as a non-root user.
  (dlehman)
- Add a contextmanager to create and remove sparse tempfiles. (dlehman)
- Fix sphinx formatting of code blocks in devicefactory docstrings. (dlehman)
- Mock selinux when building docs. (dlehman)
- Include doc files when installing on readthedocs. (dlehman)
- _maxLabelChars is no longer used by anything (bcl)
- tests: Add tests for HFSPlus labels (#821201) (bcl)
- Write a fs label for HFS+ ESP (#821201) (bcl)
- Mock non-standard modules so we can generate API docs on readthedocs.
  (dlehman)
- Split mdadd into separate functions. (amulhern)
- Refactor mdraid tests. (amulhern)
- Add a method to extract information about an mdraid array (amulhern)
- Extend mdadm() to capture output (amulhern)
- Be more robust in the face of possible changes to mdadm's UUIDs. (amulhern)
- Factor canonicalize_UUID() into separate method. (amulhern)
- Add a docstring to mdraid.mdexamine (amulhern)
- Remove DeviceFormat.probe() method (amulhern)
- Remove all references to mdMinor in current code base. (amulhern)
- Generalize the error message for the array level (amulhern)
- Use super() instead of explicit parent name (amulhern)
- Remove commented out import. (amulhern)
- Make docstring more precise. (amulhern)
- Minor fix of a docstring. (rvykydal)
- Get rid of partedFlags field. (amulhern)

* Fri Jul 11 2014 Brian C. Lane <bcl@redhat.com> - 0.61-1
- Fix conf.py version bumping (bcl)
- Add some tests for Chunk and Request class hierarchy. (dlehman)
- Honor the skip list when allocating leftover sectors. (dlehman)
- A Chunk is done growing when its pool is empty. (dlehman)
- Don't use integer division to calculate a fraction. (dlehman)
- Bump version in sphinx config from scripts/makebumpver. (dlehman)
- Remove spec= from Size usage in intro.rst. (dlehman)
- Attempt to reset the uuid of the mdraid member device (#1070095) (amulhern)
- Add new method udev.device_get_md_device_uuid() method (#1070095) (amulhern)
- Canonicalize mdadm generated UUIDS (#1070095) (amulhern)
- Add a udev.device_get_md_metadata() method to udev and use it. (amulhern)
- Change use of METADATA to MD_METADATA. (amulhern)
- Check for md_level of None (amulhern)
- Do not convert the result of udev.device_get_md_devices() to int. (amulhern)
- Add documentation to udev.device_get_md_*() methods. (amulhern)
- Document udev.device_get_uuid() method. (amulhern)
- Add a few small tests for mdexamine (amulhern)
- Add test for raid level descriptor None. (amulhern)
- Use context manager with assertRaises*() tests. (amulhern)
- Change uuid parameter to array_uuid (amulhern)
- Remove udev_ prefix from udev methods. (amulhern)
- Remove all references to DeviceFormat.majorminor (amulhern)
- Use add_metaclass instead of with_metaclass. (amulhern)
- Disable redefined-builtin warning. (amulhern)
- Use range instead of xrange in generateBackupPassphrase() (amulhern)
- Add a simple test of generateBackupPassphrase() result format (amulhern)
- Python3 compatibility (rkuska)
- Replace python-setuptools-devel BR with python-setuptools (bcl)

* Wed Jul 02 2014 Brian C. Lane <bcl@redhat.com> - 0.60-1
- Do not use udev info to get the name of the device. (amulhern)
- Remove unnecessary fanciness about importing devices. (amulhern)
- Disable some pylint warnings that arise due to anaconda versions. (amulhern)
- Allow RAID1 on EFI (#788313) (amulhern)

* Thu Jun 26 2014 Brian C. Lane <bcl@redhat.com> - 0.59-1
- When logging, indicate whether exception was ignored by blivet. (amulhern)

* Wed Jun 25 2014 Brian C. Lane <bcl@redhat.com> - 0.58-1
- Only import ROOT_PATH if needed (bcl)
- Add early keyword to setUpBootLoader (#1086811) (bcl)
- Only log a warning about labeling if something is wrong (#1075136) (amulhern)
- When adding an md array, allow adding incomplete arrays (#1090009) (amulhern)
- Add a flag to control whether a degraded md raid array is used (#1090009)
  (amulhern)
- Remove preferLeaves parameter from getDeviceByPath() (amulhern)
- Factor out commonalities among getDevice[s|]By* methods. (amulhern)
- Omit special check for md devices in addUdevDevice(). (amulhern)
- Remove unused 'slaves' variable. (amulhern)
- Move down or remove assignment to device in add* methods. (amulhern)
- Move DevicelibsTestCase up to the top level of the testing directory.
  (amulhern)
- Accept None for btrfs raid levels (#1109195) (amulhern)
- Add a test for a btrfs error associated with small devices (#1109195)
  (amulhern)

* Thu Jun 19 2014 Brian C. Lane <bcl@redhat.com> - 0.57-1
- Make DevicelibsTestCase devices configurable. (amulhern)
- Use correct parameters in __init__() in subclasses of unittest.TestCase.
  (amulhern)
- Add num_blocks parameter to makeLoopDev(). (amulhern)
- Move skipUnless decorator to the top level class of skipped classes.
  (amulhern)
- Explicitly accept a string as well as a RAIDLevel object. (amulhern)
- Update BTRFS initializer comments for level type. (amulhern)
- Remove some extra imports. (amulhern)
- Add method to set the default disklabel (#1078537) (bcl)
- Do not try to activate dmraid sets if the dmraid usage flag is false
  (mkolman)
- Use the value of the Anaconda dmraid flag to set the Blivet dmraid flag
  (mkolman)
- Use the value of the Anaconda ibft flag to set the Blivet ibft flag (mkolman)
- Ignore _build directory in doc directory. (amulhern)
- Change intersphinx mapping to avoid linkcheck redirect errors. (amulhern)
- Remove doctest target from Makefile. (amulhern)
- Allow the table of contents to go one level deeper. (amulhern)
- Automate generation of the .rst files which just set up the modules.
  (amulhern)

* Thu Jun 12 2014 Brian C. Lane <bcl@redhat.com> - 0.56-1
- Skip device name validation for some device types. (dlehman)
- Add a property indicating whether a device is directly accessible. (dlehman)
- Add support for read-only btrfs snapshots. (dlehman)
- Add tests for snapshots. (dlehman)
- Special treatment for getting parted device for old-style lvm snapshots.
  (dlehman)
- Some devices have immutable formatting. (dlehman)
- Detect existing btrfs snapshots. (dlehman)
- Drop special accounting for snapshot space usage in VG. (dlehman)
- Use LVMSnapshotDevice when populating the devicetree. (dlehman)
- Add Device classes for snapshots. (dlehman)
- Add ignore_skip keyword arg to lvactivate. (dlehman)
- Add optional kwarg to force removal of a logical volume. (dlehman)
- Add backend functions for creating and managing snapshots. (dlehman)
- Add docstrings for BTRFSVolumeDevice and BTRFSSubVolumeDevice. (dlehman)
- Remove duplicate portion of lvm config string. (dlehman)
- Reset the devicetree before tearing everything down in _cleanUp. (dlehman)
- Make sure disk filters are applied even if populate fails. (dlehman)
- Sync the spec file with downstream (vpodzime)

* Mon Jun 09 2014 Vratislav Podzimek <vpodzime@redhat.com> - 0.55-1
- IPSeriesPPC now supports GPT in Open Firmware (hamzy)
- Fix device name validation for devices that can contain / (#1103751) (dshea)
- Add a getRaidLevel() convenience method to raid.py (amulhern)
- Make a StorageDevice.raw_device property and use it where appropriate
  (amulhern)
- Simplify a small chunk of Blivet.updateKSData() (amulhern)
- Move the code for getting a space requirement from devicefactory to raid.
  (amulhern)
- Make all devicefactory classes uses RAID objects instead of strings.
  (amulhern)
- Remove devicefactory.get_raid_level from blivet (amulhern)
- Put get_supported_raid_levels in devicefactory.py (amulhern)
- Make BTRFS devices use RAID objects instead of strings for levels (amulhern)
- Add lists of supported RAID levels for btrfs and lvm (amulhern)
- Add "linear" to mdraid's list of supported raid levels. (amulhern)
- Remove getRaidLevel() from mdraid file and make RAID_levels public (amulhern)
- Check for required methods in MDRaidLevels.isRaidLevel. (amulhern)
- Use has_redundancy property to decide how to add a member to an array.
  (amulhern)
- Update the mdraid.mdadd comments (amulhern)
- Use has_redundancy raid property when checking whether a device is removable
  (amulhern)
- Make createBitmap() a property and update tests appropriately. (amulhern)
- Add a Dup class to the various descendants of RAIDLevel. (amulhern)
- Add an is_uniform property to the RAID levels. (amulhern)
- Add a has_redundancy method that returns True if there is actual redundancy
  (amulhern)
- Add Linear and Single to the RAID classes. (amulhern)
- Move Container class to raid package and tidy it up (amulhern)
- Allow the RAID object itself to be a valid RAID descriptor for lookup.
  (amulhern)
- Adjust RaidLevel hierarchy so that all raid level objects extend RAIDLevel
  (amulhern)
- No longer use _standard_levels as the default set of RAID levels. (amulhern)
- Extract selection of members in complete() into a separate method. (amulhern)
- Remove DMRaidArrayDevice.members property. (amulhern)
- Comment mdraid.mdcreate() and update tests appropriately. (amulhern)
- Import name 'lvm' instead of names from lvm package. (amulhern)

* Sat Jun 07 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.54-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_Mass_Rebuild

* Wed May 28 2014 Brian C. Lane <bcl@redhat.com> - 0.54-1
- Add tests for setting device's parent list directly (vpodzime)
- Do not alter the ParentList being iterated over (#1083581) (vpodzime)
- Do not limit ThinLV's size to VG's free space (vpodzime)
- Take extra RAID metadata into account when growing LV (#1093144) (vpodzime)
- Move apply_chunk_growth outside of a for-cycle (vpodzime)
- Multiple arguments for string formatting need to be in parentheses (#1100263)
  (mkolman)
- Make print statements Python 3 compatible (mkolman)
- Validate device names (dshea)
- Use a setter for Device.name as foretold by the prophecy of TODO (dshea)

* Tue May 20 2014 Brian C. Lane <bcl@redhat.com> - 0.53-1
- Remove extra quotes from the xfs_db arguments. (dshea)
- Factor duplicate code in __deepcopy__ methods into one method (#1095244)
  (amulhern)
- Rearrange code related to handleUdevDeviceFormat() (#1095329) (amulhern)
- Make dumpState catch and log all AttributeErrors (#1095329) (amulhern)
- Add sectorSize property to catch and handle missing partedDevice (#1095329)
  (amulhern)
- Get rid of remaining uses of spec keyword for Size() in examples directory.
  (amulhern)
- Generalize false positive regular expression for multiple pylint versions
  (amulhern)
- Do not run some tests unless running on Jenkins. (amulhern)
- Miscellaneous pylint fixes. (amulhern)
- Globally disable pointless string statement warning (amulhern)
- Disable unused argument warning for 'args' in TmpFSDevice constructor
  (amulhern)
- Omit 'args' parameter from formats constructors (amulhern)
- Disabled unused argument warning for kwargs in formats.destroy() (amulhern)
- Omit *args from parameters for format.create() and formats.destroy()
  (amulhern)
- Omit *args from parameters in formats.setup() (amulhern)
- Make formats.teardown() not take any extra parameters. (amulhern)
- Make formats.mount use explicit keywords instead of kwargs. (amulhern)
- Remove non-self params from FS.doResize method (amulhern)
- Make doFormat use regular style keyword parameters (amulhern)
- Do not use *args, **kwargs idiom in scheduleCreateFormat. (amulhern)
- Do not use *args, **kwargs idiom in various schedule* auxiliary test methods.
  (amulhern)
- Remove upgrading param from turnOnSwap() (amulhern)
- Disable unused-argument warning (amulhern)
- Disable pylint unused-argument warning. (amulhern)

* Thu May 08 2014 Brian C. Lane <bcl@redhat.com> - 0.52-1
- Split ROOT_PATH usage into getTargetPhysicalRoot()/getSysroot() (walters)
- Update and fix copyright info for docs. (dlehman)
- Add some tests for extended partition management. (dlehman)
- Add some tests that verify the results of DeviceTree.populate. (dlehman)
- Add a base class for tests backed by disk image storage. (dlehman)
- Adapt examples to examples/common.py function dispersement. (dlehman)
- Change devices.SparseFileDevice._create to use util.create_sparse_file.
  (dlehman)
- Move set_up_logging and create_sparse_file into blivet.util for reuse.
  (dlehman)
- Make examples.common.tear_down_disk_images a DeviceTree method. (dlehman)
- Fix handling of devices activated as a side-effect of actions. (dlehman)
- Check for problematic active devices before processing any actions. (dlehman)
- Split some large blocks out of DeviceTree.processActions. (dlehman)
- Explicitly requested extended partitions already have an action. (dlehman)
- Fix handling of extended partitions across various modes of operation.
  (dlehman)
- Handle the case of md arrays getting activated from outside blivet. (dlehman)
- Make an extra effort to remove dm partition nodes that want to stay.
  (dlehman)
- Fix handling of clearing a partitioned disk and leaving it cleared. (dlehman)
- Don't check for disklabels on partitions. (dlehman)
- Update targetSize to reflect actual size after a device is created. (dlehman)
- Remove redundant msecs from logging timestamp. (dlehman)
- Make signature of Size.__new__ match signature of Decimal.__new__ (amulhern)
- Change Size so that it takes a single value parameter. (amulhern)
- Change all 'format' keyword args to 'fmt' in Device constructors (amulhern)
- Change format keyword argument to fmt in scheduleCreateFormat (amulhern)
- Change keyword parameters in devicetree.findActions (amulhern)
- Change ActionCreateFormat constructor keyword argument to 'fmt' (amulhern)
- Remove unused parameter 'ignoreErrors' from umountFilesystems() (amulhern)
- Remove parameter 'raiseErrors' from mountFilesystems() methods. (amulhern)
- Disable unused argument warning for 'major' and 'minor' (amulhern)
- Set dummy functions as values rather than via function definition syntax.
  (amulhern)
- Pass size value to superconstructor for LVMVolumeGroupDevice. (amulhern)
- Sort the pylint-false-positives file (amulhern)
- Do not disable unused argument warning. (amulhern)
- Omit pylint warning about disabled warnings or errors from pylint log.
  (amulhern)
- Put the pyblock warning in pylint-false-positives (amulhern)
- Remove obsolete documentation for parameter 'label'. (amulhern)

* Mon May 05 2014 Brian C. Lane <bcl@redhat.com> - 0.51-1
- Adjust the available size on each disk using chunk size. (amulhern)
- Removed some now unused methods from devices (#1085474) (amulhern)
- Rename size() method to get_size() method. (amulhern)
- Remove unused get_size method (#1085474) (amulhern)
- Use raid.size method to get size of device (#1085474) (amulhern)
- Add a size() method to the raid classes (#1085474) (amulhern)
- Move line that might throw an MDRaid exception inside try block (#1085474)
  (amulhern)
- Check whether type is mdbiosraidarray before checking smallest member
  (#1085474) (amulhern)
- Log if there was a failure to calculate the size of the MDRaidArrayDevice
  (#1085474) (amulhern)
- Rename get_raw_array_size to get_net_array_size (#1085474) (amulhern)
- Rename _get_size to _trim, which describes its function better (#1085474)
  (amulhern)
- Improve comments on a few methods (#1085474) (amulhern)
- Make RAIDLevels iterable (#1085474) (amulhern)
- Update makebumpver for python-bugzilla 1.0.0 (bcl)
- Disable unused argument warning for 'key_file' in devicelibs.crypto methods
  (amulhern)
- Disable unused argument warning for 'del_passphrase' in luks_remove_key
  (amulhern)
- Disable unused argument warning for 'data' in doAutoPartition (amulhern)
- Disable unused argument warning for 'info' in handleUdevLuksFormat (amulhern)
- Disable unused argument warning for 'disks' in get_pv_space. (amulhern)
- Remove pointless parameters from unittest methods. (amulhern)
- Disable a no member warning for EddTestFS initializer. (amulhern)
- Get rid of unused argument 'args' in MakeBumpVer constructors (amulhern)
- Changes to _parseOneLine() and its single invocation. (amulhern)
- Remove obsolete comment (amulhern)
- Rename to avoid redefining parameter built-ins (amulhern)
- Change name to avoid redefining built-in (amulhern)
- Remove unused parameter in makeupdates. (amulhern)
- Removed unused argument 'options' from testMount (amulhern)
- Make signature of _setSize match that of the method it overrrides. (amulhern)
- Actually use argv parameter (amulhern)
- Pass fname as first argument to shutil.copy2 (amulhern)
- Remove minimumSector method and _minimumSector attribute (amulhern)
- Disable not-callable pylint warning. (amulhern)
- Set child_factory_fstype to None in DeviceFactory (amulhern)
- Suppress unpacking-non-sequence pylint warning (amulhern)
- Prefix name with defining package (amulhern)
- Update Platform instance from flags instead of replacing it. (#1090646)
  (dlehman)
- Rename to avoid redefining built-ins where the redefinition is method local.
  (amulhern)
- Set device.format in else block of try/except/else. (amulhern)
- Do not run pylint on sphinx generated conf.py (amulhern)
- Get rid of a redefined builtin while simplifying method. (amulhern)
- Compress loop into generator list comprehension (amulhern)
- Rewrite resize() method to depend on _resizable. (amulhern)
- Remove definition of LVMThinLogicalVolumeDevice._resizable (amulhern)
- Add an attribute docstring for _resizable. (amulhern)
- Correct comment on resizable property (amulhern)

* Thu Apr 24 2014 Brian C. Lane <bcl@redhat.com> - 0.50-1
- Don't apply action until after all checks have passed. (dlehman)
- Apply action for extended partition creation. (dlehman)
- Fix an issue introduced in commit a210eb5c. (dlehman)
- Move changes from action ctors into apply methods. (dlehman)
- Tell lvm to prefer /dev/mapper/ and /dev/md/ to dm-X and mdX nodes. (dlehman)
- Use the right md UUID when trying to look one up from addUdevDevice.
  (dlehman)
- Pass UUID of existing md array to superclass constructor. (dlehman)
- Fix accounting related to addition of md member devices. (dlehman)
- Add some more tests for the Size.humanReadable method (vpodzime)
- If size is an integer value, show it as an integer value (vpodzime)
- Make sure that using just k/m/g/... results in KiB/MiB/GiB/... (vpodzime)
- Make humanReadable size use binary prefixes and nicer units (vpodzime)
- Round sizes in humanReadable instead of flooring them (vpodzime)
- Do not assign result of evaluating EddTestFS() to a variable (amulhern)
- Rename bits() to numBits() (amulhern)
- Rename to avoid conflict with name in outer scope. (amulhern)
- Put module level code in a method (amulhern)
- Do not use strip() incorrectly (amulhern)
- Disable E1101 (no-member) error (amulhern)
- Use isResize in isShrink and isGrow. (amulhern)
- Suppress W0612 (unused-variable) false positives (amulhern)
- Suppress W0621 warnings (amulhern)
- Add a stub function for get_bootloader (amulhern)
- Suppress W0602 false positives (amulhern)
- Remove BootLoaderError definitions (amulhern)
- Disable E1003 warning. (amulhern)
- Do not cache the DeviceFormat object (amulhern)
- Suppress W0201 error where attribute is set in __new__. (amulhern)
- Add to false positives an error which is not suppressed by a pragma.
  (amulhern)
- Suppress W0201 errors (amulhern)
- Make signature of Size.__str__ match signature of Decimal.__str__ (amulhern)
- Do not evaluate %% operator in log message arguments (amulhern)
- Remove suite() methods in tests (amulhern)
- Remove addKeyFromFile() method (amulhern)
- Import name 'deviceaction' where needed (amulhern)
- Setting variables in __init__ (amulhern)
- Log exception information and disable W0703 warning. (amulhern)
- Disable some W0703 warnings (amulhern)
- Disable some W0703 warnings. (amulhern)
- Add a function that logs available exception info. (amulhern)
- Restrict scope of pylint pragmas as much as possible (amulhern)
- Change all pylint numeric codes to mnemonic strings. (amulhern)

* Thu Apr 17 2014 Brian C. Lane <bcl@redhat.com> - 0.49-1
- Slightly reduce loop and get rid of obsolete comment (amulhern)
- Slightly rewrite loop to avoid a redefining builtin error (amulhern)
- Simplify find_library and fix redefining built-in errors. (amulhern)
- Make loop variables a little more descriptive (amulhern)
- Make regular expressions raw strings. (amulhern)
- Suppress unused variable warning and check for failure. (amulhern)
- Add W0105 warning about attribute docstrings to false positives (amulhern)
- Make signature of setup() in parent class same as in children (amulhern)
- Suppress some correct pylint warnings (amulhern)
- Get _loopMap.values() when all that's needed is the values (amulhern)
- Obvious fix inspired by pylint E0602 error (amulhern)
- Suppress W0631 warning for abbr and prefix. (amulhern)
- Do not do formatting operation in the argument of the translation (amulhern)
- Remove unnecessary global statements (amulhern)
- Disable W0703 message in test (amulhern)
- Explicitly set the module level platform variable (amulhern)

* Thu Apr 10 2014 Brian C. Lane <bcl@redhat.com> - 0.48-1
- Do not execute smallestMember property method twice. (amulhern)
- Remove unnecessary function definitions in abstract properties (amulhern)
- Pass format args as arguments to debug method (#1085057) (amulhern)
- Move udev_settle call from util into fs to break circular dependency
  (amulhern)
- Change implicit relative imports to explicit relative imports (amulhern)
- Remove unused imports (amulhern)
- Get rid of os.path import (amulhern)
- Really avoid dynamic import of formats/__init__.py by itself (amulhern)
- Ignore E1101 errors in savePassphrase. (amulhern)
- Add a bunch of E1120 errors to the false positives file (amulhern)
- Make LabelingAsRoot class an abstract class and define two properties
  (amulhern)
- Suppress false positive W0631 error. (amulhern)
- Use self.nic instead of nic (amulhern)
- Make sure _state_functions is a dictionary in base class (amulhern)
- Remove unnecessary lambda wrappers on assertion functions (amulhern)
- Obvious fix inspired by an "Undefined variable warning" (amulhern)
- Remove all references to lvm_vg_blacklist and blacklistVG. (amulhern)
- Update for changes in the anaconda errorHandler API. (dshea)
- Remove unused imports. (amulhern)
- Import from the defining module. (amulhern)
- Move import to top level. (amulhern)
- Do not use implicit relative imports (amulhern)
- Remove wildcard import (amulhern)
- Fix a bug and catch a change in lvm's thin pool layout. (dlehman)
- Plumb uuid down through DMDevice. (dlehman)

* Wed Apr 02 2014 Brian C. Lane <bcl@redhat.com> - 0.47-1
- Change labelApp to a more concisely defined abstract property (amulhern)
- Change defaultLabel to a more concisely defined abstract property. (amulhern)
- Change _labelstrRegex to a more concisely defined abstract property.
  (amulhern)
- Make reads property a bit more succinct. (amulhern)
- Make name an abstract property and omit _name (amulhern)
- Remove an unused import from devicelibs/raid.py (vpodzime)
- Fix all pylint errors in pylintcodediff (amulhern)
- Don't run test if the git branch is dirty (amulhern)
- Exit if the specified log file does not exist. (amulhern)
- Update lvm devicelibs tests to reflect recent changes. (dlehman)
- Add required LVs as needed instead of trying to sort by attrs. (dlehman)
- Fix missed conversion of rm->missing in vgreduce call. (dlehman)
- Only gather lvm information one time per DeviceTree.populate call. (dlehman)
- Add support for listing everything to pvinfo and lvs. (dlehman)
- Get lv list from lvm in a more straightforward format. (dlehman)
- Gather lv list where we use it to save from having to stash it. (dlehman)
- Split out common lvm parsing code. (dlehman)
- Add tests that use ParentList as part of Device. (dlehman)
- Parent list length doesn't reflect new member in _addParent. (dlehman)
- Rearrange _startEdd to be a little more obvious. (amulhern)
- Raise exceptions using the new syntax (amulhern)
- Do not import logging twice. (amulhern)
- Suppress unused variable warning (amulhern)
- Get rid of writeRandomUUID. (amulhern)
- Remove unused variable but retain call for its side-effects (amulhern)
- Put docstring in class (amulhern)
- Remove appendiceal assignment (amulhern)
- Keep first parameter "self" (amulhern)
- Omit compile flag (amulhern)
- Move lines beneath __main__ into a main method (amulhern)
- Indent with spaces, not tabs (amulhern)
- Change param default [] to None and convert in method (amulhern)
- Change to a semantically equivalent version of FileDevice.path (amulhern)
- Adapt existing tests to changed signature of some methods (amulhern)
- Don't assign return value to unused variable (amulhern)
- Be specific when catching exceptions (dshea)
- Remove appendiceal assignments (amulhern)
- Remove a lot of unused variables extracted from udev info (amulhern)
- Don't get return values from communicate() if they are ignored (amulhern)
- Use the disk's name in log message (amulhern)
- Get rid of old exception unpacking syntax (dshea)
- Rearranged some iffy exception checking (dshea)
- Replace with a semantically equivalent chunk. (amulhern)
- Remove some unused exception names. (amulhern)
- Remove unused assignment to boot. (amulhern)
- Delete method-local pruneFile function. (amulhern)
- Don't comment out function headers but leave their bodies uncommented
  (amulhern)
- Get rid of unnecessary pass statements (amulhern)
- Put a field and a method in the base class (amulhern)
- Spell parameter self correctly (amulhern)
- Give abstract method the same signature as its overriding methods. (amulhern)
- Catch correct error and disable warning. (amulhern)

* Wed Mar 26 2014 Brian C. Lane <bcl@redhat.com> - 0.46-1
- Adapt callers to use the new parent list interface. (dlehman)
- Change management of Device parents to use a simple list interface. (dlehman)
- Convert ContainerDevice to an abstract base class. (dlehman)
- Set device uuid before calling Device ctor. (dlehman)
- Improve the mechanism for VG completeness. (dlehman)
- Support mutually-obsoleting actions. (dlehman)
- Add some checking to MDRaidArrayDevice._setSpares. (dlehman)
- Make sorting by action type part of the action classes. (dlehman)
- Add action classes for container member set management. (dlehman)
- Add a property to provide consistent access to parent container device.
  (dlehman)
- Add type-specific methods for member set management. (dlehman)
- Adapt callers to new method names for add/remove member device. (dlehman)
- Add a ContainerDevice class to consolidate member management code. (dlehman)
- Add backend functions for container member set management. (dlehman)
- Teardown RAID device once testing is over (amulhern)
- Make lvm tests runnable. (amulhern)
- Make crypt tests runnable. (amulhern)
- Replace unnecessarily complicated expression with string multiplication
  (amulhern)
- Suppress unused variable warning for index in range (amulhern)
- Suppress some unused variable warnings. (amulhern)
- Suppress some unused variable warnings (amulhern)
- Update to the new raise syntax (dshea)
- Removed an unnecessary semicolon (dshea)
- Removed a redundant definition of NoDisksError (dshea)
- Specify regular expressions containing backslashes as raw strings (dshea)
- Fixed some questionable indentation (dshea)
- Fix logging function string format warnings. (dshea)
- All size specifications should be Size instances (#1077163) (vpodzime)
- Make sure StorageDevice's self._size is a Size instance (#1077179) (vpodzime)
- Allow creating Size instance from another Size instance (vpodzime)
- Force removal of hidden devices (#1078163) (amulhern)
- Get action_test into working order. (dlehman)
- Update action_test.py to specify sizes using blivet.size.Size. (dlehman)
- Don't corrupt the environment when setting up StorageTestCase. (dlehman)
- Make minSize, maxSize consistent and correct. (dlehman)
- Don't prevent grow actions on devices with no max size. (dlehman)

* Thu Mar 20 2014 Brian C. Lane <bcl@redhat.com> - 0.45-1
- Changes to allow pylint checks to be run on a distribution of the source.
  (amulhern)
- Remove non-doing check target (amulhern)
- Add a script to relate pylint errors to lines changed. (amulhern)
- Change output format so that it is suitable for diff-cover. (amulhern)
- Do an initial setup for running pylint tests in blivet. (amulhern)
- Handle None in devicePathToName(#996303) (dshea)
- Remove bootloader.packages from storage.packages (#1074522). (clumens)
- Whitespace fixes for the crypto devicelib module (vpodzime)
- Use random.choice for generating LUKS backup passphrase (vpodzime)
- Trivial fixes for the lvm devicelib module (vpodzime)
- Make vginfo work the same way as pvinfo and other LVM functions (vpodzime)
- Allow NTFS to be mountable. (#748780) (dshea)
- Limit the LV size to VG's free space size (vpodzime)

* Fri Mar 07 2014 Brian C. Lane <bcl@redhat.com> - 0.44-1
- Fix an old typo in zeroing out a PReP partition. (#1072781) (dlehman)
- Only count with the extra metadata extents in new VGs and LVs (#1072999)
  (vpodzime)
- Use container's parent's name for PV if available (#1065737) (vpodzime)
- Fix traceback with write_dasd_conf. (#1072911) (sbueno+anaconda)
- When copying a root, also copy hidden devices (#1043763) (amulhern)
- Add hidden flag to devicetree.getDeviceByID (#1043763) (amulhern)
- Only set device for mountpoint if it is not None (#1043763) (amulhern)
- Extend the list of things to be omitted if moddisk is False (#1043763)
  (amulhern)
- Set req_name to None at the top of initializer (#1043763) (amulhern)
- Log action cancelation (#1043763) (amulhern)
- Make DeviceTree.hide() remove a larger set (#1043763) (amulhern)
- Re-write the DASD storage code. (#1001070) (sbueno+anaconda)
- Include image install flag when updating from anaconda flags. (#1066008)
  (dlehman)

* Fri Feb 28 2014 Brian C. Lane <bcl@redhat.com> - 0.43-1
- Include tmpfs mounts in post-install kickstart (#1061063) (mkolman)
- Count with the extra metadata extents for RAID consistently (#1065737)
  (vpodzime)
- Make partitioning error message more friendly (#1020388) (amulhern)
- Fix partition handling across multiple processActions calls. (#1065522)
  (dlehman)
- Let the udev queue settle before populating the devicetree. (#1049772)
  (dlehman)
- Don't activate or deactivate devices from the action classes. (#1064898)
  (dlehman)
- Improve handling of parted.DiskLabelCommitError slightly. (dlehman)
- Make teardownAll work regardless of flags. (dlehman)
- Fix maxSize test when setting device target size. (dlehman)
- Size.convertTo should return a Decimal. (dlehman)
- Don't use float for anything. (dlehman)
- Fix type of block count in PartitionDevice._wipe. (dlehman)
- Fix handling of size argument to devicelibs.lvm.thinlvcreate. (#1062223)
  (dlehman)
- return empty set when no matching fcoe nic (#1067159) (bcl)
- Return str from Size.humanReadable (#1066721) (dshea)
- Add a coverage test target (#1064895) (amulhern)
- Filesystem labeling tests will not run without utilities (#1065422)
  (amulhern)
- Rename misc_test.py to something more descriptive (#1065422) (amulhern)
- Refactor labeling tests (#1065422) (amulhern)
- Move SwapSpace tests into a separate class (#1065422) (amulhern)

* Tue Feb 18 2014 Brian C. Lane <bcl@redhat.com> - 0.42-1
- Wait for udev to create device node for new md arrays. (#1036014) (dlehman)
- Fix detection of thin pool with non-standard segment types. (#1022810)
  (dlehman)
- NFSDevice does not accept the exists kwarg. (#1063413) (dlehman)
- Don't run mpathconf for disk image installations. (#1066008) (dlehman)
- If /etc/os-release exists, check it to identify an installed system.
  (clumens)
- Get the unit tests into a runnable state. (dlehman)
- Update Source URL in spec file to use github. (dlehman)

* Tue Feb 11 2014 Brian C. Lane <bcl@redhat.com> - 0.41-1
- ntfs _getSize needs to use Decimal (#1063077) (bcl)
- Separate sanityCheck-ing from doAutoPartition (#1060255) (amulhern)
- Change messages to SanityExceptions objects (#1060255) (amulhern)
- Make a small SanityException hierarchy (#1060255) (amulhern)
- Remove unused exception class (#1060255) (amulhern)
- Add another .decode("utf-8") to humanReadable (#1059807) (dshea)
- makebumpver: Any failure should cancel the bump (bcl)

* Tue Feb 04 2014 Brian C. Lane <bcl@redhat.com> - 0.40-1
- makebumpver: Only remove from list if action is not Resolves (bcl)
- Update bumpver to allow Related bugs (bcl)
- Remove all dependent devices of san device becoming multipath (#1058939)
  (rvykydal)
- When repopulating multipath members mark them as multipath (#1056024)
  (rvykydal)
- fcoe: parse yet another sysfs structure for bnx2fc devices (#903122)
  (rvykydal)
- fcoe: add fcoe=<NIC>:<EDB> to boot options for nics added manually (#1040215)
  (rvykydal)
- Convert the ntfs minsize to an int (#1060031) (dshea)
- Convert the string representation of Size to a str type. (#1060382) (dshea)
- don't display stage2 missing error as well if the real problem is stage1
  (awilliam)
- Provide a mechanism for platform-specific error messages for stage1 failure
  (awilliam)
- Don't add None value to req_disks (#981316) (amulhern)
- Make error message more informative (#1022497) (amulhern)
- Check that file that loop device is going to use exists (#982164) (amulhern)
- Use os.path.isabs to check whether path name is absolute (#994488) (amulhern)

* Tue Jan 28 2014 Brian C. Lane <bcl@redhat.com> - 0.39-1
- escrow: make sure the output directory exists (#1026653) (wwoods)
- provide a more useful error message if user fails to create an ESP (awilliam)
- Tell lvcreate not to ask us any questions and do its job. (#1057066)
  (dlehman)

* Fri Jan 24 2014 Brian C. Lane <bcl@redhat.com> - 0.38-1
- Some simple tests for _verifyLUKSDevicesHaveKey (#1023442) (amulhern)
- Verify that LUKS devices have some encryption key (#1023442) (amulhern)

* Wed Jan 22 2014 Brian C. Lane <bcl@redhat.com> - 0.37-1
- Only do SELinux context resets if in installer mode (#1038146) (amulhern)
- Look up SELinux context for lost+found where it is needed (#1038146)
  (amulhern)
- Don't reset the SELinux context before the filesystem is mounted (#1038146)
  (amulhern)
- Test setting selinux context on lost+found (#1038146) (amulhern)
- Only retrieve the unit specifier once (dshea)
- Fix the Device.id usage. (dshea)
- Accept both English and localized sizes in Size specs. (dshea)
- Use a namedtuple to store information on unit prefixes (dshea)
- Remove en_spec Size parameters. (dshea)
- Fix potential traceback in devicetree.populate. (#1055523) (dlehman)
- Fall back on relabeling app where available (#1038590) (amulhern)
- Change the meaning of label field values (#1038590) (amulhern)
- Enable labeling on NTFS filesystem (#1038590) (amulhern)
- Enable labeling on HFS filesystem (#1038590) (amulhern)
- Add a method that indicates ability to relabel (#1038590) (amulhern)
- Use filesystem creation app to set filesystem label (#1038590) (amulhern)
- Import errors so FSError name is resolved (#1038590) (amulhern)
- Remove BTRFS._getFormatOptions (#1038590) (amulhern)
- Make an additional class for labeling abstractions (#1038590) (amulhern)
- Fix copyright date (#1038590) (amulhern)
- Remove redundant _defaultFormatOptions field (#1038590) (amulhern)
- Remove code about unsetting a label (#1038590) (amulhern)
- Return None if the filesystem has no label (#1038590) (amulhern)
- Removed redundant check for existance of filesystem (#1038590) (amulhern)
- Have writeLabel throw a more informative exception (#1038590) (amulhern)

* Fri Jan 17 2014 Brian C. Lane <bcl@redhat.com> - 0.36-1
- Update the TODO list. (dlehman)
- Multipath, fwraid members need not be in exclusiveDisks. (#1032919) (dlehman)
- Convert parted getLength values to Size (dshea)
- Last of the Device._id -> Device.id (bcl)
- iscsi: in installer automatically log into firmware iscsi targets (#1034291)
  (rvykydal)
- Use isinstance for testing numeric types (vpodzime)
- Device._id -> Device.id (clumens)
- Allow resetting partition size to current on-disk size. (#1040352) (dlehman)

* Fri Jan 10 2014 Brian C. Lane <bcl@redhat.com> - 0.35-1
- Convert everything to use Size. (dlehman)
- Allow negative sizes. (dlehman)
- Fix return value of Size.convertTo with a spec of bytes. (dlehman)
- Discard partial bytes in Size constructor. (dlehman)
- Prefer binary prefixes since everything is really based on them. (dlehman)
- Fix a few minor problems introduced by recent raid level changes. (dlehman)
- Move label setter and getter into DeviceFormat class (#1038590) (amulhern)
- Add a test for labeling swap devices (#1038590) (amulhern)
- Default to None to mean none, rather than empty string (#1038590) (amulhern)
- Add a labelFormatOK method to the DeviceFormat's interface (#1038590)
  (amulhern)
- Indicate whether the filesystem can label (#1038590) (amulhern)
- Restore ability to write an empty label where possible (#1038590) (amulhern)
- More tests to check writing and reading labels (#1038590) (amulhern)
- Remove fsConfigFromFile (#1038590) (amulhern)
- Changes to the handling of filesystem labeling (#1038590) (amulhern)
- Add some simple tests for file formats. (amulhern)
- Give DeviceFormat objects an id (#1043763) (amulhern)
- Refactor to use ObjectID class (#1043763) (amulhern)
- Make a class that creates a unique-per-class id for objects (#1043763)
  (amulhern)
- Revert "Make a class that creates a unique-per-class id for objects
  (#1043763)" (amulhern)
- Revert "Give DeviceFormat objects an object_id (#1043763)" (amulhern)
- Make the maximum end sector for PReP boot more benevolent (#1029893)
  (vpodzime)
- Give DeviceFormat objects an object_id (#1043763) (amulhern)
- Make a class that creates a unique-per-class id for objects (#1043763)
  (amulhern)
- Make get_device_format_class return None if class not found (#1043763)
  (amulhern)
- A few simple unit tests for some formats methods (#1043763) (amulhern)
- Don't translate format names (dshea)

* Thu Dec 19 2013 Brian C. Lane <bcl@redhat.com> - 0.34-1
- Forget existing partitions of device becoming a multipath member (#1043444)
  (rvykydal)
- Include blivet.devicelibs.raid in the generated documentation. (amulhern)
- Upgrade the comments in raid.py to be compatible with sphinx. (amulhern)
- Make space for LUKS metadata if creating encrypted device (#1038847)
  (vpodzime)
- fcoe: give error message in case of fail when adding device (#903122)
  (rvykydal)
- fcoe: adapt bnx2fc detection to changed sysfs path structure (#903122)
  (rvykydal)
- Update format of iscsi device becoming multipath member (#1039086) (rvykydal)

* Tue Dec 17 2013 Brian C. Lane <bcl@redhat.com> - 0.33-1
- Add initial 64-bit ARM (aarch64) support (#1034435) (dmarlin)
- Convert to sphinx docstrings. (dlehman)
- Add some documentation. (dlehman)
- Move getActiveMounts from Blivet into DeviceTree. (dlehman)
- Add an example of creating lvs using growable requests. (dlehman)
- Remove a whole bunch of unused stuff from Blivet. (dlehman)
- Remove usage of float in Size.humanReadable. (dlehman)
- Add missing abbreviations for binary size units. (dlehman)
- Fix shouldClear for devices with protected descendants. (#902417) (dlehman)
- Use // division so that it continues to be floor division in Python 3.
  (amulhern)

* Thu Dec 12 2013 Brian C. Lane <bcl@redhat.com> - 0.32-1
- Work on devicelibs.btrfs methods that require that the device be mounted.
  (amulhern)
- Remove some methods from devicelibs.btrfs. (amulhern)
- Add a comment to btrfs.create_volume. (amulhern)
- Add a file to run btrfs tests. (amulhern)
- Remove format.luks.LUKS.removeKeyFromFile. (amulhern)
- Changes to devicelibs.mdraid.mdactivate. (amulhern)
- Restore an import removed in a previous commit. (amulhern)
- Add a PE for LUKS metadata (#1038969) (bcl)
- Adjust currentSize methods slightly. (amulhern)
- Put additional constraints on the ActionResizeDevice initializer. (amulhern)
- Remove redundant checks in existing resize() methods. (amulhern)
- Add some baseline unit tests for BTRFS devices. (amulhern)
- Robustify use of defaultSubVolumeID field. (amulhern)
- Check that a BTRFS subvolume has exactly one parent in constructor.
  (amulhern)
- BTRFSSubVolume.volume checks the class of its return value. (amulhern)
- Raise ValueError in BTRFS constructor if no parents specified. (amulhern)
- Add tests for a couple of additional properties for MDRaidArrayDevice.
  (amulhern)
- Factor state testing behavior into a separate class. (amulhern)
- Remove redundant condition in if statement. (amulhern)

* Thu Dec 05 2013 Brian C. Lane <bcl@redhat.com> - 0.31-1
- Make RAIDLevel an abstract class using abc. (amulhern)
- Restore a util import that was removed in a recent commit. (amulhern)

* Wed Dec 04 2013 Brian C. Lane <bcl@redhat.com> - 0.30-1
- Always run action's cancel method as part of cancelAction. (dlehman)
- Show Invalid Disk Label for damaged GPT (#1020974) (bcl)
- Make error message in setDefaultFSType more informative (#1019766) (amulhern)
- Set sysfsPath of LUKSDevice when adding to device tree (#1019638) (jsafrane)
- Use given format type as format's name instead of type (vpodzime)

* Wed Nov 27 2013 Brian C. Lane <bcl@redhat.com> - 0.29-1
- btrfs and xfs do not support fsck or dump at boot time (#862871) (bcl)
- Removed raid level constants from mdraid.py. (amulhern)
- Remove raidLevel and get_raid_min_members for mdraid.py. (amulhern)
- Remove raidLevelString in raid and mdraid. (amulhern)
- In devicefactory.py change mdraid procedures call to raid method calls.
  (amulhern)
- Removed mdraid.raid_levels (amulhern)
- Removed mdraid.get_raid_max_spares. (amulhern)
- Change MDRaidArrayDevice to use raid package. (amulhern)
- Changed devicelibs.mdraid to make use of devicelibs.raid. (amulhern)
- Implement a RAID class hierarchy. (amulhern)
- A few small tests for MDFactory class. (amulhern)
- Add some additional unit tests in mdraid_tests.py. (amulhern)
- Make MDRaidArrayDevice initializer not except raid level of None. (amulhern)
- Add some basic unit tests for MDRaidArrayDevice. (amulhern)
- Move pyanaconda import into blivet.enable_installer_mode. (amulhern)

* Mon Nov 25 2013 David Lehman <dlehman@redhat.com> - 0.28-1
- Clear whole-disk formatting before initializing disks. (#1032380) (dlehman)
- Simplify calculation of vol size when adding a btrfs subvol. (#1033356)
  (dlehman)
- Handle passing a btrfs volume as device to BTRFSFactory. (dlehman)
- Add support for detecting btrfs default subvolume. (dlehman)
- Handle nested btrfs subvolumes correctly. (#1016959) (dlehman)
- Mark all format names as translatable (dshea)
- Add parameters for untranslated Size specs. (dshea)
- Fix usage of _ vs N_ (dshea)
- Added a i18n module for gettext functions. (dshea)
- Allow non-ASCII characters in the size spec (dshea)

* Tue Nov 19 2013 David Lehman <dlehman@redhat.com> - 0.27-1
- Specify btrfs volumes by UUID in /etc/fstab. (dlehman)
- Catch any exception raised by findExistingInstallations. (#980267) (dlehman)
- Prevent md_node_from_name from raising OSError. (#980267) (dlehman)
- Tidy up tests in devicelibs_test directory. (amulhern)
- Preparation for lv resize is a subset of that for lv destroy. (#1027682)
  (dlehman)
- Make sure new values of targetSize are within bounds. (dlehman)
- Devices with non-existent formatting are resizable. (#1027714) (dlehman)
- Do not hide non-existent devices. (#1027846) (dlehman)
- Change XFS maximum to 16EB (#1016035) (bcl)
- Add tmpfs support (#918621) (mkolman)
- Add support for returning machine word length (mkolman)
- Require cryptsetup instead of cryptsetup-luks (#969597) (amulhern)
- Fix initialization of disks containing sun or mac disklabels. (dlehman)
- Newly formatted devices are used unless mountpoint is empty. (#966078)
  (dlehman)
- Fix detection of lvm setups. (#1026466) (dlehman)
- Fix handling of overcommitted thin pools in thinp factory. (#1024144)
  (dlehman)
- Fix name checking for new thin lvs. (#1024076) (dlehman)

* Wed Oct 30 2013 Brian C. Lane <bcl@redhat.com> - 0.26-1
- Add macefi format type (#1010495) (bcl)
- Allow hfs+ boot devices to have their name set (#1010495) (bcl)
- Update parted partitions on hidden disks when copying a Blivet. (#1023556)
  (dlehman)
- Add ack flag checking to makebumpver (bcl)
- Add makebumpver script (bcl)

* Fri Oct 25 2013 Brian C. Lane <bcl@redhat.com> - 0.25-1
- Remove requirement for btrfsctl which no longer exists. (#1012504) (dlehman)
- Allow for adjustment of factory vg after removal of thin pool. (#1021890) (dlehman)
- Add boot description for "disk" devices on s390. (#867777, #903237, #960143) (sbueno+anaconda)
- Add initial spport for aarch64 as we only plan to support UEFI this should be enough (dennis)

* Wed Oct 16 2013 David Lehman <dlehman@redhat.com> - 0.24-1
- Close file descriptors other than stdin,stdout,stderr on exec. (#1016467) (dlehman)
- Don't use hardcoded /tmp paths. (#1004404) (dlehman)
- Fix detection of lvm thinp setups. (#1013800) (dlehman)
- Generate a name if necessary when reconfiguring a factory device. (#1019500) (dlehman)
- Handle anaconda's cmdline option to disable mpath friendly names. (#977815) (dlehman)
- Allow specifying which swaps should appear in fstab (vpodzime)
- Do not limit swap size to 10 % of disk space for hibernation (vpodzime)

* Wed Oct 09 2013 Brian C. Lane <bcl@redhat.com> - 0.23-1
- Make sure bootloader is setup after autopart (#1015277) (bcl)
- Let setUpBootLoader raise BootloaderError (#1015277) (bcl)
- Limit the maximum swap size to 10 % of disk space (if given) (vpodzime)
- support ppc64le architecture (hamzy)
- Don't call handleUdevDeviceFormat without udev device (#1009809) (dshea)

* Fri Sep 06 2013 David Lehman <dlehman@redhat.com> - 0.22-1
- Allow implicit inclusion of multipath/fwraid by including all members. (dlehman)
- If a device has been removed, omit it from the copied root. (#1004572) (dlehman)
- Thinp metadata and chunk size default to 0 -- not None. (#1004718) (dlehman)
- Revert "Do not try to align partitions to optimal_io_size. (#989333)" (dlehman)

* Thu Sep 05 2013 Brian C. Lane <bcl@redhat.com> - 0.21-1
- Only force luks map names to include UUID during OS installation. (#996457) (dlehman)
- Allow DiskLabelCommitError to reach the caller. (#1001586) (dlehman)
- Do not try to align partitions to optimal_io_size. (#989333) (gustavold)
- Fix rpmlog make target (bcl)
- Add missing changelog lines to spec (bcl)

* Fri Aug 23 2013 Brian C. Lane <bcl@redhat.com> - 0.20-1
- Fix typo in examples/list_devices.py (dlehman)
- Use iscsi-iname instead of trying to reimplemnt it in python. (dlehman)
- Catch exceptions raised while finding old installations. (#981991) (dlehman)
- Keep the dasd list in sync with the devicetree's device list. (#965694) (dlehman)
- Don't save luks keys unless installer_mode flag is set. (#996118) (dlehman)
- Pass mount options to resolveDevice in _parseOneLine (#950206) (vpodzime)
- Fix handling of devices in detected installations in Blivet.copy. (dlehman)
- Clean up detection of lvm raid. (dlehman)
- Tag the first build of each version without the release. (dlehman)
- Remove dangling code block from commit 737169b75af1. (dlehman)

* Wed Jul 31 2013 Brian C. Lane <bcl@redhat.com> - 0.19-1
- Don't waste time looking for devices dependent on leaf devices. (dlehman)
- Add some example code for creation of disk partitions. (dlehman)
- Don't manipulate partition boot flags except in installer mode. (dlehman)
- Add an example of DeviceFactory usage. (dlehman)
- Cosmetic changes for the arch module (vpodzime)
- No more sparc support (vpodzime)
- Cleanup arch.py reredux (hamzy)
- Allow explicit requests for extended partitions. (#891861) (dlehman)
- Fix disklabel handling for multiple calls to processActions. (dlehman)
- Add support for explicit start/end sectors in partition requests. (#881025) (dlehman)
- Store current mount options in getActiveMounts. (#914898) (dlehman)
- Lack of formatting does not preclude device resize. (dlehman)
- Handle negative sizes correctly. (dlehman)
- Fix handling of clearpart type linux in shouldClear. (dlehman)
- Add some tests for clearpart and related functionality. (dlehman)
- Update unit tests and add a make target to run them. (dlehman)
- Don't pass dracut args for lvm thin pools. (dlehman)
- Update the TODO list. (dlehman)
- Fix a copy/paste error. (dlehman)
- Remove transifex-client BuildRequires. (dlehman)

* Tue Jul 09 2013 Brian C. Lane <bcl@redhat.com> - 0.18-1
- Raise XFS max size limit to 100TB. (sbueno+anaconda)
- Add a device factory class for thinly-provisioned lvm. (dlehman)
- Add support for automatic partitioning using lvm thin provisioning. (dlehman)
- Add convenience methods related to lvm thin provisioning. (dlehman)
- Add support for detection of lvm thinp setups. (dlehman)
- Add classes for lvm thin pool and thin volume. (dlehman)
- Add backend support for lvm thinp operations. (dlehman)
- Fix return value of get_pv_space for size of 0. (dlehman)
- Fix ksdata for lvm created in custom spoke based on autopart. (dlehman)
- Only put max size in ksdata if partition is growable. (dlehman)
- Allow subclasses to inherit ksdata classes. (dlehman)

* Mon Jun 24 2013 Brian C. Lane <bcl@redhat.com> - 0.17-1
- Used Python type instead of variable name (#968122) (hamzy)
- Fix detection of valid EFI system partition during autopart. (dlehman)
- New version: 0.16 (bcl)

* Thu Jun 13 2013 Brian C. Lane <bcl@redhat.com> - 0.16-1
- Install utilities for all devices -- not just those being used. (#964586) (dlehman)
- Add a method to apply Blivet settings to ksdata. (dlehman)
- Increase padding for md metadata in lvm factory. (#966795) (dlehman)
- Move lvm-on-md into LVMFactory. (dlehman)
- Switch to a minimum of four members for raid10. (#888879) (dlehman)
- Update the TODO list. (dlehman)
- Deactivate devices before hiding those on ignored disks. (#965213) (dlehman)
- Allow udev queue to settle after writing zeros to disk. (#969182) (hamzy)
- Run lsof when umount fails (bcl)
- Run udev settle before umount (bcl)

* Mon Jun 03 2013 Brian C. Lane <bcl@redhat.com> - 0.15-1
- Switch to the LGPLv2+. (dlehman)
- Clear md arrays' sysfs path after deactivating them. (#954062) (dlehman)
- Factories with existing containers use the container's disk set. (dlehman)
- Don't set up a child factory if the container is set and exists. (dlehman)
- Set a non-zero size for new btrfs subvols in an existing volume. (dlehman)
- Open as many luks devs as possible with any given passphrase. (#965754) (dlehman)
- Make sure container changes worked before applying device changes. (#965805) (dlehman)
- Re-initialize platform in storageInitialize (#962104) (bcl)
- Make a copy of devicetree._devices before using the append operator. (clumens)
- Handle incomplete devices becoming complete on device rescan. (clumens)
- Don't allow a device to be on the hidden list more than once. (clumens)

* Wed May 15 2013 David Lehman <dlehman@redhat.com> - 0.14-1
- total_memory calculation needs to round up (#962231) (bcl)
- The dev.node attribute for iscsi devices is not copyable (#962865). (clumens)
- Wipe partitions before they are created (#950145) (bcl)
- Pass ROOT_PATH as an argument instead of importing it. (clumens)
- If no iscsi nodes are discovered, return an empty list instead of None. (clumens)

* Thu May 09 2013 Brian C. Lane <bcl@redhat.com> - 0.13-1
- Make sure createBitmap is updated when level changes (#960271) (bcl)
- Update biosboot error message (#960691) (bcl)

* Fri May 03 2013 David Lehman <dlehman@redhat.com> - 0.12-1
- Fix a bug in renaming lvm lvs. (dlehman)
- Add container size policies for unlimited growth and fixed size. (dlehman)
- Remove device factory methods to change container name. (dlehman)
- Override any default subvol when mounting main btrfs volume. (#921757) (dlehman)
- Fix detection of multipath. (#955664) (dlehman)
- When a btrfs subvol's name is changed, change its subvol argument too. (clumens)
- Allow returning hidden disks from the getDeviceBy* methods, if asked. (clumens)
- Fix fipvlan -f argument once more and for good (#836321) (rvykydal)
- Remove the intf parameters from the iscsi class. (clumens)
- Don't relly on /proc/mdstat when enumeraing RAID levels. (jsafrane)
- Set product names in non-installer mode. (jsafrane)
- Fixed checking status of MD RAID which was just deleted. (jsafrane)
- Account for the fact that md's metadata usage is unpredictable. (dlehman)
- Remove members from their containers before destroying them. (dlehman)
- Make get_container work even if there are duplicate names. (dlehman)
- LVMFactory with a container_raid_level means use LVMOnMDFactory. (dlehman)
- Add a check for enough raid members after allocating partitions. (dlehman)
- Make parent_factory an attribute of the DeviceFactory instance. (dlehman)
- All container settings use container_ kwargs. (dlehman)
- Add ability to find raid level of an lvm vg. (dlehman)
- Always pass -f to wipefs since it lies about in-use devices. (#953329) (dlehman)
- Fix a bug extended partition management. (#951765) (dlehman)
- Don't return incomplete devices from getDeviceByFoo methods by default. (dlehman)
- Don't traceback when degraded md raid arrays are present. (#953184) (dlehman)

* Mon Apr 15 2013 David Lehman <dlehman@redhat.com> - 0.11-1
- Fix handling of isohybrid media. (#950510) (dlehman)
- Fix getting dracut setup args from dasd.conf. (#950964) (dlehman)

* Tue Apr 09 2013 David Lehman <dlehman@redhat.com> - 0.10-1
- Extended partitions containing logical partitions are not leaves. (#949912) (dlehman)
- Remove devices in reverse order in Blivet.recursiveRemove. (#949912) (dlehman)
- Rewrite the DeviceFactory classes. (dlehman)
- Hook up error handling in installer-specific methods. (#948250) (dlehman)
- Don't traceback if fcoe.startup is called without fcoe utils present. (dlehman)
- Fix logic error that causes us to ignore disks in exclusiveDisks. (dlehman)
- Slightly improve currentSize for btrfs volumes. (dlehman)
- Simplify multipath handling. (dlehman)
- Don't expect anaconda udev rules to be in use. (dlehman)
- Drop requires for things only needed for OS installation. (dlehman)
- New version: 0.9 (bcl)
- Only install packages for devices and filesystems used by the OS. (dlehman)
- Fix LVMLogicalVolumeDevice.maxSize. (dlehman)
- Fix handling of name=None in newLV, newMDArray, newVG. (dlehman)
- Allow calls to suggestDeviceName with only a prefix argument. (dlehman)
- Move mdadm superblock size calculation into devicelibs.mdraid. (dlehman)

* Thu Mar 28 2013 Brian C. Lane <bcl@redhat.com> - 0.9-1
- NTFS.minSize is supposed to be a property. (#924410) (dlehman)
- Mount /run during install and fix /sys mount (#922988) (bcl)
- Fix two excptions triggered by calls to copy_to_system. (hamzy)

* Wed Mar 13 2013 David Lehman <dlehman@redhat.com> - 0.8-1
- Check for "ip=ibft" cmdline option, not for "ibft". (rvykydal)
- run_program returns an int. (#920584) (dlehman)
- Fix units for lvs output. (dlehman)
- Don't pass an intf arg to ISCSI.stabilize. (#920041) (dlehman)
- Add __version__ to blivet/__init__.py. (dlehman)
- Only run info prog (eg: dumpe2fs) once per filesystem. (dlehman)
- Processing of a PV with no VG metadata is easy. (dlehman)
- Add some convenience properties for displaying DeviceAction info. (dlehman)
- Ignore MTDs, as we do not have the tools to write to them (#916771). (clumens)
- Include udev's list of symbolic links in StorageDevice. (#914724) (dlehman)
- Set a DeviceFormat instance's type attribute to the requested type. (dlehman)
- Allow size specs that do not include a 'b' or 'B'. (#888851) (dlehman)
- Fix reference to 'factory' from within DeviceFactory class. (dlehman)
- Fix problems detecting lvm and md devices. (#914730) (dlehman)
- Allow passing size=None to device factories for unbounded growth. (dlehman)
- Provide a way to set the default fstype for a Blivet instance. (#838145) (dlehman)
- Allow changing the size of encrypted devices via DeviceFactory. (#913169) (dlehman)
- Don't dump storage state except in installer mode. (dlehman)
- Fix device resolution for btrfs. (dlehman)
- Fix device resolution to find named md devices. (dlehman)
- Account for active mounts in normal mode. (#914898) (dlehman)
- Add an example script which lists all devices. (dlehman)
- Add scripts/makeupdates script (bcl)

* Thu Feb 21 2013 Brian C. Lane <bcl@redhat.com> - 0.7-1
- Merge branch 'master' of git+ssh://git.fedorahosted.org/git/blivet (bcl)
- Bring in productName from pyanaconda in installer mode. (#913559) (dlehman)

* Wed Feb 20 2013 Brian C. Lane <bcl@redhat.com> - 0.6-1
- parse buffer output from resize (#913141) (bcl)
- prevent traceback when root device is not defined #rhbz883768 (sbueno+anaconda)
- Move empty_disk to a top-level function, and rename. (clumens)
- Add some high-level comments to DeviceFactory.configure_device. (dlehman)
- Refactor DeviceFactory.set_container_members for clarity. (dlehman)
- Rename the main blivet logger from "storage" to "blivet". (dlehman)
- Use the blivet domain for translations. (dlehman)
- Move DeviceFactory classes and related code into a new file. (dlehman)
- New version: 0.5 (dlehman)

* Fri Feb 08 2013 David Lehman <dlehman@redhat.com> - 0.5-1
- Add mountOnly to turnOnFilesystems (bcl)
- Update lvm scanning to account for new ignored device handling. (dlehman)
- Scan in all devices and then hide those that use ignored disks. (dlehman)
- Adjust child counts correctly when unhiding a device. (dlehman)
- Generate lvm config args each time they're needed/used. (dlehman)
- Add ability to grab 70-anaconda.rules udev data directly. (dlehman)
- Add support for active luks mappings at populate time. (dlehman)
- Don't require nss, required only for escrow key support. (dlehman)
- Update the TODO list. (dlehman)
- Add missing constant DMI_CHASSIS_VENDOR. (dlehman)
- Allow for multiple calls to DeviceTree.processActions. (#881023,#846573) (dlehman)
- Use CGit snaphot URL for Source in specfile. (dlehman)
- Streamline some logic in storageInitialize. (dlehman)
- Don't re-add deleted or hidden devices during DeviceTree.populate. (dlehman)
- Only run findExistingInstallations and start iscsi, &c in installer mode. (dlehman)
- Do not change device status during populate in normal mode. (#817064) (dlehman)
- Drop old code related to saving clearPartType from pre-f18. (dlehman)
- check for skipping bootloader in doIt (bcl)
- check for stage1 when not installing bootloader (#882065,#895232) (bcl)
- explicitly detect iso9660 on a disk (#903158) (bcl)
- Fix several problems in python-blivet.spec. (dlehman)
- Remove #!/usr/bin/python from tsort.py (dlehman)
- Update COPYING file. (dlehman)
- Add a Requires for dmidecode on x86. (dlehman)

* Sun Jan 20 2013 David Lehman <dlehman@redhat.com> - 0.4-1
- Use a two-part version number instead of three. (dlehman)
- Rename the rpm package from blivet to python-blivet. (dlehman)
- Move get_mount_device, get_mount_paths from pyanaconda.packaging to util. (dlehman)
- Update the TODO list. (dlehman)
- Carry over s390 exclusion of fcoe-utils from anaconda. (dlehman)
- Enable translations via transifex. (dlehman)

* Fri Jan 18 2013 David Lehman <dlehman@redhat.com> - 0.2-1
- Add Requires: iscsi-initiator-utils, fcoe-utils, device-mapper-multipath. (dlehman)
- Use a threading lock to control program log output. (dlehman)
- Fix reference to data to refer to ksdata in Blivet constructor. (dlehman)
- Remove the loop around proc.communicate in util._run_program. (dlehman)

* Tue Jan 15 2013 David Lehman <dlehman@redhat.com> 0.2-1
- Updated source from final pre-split anaconda source.
- Renamed pyanaconda.storage to blivet throughout.
- Updated spec file to include runtime Requires.

* Fri Jan 04 2013 David Lehman <dlehman@redhat.com> 0.1-1
- Created package from anaconda storage module.
