"""The twin, composed: HTTPS REST + MQTT/TLS broker on local ports."""

from __future__ import annotations

import asyncio
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from aiohttp import web

from ecoflow.endpoints import ENV_CA_FILE, ENV_REST_BASE, Endpoints
from ecoflow_twin.broker import Broker, BrokerConfig
from ecoflow_twin.certs import ensure_certs
from ecoflow_twin.recording import Recording
from ecoflow_twin.rest import RestConfig, RestStats, build_app
from ecoflow_twin.state import DeviceState

TWIN_ACCESS_KEY = "twin-access-key"
TWIN_SECRET_KEY = "twin-secret-key"
TWIN_ACCOUNT = "open-twin"
TWIN_ACCOUNT_PASSWORD = "twin-mqtt-password"


@dataclass(frozen=True)
class TwinEndpoints:
    rest_base: str
    mqtt_host: str
    mqtt_port: int
    ca_file: str
    access_key: str
    secret_key: str
    account: str
    account_password: str

    def sdk_endpoints(self) -> Endpoints:
        return Endpoints(rest_base=self.rest_base, ca_file=self.ca_file)

    def env(self) -> dict[str, str]:
        """Environment that points any SDK-based app at this twin."""
        return {
            ENV_REST_BASE: self.rest_base,
            ENV_CA_FILE: self.ca_file,
            "ECOFLOW_ACCESS_KEY": self.access_key,
            "ECOFLOW_SECRET_KEY": self.secret_key,
        }


def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if sys.platform != "win32":  # Windows SO_REUSEADDR allows port hijacking
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.setblocking(False)
    return sock


class TwinServer:
    def __init__(
        self,
        recording: Recording,
        *,
        state_dir: Path,
        host: str = "127.0.0.1",
        rest_port: int = 0,
        mqtt_port: int = 0,
        speed: float = 20.0,
        access_key: str = TWIN_ACCESS_KEY,
        secret_key: str = TWIN_SECRET_KEY,
        client_id_limit: int = 10,
    ) -> None:
        self._recording = recording
        self._state_dir = state_dir
        self._host = host
        self._rest_port = rest_port
        self._mqtt_port = mqtt_port
        self._access_key = access_key
        self._secret_key = secret_key
        self.state = DeviceState(recording)
        self.rest_stats = RestStats()
        self.broker = Broker(
            recording,
            self.state,
            BrokerConfig(TWIN_ACCOUNT, TWIN_ACCOUNT_PASSWORD, speed, client_id_limit),
        )
        self._mqtt_server: asyncio.Server | None = None
        self._runner: web.AppRunner | None = None

    async def start(self) -> TwinEndpoints:
        certs = ensure_certs(self._state_dir)
        tls = certs.server_context()
        mqtt_sock = _bind(self._host, self._mqtt_port)
        rest_sock = _bind(self._host, self._rest_port)
        mqtt_port = int(mqtt_sock.getsockname()[1])
        rest_port = int(rest_sock.getsockname()[1])
        self._mqtt_server = await asyncio.start_server(
            self.broker.handle, sock=mqtt_sock, ssl=tls
        )
        config = RestConfig(
            self._access_key,
            self._secret_key,
            TWIN_ACCOUNT,
            TWIN_ACCOUNT_PASSWORD,
            self._host,
            mqtt_port,
        )
        app = build_app(
            self.state, self._recording.device_list, config, self.rest_stats
        )
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.SockSite(self._runner, rest_sock, ssl_context=tls).start()
        bracketed = f"[{self._host}]" if ":" in self._host else self._host
        return TwinEndpoints(
            rest_base=f"https://{bracketed}:{rest_port}",
            mqtt_host=self._host,
            mqtt_port=mqtt_port,
            ca_file=str(certs.ca_file),
            access_key=self._access_key,
            secret_key=self._secret_key,
            account=TWIN_ACCOUNT,
            account_password=TWIN_ACCOUNT_PASSWORD,
        )

    async def stop(self) -> None:
        self.broker.close_all()
        if self._mqtt_server is not None:
            self._mqtt_server.close()
            await self._mqtt_server.wait_closed()
            self._mqtt_server = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def __aenter__(self) -> TwinEndpoints:
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()
