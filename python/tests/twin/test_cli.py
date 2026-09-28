from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from ecoflow.auth import EcoFlowCredentials, build_auth_headers
from ecoflow_twin.cli import main
from tests.support.recordings import RECORDINGS_DIR


def test_missing_recording_exits_2(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["serve", "--recording", str(tmp_path / "nope.json")]) == 2
    assert "nope.json" in capsys.readouterr().err


def test_serve_prints_endpoints_and_answers_signed_curl_style_request(
    tmp_path: Path,
) -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ecoflow_twin",
            "serve",
            "--recording",
            str(RECORDINGS_DIR / "synthetic" / "recording.json"),
            "--state-dir",
            str(tmp_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        info = json.loads(proc.stdout.readline())
        headers = build_auth_headers(
            EcoFlowCredentials(info["access_key"], info["secret_key"])
        )
        r = httpx.get(
            f"{info['rest_base']}/iot-open/sign/device/list",
            headers=headers,
            verify=info["ca_file"],
            timeout=10,
        )
        assert r.json()["code"] == "0"
        assert info["env"]["ECOFLOW_CA_FILE"] == info["ca_file"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
