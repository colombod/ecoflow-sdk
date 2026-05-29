"""StreamAcProDevice — EcoFlow STREAM AC Pro (shares payload with STREAM Ultra)."""

from ecoflow.devices.stream_ultra import StreamUltraDevice


class StreamAcProDevice(StreamUltraDevice):
    """EcoFlow STREAM AC Pro home energy system.

    Shares the same quota/all payload format as STREAM Ultra.
    productName lookup uses SN prefix 'BK31'.
    """
