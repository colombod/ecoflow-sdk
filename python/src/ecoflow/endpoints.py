"""Where the SDK connects: EcoFlow's cloud by default, or a digital twin."""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass

ENV_REST_BASE = "ECOFLOW_REST_BASE"
ENV_CA_FILE = "ECOFLOW_CA_FILE"


@dataclass(frozen=True)
class Endpoints:
    """Network endpoints for the public Developer API.

    ``rest_base`` replaces the region's REST host (e.g. a twin's
    ``https://127.0.0.1:8443``). The MQTT broker always comes from the
    ``certification`` response, so pointing REST at a twin is enough.
    ``ca_file`` is a PEM CA trusted for REST and MQTT TLS; ``None`` means the
    system trust store.
    """

    rest_base: str | None = None
    ca_file: str | None = None

    @classmethod
    def from_env(cls) -> Endpoints:
        """``ECOFLOW_REST_BASE`` / ``ECOFLOW_CA_FILE``; unset means EcoFlow's cloud."""
        return cls(
            rest_base=os.environ.get(ENV_REST_BASE) or None,
            ca_file=os.environ.get(ENV_CA_FILE) or None,
        )

    def ssl_context(self) -> ssl.SSLContext:
        """TLS context trusting ``ca_file`` when set, else the system store."""
        return ssl.create_default_context(cafile=self.ca_file)
