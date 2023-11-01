#!/usr/bin/python

# Debian based distributions do not have python3-libmount (and never will). This does manual
# installation of it.
# Requires autopoint and bison packages to work.

from __future__ import print_function

import os
import re
import shutil
import subprocess
import sys
import tempfile

LM_GIT = 'https://github.com/util-linux/util-linux'
LM_CONFIG_CMD = './autogen.sh && ./configure --prefix=/usr ' \
                '--with-python=3 ' \
                '--disable-all-programs --enable-pylibmount ' \
                '--enable-libmount --enable-libblkid'
LM_BUILD_PATH = 'util-linux'


def run_command(command, cwd=None):
    res = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, cwd=cwd)

    out, err = res.communicate()
    if res.returncode != 0:
        output = out.decode().strip() + '\n' + err.decode().strip()
    else:
        output = out.decode().strip()
    return (res.returncode, output)

def get_arch():
    _ret, arch = run_command('uname -p')
    return arch

def get_distro():
    _ret, distro = run_command('cat /etc/os-release | grep ^ID= | cut -d= -f2 | tr -d \"')
    return distro

def main():

    tempname = tempfile.mkdtemp()

    # clone the repo
    print("Cloning '%s' repository into '%s'... " % (LM_GIT, tempname), end='', flush=True)
    ret, out = run_command('git clone --depth 1 %s' % LM_GIT, tempname)
    if ret != 0:
        raise RuntimeError('Cloning libmount failed:\n%s' % out)
    print('Done')

    print("Getting libmount version... ", end='', flush=True)
    ret, out = run_command('mount --version')
    if ret != 0:
        raise RuntimeError('Getting mount version failed:\n%s' % out)

    match = re.match("^.*libmount (.*):.*$", out)
    if not match:
        raise RuntimeError('Getting mount version failed:\n%s' % out)

    libmount_version = 'v'+match.group(1)

    print('Done. (libmount version: %s)' % libmount_version)

    # Python-libmount wrapper is a part of util-linux repo, paths have to be set accordingly.
    # Correct version of the repo has to be checked out as well.

    workpath = os.path.join(tempname, LM_BUILD_PATH, 'libmount')

    print("Fetching tags (takes a minute)... ", end='', flush=True)
    ret, out = run_command('git fetch origin +refs/tags/%s:refs/tags/%s' %
                            (libmount_version, libmount_version), cwd=workpath)
    if ret != 0:
        raise RuntimeError('Fetching tags failed:\n%s' % out)
    print('Done')

    print("Checking out '%s'... " % libmount_version, end='', flush=True)

    ret, out = run_command('git checkout tags/%s -b tag_temp' % libmount_version, cwd=workpath)
    if ret != 0:
        raise RuntimeError("Checking out tag '%s' failed:\n%s" % (libmount_version, out))
    print('Done')

    print("Running configure... ", end='', flush=True)
    ret, out = run_command(LM_CONFIG_CMD, os.path.join(tempname, LM_BUILD_PATH))
    if ret != 0:
        raise RuntimeError('Configure of libmount failed:\n%s' % out)
    print('Done')

    print("Running make & make install... ", end='', flush=True)
    ret, out = run_command('make -j6 && sudo make install', os.path.join(tempname, LM_BUILD_PATH))
    if ret != 0:
        raise RuntimeError('Installing of libmount failed:\n%s' % out)
    print('Done')

    print("Creating symlinks 'site-packages -> dist-packages'... ", end='', flush=True)
    python_ver = '.'.join(sys.version.split('.')[0:2])
    install_dir = '/usr/lib/python%s/site-packages/libmount' % python_ver
    target_dir = '/usr/lib/python%s/dist-packages/libmount' % python_ver
    target_dir_local = '/usr/local/lib/python%s/dist-packages/libmount' % python_ver

    ret1, out1 = run_command('ln -fs %s %s' % (install_dir, target_dir))
    ret2, out2 = run_command('ln -fs %s %s' % (install_dir, target_dir_local))

    # One can/will fail but not both
    if ret1 + ret2 > 1:
        raise RuntimeError('Symlink creation for libmount failed:\n%s\n%s' % (out1, out2))
    print('Done')

    shutil.rmtree(tempname)


if __name__ == '__main__':

    try:
        main()
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    sys.exit(0)
