"""OKX adapter module (import-friendly package)."""

from .client import OKXAdapter, OKXClient, OKXConfig, OKXApiError
from .alerts import PriceAlert, PriceAlertManager
from .ws_private import OKXPrivateWebSocket, OKXWebSocketConfig

__all__ = [
    "OKXAdapter",
    "OKXClient",
    "OKXConfig",
    "OKXApiError",
    "PriceAlert",
    "PriceAlertManager",
    "OKXPrivateWebSocket",
    "OKXWebSocketConfig",
]
