# fslib.py
# Library to support filesystem classes.
#
# Copyright (C) 2015  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Dave Lehman <dlehman@redhat.com>
#                    David Cantrell <dcantrell@redhat.com>
#                    Anne Mulhern <amulhern@redhat.com>

kernel_filesystems = []
nodev_filesystems = []


def update_kernel_filesystems():
    with open("/proc/filesystems") as filesystems:
        for line in filesystems:
            fields = line.split()
            fstype = fields[-1]
            kernel_filesystems.append(fstype)
            if fields[0] == "nodev":
                nodev_filesystems.append(fstype)


update_kernel_filesystems()
