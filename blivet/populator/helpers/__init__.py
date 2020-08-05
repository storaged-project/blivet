import inspect as _inspect
import six as _six

from .devicepopulator import DevicePopulator
from .formatpopulator import FormatPopulator

from .btrfs import BTRFSFormatPopulator
from .boot import AppleBootFormatPopulator, EFIFormatPopulator, MacEFIFormatPopulator
from .disk import DiskDevicePopulator, iScsiDevicePopulator, FCoEDevicePopulator, MDBiosRaidDevicePopulator, DASDDevicePopulator, ZFCPDevicePopulator, NVDIMMNamespaceDevicePopulator
from .disklabel import DiskLabelFormatPopulator
from .dm import DMDevicePopulator
from .dmraid import DMRaidFormatPopulator
from .loop import LoopDevicePopulator
from .luks import LUKSDevicePopulator, LUKSFormatPopulator, IntegrityDevicePopulator, IntegrityFormatPopulator
from .lvm import LVMDevicePopulator, LVMFormatPopulator
from .mdraid import MDDevicePopulator, MDFormatPopulator
from .multipath import MultipathDevicePopulator, MultipathFormatPopulator
from .optical import OpticalDevicePopulator
from .partition import PartitionDevicePopulator

__all__ = ["get_device_helper", "get_format_helper"]

_device_helpers = []
_format_helpers = []


def _build_helper_lists():
    """Build lists of known device and format helper classes."""
    global _device_helpers  # pylint: disable=global-variable-undefined
    global _format_helpers  # pylint: disable=global-variable-undefined
    _device_helpers = []
    _format_helpers = []
    for obj in globals().values():
        if not _inspect.isclass(obj):
            continue
        elif issubclass(obj, DevicePopulator):
            _device_helpers.append(obj)
        elif issubclass(obj, FormatPopulator):
            _format_helpers.append(obj)

    _device_helpers.sort(key=lambda h: h.priority, reverse=True)
    _format_helpers.sort(key=lambda h: h.priority, reverse=True)


_build_helper_lists()


def get_device_helper(data):
    """ Return the device helper class appropriate for the specified data.

        The helper lists are sorted according to priorities defined within each
        class. This function returns the first matching class.
    """
    return _six.next((h for h in _device_helpers if h.match(data)), None)


def get_format_helper(data, device):
    """ Return the device helper class appropriate for the specified data.

        The helper lists are sorted according to priorities defined within each
        class. This function returns the first matching class.
    """
    return _six.next((h for h in _format_helpers if h.match(data, device=device)), None)
