Summary:  A python module for system storage configuration
Name: python-blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 0.4
Release: 1%{?dist}
License: GPLv2
Group: System Environment/Libraries
# This is a Red Hat maintained package which is specific to
# our distribution.  Thus the source is only available from
# within this srpm.
%define realname blivet
Source0: %{realname}-%{version}.tar.gz

%define fcoeutilsver 1.0.12-3.20100323git
%define iscsiver 6.2.0.870-3

BuildArch: noarch
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires: python-devel
BuildRequires: gettext
BuildRequires: python-setuptools-devel
BuildRequires: transifex-client

Requires: python
Requires: anaconda
Requires: util-linux >= %{utillinuxver}
Requires: parted >= %{partedver}
Requires: pyparted >= %{pypartedver}
Requires: device-mapper >= %{dmver}
Requires: cryptsetup-luks
Requires: python-cryptsetup >= %{pythoncryptsetupver}
Requires: mdadm
Requires: lvm2
Requires: dosfstools
Requires: e2fsprogs >= %{e2fsver}
Requires: btrfs-progs
%if ! 0%{?rhel}
Requires: hfsplus-tools
%endif
Requires: python-pyblock >= %{pythonpyblockver}
Requires: device-mapper-multipath
%ifnarch s390 s390x
Requires: fcoe-utils >= %{fcoeutilsver}
%endif
Requires: iscsi-initiator-utils >= %{iscsiver}


%description
The python-blivet package is a full-featured python module for examining and modifying storage configuration.

%prep
%setup -q -n %{realname}-%{version}

%build
make

%install
rm -rf %{buildroot}
make DESTDIR=%{buildroot} install
%find_lang %{realname}

%clean
rm -rf %{buildroot}

%files -f %{realname}.lang
%defattr(-,root,root,-)
%doc README ChangeLog COPYING
%{python_sitelib}/*

%changelog
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
