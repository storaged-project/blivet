import unittest
from unittest.mock import Mock, patch, sentinel

from blivet.devicelibs import disk as disklib
from blivet.size import Size


class FakeLsmError(Exception):
    pass


class OtherError(Exception):
    pass


def raise_lsm_error(*args):
    raise FakeLsmError("fake message")


def raise_other_error(*args):
    raise OtherError("other message")


class DiskLibTestCase(unittest.TestCase):
    def test_lsm_dependency_guard(self):
        """Validate handling of missing lsm dependency."""
        # If lsm cannot be imported update_volume_info should yield an empty volume list.
        with patch("blivet.devicelibs.disk._lsm_required._check_avail", return_value=False):
            disklib.update_volume_info()
            self.assertEqual(disklib.volumes, dict())

    def test_lsm_error_handling(self):
        """Validate handling of potential lsm errors."""
        with patch("blivet.devicelibs.disk._lsm_required._check_avail", return_value=True):
            with patch("blivet.devicelibs.disk.lsm") as _lsm:
                _lsm.LsmError = FakeLsmError

                # verify that we end up with an empty dict if lsm.Client() raises LsmError
                _lsm.Client.side_effect = raise_lsm_error
                disklib.update_volume_info()
                self.assertEqual(disklib.volumes, dict())

                # verify that any error other than LsmError gets raised
                _lsm.Client.side_effect = raise_other_error
                with self.assertRaises(OtherError):
                    disklib.update_volume_info()

    def test_update_volume_list(self):
        """Validate conversion of lsm data."""
        _client_systems = [Mock(), Mock(), Mock()]
        _client_systems[0].configure_mock(name="Smart Array P840 in Slot 1", raid=True)
        _client_systems[1].configure_mock(name="LSI MegaRAID SAS", raid=True)
        _client_systems[2].configure_mock(name="Supermicro Superchassis", raid=False)

        _client_volumes = [Mock(system_id=_client_systems[0].id,
                                nodes=["/dev/sda"],
                                vpd83=0,
                                raid_type=sentinel.RAID_TYPE_RAID0,
                                stripe_size=262144,
                                drives=4,
                                min_io=262144,
                                opt_io=1048576),
                           Mock(system_id=_client_systems[1].id,
                                nodes=["/dev/sdb"],
                                vpd83=1,
                                raid_type=sentinel.RAID_TYPE_OTHER,
                                stripe_size=524288,
                                drives=2,
                                min_io=524288,
                                opt_io=1048576),
                           Mock(system_id=_client_systems[2].id,
                                nodes=["/dev/sdc"],
                                vpd83=2,
                                raid_type=None,
                                strip_size=None,
                                drives=None,
                                min_io=None,
                                opt_io=None)]

        def client_capabilities(system):
            caps = Mock(name="Client.capabilities(%s)" % system.name)
            caps.configure_mock(**{"supported.return_value": system.raid})
            return caps

        def client_volume_raid_info(volume):
            return (volume.raid_type, volume.stripe_size, volume.drives, volume.min_io, volume.opt_io)

        def vpd83_search(vpd83):
            return next((vol.nodes for vol in _client_volumes if vol.vpd83 == vpd83), None)

        def system_by_id(sys_id):
            return next((sys for sys in _client_systems if sys.id == sys_id), None)

        with patch("blivet.devicelibs.disk._lsm_required._check_avail", return_value=True):
            with patch("blivet.devicelibs.disk.lsm") as _lsm:
                _lsm.Volume.RAID_TYPE_RAID0 = sentinel.RAID_TYPE_RAID0
                _lsm.Volume.RAID_TYPE_OTHER = sentinel.RAID_TYPE_OTHER
                _lsm.Capabilities.VOLUME_RAID_INFO = sentinel.VOLUME_RAID_INFO
                _lsm.LocalDisk.vpd83_search.side_effect = vpd83_search
                client_mock = Mock(name="lsm.Client")
                client_mock.configure_mock(**{"return_value": client_mock,
                                              "volumes.return_value": _client_volumes,
                                              "systems.return_value": _client_systems,
                                              "capabilities.side_effect": client_capabilities,
                                              "volume_raid_info.side_effect": client_volume_raid_info})
                _lsm.Client = client_mock
                disklib.update_volume_info()
                for (_i, lvol) in enumerate(_client_volumes):
                    bvol = disklib.volumes[lvol.nodes[0]]
                    system = system_by_id(lvol.system_id)
                    self.assertEqual(bvol.system, system.name)
                    if client_mock.capabilities(system).supported(sentinel.VOLUME_RAID_INFO):
                        self.assertEqual(bvol.raid_type, disklib._get_lsm_raid_level(lvol.raid_type))
                        self.assertEqual(bvol.raid_stripe_size, Size(lvol.stripe_size))
                        self.assertEqual(bvol.raid_disk_count, lvol.drives)
                    else:
                        self.assertIsNone(bvol.raid_type)
                        self.assertIsNone(bvol.raid_stripe_size)
                        self.assertIsNone(bvol.raid_disk_count)
