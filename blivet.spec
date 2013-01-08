# TODO: finalize summary/description text here, in setup.py and in README
Summary:  A python library for working with system storage
Name: blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 0.1
Release: 1%{?dist}
# This is a Red Hat maintained package which is specific to
# our distribution.  Thus the source is only available from
# within this srpm.
Source0: %{name}-%{version}.tar.gz

License: GPLv2
Group: System Environment/Libraries
BuildArch: noarch
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires: python-devel
BuildRequires: gettext
BuildRequires: python-setuptools-devel
BuildRequires: transifex-client
Requires: python
Requires: anaconda
# TODO: add runtime requires

%description
The blivet package is a python module for examining and modifying storage configuration.

%prep
%setup -q

%build
make

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
* Fri Jan 04 2013 David Lehman <dlehman@redhat.com> 0.1-1
- Created package from anaconda storage module.
