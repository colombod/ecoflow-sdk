"""EcoFlow Python SDK."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from ecoflow.auth import EcoFlowCredentials
from ecoflow.client import EcoFlowClient
from ecoflow.devices import (
    BatteryDevice,
    DiscoveredDevice,
    MicroInverterDevice,
    SmartHomePanelDevice,
    SmartMeterDevice,
    SmartPlugDevice,
    StreamAcProDevice,
    StreamUltraDevice,
    Wave3Device,
)
from ecoflow.endpoints import Endpoints
from ecoflow.exceptions import (
    EcoFlowAuthError,
    EcoFlowConnectionError,
    EcoFlowDeviceNotFoundError,
    EcoFlowDeviceOfflineError,
    EcoFlowError,
    EcoFlowTimeoutError,
)
from ecoflow.models import (
    BatteryStatus,
    SmartMeterData,
    SmartPlugData,
    StreamUltraStatus,
    Wave3Mode,
    Wave3Status,
)

# Wave3Connection is an optional import — requires pip install ecoflow-python[wave3]
try:
    from ecoflow.private import Wave3Connection
except ImportError:
    pass  # protobuf not installed — Wave3Connection silently unavailable

try:
    # Single source of truth: pyproject.toml [project].version.
    __version__ = _dist_version("ecoflow-python")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0+unknown"

__all__ = [
    "EcoFlowClient",
    "EcoFlowCredentials",
    "Endpoints",
    "EcoFlowError",
    "EcoFlowAuthError",
    "EcoFlowConnectionError",
    "EcoFlowDeviceNotFoundError",
    "EcoFlowTimeoutError",
    "EcoFlowDeviceOfflineError",
    "BatteryStatus",
    "SmartPlugData",
    "SmartMeterData",
    "StreamUltraStatus",
    "Wave3Status",
    "Wave3Mode",
    "BatteryDevice",
    "SmartPlugDevice",
    "SmartMeterDevice",
    "MicroInverterDevice",
    "StreamUltraDevice",
    "StreamAcProDevice",
    "Wave3Device",
    "SmartHomePanelDevice",
    "DiscoveredDevice",
    "Wave3Connection",  # requires pip install ecoflow-python[wave3]
]
