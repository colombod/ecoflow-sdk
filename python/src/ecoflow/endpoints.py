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
        # Signed requests carry the access key; never send them in cleartext,
        # and reject malformed values ("https:foo", "https://", a bad port) up
        # front. Credentials in the URL are refused so no message or log line
        # can echo them; errors never repeat the value itself.
        if self.rest_base is not None:
            try:
                parts = urlsplit(self.rest_base)
                port = parts.port  # raises ValueError on a malformed port
            except ValueError:
                raise ValueError("rest_base is not a valid URL") from None
            if port == 0:
                raise ValueError("rest_base has an invalid port")
            host = parts.hostname or ""
            if parts.scheme != "https" or not host or any(c.isspace() for c in host):
                raise ValueError("rest_base must be an https://host URL")
            if parts.username is not None or parts.password is not None:
                raise ValueError("rest_base must not contain credentials")
            # httpx would carry these into every request (and the signature
            # covers the query), so they can only be a mistake.
            if parts.query or parts.fragment:
                raise ValueError("rest_base must not have a query or fragment")

    @property
    def rest_origin(self) -> str | None:
        """``https://host[:port]`` of ``rest_base``: safe to log."""
        if self.rest_base is None:
            return None
        parts = urlsplit(self.rest_base)
        port = f":{parts.port}" if parts.port is not None else ""
        host = (
            f"[{parts.hostname}]" if ":" in (parts.hostname or "") else parts.hostname
        )
        return f"{parts.scheme}://{host}{port}"

    @classmethod
    def from_env(cls) -> Endpoints:
        """``ECOFLOW_REST_BASE`` / ``ECOFLOW_CA_FILE``; unset means EcoFlow's cloud.

        Each override is logged as a warning: ``ECOFLOW_REST_BASE`` redirects
        every request, including the access-key header; ``ECOFLOW_CA_FILE``
        changes which CA is trusted (the host stays EcoFlow's).
        """
        endpoints = cls(
            rest_base=os.environ.get(ENV_REST_BASE) or None,
            ca_file=os.environ.get(ENV_CA_FILE) or None,
        )
        if endpoints.rest_base is not None:
            _log.warning(
                "EcoFlow REST host overridden from the environment (%s=%s): "
                "requests, including your access key, go there instead of "
                "EcoFlow's cloud. Unset it unless you are using a twin.",
                ENV_REST_BASE,
                endpoints.rest_origin,
            )
        if endpoints.ca_file is not None:
            _log.warning(
                "EcoFlow TLS trust overridden from the environment (%s=%s): "
                "connections trust that CA instead of the system store. Unset "
                "it unless you are using a twin.",
                ENV_CA_FILE,
                endpoints.ca_file,
            )
        return endpoints

    def ssl_context(self) -> ssl.SSLContext:
        """TLS context trusting ``ca_file`` when set, else the system store."""
        return ssl.create_default_context(cafile=self.ca_file)
