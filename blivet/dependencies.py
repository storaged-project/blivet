
import abc
import gi
import six

gi.require_version("BlockDev", "2.0")
from gi.repository import BlockDev as blockdev

from .util import DependencyGuard


@six.add_metaclass(abc.ABCMeta)
class BlockDevDependencyGuard(DependencyGuard):
    _tech = abc.abstractproperty(doc="BlockDev tech list")
    _mode = abc.abstractproperty(doc="BlockDev tech mode")
    _is_tech_avail = abc.abstractproperty(doc="BlockDev tech check method")

    def _check_avail(self):
        try:
            return all(self.__class__._is_tech_avail(tech, self.__class__._mode) for tech in self.__class__._tech)
        except blockdev.BlockDevNotImplementedError:  # pylint: disable=catching-non-exception
            return False


class DMDependencyGuard(BlockDevDependencyGuard):
    error_msg = "libblockdev device-mapper functionality not available"
    _tech = [blockdev.DMTech.MAP]
    _mode = blockdev.DMTechMode.QUERY
    _is_tech_avail = blockdev.dm.is_tech_avail

blockdev_dm_required = DMDependencyGuard()


class DMRaidDependencyGuard(DMDependencyGuard):
    error_msg = "libblockdev dmraid functionality not available"
    _tech = [blockdev.DMTech.RAID]

blockdev_dmraid_required = DMRaidDependencyGuard()


class LoopDependencyGuard(BlockDevDependencyGuard):
    error_msg = "libblockdev loop functionality not available"
    _tech = [blockdev.LoopTech.LOOP_TECH_LOOP]
    _mode = blockdev.LoopTechMode.QUERY
    _is_tech_avail = blockdev.loop.is_tech_avail

blockdev_loop_required = LoopDependencyGuard()


class LUKSDependencyGuard(BlockDevDependencyGuard):
    error_msg = "libblockdev LUKS functionality not available"
    _tech = [blockdev.CryptoTech.LUKS]
    _mode = blockdev.CryptoTechMode.QUERY
    _is_tech_avail = blockdev.crypto.is_tech_avail

blockdev_luks_required = LUKSDependencyGuard()


class LVMDependencyGuard(BlockDevDependencyGuard):
    error_msg = "libblockdev LVM functionality not available"
    _tech = [blockdev.LVMTech.BASIC,
             blockdev.LVMTech.BASIC_SNAP,
             blockdev.LVMTech.THIN,
             blockdev.LVMTech.CACHE,
             blockdev.LVMTech.CALCS,
             blockdev.LVMTech.THIN_CALCS,
             blockdev.LVMTech.CACHE_CALCS,
             blockdev.LVMTech.GLOB_CONF]
    _mode = blockdev.LVMTechMode.QUERY
    _is_tech_avail = blockdev.lvm.is_tech_avail

blockdev_lvm_required = LVMDependencyGuard()


class MDDependencyGuard(BlockDevDependencyGuard):
    error_msg = "libblockdev MD RAID functionality not available"
    _tech = [blockdev.MDTech.MD_TECH_MDRAID]
    _mode = blockdev.MDTechMode.QUERY
    _is_tech_avail = blockdev.md.is_tech_avail

blockdev_md_required = MDDependencyGuard()


class MultipathDependencyGuard(BlockDevDependencyGuard):
    error_msg = "libblockdev multipath functionality not available"
    _tech = [blockdev.MpathTech.BASE,
             blockdev.MpathTech.FRIENDLY_NAMES]
    _mode = blockdev.MpathTechMode.QUERY
    _is_tech_avail = blockdev.mpath.is_tech_avail

blockdev_mpath_required = MultipathDependencyGuard()
