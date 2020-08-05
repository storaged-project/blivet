from collections import namedtuple

from . import raid
from .. import errors
from .. import util
from ..size import Size

lsm = None

_HBA_PLUGIN_URIS = ("hpsa://", "megaraid://")
LSMInfo = namedtuple('HBAVolumeInfo', ['system', 'nodes', 'raid_type', 'raid_stripe_size', 'raid_disk_count'])
""" .. class:: LSMInfo

        .. attribute:: system (str): descriptive name of HBA unit
        .. attribute:: nodes (list[str]): list of device node paths for the volume
        .. attribute:: raid_type (:class:`~.devicelibs.raid.RAIDLevel` or None): RAID level
        .. attribute:: raid_stripe_size (:class:`~.size.Size` or None): stripe size
        .. attribute:: raid_disk_count (int or None): number of disks in the RAID set
"""
volumes = dict()
_raid_levels = dict()


class _LSMRAIDLevelStub(raid.RAIDLevel):
    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def names(self):
        return [self.name]

    @property
    def min_members(self):
        return 0

    def has_redundancy(self):
        return False

    def is_uniform(self):
        return False


class _LSMDependencyGuard(util.DependencyGuard):
    error_msg = "libstoragemgmt functionality not available"

    def _check_avail(self):
        global lsm
        if lsm is None:  # pylint: disable=used-before-assignment
            try:
                import lsm  # pylint: disable=redefined-outer-name
            except ImportError:
                lsm = None

        return lsm is not None


_lsm_required = _LSMDependencyGuard()


def _update_lsm_raid_levels():
    """ Build a mapping of lsm.RAID_TYPE->blivet.devicelibs.raid.RAIDLevel """
    global _raid_levels
    _raid_levels = dict()
    lsm_raid_levels = dict((k, v) for (k, v) in lsm.Volume.__dict__.items() if k.startswith("RAID_TYPE_"))
    for constant_name, value in lsm_raid_levels.items():
        name = constant_name[len("RAID_TYPE_"):]
        try:
            level = raid.get_raid_level(name)
        except errors.RaidError:
            level = _LSMRAIDLevelStub(name)

        _raid_levels[value] = level


def _get_lsm_raid_level(lsm_raid_type):
    """ Return a blivet.devicelibs.raid.RAIDLevel corresponding the lsm-reported RAID level."""
    return _raid_levels.get(lsm_raid_type, _raid_levels.get(lsm.Volume.RAID_TYPE_UNKNOWN))


@_lsm_required(critical=False, eval_mode=util.EvalMode.always)
def update_volume_info():
    """ Build a dict of namedtuples containing basic HBA RAID info w/ device path keys. """
    global volumes
    volumes = dict()
    _update_lsm_raid_levels()
    for uri in _HBA_PLUGIN_URIS:
        try:
            client = lsm.Client(uri)
        except lsm.LsmError:
            continue

        systems = dict((s.id, s) for s in client.systems())
        for vol in client.volumes():
            nodes = lsm.LocalDisk.vpd83_search(vol.vpd83)
            system = systems[vol.system_id]
            caps = client.capabilities(system)

            raid_level = None
            stripe_size = None
            disk_count = None
            if caps.supported(lsm.Capabilities.VOLUME_RAID_INFO):
                raid_info = client.volume_raid_info(vol)[:3]
                raid_level = _get_lsm_raid_level(raid_info[0])
                stripe_size = Size(raid_info[1])
                disk_count = raid_info[2]

            info = LSMInfo(system.name, nodes, raid_level, stripe_size, disk_count)
            volumes.update([(node, info) for node in nodes])
