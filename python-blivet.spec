Summary:  A python module for system storage configuration
Name: python-blivet
Url: https://storageapis.wordpress.com/projects/blivet
Version: 3.11.0

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
%global libblockdevver 3.3.0
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

%{?python_provide:%python_provide python3-%{realname}}

BuildRequires: gettext
BuildRequires: python3-devel
BuildRequires: python3-setuptools

Requires: python3
Requires: python3-pyudev >= %{pyudevver}
Requires: parted >= %{partedver}
Requires: python3-pyparted >= %{pypartedver}
Requires: libselinux-python3
Requires: python3-libmount
Requires: python3-blockdev >= %{libblockdevver}
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

%build
make

%install
make DESTDIR=%{buildroot} install

%find_lang %{realname}

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
