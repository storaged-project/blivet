Summary:  A python module for system storage configuration
Name: blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 0.3
Release: 1%{?dist}
License: GPLv2
Group: System Environment/Libraries
# This is a Red Hat maintained package which is specific to
# our distribution.  Thus the source is only available from
# within this srpm.
Source0: %{name}-%{version}.tar.gz

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
Requires: fcoe-utils >= %{fcoeutilsver}
Requires: iscsi-initiator-utils-devel >= %{iscsiver}


%description
The blivet package is a full-featured python module for examining and modifying storage configuration.

%prep
%setup -q

%build
#make

%install
rm -rf %{buildroot}
make DESTDIR=%{buildroot} install
%find_lang %{name}

%clean
rm -rf %{buildroot}

%files -f %{name}.lang
%defattr(-,root,root,-)
%doc README ChangeLog COPYING
%{python_sitelib}/*

%changelog
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
