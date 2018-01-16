#!/usr/bin/python2

from distutils.core import setup
from distutils import filelist
import subprocess
import sys
import glob
import os
import re

# this is copied straight from distutils.filelist.findall , but with os.stat()
# replaced with os.lstat(), so S_ISLNK() can actually tell us something.
def findall(dirname = os.curdir):
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

filelist.findall = findall

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

setup(name='blivet', version='1.20.4',
      description='Python module for system storage configuration',
      author='David Lehman', author_email='dlehman@redhat.com',
      url='http://github.com/rhinstaller/blivet',
      data_files=data_files,
      packages=['blivet', 'blivet.devices', 'blivet.devicelibs', 'blivet.formats', 'blivet.tasks'])
