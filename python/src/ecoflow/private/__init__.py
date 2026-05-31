"""EcoFlow private API support (Wave 3, email/password authentication).

Provides Wave3Connection for devices not supported by the public Developer API.
Wave 3 portable ACs (SN prefix AC71) return error 1006 from the public REST API —
use this module instead.

Install: pip install ecoflow-python[wave3]

If protobuf is not installed, importing this module raises ImportError with
a clear install instruction — the error appears at import time, not at first use.
"""

# Wave3Mode is re-exported here for user convenience — it does not require protobuf.
from ecoflow.models.wave3 import Wave3Mode

try:
    from ecoflow.private.connection import Wave3Connection
except ImportError as exc:
    if "google.protobuf" in str(exc) or "protobuf" in str(exc).lower():
        raise ImportError(
            "ecoflow.private requires the 'protobuf' package.\n"
            "Install it with: pip install ecoflow-python[wave3]\n"
            f"Original error: {exc}"
        ) from exc
    raise

__all__ = ["Wave3Connection", "Wave3Mode"]
