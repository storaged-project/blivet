Summary:  A python module for system storage configuration
Name: python-blivet
Url: https://storageapis.wordpress.com/projects/blivet
Version: 3.13.0

#%%global prerelease .b2
# prerelease, if defined, should be something like .a1, .b1, .b2.dev1, or .c2
Release: 1%{?prerelease}%{?dist}
Epoch: 1
License: LGPL-2.1-or-later
%global realname blivet
%global realversion %{version}%{?prerelease}
Source0: http://github.com/storaged-project/blivet/releases/download/%{realname}-%{realversion}/%{realname}-%{realversion}.tar.gz
Source1: http://github.com/storaged-project/blivet/releases/download/%{realname}-%{realversion}/%{realname}-%{realversion}-tests.tar.gz

%if 0%{?rhel} >= 9
Patch0: 0001-remove-btrfs-plugin.patch
%endif

# Versions of required components (done so we make sure the buildrequires
# match the requires versions of things).
%global partedver 1.8.1
%global pypartedver 3.10.4
%global utillinuxver 2.15.1
%global libblockdevver 3.4.0
%global libbytesizever 0.3
%global pyudevver 0.18
%global s390utilscorever 2.31.0

BuildArch: noarch

%description
The python-blivet package is a python module for examining and modifying
storage configuration.

%package -n %{realname}-data
Summary: Data for the %{realname} python module.

BuildRequires: make
BuildRequires: systemd

Conflicts: python-blivet < 1:2.0.0
Conflicts: python3-blivet < 1:2.0.0

%description -n %{realname}-data
The %{realname}-data package provides data files required by the %{realname}
python module.

%package -n python3-%{realname}
Summary: A python3 package for examining and modifying storage configuration.

BuildRequires: gettext
BuildRequires: python3-devel

# For tests
BuildRequires: python3-pyudev >= %{pyudevver}
BuildRequires: parted >= %{partedver}
BuildRequires: python3-pyparted >= %{pypartedver}
BuildRequires: libselinux-python3
BuildRequires: python3-libmount
BuildRequires: python3-blockdev
BuildRequires: python3-bytesize >= %{libbytesizever}
BuildRequires: util-linux >= %{utillinuxver}
BuildRequires: lsof
BuildRequires: python3-gobject-base
BuildRequires: systemd-udev
BuildRequires: libblockdev-plugins-all
BuildRequires: python3-dbus
BuildRequires: python3-pyyaml
BuildRequires: python3-dasbus

Requires: python3-pyudev >= %{pyudevver}
Requires: parted >= %{partedver}
Requires: python3-pyparted >= %{pypartedver}
Requires: libselinux-python3
Requires: python3-libmount
Requires: python3-blockdev >= %{libblockdevver}
Requires: python3-dasbus
Recommends: libblockdev-btrfs >= %{libblockdevver}
Recommends: libblockdev-crypto >= %{libblockdevver}
Recommends: libblockdev-dm >= %{libblockdevver}
Recommends: libblockdev-fs >= %{libblockdevver}
Recommends: libblockdev-loop >= %{libblockdevver}
Recommends: libblockdev-lvm >= %{libblockdevver}
Recommends: libblockdev-mdraid >= %{libblockdevver}
Recommends: libblockdev-mpath >= %{libblockdevver}
Recommends: libblockdev-nvme >= %{libblockdevver}
Recommends: libblockdev-part >= %{libblockdevver}
Recommends: libblockdev-swap >= %{libblockdevver}
Recommends: libblockdev-s390 >= %{libblockdevver}
Recommends: s390utils-core >= %{s390utilscorever}

Requires: python3-bytesize >= %{libbytesizever}
Requires: util-linux >= %{utillinuxver}
Requires: lsof
Requires: python3-gobject-base
Requires: systemd-udev
Requires: %{realname}-data = %{epoch}:%{version}-%{release}

Obsoletes: blivet-data < 1:2.0.0

%description -n python3-%{realname}
The python3-%{realname} is a python3 package for examining and modifying storage
configuration.

%prep
%autosetup -n %{realname}-%{realversion} -N
%autosetup -n %{realname}-%{realversion} -b1 -p1

%generate_buildrequires
%pyproject_buildrequires

%build
make

%install
make DESTDIR=%{buildroot} install

%find_lang %{realname}

%check
%{py3_test_envvars} %{python3} tests/run_tests.py unit_tests

%files -n %{realname}-data -f %{realname}.lang
%{_sysconfdir}/dbus-1/system.d/*
%{_datadir}/dbus-1/system-services/*
%{_libexecdir}/*
%{_unitdir}/*

%files -n python3-%{realname}
%license COPYING
%doc README.md ChangeLog examples
%{python3_sitelib}/*

%changelog
* Fri Oct 03 2025 Vojtech Trefny <vtrefny@redhat.com> - 3.13.0-1
- tests: Skip translation tests if required locales aren't available (vtrefny)
- tests: Select only available libbytesize locales for size tests (vtrefny)
- tests: Move VM tests to StorageTestCase (vtrefny)
- tests: Move partitioning tests that don't need storage to unit tests (vtrefny)
- tests: Move ImageBackedTestCase tests to StorageTestCase (vtrefny)
- misc: Remove custom Vagrantfile (vtrefny)
- tests: Use dasbus in run_tests too (vtrefny)
- spec: Bump required version of libblockdev to 3.4.0 (vtrefny)
- luks: Check for LUKS escrow support separately (vtrefny)
- Do not run Stratis populator on other formats than stratis and LUKS (vtrefny)
- Use dasbus for DBus connections (vtrefny)
- Fix assert in md_test.MDLUKSTestCase (vtrefny)
- Run udev trigger after creating a new MD array (vtrefny)
- Add support for percentage based sizes for thin logical volumes (vtrefny)
- Create helper functions for common code in LVM tests (vtrefny)
- Add tests for percentage based sizes and grow with LVM (vtrefny)
- Use libblockdev for (un)mounting for btrfs operations (vtrefny)
- infra: bump actions/checkout from 4 to 5 (49699333+dependabot[bot])
- ci: Add UDisks iSCSI module to test dependencies (vtrefny)
- ci: Run all tests in Packit (vtrefny)
- tests: Add parameter to allow running CI-only tests too (vtrefny)
- tests: Make sure iscsi-init.service is started for iSCSI tests (vtrefny)
- Add a pre-wipe fixup function for LVM logical volumes (vtrefny)
- Add support for changing label on LUKS format (vtrefny)
- Add support for specifying label and subsystem for LUKS format (vtrefny)
- Fix removing stale LVM metadata on MD with devices file (vtrefny)
- pylint: Ignore some new false positives with the latest pylint (vtrefny)
- tests: Add udev trigger and settle calls after creating DDF array (vtrefny)
- tests: Do not run do_it in DDF MD RAID test (vtrefny)
- Run python build with --no-isolation (vtrefny)
- ci: Do not use setup.py install in anaconda tests (vtrefny)
- Add make target for making a PyPI release (vtrefny)
- Adjust makebumpver script to work with pyproject.toml (vtrefny)
- Run pip install with --no-deps --no-build-isolation in make install (vtrefny)
- spec: Add macros to automatically install build dependencies (vtrefny)
- packit: Add python3-build to SRPM dependencies (vtrefny)
- Move all project definitions from setup.py to pyproject.toml (vtrefny)
- Remove unused targets from Makefile (vtrefny)
- Remove unused custom setuptools.findall method from setup.py (vtrefny)
- Include "dbus" directory in MANIFEST.in (vtrefny)
- Use "pip install" instead of "setup.py install" in Makefile (vtrefny)
- Install DBus config files manually (vtrefny)
- Add a simple pyproject.toml (vtrefny)
- Use "python -m build" instead of setup.py to generate archive (vtrefny)
- setup.py: Remove custom sdist function (vtrefny)
- Group DEVICE_TYPE_* constants in an Enum (a.badger)
- Do not return unittest.skip from test cases (vtrefny)
- Use staticmethod with functools.partial in ObjectID (vtrefny)
- udev: Use the Device.properties API when accessing subsystem (vtrefny)
- Use constructor when creating BlockDev.ExtraArgs (vtrefny)
- Remove the "debug_threads" flag (vtrefny)
- Do not use the "verbose" argument with threading.RLock (vtrefny)
- tests: Fix reading distro and version from CPE version 2.3 (vtrefny)
- Tell LVM DBus to refresh it's internal status during reset (vtrefny)
- Shorten the safe_device_name length to 55 characters (takuya.wakazono)
- Fix creating tests archive during 'make local' (vtrefny)
- Sync spec with downstream (vtrefny)
- tests: Skip test_detect_virt on systems without running DBus (vtrefny)
- Fix getting missing libblockdev technologies with Python 3.14 (vtrefny)
- README update (vtrefny)
- scripts: Remove the git-multi-merge helper script (vtrefny)
- Do not try to destroy "None" formats in recursive_remove (vtrefny)
- tests: Add tests for wiping stale metadata from new partitions (vtrefny)
- Wipe end partition before creating it as well as the start (vtrefny)
- Add some basic partitioning storage tests (vtrefny)
- Protect against broken devices in udev.device_is_nvme_namespace (vtrefny)
- tests: Clarify usage of logdir and logging enabling (vtrefny)
- tests: Add test case for removing broken thin pool (vtrefny)
- tests: Add a simple test case for optional format destroy action (vtrefny)
- Make ActionDestroyFormat optional when device is also removed (vtrefny)
- Allow ActionDestroyFormat to be marked as optional (vtrefny)
- Fix removing stopped stratis pools (vtrefny)
- Add tests for stopping and starting stratis pools (vtrefny)
- Include stopped stratis pools in devicetree (vtrefny)
- Remove stray debug print from devicelibs/stratis (vtrefny)
- Add support for starting stopped stratis pools (vtrefny)
- Add list of stopped pools to stratis static data (vtrefny)
- Do not stop stratis pools before removal (vtrefny)
- Add support for stopping stratis pools (vtrefny)
- Add status property for stratis pools (vtrefny)
- Fix unlocking pools with Stratis 3.8.0 (vtrefny)
- Fix getting list of locked pools with Stratis 3.8.0 (vtrefny)
- tests: Add a simple test case for FS size task (vtrefny)
- Trigger an udev event before getting FS size from udev (vtrefny)
- Get FS size from udev only for filesystems known to be supported (vtrefny)
- udev: Add an option "path" argument to trigger (vtrefny)
- Fix getting filesystem size from udev (vtrefny)
- Fix expected exception type when activating devices in populor (vtrefny)
- tests: Add udev trigger call after creating MD array for tests (vtrefny)
- Fix resolve_device for non-existing btrfs subvolumes (vtrefny)
- ci: Skip the new RAID tests on CentOS/RHEL 9 too (vtrefny)
- tests: Remove code duplication in storage tests setup (vtrefny)
- tests: Limit number of disks created for tests (vtrefny)
- Release notes markup fix (vtrefny)
- tests: Use pbkdf2 for non-LUKS tests with encryption (vtrefny)
- Add test case with RAID re-created outside blivet (vtrefny)
- Drop parted device cache during reset (vtrefny)
- ci: Add exfatprogs to test dependencies (vtrefny)
- Add support for creating ExFAT filesystem (vtrefny)
- Fix handling devices with "no" parents in udev (vtrefny)
- Make FS temporary mounts read-only (vtrefny)
- Fix calling mount without options (vtrefny)
- tests: Limit number of disks created for MD RAID tests (vtrefny)
- tests: Remove stray print from md_test (vtrefny)
- tests: Add test case for MD RAID on top of disks (vtrefny)
- tests: Add test cases for MD RAID with metadata ver 1.0 and 1.1 (vtrefny)
- Adjust LUKS static data to the new context/passphrase API (vtrefny)
- Make "contexts" a property of LUKS format (vtrefny)
- Add note documenting the LUKS key slot contexts usage (vtrefny)
- Add tests for working with LUKS contexts (vtrefny)
- Rework adding and removing keys to/from LUKS (vtrefny)
- Allow removing contexts by setting passphrase or key file to None (vtrefny)
- Add support for using multiple passphrases or key files with LUKS (vtrefny)

* Wed Mar 19 2025 Vojtech Trefny <vtrefny@redhat.com> - 3.12.1-1
- Fix running filesystem sync in installation environment (vtrefny)
- Add a simple test for setting the allow-discards flag on LUKS (vtrefny)
- tests: Add tests for FSTabManager.find_device (vtrefny)
- Fix reading fstab options in FSTabManager.find_device (vtrefny)
- Set persitent allow-discards flag for newly created LUKS devices (vtrefny)
- tests: Run LUKS test cases with both LUKS 1 and 2 (vtrefny)
- iscsi: Use node.startup=onboot option for Login (vtrefny)
- tests: Add a simple test case for generating LUKS escrow packet (vtrefny)
- luks/escrow: Only add backup passphrase when asked to (vtrefny)

* Fri Feb 14 2025 Vojtech Trefny <vtrefny@redhat.com> - 3.12.0-1
- spec: Remove old changelog entries from SPEC file (vtrefny)
- spec: Bump required version of libblockdev to 3.3.0 (vtrefny)
- fstab: Add a simple test to read fstab using our code (vtrefny)
- fstab: Rename "mntops" to "mntopts" (vtrefny)
- tests: Add some more tests for fstab management (vtrefny)
- fstab: Remove the special FSTabOption attribute (vtrefny)
- Do not mark non-existing btrfs subvolumes format as immutable (vtrefny)
- misc: Update Vagrantfile (vtrefny)
- misc: Add python3-yaml to test dependencies (vtrefny)
- fstab: Fix appending options to an existing fstab entry (vtrefny)
- fstab: Fix setting freq and passno for devices (vtrefny)
- fstab: Fix defaults for fs_freq and fs_passno (vtrefny)
- fstab: Fix setting default mount options for entry (vtrefny)
- fstab: Fix setting mount options for devices (vtrefny)
- fstab: Accept mount options passed as string (vtrefny)
- fstab: Set target/mountpoint for swaps to "none" (vtrefny)
- lvm: Add a function to disable and enable LVM auto-activation (vtrefny)
- lvm: Check lvm.conf for auto-activation support (vtrefny)
- Revert "Remove support for the MD linear RAID level" (vtrefny)
- ci: Manually download blivet-gui playbooks for revdeps tests (vtrefny)
- misc: Separate Ansible tasks into a different file (vtrefny)
- Include additional information in PartitioningError (vtrefny)
- Fix BitLocker format status and allow closing active BITLK devices (vtrefny)
- Add a separate test case for LVMPV smaller than the block device (vtrefny)
- Add more tests for PV and VG size and free space (vtrefny)
- Use LVMPV format size when calculating VG size and free space (vtrefny)
- Update PV format size after adding/removing the PV to/from the VG (vtrefny)
- Get the actual PV format size for LVMPV format (vtrefny)
- Use pvs info from static data to get PV size in PVSize (vtrefny)
- Do not remove PVs from devices file if disabled or doesn't exists (vtrefny)
- Protect against exceptions when getting properties from udev (vtrefny)
- Use name as device ID for BIOS RAID arrays (#2335009) (vtrefny)
- ci: Bump Ubuntu version for Anaconda tests to 24.04 (vtrefny)
- ci: Use rpm instead of dnf to remove blivet in Anaconda tests (vtrefny)
- ci: Change branch for Anaconda tests from 'master' to 'main' (vtrefny)
- Use just name as device ID for multipath devices (#2327619) (vtrefny)
- Ignore errors when setting multipath friendly names (vtrefny)
- Do not crash when we fail to get discoverable GPT type UUID (vtrefny)
- Fix ppc64le name in devicelibs/gpt.py (vtrefny)
- Make GPT default label type on all architectures (vtrefny)
- Get filesystem size from udev database (vtrefny)
- Fix running unit tests without root privileges (vtrefny)
- Do not crash when libblockdev LVM plugin is not available (vtrefny)
- tests: Fix writing key file for LUKS tests (vtrefny)
- Fix "Modified passphrase in stratis test" (vtrefny)
- Translate vendor id 0x1af4 to Virtio Block Device (#1242117) (bcl)
- Allow setting parted partition flags using ActionConfigureDevice (vtrefny)
- tests: Allow specifying number of disks needed for StorageTestCase (vtrefny)
- Fix error message in StorageDevice._set_size (vtrefny)
- Add some more verbose logs around LUKS size changes (vtrefny)
- Align sizes up for growable LVs (vtrefny)
- Fix looking for the latests tag in makeupdates script (vtrefny)
- misc: Add libblockdev-tools to test dependencies (vtrefny)
- fs: Add support for resizing FAT filesystem (vtrefny)
- fs: Add suport for getting VFAT filesystem info and size (vtrefny)
- Don't crash in populate when blockdev plugins are missing (dlehman)
- Add blockdev dependency guards for populator (dlehman)
- Modified passphrase in stratis test (japokorn)
- ci: Store blivet logs from the test run (vtrefny)
- tests: Allow enabling logging when running tests (vtrefny)
- tests: Do not set logging when loading gpt_test (vtrefny)
- General protection against tracebacks during populate. (dlehman)
- Base UnusableConfigurationError on DeviceTreeError. (dlehman)
- Allow duplicate UUIDs until/unless a by-uuid query occurs. (dlehman)
- DASDDevice: dracut_setup_args() without deprecated dasd.conf (#1802482,#1937049) (maier)
- respect explicit user choice for full path in zfcp dracut_setup_args (maier)
- blivet/zfcp: remove no longer used read_config functionality (#1802482,#1937049) (maier)
- blivet/zfcp: change to consolidated persistent device config by zdev (#1802482,#1937049) (maier)
- blivet/zfcp: drop old zfcp port handling gone from the kernel long ago (maier)
- blivet/zfcp: remove code broken since zfcp automatic LUN scan (maier)
- blivet/zfcp: drop modprobe alias, which is superfluous since udev in RHEL6 (maier)
- spec: Fix dependency on libblockdev-s390 (vtrefny)
- free_space_estimate: adjust for compression on btrfs (awilliam)
- Sync spec with downstream (vtrefny)
- Do not raise libblockdev errors in FSMinSize tasks (#2314637) (vtrefny)
- ci: Remove amazon-ec2-utils when running tests in AWS (vtrefny)
- ci: Install 'python3-libdnf5' for TMT test plans (vtrefny)
- packit: Switch tests to the latest branched Fedor (now Fedora 41) (vtrefny)
- makeupdates: Ignore that getopt is deprecated (vtrefny)
- release_notes: Fix links (vtrefny)
- setup.py: Add some project URLs (vtrefny)
- spec: Update sources URL (vtrefny)
- Ignore partitions on disks without parted disk (vtrefny)

* Fri Sep 20 2024 Vojtech Trefny <vtrefny@redhat.com> - 3.11.0-1
- Fix checking for NVMe plugin availability (vtrefny)
- packit: Add upstream_tag_template (vtrefny)
- packit: Bump release only for daily builds not for regular builds (vtrefny)
- Makefile: Create just one tag for the release (vtrefny)
- CONTRIBUTING: Add a short note about RHEL branches and development (vtrefny)
- Fix spelling issues found by codespell and spellintian (vtrefny)
- ci: Fix some copy-paste errors in CI job descriptions (vtrefny)
- packit: Add tmt tests for rhel10-branch running on C10S (vtrefny)
- packit: Add RPM build for pull requests against the rhel10-branch (vtrefny)
- ci: Limit running Anaconda tests to 'main' branch only (vtrefny)
- packit: Limit Fedora builds and tests to the 'main' branch (vtrefny)
- ci: Add a GH action to run static analysis on CentOS 10 Stream (vtrefny)
- dm: Remove unused code (vtrefny)
- misc: Add support for installing dependencies on CentOS 1O Stream (vtrefny)
- tests: Change expected Stratis metadata size for stratisd 3.7.0 (vtrefny)
- Disable the "testdata" logging (vtrefny)
- Log reason for ignoring disks in devicefactory (vtrefny)
- Add partition type human-readable string to PartitionDevice (vtrefny)
- spec: Bump required version of libblockdev to 3.2.0 (vtrefny)
- ci: Bump Ubuntu in GitHub actions to 24.04 (vtrefny)
- ci: Update branches in GitHub actions (vtrefny)
- Remove TODO list from the repository (vtrefny)
- Update CONTRIBUTING with the new branching and release model (vtrefny)
- ci: Add Packit configuration for downstream builds on release (vtrefny)
- packit: Set branch for Copr builds to "main" (vtrefny)
- Fix intel biosraid can't get device name causing crashed (yurii.huang)
- Fix getting LUKS subsystem for existing LUKS formats (vtrefny)
- ci: Remove priority from Testing farm repositories (vtrefny)
- Rename "opal_passphrase" to "opal_admin_passphrase" (vtrefny)
- Add support for creating LUKS HW-OPAL devices (vtrefny)
- Mark existing LUKS HW-OPAL formats as protected (vtrefny)
- devices: catch exceptions where invalid access happens first (kkoukiou)
- Allow marking formats as protected (vtrefny)
- Add support for recognizing LUKS HW-OPAL devices (vtrefny)
- README: Remove mentions about supported Ubuntu and Debian versions (vtrefny)
- Use correct LUKS metadata size for LUKS 2 (vtrefny)
- part_type_uuid: guard against pyparted type_uuid being None (awilliam)
- Fix checking for FS min size application availability (vtrefny)
- blivet fstab method change (japokorn)
- tests: Add a test case for BTRFS device factory (vtrefny)
- Preserve mount options when renaming btrfs factory device (vtrefny)
- Fix device factory example (vtrefny)
- Fix passing extra mkfs options for btrfs volumes (#2036976) (vtrefny)
- tests: Remove logging from LVMTestCase (vtrefny)
- devicetree: resolve devices also with the PARTUUID=.. naming (kkoukiou)
- spec: Bump required version of libblockdev to 3.1.0 (vtrefny)
- tasks: Use libblockdev for the fsminsize task (vtrefny)
- Make sure ignored and exclusive disks work with device IDs too (vtrefny)
- tests: Make sure selinux_test doesn't try to create mountpoints (vtrefny)
- infra: bump actions/upload-artifact from 2 to 4 (49699333+dependabot[bot])
- infra: Add dependabot to automatically update GH actions (vtrefny)
- Fix skipping MD tests on CentOS 9 (vtrefny)
- ci: Remove GH action to run blivet-gui tests (vtrefny)
- tests: Try waiting after partition creation for XFS resize test (vtrefny)
- Set log level to INFO for libblockdev (vtrefny)
- Run mkfs.xfs with the force (-f) option by default (vtrefny)
- ci: Disable the Blivet-GUI test case by default (vtrefny)
- ci: Add a simple tmt test and run it via packit (vtrefny)
- ci: Run Blivet-GUI reverse dependency tests on pull requests (vtrefny)
- TFT is still broken so let's avoid failures by just doing a build (jkonecny)
