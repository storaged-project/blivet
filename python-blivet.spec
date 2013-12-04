Summary:  A python module for system storage configuration
Name: python-blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 0.30
Release: 1%{?dist}
License: LGPLv2+
Group: System Environment/Libraries
%define realname blivet
Source0: http://git.fedorahosted.org/cgit/blivet.git/snapshot/%{realname}-%{version}.tar.gz

# Versions of required components (done so we make sure the buildrequires
# match the requires versions of things).
%define dmver 1.02.17-6
%define pykickstartver 1.99.22
%define partedver 1.8.1
%define pypartedver 2.5-2
%define pythonpyblockver 0.45
%define e2fsver 1.41.0
%define pythoncryptsetupver 0.1.1
%define utillinuxver 2.15.1

BuildArch: noarch
BuildRequires: gettext
BuildRequires: python-setuptools-devel

Requires: python
Requires: pykickstart >= %{pykickstartver}
Requires: util-linux >= %{utillinuxver}
Requires: parted >= %{partedver}
Requires: pyparted >= %{pypartedver}
Requires: device-mapper >= %{dmver}
Requires: cryptsetup
Requires: python-cryptsetup >= %{pythoncryptsetupver}
Requires: mdadm
Requires: lvm2
Requires: dosfstools
Requires: e2fsprogs >= %{e2fsver}
Requires: btrfs-progs
Requires: python-pyblock >= %{pythonpyblockver}
Requires: device-mapper-multipath
Requires: lsof

%description
The python-blivet package is a python module for examining and modifying
storage configuration.

%prep
%setup -q -n %{realname}-%{version}

%build
make

%install
rm -rf %{buildroot}
make DESTDIR=%{buildroot} install
%find_lang %{realname}

%files -f %{realname}.lang
%defattr(-,root,root,-)
%doc README ChangeLog COPYING examples
%{python_sitelib}/*

%changelog
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
