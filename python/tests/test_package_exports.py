"""Tests for public package exports from ecoflow.devices and ecoflow.models."""


def test_devices_package_exports_all_typed_devices() -> None:
    """All typed device classes should be importable from ecoflow.devices."""
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

    assert BatteryDevice.__name__ == "BatteryDevice"
    assert SmartPlugDevice.__name__ == "SmartPlugDevice"
    assert SmartMeterDevice.__name__ == "SmartMeterDevice"
    assert MicroInverterDevice.__name__ == "MicroInverterDevice"
    assert Wave3Device.__name__ == "Wave3Device"
    assert SmartHomePanelDevice.__name__ == "SmartHomePanelDevice"
    assert DiscoveredDevice.__name__ == "DiscoveredDevice"
    assert StreamUltraDevice.__name__ == "StreamUltraDevice"
    assert StreamAcProDevice.__name__ == "StreamAcProDevice"


def test_models_package_exports_all_typed_models() -> None:
    """All model names should be importable from ecoflow.models."""
    from ecoflow.models import (
        WATTS_RAW_FACTOR,
        BatteryStatus,
        BmsModule,
        ExpansionBatteryModule,
        SmartMeterData,
        SmartPlugData,
        SolarInput,
        StreamUltraStatus,
        Wave3Mode,
        Wave3Status,
    )

    assert BatteryStatus.__name__ == "BatteryStatus"
    assert BmsModule.__name__ == "BmsModule"
    assert ExpansionBatteryModule.__name__ == "ExpansionBatteryModule"
    assert SolarInput.__name__ == "SolarInput"
    assert SmartPlugData.__name__ == "SmartPlugData"
    assert SmartMeterData.__name__ == "SmartMeterData"
    assert StreamUltraStatus.__name__ == "StreamUltraStatus"
    assert Wave3Status.__name__ == "Wave3Status"
    assert WATTS_RAW_FACTOR == 0.1
    assert Wave3Mode.COOL.value == 0
