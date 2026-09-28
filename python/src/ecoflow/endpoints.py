"""Where the SDK connects: EcoFlow's cloud by default, or a digital twin."""

from __future__ import annotations

import logging
import os
import ssl
from dataclasses import dataclass
from urllib.parse import urlsplit

_log = logging.getLogger(__name__)

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

    def __post_init__(self) -> None:
        # Signed requests carry the access key; never send them in cleartext.
        if self.rest_base is not None and urlsplit(self.rest_base).scheme != "https":
            raise ValueError(
                f"rest_base must be an https:// URL, got {self.rest_base!r}"
            )

    @classmethod
    def from_env(cls) -> Endpoints:
        """``ECOFLOW_REST_BASE`` / ``ECOFLOW_CA_FILE``; unset means EcoFlow's cloud.

        An override redirects every request, including the access key header,
        and changes which CA is trusted, so it is logged as a warning.
        """
        endpoints = cls(
            rest_base=os.environ.get(ENV_REST_BASE) or None,
            ca_file=os.environ.get(ENV_CA_FILE) or None,
        )
        if endpoints != cls():
            _log.warning(
                "EcoFlow endpoints overridden from the environment "
                "(%s=%s, %s=%s): requests, including your access key, go there "
                "instead of EcoFlow's cloud. Unset them unless you are using a twin.",
                ENV_REST_BASE,
                endpoints.rest_base,
                ENV_CA_FILE,
                endpoints.ca_file,
            )
        return endpoints

    def ssl_context(self) -> ssl.SSLContext:
        """TLS context trusting ``ca_file`` when set, else the system store."""
        return ssl.create_default_context(cafile=self.ca_file)
