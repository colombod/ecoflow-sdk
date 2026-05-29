"""EcoFlow Python SDK."""

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

__version__ = "0.2.0"

__all__ = [
    "EcoFlowClient",
    "EcoFlowCredentials",
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
]
