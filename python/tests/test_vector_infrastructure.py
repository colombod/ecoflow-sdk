"""Tests that verify the test vector infrastructure exists with the required content.

These tests are the RED-first verification for task-6-test-vector-infrastructure.
They check that the JSON fixture files, directory structure, and conftest.py exist
with exactly the content required by the spec.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
VECTORS_DIR = TESTS_DIR / "vectors"


class TestVectorDirectories:
    """Verify the vector directory structure exists."""

    def test_vectors_dir_exists(self) -> None:
        assert VECTORS_DIR.is_dir(), "tests/vectors/ directory must exist"

    def test_battery_subdir_exists(self) -> None:
        assert (VECTORS_DIR / "battery").is_dir(), "tests/vectors/battery/ must exist"

    def test_smart_plug_subdir_exists(self) -> None:
        assert (VECTORS_DIR / "smart_plug").is_dir(), (
            "tests/vectors/smart_plug/ must exist"
        )

    def test_stream_ultra_subdir_exists(self) -> None:
        assert (VECTORS_DIR / "stream_ultra").is_dir(), (
            "tests/vectors/stream_ultra/ must exist"
        )


class TestBatteryVectors:
    """Verify battery test vector files exist with correct content."""

    def test_battery_payload_json_exists(self) -> None:
        assert (VECTORS_DIR / "battery" / "payload_status.json").exists(), (
            "battery payload_status.json must exist"
        )

    def test_battery_expected_json_exists(self) -> None:
        assert (VECTORS_DIR / "battery" / "payload_status.expected.json").exists(), (
            "battery payload_status.expected.json must exist"
        )

    def test_battery_payload_bms_section(self) -> None:
        data = json.loads((VECTORS_DIR / "battery" / "payload_status.json").read_text())
        bms = data["bms_bmsStatus"]
        assert bms["soc"] == 85
        assert bms["vol"] == 51200
        assert bms["amp"] == -5000
        assert bms["temp"] == 280
        assert bms["cycles"] == 42
        assert bms["designCap"] == 102400
        assert bms["fullCap"] == 98000
        assert bms["remainCap"] == 83300
        assert bms["soh"] == 96
        assert bms["minCellTemp"] == 270
        assert bms["maxCellTemp"] == 290
        assert bms["minCellVol"] == 3200
        assert bms["maxCellVol"] == 3250

    def test_battery_payload_pd_section(self) -> None:
        data = json.loads((VECTORS_DIR / "battery" / "payload_status.json").read_text())
        pd = data["pd"]
        assert pd["soc"] == 85
        assert pd["chgRemTime"] == 0
        assert pd["dsgRemTime"] == 240
        assert pd["wattsInSum"] == 0
        assert pd["wattsOutSum"] == 200
        assert pd["usb1Watts"] == 10
        assert pd["usb2Watts"] == 5

    def test_battery_payload_inv_section(self) -> None:
        data = json.loads((VECTORS_DIR / "battery" / "payload_status.json").read_text())
        inv = data["inv"]
        assert inv["inputWatts"] == 0
        assert inv["outputWatts"] == 200
        assert inv["cfgAcEnabled"] == 1
        assert inv["invInTemp"] == 350

    def test_battery_payload_mppt_section(self) -> None:
        data = json.loads((VECTORS_DIR / "battery" / "payload_status.json").read_text())
        mppt = data["mppt"]
        assert mppt["inWatts"] == 0
        assert mppt["dcdc12vWatts"] == 15

    def test_battery_expected_content(self) -> None:
        data = json.loads(
            (VECTORS_DIR / "battery" / "payload_status.expected.json").read_text()
        )
        assert data["soc"] == 85
        assert data["remaining_discharge_time_min"] == 240
        assert data["ac_output_watts"] == 200
        assert data["ac_output_enabled"] is True
        assert data["total_output_watts"] == 200
        assert data["dc_output_watts"] == 15


class TestSmartPlugVectors:
    """Verify smart_plug test vector files exist with correct content.

    Vector format updated 2026-05 to real REST /quota/all flat '2_1.*' keys.
    Confirmed from live HW52-series Smart Plug device.
    """

    def test_smart_plug_payload_json_exists(self) -> None:
        assert (VECTORS_DIR / "smart_plug" / "payload_power.json").exists(), (
            "smart_plug payload_power.json must exist"
        )

    def test_smart_plug_expected_json_exists(self) -> None:
        assert (VECTORS_DIR / "smart_plug" / "payload_power.expected.json").exists(), (
            "smart_plug payload_power.expected.json must exist"
        )

    def test_smart_plug_payload_content(self) -> None:
        """Vector uses flat 2_1.* REST quota/all format (not MQTT plug_heartbeat)."""
        data = json.loads(
            (VECTORS_DIR / "smart_plug" / "payload_power.json").read_text()
        )
        assert data["2_1.switchSta"] is True
        assert data["2_1.watts"] == 2640
        assert data["2_1.volt"] == 242
        assert data["2_1.current"] == 1598
        assert data["2_1.temp"] == 36
        assert data["2_1.brightness"] == 1023
        assert data["2_1.runTime"] == 1846450
        assert data["2_1.freq"] == 50
        assert data["2_1.consWatt"] == -2690

    def test_smart_plug_expected_content(self) -> None:
        data = json.loads(
            (VECTORS_DIR / "smart_plug" / "payload_power.expected.json").read_text()
        )
        assert data["is_on"] is True
        assert data["power_watts"] == 264.0
        assert data["voltage"] == 242.0
        assert data["current"] == pytest.approx(1.598)
        assert data["temp"] == 36.0
        assert data["brightness"] == 100


class TestStreamUltraVectors:
    """Verify stream_ultra test vector files exist with correct content.

    Confirmed from live STREAM Ultra BK11ZK1B2H5S1478, 2026-05.
    """

    def test_stream_ultra_payload_json_exists(self) -> None:
        assert (VECTORS_DIR / "stream_ultra" / "payload_status.json").exists(), (
            "stream_ultra payload_status.json must exist"
        )

    def test_stream_ultra_expected_json_exists(self) -> None:
        assert (
            VECTORS_DIR / "stream_ultra" / "payload_status.expected.json"
        ).exists(), "stream_ultra payload_status.expected.json must exist"

    def test_stream_ultra_payload_content(self) -> None:
        """Vector uses real MQTT data from BK11ZK1B2H5S1478, 2026-05-29."""
        data = json.loads(
            (VECTORS_DIR / "stream_ultra" / "payload_status.json").read_text()
        )
        # Real fields: bmsBattSoc is individual battery SOC (correct)
        assert data["bmsBattSoc"] == pytest.approx(47.0)
        assert data["cmsBattSoc"] == pytest.approx(45.0)
        assert data["cascadeSysSoc"] == 44
        assert data["powGetSysGrid"] == pytest.approx(4924.0)
        assert data["cmsMaxChgSoc"] == 95
        assert data["cmsMinDsgSoc"] == 10
        assert data["feedGridMode"] == 2
        assert data["relay2Onoff"] is False
        assert data["relay3Onoff"] is False
        assert data["backupReverseSoc"] == 13
        assert data["chgDsgState"] == 2
        assert data["cycles"] == 219

    def test_stream_ultra_expected_content(self) -> None:
        """Expected output uses bmsBattSoc=47.0 (not the legacy cmsBattSoc=45.0)."""
        data = json.loads(
            (VECTORS_DIR / "stream_ultra" / "payload_status.expected.json").read_text()
        )
        assert data["batt_soc"] == pytest.approx(47.0)
        assert data["cascade_soc"] == 44
        assert data["grid_power_watts"] == pytest.approx(4924.0)
        assert data["pv_power_watts"] == pytest.approx(0.0)
        assert data["max_charge_soc"] == 95
        assert data["min_discharge_soc"] == 10


class TestConftestPy:
    """Verify conftest.py exists with the required content."""

    def test_conftest_exists(self) -> None:
        assert (TESTS_DIR / "conftest.py").exists(), "tests/conftest.py must exist"

    def test_conftest_has_vectors_dir_constant(self) -> None:
        content = (TESTS_DIR / "conftest.py").read_text()
        assert "VECTORS_DIR" in content, "conftest.py must define VECTORS_DIR constant"

    def test_conftest_has_load_vector_function(self) -> None:
        content = (TESTS_DIR / "conftest.py").read_text()
        assert "def load_vector" in content, (
            "conftest.py must define load_vector() function"
        )

    def test_conftest_has_quirk_note(self) -> None:
        content = (TESTS_DIR / "conftest.py").read_text()
        assert "QUIRK NOTE" in content, (
            "conftest.py must contain the smart_plug QUIRK NOTE"
        )
        assert "10" in content and "watts" in content.lower(), (
            "conftest.py must document the 10x watts factor"
        )

    def test_load_vector_function_works(self) -> None:
        """Test that load_vector() can actually load vector pairs."""
        # Force reload to pick up fresh conftest if needed
        if "conftest" in sys.modules:
            del sys.modules["conftest"]
        # We import conftest from the tests package as a plain module
        spec = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
            "conftest", TESTS_DIR / "conftest.py"
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)  # type: ignore[attr-defined]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        payload, expected = module.load_vector("battery", "payload_status")
        assert "bms_bmsStatus" in payload
        assert "soc" in expected
        assert expected["soc"] == 85
