Blivet is a python module for system storage configuration.

### CI status

<img alt="CI status" src="https://fedorapeople.org/groups/storage_apis/statuses/blivet-master.svg" width="100%" height="300ex" />

### License

See [COPYING](https://github.com/storaged-project/blivet/blob/master/COPYING)

### Installation

#### From Fedora repositories

Blivet is available in Fedora repositories. You can install it using

    # dnf install python3-blivet

#### Daily builds for Fedora

Daily builds of Blivet are available in `@storage/blivet-daily` Copr repository.
You can enable it using

    # dnf copr enable @storage/blivet-daily

Daily builds of _libblockdev_ and _libbytesize_ are also in this repo.

#### OBS repository for Ubuntu and Debian

Packages for Debian and Ubuntu are available through the Open Build Service.
Instructions for adding the repository are available [here](https://software.opensuse.org/download.html?project=home:vtrefny&package=python3-blivet).

#### Copr repository for openSUSE, Mageia and OpenMandriva

Packages for openSUSE Tumbleweed, Mageia (8 and newer) and OpenMandriva (Cooker and Rolling) are available in our [blivet-stable Copr repository](https://copr.fedorainfracloud.org/coprs/g/storage/blivet-stable/).

#### PyPI

Blivet is also available through the [Python Package Index](https://pypi.org/project/blivet/).
You can install it using

    $ pip3 install blivet

Blivet depends on some C libraries that are not available on PyPI so you need to install these manually.

The main dependencies include [libblockdev](https://github.com/storaged-project/libblockdev), [libbytesize](https://github.com/storaged-project/libbytesize), parted and their Python bindings.
These libraries should be available on most distributions in the standard repositories.

To install these dependencies use following commands:

 * On Fedora and RHEL/CentOS based distributions:

       # dnf install python3-blockdev libblockdev-plugins-all python3-bytesize libbytesize python3-pyparted parted libselinux-python3
 * On Debian and Ubuntu based distributions:

       # apt-get install python3-blockdev python3-bytesize python3-parted python3-selinux gir1.2-blockdev-3.0 libblockdev-lvm3 libblockdev-btrfs3 libblockdev-swap3 libblockdev-loop3 libblockdev-crypto3 libblockdev-mpath3 libblockdev-dm3 libblockdev-mdraid3 libblockdev-fs3

### Development

See [CONTRIBUTING.md](https://github.com/storaged-project/blivet/blob/main/CONTRIBUTING.md)

Developer documentation is available on our [website](http://storaged.org/blivet/) or on [Read the Docs](https://blivet.readthedocs.io/en/latest/).

Additional information about the release process, roadmap and other development-related materials are also available in the [GitHub Wiki](https://github.com/storaged-project/blivet/wiki).

### Localization

[![Translation](https://translate.fedoraproject.org/widgets/blivet/-/blivet-master/287x66-grey.png)](https://translate.fedoraproject.org/engage/blivet/?utm_source=widget)

### Bug reporting

Bugs should be reported to [bugzilla.redhat.com](https://bugzilla.redhat.com/enter_bug.cgi?product=Fedora&component=python-blivet).

You can also report bug using the [GitHub issues](https://github.com/storaged-project/blivet/issues).
