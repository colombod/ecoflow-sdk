"""EcoFlow library exceptions."""

from __future__ import annotations


class EcoFlowError(Exception):
    """Base class for all EcoFlow errors."""


class EcoFlowAuthError(EcoFlowError):
    """Bad API keys or invalid credentials."""


class EcoFlowConnectionError(EcoFlowError):
    """Network / transport failure."""


class EcoFlowDeviceNotFoundError(EcoFlowError):
    """Device SN not found in account."""

    def __init__(self, sn: str) -> None:
        super().__init__(f"Device not found: {sn!r}")
        self.sn = sn


class EcoFlowTimeoutError(EcoFlowError):
    """Command or query timed out."""


class EcoFlowDeviceOfflineError(EcoFlowError):
    """Action attempted on an offline device."""

    def __init__(self, sn: str) -> None:
        super().__init__(f"Device is offline: {sn!r}")
        self.sn = sn


class EcoFlowCommandError(EcoFlowError):
    """Device rejected a command."""
