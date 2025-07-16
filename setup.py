#!/usr/bin/python3

from setuptools import setup


with open("README.md", "r") as f:
    long_description = f.read()


setup(name='blivet',
      version='3.12.1',
      description='Python module for system storage configuration',
      long_description=long_description,
      long_description_content_type="text/markdown",
      author='David Lehman', author_email='dlehman@redhat.com',
      url='http://github.com/storaged-project/blivet',
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
