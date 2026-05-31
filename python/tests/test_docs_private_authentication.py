"""Doc-coverage tests: private-authentication.md must have all 9 required sections."""

import re
from pathlib import Path

# The doc ships with the library at python/docs/api/ inside the repo.
# From tests/ go up 2 levels to reach the python/ directory.
DOC_PATH = Path(__file__).parent.parent / "docs" / "api" / "private-authentication.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_file_exists() -> None:
    """The documentation file must exist."""
    assert DOC_PATH.exists(), f"Missing: {DOC_PATH}"


def test_intro_section() -> None:
    """Section 1: intro mentions Wave 3 (AC71), error 1006, and Wave3Connection."""
    text = _read_doc()
    assert "AC71" in text, "Intro must mention AC71 prefix"
    assert "1006" in text, "Intro must mention error 1006"
    assert "Wave3Connection" in text, "Intro must mention Wave3Connection"


def test_installation_section() -> None:
    """Section 2: installation shows pip install ecoflow-python[wave3] and protobuf."""
    text = _read_doc()
    assert "pip install ecoflow-python[wave3]" in text, "Must show install command"
    assert "protobuf" in text, "Must mention protobuf dependency"


def test_quick_start_section() -> None:
    """Section 3: quick-start with Wave3Connection, battery_soc, mode, ambient_temp."""
    text = _read_doc()
    assert "async with Wave3Connection" in text, (
        "Quick start must show async with Wave3Connection"
    )
    assert "battery_soc" in text, "Quick start must reference battery_soc"
    assert "ambient_temp" in text, "Quick start must reference ambient_temp"
    assert "mode" in text, "Quick start must reference mode"
    assert "asyncio.sleep" in text, "Quick start must include asyncio.sleep"


def test_how_it_works_section() -> None:
    """Section 4: data flow — auth/login, MQTT creds, Protobuf/XOR, device.status."""
    text = _read_doc()
    assert "auth/login" in text, "Data flow must mention auth/login endpoint"
    assert re.search(r"certificateAccount|certificatePassword", text), (
        "Must mention MQTT credentials fields"
    )
    assert "aiomqtt" in text or "mqtt.ecoflow.com" in text, (
        "Must mention MQTT connection"
    )
    assert "/app/device/property/" in text, "Must mention MQTT topic pattern"
    assert re.search(r"[Pp]rotobuf", text), "Must mention Protobuf decoding"
    assert re.search(r"XOR", text), "Must mention XOR decryption"
    assert "_handle_message" in text, "Must mention _handle_message"


def test_credentials_comparison_table() -> None:
    """Section 5: comparison table — Private API vs Public Developer API."""
    text = _read_doc()
    assert re.search(r"Private.*API|private.*api", text, re.IGNORECASE), (
        "Must reference Private API"
    )
    assert re.search(r"Public.*Developer.*API|Developer.*API", text, re.IGNORECASE), (
        "Must reference Public Developer API"
    )
    # Table columns: auth input, MQTT broker, Wave 3 support, other device support
    assert re.search(
        r"auth.*input|Auth.*input|email|accessKey|access.?key", text, re.IGNORECASE
    ), "Must compare auth input"
    assert "mqtt.ecoflow.com" in text, "Table must show mqtt.ecoflow.com broker"
    assert re.search(r"Wave.?3.*support|support.*Wave.?3", text, re.IGNORECASE), (
        "Table must mention Wave 3 support"
    )


def test_security_note_section() -> None:
    """Section 6: security note about passwords, env vars, .env file, never commit."""
    text = _read_doc()
    assert re.search(r"secret|password.*secret|treat.*password", text, re.IGNORECASE), (
        "Must warn about passwords as secrets"
    )
    assert re.search(r"env.*var|environment.*variable|\benv\b", text, re.IGNORECASE), (
        "Must recommend env vars"
    )
    assert re.search(r"\.env", text), "Must mention .env file"
    assert re.search(r"never.*commit|don.t.*commit|gitignore", text, re.IGNORECASE), (
        "Must say never commit secrets"
    )


def test_regions_section() -> None:
    """Section 7: regions — global endpoint; warn NOT to use mqtt-e."""
    text = _read_doc()
    assert re.search(
        r"global|same.*URL|same.*endpoint|EU.*US|US.*EU", text, re.IGNORECASE
    ), "Must mention global endpoint"
    assert "mqtt-e.ecoflow.com" in text, (
        "Must mention mqtt-e.ecoflow.com to warn against it"
    )
    assert re.search(
        r"do not use|don.t use|NOT.*mqtt-e|avoid.*mqtt-e", text, re.IGNORECASE
    ), "Must warn not to use mqtt-e"


def test_reconnection_section() -> None:
    """Section 8: reconnection — exponential backoff, 1s→2s→4s→300s cap."""
    text = _read_doc()
    assert re.search(r"reconnect|backoff|exponential", text, re.IGNORECASE), (
        "Must describe reconnection"
    )
    assert re.search(
        r"exponential backoff|exponential back.?off", text, re.IGNORECASE
    ), "Must say exponential backoff"
    assert "300" in text, "Must mention 300s cap"
    assert re.search(r"1s|1 s|1 second", text, re.IGNORECASE), (
        "Must mention 1s starting delay"
    )


def test_known_limitations_section() -> None:
    """Section 9: limitations — write commands, token expiry, other devices."""
    text = _read_doc()
    assert re.search(
        r"write.*command|command.*not.*implement|write.*not.*implement",
        text,
        re.IGNORECASE,
    ), "Must mention write commands not yet implemented"
    assert re.search(
        r"token.*expir|expir.*token|token.*undocument", text, re.IGNORECASE
    ), "Must mention token expiry undocumented"
    assert re.search(
        r"Wave.?2|other.*device|device.*not.*confirm", text, re.IGNORECASE
    ), "Must mention Wave 2 or other devices not confirmed"
