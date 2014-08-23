Summary:  A python module for system storage configuration
Name: python-blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 0.18.37
Release: 1%{?dist}
License: LGPLv2+
Group: System Environment/Libraries
%define realname blivet
Source0: http://github.com/dwlehman/blivet/archive/%{realname}-%{version}.tar.gz

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
%define lvm2ver 2.02.99

BuildArch: noarch
BuildRequires: gettext
BuildRequires: python-setuptools-devel

Requires: python
Requires: pykickstart >= %{pykickstartver}
Requires: util-linux >= %{utillinuxver}
Requires: parted >= %{partedver}
Requires: pyparted >= %{pypartedver}
Requires: device-mapper >= %{dmver}
Requires: cryptsetup-luks
Requires: python-cryptsetup >= %{pythoncryptsetupver}
Requires: mdadm
Requires: lvm2 >= %{lvm2ver}
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
* Fri Aug 22 2014 Brian C. Lane <bcl@redhat.com> - 0.18.37-1
- Make missing encryption key error message more helpful (amulhern)
  Resolves: rhbz#1074441
- Only log a warning about labeling if something is wrong (amulhern)
  Resolves: rhbz#1075136

* Fri Aug 01 2014 Brian C. Lane <bcl@redhat.com> - 0.18.36-1
- Do not limit ThinLV's size to VG's free space (vpodzime)
  Resolves: rhbz#1100772
- Split ROOT_PATH usage into getTargetPhysicalRoot()/getSysroot() (walters)
  Related: rhbz#1113535

* Fri Jul 25 2014 Brian C. Lane <bcl@redhat.com> - 0.18.35-1
- Added a i18n module for gettext functions. (dshea)
  Resolves: rhbz#1079440
- Multiple arguments for string formatting need to be in parentheses (mkolman)
  Resolves: rhbz#1100263

* Fri Mar 21 2014 Brian C. Lane <bcl@redhat.com> - 0.18.34-1
- Force removal of hidden devices (amulhern)
  Resolves: rhbz#1078163

* Tue Mar 18 2014 Brian C. Lane <bcl@redhat.com> - 0.18.33-1
- fcoe: add sleep for dcbtool command (rvykydal)
  Related: rhbz#1039223
- Add a PE for LUKS metadata (bcl)
  Resolves: rhbz#1076078

* Fri Mar 07 2014 Brian C. Lane <bcl@redhat.com> - 0.18.32-1
- Resolve md names in udev_resolve_devspec. (dlehman)
  Related: rhbz#1047338
- Fix an old typo in zeroing out a PReP partition. (dlehman)
  Resolves: rhbz#1072781
- Use container's parent's name for PV if available (vpodzime)
  Resolves: rhbz#1065737
- Limit the LV size to VG's free space size (vpodzime)
  Related: rhbz#1072999
- Only count with the extra metadata extents in new VGs and LVs (vpodzime)
  Resolves: rhbz#1072999

* Wed Mar 05 2014 Brian C. Lane <bcl@redhat.com> - 0.18.31-1
- Fix traceback with write_dasd_conf. (sbueno+anaconda)
  Resolves: rhbz#1072911

* Tue Mar 04 2014 Brian C. Lane <bcl@redhat.com> - 0.18.30-1
- When copying a root, also copy hidden devices (amulhern)
  Related: rhbz#1043763
- Add hidden flag to devicetree.getDeviceByID (amulhern)
  Resolves: rhbz#1043763
- Only set device for mountpoint if it is not None (amulhern)
  Related: rhbz#1043763
- Extend the list of things to be omitted if moddisk is False (amulhern)
  Related: rhbz#1043763
- Set req_name to None at the top of initializer (amulhern)
  Related: rhbz#1043763
- Log action cancelation (amulhern)
  Resolves: rhbz#1043763
- Make DeviceTree.hide() remove a larger set (amulhern)
  Related: rhbz#1043763
- Find more used devices when calculating unused devices (dlehman)
  Related: rhbz#1043763
- Re-write the DASD storage code. (sbueno+anaconda)
  Resolves: rhbz#1001070
- Include image install flag when updating from anaconda flags. (dlehman)
  Resolves: rhbz#1066008

* Wed Feb 26 2014 Brian C. Lane <bcl@redhat.com> - 0.18.29-1
- Let the udev queue settle before populating the devicetree. (dlehman)
  Resolves: rhbz#1049772
- Allow use of a single path if multipath activation fails. (dlehman)
  Resolves: rhbz#1054806

* Tue Feb 25 2014 Brian C. Lane <bcl@redhat.com> - 0.18.28-1
- Count with the extra metadata extents for RAID consistently (vpodzime)
  Resolves: rhbz#1065737
- Make partitioning error message more friendly (amulhern)
  Resolves: rhbz#1020388

* Fri Feb 21 2014 Brian C. Lane <bcl@redhat.com> - 0.18.27-1
- Leave already-active devices up after destroying formatting. (dlehman)
  Resolves: rhbz#1064898
- Fix partition handling across multiple processActions calls. (dlehman)
  Resolves: rhbz#1065522
- return empty set when no matching fcoe nic (bcl)
  Resolves: rhbz#1067159
- Include tmpfs mounts in post-install kickstart (mkolman)
  Resolves: rhbz#1061063

* Wed Feb 19 2014 Brian C. Lane <bcl@redhat.com> - 0.18.26-1
- Add a coverage test target (amulhern)
  Resolves: rhbz#1064895
- Disable tests in action_test.py (amulhern)
  Resolves: rhbz#1065437
- Fix some problems with action_test.py (amulhern)
  Related: rhbz#1065437
- Update tests/storagetestcase.py (amulhern)
  Related: rhbz#1065437
- Skip a test if device isn't available (amulhern)
  Related: rhbz#1065431
- Fix failing udev_test (amulhern)
  Resolves: rhbz#1065431
- Fix some size_test.py ERRORs (amulhern)
  Resolves: rhbz#1065443
- Filesystem labeling tests will not run without utilities (amulhern)
  Resolves: rhbz#1065422
- Rename misc_test.py to something more descriptive (amulhern)
  Related: rhbz#1065422
- Refactor labeling tests (amulhern)
  Related: rhbz#1065422
- Move SwapSpace tests into a separate class (amulhern)
  Resolves: rhbz#1065422

* Tue Feb 18 2014 Brian C. Lane <bcl@redhat.com> - 0.18.25-1
- Wait for udev to create device node for new md arrays. (dlehman)
  Resolves: rhbz#1036014
- Fix detection of thin pool with non-standard segment types. (dlehman)
  Resolves: rhbz#1029915
- NFSDevice does not accept the exists kwarg. (dlehman)
  Resolves: rhbz#1063413
- Don't run mpathconf for disk image installations. (dlehman)
  Resolves: rhbz#1066008

* Tue Feb 11 2014 Brian C. Lane <bcl@redhat.com> - 0.18.24-1
- Separate sanityCheck-ing from doAutoPartition (amulhern)
  Related: rhbz#1060255
- Change messages to SanityExceptions objects (amulhern)
  Related: rhbz#1060255
- Make a small SanityException hierarchy (amulhern)
  Related: rhbz#1060255
- Remove unused exception class (amulhern)
  Related: rhbz#1060255
- Add a test target to Makefile (amulhern)
  Resolves: rhbz#1057665

* Tue Feb 04 2014 Brian C. Lane <bcl@redhat.com> - 0.18.23-1
- Remove all dependent devices of san device becoming multipath (rvykydal)
  Resolves: rhbz#1058939
- When repopulating multipath members mark them as multipath (rvykydal)
  Resolves: rhbz#1056024
- Don't add None value to req_disks (amulhern)
  Resolves: rhbz#981316
- Make error message more informative (amulhern)
  Resolves: rhbz#1022497
- fcoe: parse yet another sysfs structure for bnx2fc devices (rvykydal)
  Related: rhbz#903122

* Fri Jan 31 2014 Brian C. Lane <bcl@redhat.com> - 0.18.22-1
- Check that file that loop device is going to use exists (amulhern)
  Resolves: rhbz#982164
  Related: rhbz#982164
- Use os.path.isabs to check whether path name is absolute (amulhern)
  Resolves: rhbz#994488
  Related: rhbz#994488

* Tue Jan 28 2014 Brian C. Lane <bcl@redhat.com> - 0.18.21-1
- escrow: make sure the output directory exists (wwoods)
  Resolves: rhbz#1026653

* Mon Jan 27 2014 David Lehman <dlehman@redhat.com> - 0.18.20-1
- Tell lvcreate not to ask us any questions and do its job. (dlehman)
  Resolves: rhbz#1057066
- Some simple tests for _verifyLUKSDevicesHaveKey (amulhern)
  Related: rhbz#1023442
  Resolves: rhbz#1023442
- Verify that LUKS devices have some encryption key (amulhern)
  Resolves: rhbz#1023442
- Make the maximum end sector for PReP boot more benevolent (vpodzime)
  Resolves: rhbz#1041535

* Wed Jan 22 2014 Brian C. Lane <bcl@redhat.com> - 0.18.19-1
- Only do SELinux context resets if in installer mode (amulhern)
  Related: rhbz#1038146
  Resolves: rhbz#1038146
- Look up SELinux context for lost+found where it is needed (amulhern)
  Resolves: rhbz#1038146
- Don't reset the SELinux context before the filesystem is mounted (amulhern)
  Related: rhbz#1038146
  Resolves: rhbz#1038146
- Test setting selinux context on lost+found (amulhern)
  Related: rhbz#1038146
  Resolves: rhbz#1038146
- fcoe: add fcoe=<NIC>:<EDB> to boot options for nics added manually (rvykydal)
  Related: rhbz#1040215
- Only retrieve the unit specifier once (dshea)
  Related: rhbz#1039485
- Accept both English and localized sizes in Size specs. (dshea)
  Related: rhbz#1039485
- Use a namedtuple to store information on unit prefixes (dshea)
  Related: rhbz#1039485
- Catch any exception raised by findExistingInstallations. (dlehman)
  Resolves: rhbz#1052454
- Multipath, fwraid members need not be in exclusiveDisks. (dlehman)
  Resolves: rhbz#1032919

* Mon Jan 20 2014 Brian C. Lane <bcl@redhat.com> - 0.18.18-1
- Fall back on relabeling app where available (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Change the meaning of label field values (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Enable labeling on NTFS filesystem (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Enable labeling on HFS filesystem (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Add a method that indicates ability to relabel (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Use filesystem creation app to set filesystem label (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Import errors so FSError name is resolved (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Remove BTRFS._getFormatOptions (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Make an additional class for labeling abstractions (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Fix copyright date (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Remove redundant _defaultFormatOptions field (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Remove code about unsetting a label (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Return None if the filesystem has no label (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Removed redundant check for existance of filesystem (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Have writeLabel throw a more informative exception (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Clear whole-disk formatting before initializing disks. (dlehman)
  Resolves: rhbz#1052442

* Fri Jan 17 2014 Brian C. Lane <bcl@redhat.com> - 0.18.17-1
- Simplify calculation of vol size when adding a btrfs subvol. (dlehman)
  Resolves: rhbz#1052439
- Preparation for lv resize is a subset of that for lv destroy. (dlehman)
  Resolves: rhbz#1029634

* Thu Jan 16 2014 Brian C. Lane <bcl@redhat.com> - 0.18.16-1
- iscsi: in installer automatically log into firmware iscsi targets (rvykydal)
  Resolves: rhbz#1034291

* Tue Jan 14 2014 Brian C. Lane <bcl@redhat.com> - 0.18.15-1
- Allow resetting partition size to current on-disk size. (dlehman)
  Related: rhbz#918454
  Related: rhbz#1029630
- Fix shouldClear for devices with protected descendants. (dlehman)
  Resolves: rhbz#902417
- Handle nested btrfs subvolumes correctly. (dlehman)
  Related: rhbz#1026210
- Devices with non-existent formatting are resizable. (dlehman)
  Resolves: rhbz#1029633
- Always run action's cancel method as part of cancelAction. (dlehman)
  Related: rhbz#1029630
- Do not hide non-existent devices. (dlehman)
  Resolves: rhbz#1029628
- Fix handling of overcommitted thin pools in thinp factory. (dlehman)
  Resolves: rhbz#1027376
- Fix name checking for new thin lvs. (dlehman)
  Resolves: rhbz#1027375

* Fri Jan 10 2014 Brian C. Lane <bcl@redhat.com> - 0.18.14-1
- Move label setter and getter into DeviceFormat class (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Add a test for labeling swap devices (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Default to None to mean none, rather than empty string (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Add a labelFormatOK method to the DeviceFormat's interface (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Indicate whether the filesystem can label (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Restore ability to write an empty label where possible (amulhern)
  Resolves: rhbz#1038590
- More tests to check writing and reading labels (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Remove fsConfigFromFile (amulhern)
  Related: rhbz#1038590
  Resolves: rhbz#1038590
- Changes to the handling of filesystem labeling (amulhern)
  Resolves: rhbz#1038590
- Forget existing partitions of device becoming a multipath member (rvykydal)
  Resolves: rhbz#1043444
  Related: rhbz#1043444

* Tue Dec 17 2013 Brian C. Lane <bcl@redhat.com> - 0.18.13-1
- Add initial 64-bit ARM (aarch64) support (dmarlin)
  Resolves: rhbz#1034435
- Make error message in setDefaultFSType more informative (amulhern)
  Resolves: rhbz#1019766
  Related: rhbz#1019766
- Set sysfsPath of LUKSDevice when adding to device tree (jsafrane)
  Resolves: rhbz#1019638

* Mon Dec 16 2013 Brian C. Lane <bcl@redhat.com> - 0.18.12-1
- Change XFS maximum to 16EB (bcl)
  Resolves: rhbz#1016035
- fcoe: give error message in case of fail when adding device (rvykydal)
  Related: rhbz#903122
  Resolves: rhbz#903122
- fcoe: adapt bnx2fc detection to changed sysfs path structure (rvykydal)
  Related: rhbz#903122
  Resolves: rhbz#903122
- Update format of iscsi device becoming multipath member (rvykydal)
  Resolves: rhbz#1039086

* Thu Nov 14 2013 David Lehman <dlehman@redhat.com> - 0.18.11-1
- Fix detection of lvm setups. (dlehman)
  Resolves: rhbz#1026468

* Mon Nov 11 2013 Brian C. Lane <bcl@redhat.com> - 0.18.10-1
- Add tmpfs support (mkolman)
  Related: rhbz#918621
- Add support for returning machine word length (mkolman)
  Related: rhbz#918621

* Wed Oct 30 2013 Brian C. Lane <bcl@redhat.com> - 0.18.9-1
- Update parted partitions on hidden disks when copying a Blivet. (dlehman)
  Resolves: rhbz#1023583

* Fri Oct 25 2013 Brian C. Lane <bcl@redhat.com> - 0.18.8-1
- Remove requirement for btrfsctl which no longer exists. (dlehman)
  Resolves: rhbz#1023192
- Allow for adjustment of factory vg after removal of thin pool. (dlehman)
  Resolves: rhbz#1023186
- Add boot description for "disk" devices on s390. (sbueno+anaconda)
  Resolves: rhbz#867777
  Resolves: rhbz#960143
  Resolves: rhbz#903237

* Thu Oct 17 2013 Brian C. Lane <bcl@redhat.com> - 0.18.7-1
- Handle anaconda's cmdline option to disable mpath friendly names. (#977815) (dlehman)
  Related: rhbz#977815
- Close file descriptors other than stdin,stdout,stderr on exec. (#1020013) (dlehman)
  Resolves: rhbz#1020013
- Don't use hardcoded /tmp paths. (#1004404) (dlehman)
  Resolves: rhbz#1004404
- Fix detection of lvm thinp setups. (#1016842) (dlehman)
  Resolves: rhbz#1016842
- Generate a name if necessary when reconfiguring a factory device. (#1009941) (dlehman)
  Resolves: rhbz#1009941

* Mon Oct 14 2013 Brian C. Lane <bcl@redhat.com> - 0.18.6-1
- Do not limit swap size to 10 % of disk space for hibernation (vpodzime)
Related: rhbz#1016673
- Limit the maximum swap size to 10 % of disk space (if given) (vpodzime)
Related: rhbz#1016673

* Wed Oct 09 2013 Brian C. Lane <bcl@redhat.com> - 0.18.5-1
- Make sure bootloader is setup after autopart (#1015277) (bcl)
- Let setUpBootLoader raise BootloaderError (#1015277) (bcl)
- Support ppc64le architecture (#1012519) (hamzy)

* Fri Sep 06 2013 David Lehman <dlehman@redhat.com> - 0.18.4-1
- If a device has been removed, omit it from the copied root. (#1004572) (dlehman)
- Fix handling of devices in detected installations in Blivet.copy. (dlehman)
- Allow implicit inclusion of multipath/fwraid by including all members. (dlehman)
- Thinp metadata and chunk size default to 0 -- not None. (#1004718) (dlehman)
- Revert "Do not try to align partitions to optimal_io_size. (#989333)" (dlehman)

* Wed Sep 04 2013 Brian C. Lane <bcl@redhat.com> - 0.18.3-1
- Fix rpmlog make target (bcl)
- Only force luks map names to include UUID during OS installation. (#996457) (dlehman)
- Allow DiskLabelCommitError to reach the caller. (#1001586) (dlehman)
- Do not try to align partitions to optimal_io_size. (#989333) (gustavold)
- Pass mount options to resolveDevice in _parseOneLine (#950206) (vpodzime)
- Clean up detection of lvm raid. (dlehman)
- Tag the first build of each version without the release. (dlehman)
- Allow explicit requests for extended partitions. (#891861) (dlehman)
- Fix disklabel handling for multiple calls to processActions. (dlehman)
- Add support for explicit start/end sectors in partition requests. (#881025) (dlehman)
- Store current mount options in getActiveMounts. (#914898) (dlehman)
- Lack of formatting does not preclude device resize. (dlehman)
- Don't pass dracut args for lvm thin pools. (dlehman)

* Fri Aug 23 2013 Brian C. Lane <bcl@redhat.com> - 0.18.2-1
- Use iscsi-iname instead of trying to reimplemnt it in python. (dlehman)
- Catch exceptions raised while finding old installations. (#981991) (dlehman)
- Keep the dasd list in sync with the devicetree's device list. (#965694) (dlehman)
- Don't save luks keys unless installer_mode flag is set. (#996118) (dlehman)
- transifex-client isn't used for rhel7 (bcl)

* Mon Jul 29 2013 Brian C. Lane <bcl@redhat.com> - 0.18.1-1
- Branch for rhel7
- Update Makefile for rhel7 x.y.z release numbering

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
