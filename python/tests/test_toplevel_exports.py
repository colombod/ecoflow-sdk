"""Tests for top-level ecoflow package public exports.

RED-first tests for task-10-readme-final-exports-push-phase3.
Verifies that all public symbols are importable directly from `ecoflow`.
"""


class TestTopLevelExports:
    """Verify the top-level ecoflow package exports all expected public symbols."""

    def test_ecoflow_client_importable(self) -> None:
        from ecoflow import EcoFlowClient

        assert EcoFlowClient.__name__ == "EcoFlowClient"

    def test_ecoflow_credentials_importable(self) -> None:
        from ecoflow import EcoFlowCredentials

        assert EcoFlowCredentials.__name__ == "EcoFlowCredentials"

    def test_exception_base_importable(self) -> None:
        from ecoflow import EcoFlowError

        assert issubclass(EcoFlowError, Exception)

    def test_exception_auth_importable(self) -> None:
        from ecoflow import EcoFlowAuthError

        assert issubclass(EcoFlowAuthError, Exception)

    def test_exception_connection_importable(self) -> None:
        from ecoflow import EcoFlowConnectionError

        assert issubclass(EcoFlowConnectionError, Exception)

    def test_exception_device_not_found_importable(self) -> None:
        from ecoflow import EcoFlowDeviceNotFoundError

        assert issubclass(EcoFlowDeviceNotFoundError, Exception)

    def test_exception_timeout_importable(self) -> None:
        from ecoflow import EcoFlowTimeoutError

        assert issubclass(EcoFlowTimeoutError, Exception)

    def test_exception_device_offline_importable(self) -> None:
        from ecoflow import EcoFlowDeviceOfflineError

        assert issubclass(EcoFlowDeviceOfflineError, Exception)

    def test_battery_status_importable(self) -> None:
        from ecoflow import BatteryStatus

        assert BatteryStatus.__name__ == "BatteryStatus"

    def test_smart_plug_data_importable(self) -> None:
        from ecoflow import SmartPlugData

        assert SmartPlugData.__name__ == "SmartPlugData"

    def test_smart_meter_data_importable(self) -> None:
        from ecoflow import SmartMeterData

        assert SmartMeterData.__name__ == "SmartMeterData"

    def test_wave3_status_importable(self) -> None:
        from ecoflow import Wave3Status

        assert Wave3Status.__name__ == "Wave3Status"

    def test_wave3_mode_importable(self) -> None:
        from ecoflow import Wave3Mode

        assert Wave3Mode.__name__ == "Wave3Mode"

    def test_battery_device_importable(self) -> None:
        from ecoflow import BatteryDevice

        assert BatteryDevice.__name__ == "BatteryDevice"

    def test_smart_plug_device_importable(self) -> None:
        from ecoflow import SmartPlugDevice

        assert SmartPlugDevice.__name__ == "SmartPlugDevice"

    def test_smart_meter_device_importable(self) -> None:
        from ecoflow import SmartMeterDevice

        assert SmartMeterDevice.__name__ == "SmartMeterDevice"

    def test_micro_inverter_device_importable(self) -> None:
        from ecoflow import MicroInverterDevice

        assert MicroInverterDevice.__name__ == "MicroInverterDevice"

    def test_wave3_device_importable(self) -> None:
        from ecoflow import Wave3Device

        assert Wave3Device.__name__ == "Wave3Device"

    def test_smart_home_panel_device_importable(self) -> None:
        from ecoflow import SmartHomePanelDevice

        assert SmartHomePanelDevice.__name__ == "SmartHomePanelDevice"

    def test_discovered_device_importable(self) -> None:
        from ecoflow import DiscoveredDevice

        assert DiscoveredDevice.__name__ == "DiscoveredDevice"

    def test_stream_ultra_device_importable(self) -> None:
        from ecoflow import StreamUltraDevice

        assert StreamUltraDevice.__name__ == "StreamUltraDevice"

    def test_stream_ac_pro_device_importable(self) -> None:
        from ecoflow import StreamAcProDevice

        assert StreamAcProDevice.__name__ == "StreamAcProDevice"

    def test_stream_ultra_status_importable(self) -> None:
        from ecoflow import StreamUltraStatus

        assert StreamUltraStatus.__name__ == "StreamUltraStatus"

    def test_version_is_correct(self) -> None:
        import ecoflow

        assert ecoflow.__version__ == "0.2.0"

    def test_all_list_contains_expected_symbols(self) -> None:
        import ecoflow

        assert hasattr(ecoflow, "__all__"), "ecoflow must define __all__"
        expected = {
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
        }
        actual = set(ecoflow.__all__)
        missing = expected - actual
        extra = actual - expected
        assert expected == actual, f"Missing: {missing}, Extra: {extra}"
