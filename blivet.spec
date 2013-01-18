# TODO: finalize summary/description text here, in setup.py and in README
Summary:  A python library for working with system storage
Name: blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 0.2
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
The blivet package is a python module for examining and modifying storage configuration.

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
* Tue Jan 15 2013 David Lehman <dlehman@redhat.com> 0.2-1
- Updated source from final pre-split anaconda source.
- Renamed pyanaconda.storage to blivet throughout.
- Updated spec file to include runtime Requires.

* Fri Jan 04 2013 David Lehman <dlehman@redhat.com> 0.1-1
- Created package from anaconda storage module.
