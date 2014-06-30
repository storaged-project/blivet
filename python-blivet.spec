Summary:  A python module for system storage configuration
Name: python-blivet
Url: http://fedoraproject.org/wiki/blivet
Version: 0.59
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
Requires: cryptsetup
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
