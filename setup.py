#!/usr/bin/python2
# pylint: disable=interruptible-system-call

from distutils.core import setup
import subprocess
import sys
import glob
import os
import re

AM_RE = r'(^.. automodule::.+?(?P<mo>^\s+?:member-order:.+?\n)?.+?:\n)\n(?(mo)NEVER)'

def generate_api_docs():
    if subprocess.call(["sphinx-apidoc", "-o", "doc", "blivet"]):
        sys.stderr.write("failed to generate API docs")

def add_member_order_option(files):
    """ Add an automodule option to preserve source code member order. """
    for fn in files:
        buf = open(fn).read()
        amended = re.sub(AM_RE,
                         r'\1    :member-order: bysource\n\n',
                         buf,
                         flags=re.DOTALL|re.MULTILINE)
        open(fn, "w").write(amended)

data_files = []
if os.environ.get("READTHEDOCS", False):
    generate_api_docs()
    rst_files = glob.glob("doc/*.rst")
    add_member_order_option(rst_files)
    api_doc_files = rst_files + ["doc/conf.py"]
    data_files.append(("docs/blivet", api_doc_files))

setup(name='blivet', version='1.12.5',
      description='Python module for system storage configuration',
      author='David Lehman', author_email='dlehman@redhat.com',
      url='http://fedoraproject.org/wiki/blivet',
      data_files=data_files,
      packages=['blivet', 'blivet.devices', 'blivet.devicelibs', 'blivet.formats', 'blivet.tasks'])
