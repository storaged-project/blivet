#!/usr/bin/python3

import setuptools
from setuptools import setup
from setuptools.command.sdist import sdist
import subprocess
import sys
import os

# this is copied straight from distutils.filelist.findall , but with os.stat()
# replaced with os.lstat(), so S_ISLNK() can actually tell us something.


def findall(dirname=os.curdir):
    from stat import ST_MODE, S_ISREG, S_ISDIR, S_ISLNK

    file_list = []
    stack = [dirname]
    pop = stack.pop
    push = stack.append

    while stack:
        dirname = pop()
        names = os.listdir(dirname)

        for name in names:
            if dirname != os.curdir:        # avoid the dreaded "./" syndrome
                fullname = os.path.join(dirname, name)
            else:
                fullname = name

            # Avoid excess stat calls -- just one will do, thank you!
            stat = os.lstat(fullname)
            mode = stat[ST_MODE]
            if S_ISREG(mode):
                file_list.append(fullname)
            elif S_ISDIR(mode) and not S_ISLNK(mode):
                push(fullname)

    return file_list

setuptools.findall = findall

# Extend the sdist command
class blivet_sdist(sdist):
    user_options = sdist.user_options + [('mode=', None, "specify mode for sdist; one of 'release', 'normal'"),]

    def initialize_options(self):
        sdist.initialize_options(self)
        self.mode = None  # pylint: disable=attribute-defined-outside-init

    def finalize_options(self):
        sdist.finalize_options(self)
        if self.mode not in (None, 'release', 'normal'):
            raise AttributeError('Unknown mode %s' % self.mode)

    def run(self):
        # Build the .mo files
        subprocess.check_call(['make', '-C', 'po'])

        # Run the parent command
        sdist.run(self)

    def make_release_tree(self, base_dir, files):
        # Run the parent command first
        sdist.make_release_tree(self, base_dir, files)

        if self.mode == "release":
            # Run translation-canary in release mode to remove any bad translations
            sys.path.append('translation-canary')
            from translation_canary.translated import testSourceTree  # pylint: disable=import-error
            testSourceTree(base_dir, releaseMode=True)


data_files = [
    ('/etc/dbus-1/system.d', ['dbus/blivet.conf']),
    ('/usr/share/dbus-1/system-services', ['dbus/com.redhat.Blivet0.service']),
    ('/usr/libexec', ['dbus/blivetd']),
    ('/usr/lib/systemd/system', ['dbus/blivet.service'])
]


with open("README.md", "r") as f:
    long_description = f.read()


setup(name='blivet',
      version='3.12.1',
      cmdclass={"sdist": blivet_sdist},
      description='Python module for system storage configuration',
      long_description=long_description,
      long_description_content_type="text/markdown",
      author='David Lehman', author_email='dlehman@redhat.com',
      url='http://github.com/storaged-project/blivet',
      data_files=data_files,
      packages=['blivet', 'blivet.dbus', 'blivet.devices', 'blivet.devicelibs', 'blivet.events', 'blivet.formats', 'blivet.populator', 'blivet.static_data', 'blivet.tasks', 'blivet.populator.helpers'],
      install_requires=['pyudev'],
      classifiers=["Development Status :: 5 - Production/Stable",
                   "Intended Audience :: Developers",
                   "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
                   "Programming Language :: Python :: 3",
                   "Operating System :: POSIX :: Linux"],
      project_urls={"Bug Reports": "https://github.com/storaged-project/blivet/issues",
                    "Source": "https://github.com/storaged-project/blivet",
                    "Changelog": "https://github.com/storaged-project/blivet/blob/main/release_notes.rst",
                    "Documentation": "https://storaged.org/blivet/"}
     )
