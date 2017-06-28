#!/usr/bin/python2

from distutils.core import setup

setup(name='blivet', version='0.61.15.65',
      description='Python module for system storage configuration',
      author='David Lehman', author_email='dlehman@redhat.com',
      url='http://fedoraproject.org/wiki/blivet',
      packages=['blivet', 'blivet.devices', 'blivet.devicelibs', 'blivet.formats'])
