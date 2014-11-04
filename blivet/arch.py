#
# arch.py
#
# Copyright (C) 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2013
# Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author(s): Jeremy Katz <katzj@redhat.com>
#            Paul Nasrat <pnasrat@redhat.com>
#            Peter Jones <pjones@redhat.com>
#            Chris Lumens <clumens@redhat.com>
#            Will Woods <wwoods@redhat.com>
#            Dennis Gilmore <dgilmore@ausil.us>
#            David Marlin <dmarlin@redhat.com>
#
# The absolute_import is needed so that we can
# import the "platform" module from the Python
# standard library but not the local blivet module
# that is also called "platform".
from __future__ import absolute_import

import os

from .flags import flags
from .storage_log import log_exception_info

import logging
log = logging.getLogger("blivet")

# DMI information paths
DMI_CHASSIS_VENDOR = "/sys/class/dmi/id/chassis_vendor"

def getPPCMachine():
    """
    :return: The PPC machine type, or None if not PPC.
    :rtype: string

    """
    if not isPPC():
        return None

    # ppc machine hash
    # Note: This is a substring match!
    ppcType = { 'Mac'      : 'PMac',
                'Book'     : 'PMac',
                'CHRP'     : 'pSeries',
                'CHRP IBM' : 'pSeries', # @TODO the CHRP entry above should match this
                'Pegasos'  : 'Pegasos',
                'Efika'    : 'Efika',
                'iSeries'  : 'iSeries',
                'pSeries'  : 'pSeries',
                'PReP'     : 'PReP',
                'Amiga'    : 'APUS',
                'Gemini'   : 'Gemini',
                'Shiner'   : 'ANS',
                'BRIQ'     : 'BRIQ',
                'Teron'    : 'Teron',
                'AmigaOne' : 'Teron',
                'Maple'    : 'pSeries',
                'Cell'     : 'pSeries',
                'Momentum' : 'pSeries',
                'PS3'      : 'PS3',
                'PowerNV'  : 'pSeries'
                }
    machine = None
    platform = None

    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if 'machine' in line:
                machine = line.split(':')[1]
            elif 'platform' in line:
                platform = line.split(':')[1]

    for part in (machine, platform):
        if part is None:
            continue

        for _type in ppcType.items():
            if _type[0] in part:
                return _type[1]

    log.warning("Unknown PowerPC machine type: %s platform: %s", machine, platform)

    return None

def getPPCMacID():
    """
    :return: The powermac machine type, or None if not PPC or a powermac.
    :rtype: string

    """
    if not isPPC():
        return None
    if getPPCMachine() != "PMac":
        return None

    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if 'machine' in line:
                machine = line.split(':')[1]
                return machine.strip()

    log.warning("No Power Mac machine id")
    return None

def getPPCMacGen():
    """
    :return: The PPC generation, or None if not PPC or a powermac.
    :rtype: string

    """
    # XXX: should NuBus be here?
    # Note: This is a substring match!
    pmacGen = ['OldWorld', 'NewWorld', 'NuBus']

    if not isPPC():
        return None
    if getPPCMachine() != "PMac":
        return None

    gen = None
    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if 'pmac-generation' in line:
                gen = line.split(':')[1]
                break

    if gen is None:
        log.warning("Unable to find pmac-generation")
        return None

    for _type in pmacGen:
        if _type in gen:
            return _type

    log.warning("Unknown Power Mac generation: %s", gen)
    return None

def getPPCMacBook():
    """
    :return: True if the hardware is an iBook or PowerBook, False otherwise.
    :rtype: string

    """
    if not isPPC():
        return False
    if getPPCMachine() != "PMac":
        return False

    #@TBD - Search for 'book' anywhere in cpuinfo? Shouldn't this be more restrictive?
    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if 'book' in line.lower():
                return True

    return False

def isAARCH64():
    """
    :return: True if the hardware supports Aarch64, False otherwise.
    :rtype: boolean

    """
    return os.uname()[4] == 'aarch64'

def getARMMachine():
    """
    :return: The ARM processor variety type, or None if not ARM.
    :rtype: string

    """
    if not isARM():
        return None

    if flags.arm_platform:
        return flags.arm_platform

    armMachine = os.uname()[2].rpartition('.' )[2]

    if armMachine.startswith('arm'):
        # @TBD - Huh? Don't you want the arm machine name here?
        return None
    else:
        return armMachine

def isCell():
    """
    :return: True if the hardware is the Cell platform, False otherwise.
    :rtype: boolean

    """
    if not isPPC():
        return False

    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if 'Cell' in line:
                return True

    return False

def isMactel():
    """
    :return: True if the hardware is an Intel-based Apple Mac, False otherwise.
    :rtype: boolean

    """
    if not isX86():
        mactel = False
    elif not os.path.isfile(DMI_CHASSIS_VENDOR):
        mactel = False
    else:
        buf = open(DMI_CHASSIS_VENDOR).read()
        mactel = ("apple" in buf.lower())
    return mactel

def isEfi():
    """
    :return: True if the hardware supports EFI, False otherwise.
    :rtype: boolean

    """
    # XXX need to make sure efivars is loaded...
    if os.path.exists("/sys/firmware/efi"):
        return True
    else:
        return False

# Architecture checking functions

def isX86(bits=None):
    """:return: True if the hardware supports X86, False otherwise.
    :rtype: boolean
    :param bits: The number of bits used to define a memory address.
    :type bits: int

    """
    arch = os.uname()[4]

    # x86 platforms include:
    #     i*86
    #     athlon*
    #     x86_64
    #     amd*
    #     ia32e
    if bits is None:
        if (arch.startswith('i') and arch.endswith('86')) or \
           arch.startswith('athlon') or arch.startswith('amd') or \
           arch == 'x86_64' or arch == 'ia32e':
            return True
    elif bits == 32:
        if arch.startswith('i') and arch.endswith('86'):
            return True
    elif bits == 64:
        if arch.startswith('athlon') or arch.startswith('amd') or \
           arch == 'x86_64' or arch == 'ia32e':
            return True

    return False

def isPPC(bits=None):
    """
    :return: True if the hardware supports PPC, False otherwise.
    :rtype: boolean
    :param bits: The number of bits used to define a memory address.
    :type bits: int

    """
    arch = os.uname()[4]

    if bits is None:
        if arch in ('ppc', 'ppc64', 'ppc64le'):
            return True
    elif bits == 32:
        if arch in ('ppc'):
            return True
    elif bits == 64:
        if arch in ('ppc64', 'ppc64le'):
            return True

    return False

def isS390():
    """
    :return: True if the hardware supports PPC, False otherwise.
    :rtype: boolean

    """
    return os.uname()[4].startswith('s390')

def isIA64():
    """
    :return: True if the hardware supports IA64, False otherwise.
    :rtype: boolean

    """
    return os.uname()[4] == 'ia64'

def isAlpha():
    """
    :return: True if the hardware supports Alpha, False otherwise.
    :rtype: boolean

    """
    return os.uname()[4].startswith('alpha')

def isARM():
    """
    :return: True if the hardware supports ARM, False otherwise.
    :rtype: boolean

    """
    return os.uname()[4].startswith('arm')

def getArch():
    """
    :return: The hardware architecture
    :rtype: string

    """
    if isX86(bits=32):
        return 'i386'
    elif isX86(bits=64):
        return 'x86_64'
    elif isPPC(bits=32):
        return 'ppc'
    elif isPPC(bits=64):
        # ppc64 and ppc64le are distinct architectures
        return os.uname()[4]
    elif isAARCH64():
        return 'aarch64'
    elif isAlpha():
        return 'alpha'
    elif isARM():
        return 'arm'
    else:
        return os.uname()[4]

def numBits():
    """ Return an integer representing the length
        of the "word" used by the current architecture
        -> it is usually either 32 or 64

        :return: number of bits for the current architecture
        or None if the number could not be determined
        :rtype: integer or None
    """
    try:
        import platform
        nbits = platform.architecture()[0]
        # the string is in the format:
        # "<number>bit"
        # so we remove the bit suffix and convert the
        # number to an integer
        (nbits, _rest) = nbits.split("bit", 1)
        return int(nbits)
    except Exception: # pylint: disable=broad-except
        log_exception_info(log.error, "architecture word size detection failed")
        return None
