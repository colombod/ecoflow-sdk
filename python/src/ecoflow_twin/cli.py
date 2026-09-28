"""``ecoflow-twin serve --recording PATH``: run the service twin until Ctrl+C.

Prints ONE line of JSON with the endpoints, the CA path, the twin credentials
and an ``env`` block, so scripts and agents can consume it:

    uv run ecoflow-twin serve --recording tests/recordings/live-20260928/recording.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import sys
from pathlib import Path

from ecoflow_twin.recording import Recording, RecordingError
from ecoflow_twin.server import TwinServer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecoflow-twin", description="EcoFlow service twin"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve a recording over HTTPS REST + MQTT/TLS")
    serve.add_argument("--recording", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--rest-port", type=int, default=0, help="0 = any free port")
    serve.add_argument("--mqtt-port", type=int, default=0, help="0 = any free port")
    serve.add_argument(
        "--speed", type=float, default=1.0, help="playback speed (1 = real time)"
    )
    serve.add_argument("--state-dir", type=Path, default=Path(".ecoflow-twin"))
    serve.add_argument("--client-id-limit", type=int, default=10)
    return parser


async def _serve(recording: Recording, args: argparse.Namespace) -> None:
    server = TwinServer(
        recording,
        state_dir=args.state_dir,
        host=args.host,
        rest_port=args.rest_port,
        mqtt_port=args.mqtt_port,
        speed=args.speed,
        client_id_limit=args.client_id_limit,
    )
    async with server as endpoints:
        info = dataclasses.asdict(endpoints) | {"env": endpoints.env()}
        print(json.dumps(info), flush=True)
        await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        recording = Recording.load(args.recording)
    except (OSError, RecordingError) as exc:
        print(f"ecoflow-twin: {exc}", file=sys.stderr)
        return 2
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with (
        asyncio.Runner(loop_factory=factory) as runner,
        contextlib.suppress(KeyboardInterrupt),
    ):
        runner.run(_serve(recording, args))
    return 0
