"""EcoFlow service digital twin: the Developer API, served locally from recordings."""

# The twin ships in the ecoflow-python wheel, but its dependencies are the
# optional "twin" extra; say how to get them instead of a bare ModuleNotFound.
try:
    import aiohttp  # noqa: F401  # pyright: ignore[reportUnusedImport]
    import cryptography  # noqa: F401  # pyright: ignore[reportUnusedImport]
except ImportError as exc:  # pragma: no cover - exercised in a subprocess test
    raise ImportError(
        "ecoflow-twin needs the optional 'twin' dependencies: "
        "pip install 'ecoflow-python[twin]'"
    ) from exc

from ecoflow_twin.recording import Recording, RecordingError, discover_recordings
from ecoflow_twin.server import (
    TWIN_ACCESS_KEY,
    TWIN_ACCOUNT,
    TWIN_ACCOUNT_PASSWORD,
    TWIN_SECRET_KEY,
    TwinEndpoints,
    TwinServer,
)

__all__ = [
    "TWIN_ACCESS_KEY",
    "TWIN_ACCOUNT",
    "TWIN_ACCOUNT_PASSWORD",
    "TWIN_SECRET_KEY",
    "Recording",
    "RecordingError",
    "TwinEndpoints",
    "TwinServer",
    "discover_recordings",
]
