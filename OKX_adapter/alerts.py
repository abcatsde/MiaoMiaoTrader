from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Callable, Dict, Optional

from Monitoring import MonitoringClient
from .client import OKXAdapter

logger = logging.getLogger(__name__)


@dataclass
class PriceAlert:
    inst_id: str
    target_price: float
    direction: str  # "above" or "below"
    message: str
    last_triggered: str | None = None


class PriceAlertManager:
    """Polling-based price alert manager."""

    def __init__(
        self,
        okx: OKXAdapter,
        *,
        monitoring: Optional[MonitoringClient] = None,
        on_trigger: Optional[Callable[[PriceAlert, float], None]] = None,
    ) -> None:
        self._okx = okx
        self._monitoring = monitoring
        self._on_trigger = on_trigger
        self._alerts: Dict[str, PriceAlert] = {}

    def add_alert(
        self,
        *,
        inst_id: str,
        target_price: float,
        direction: str,
        message: str,
    ) -> str:
        if direction not in ("above", "below"):
            raise ValueError("direction must be 'above' or 'below'")
        key = f"{inst_id}:{direction}:{target_price}"
        self._alerts[key] = PriceAlert(
            inst_id=inst_id,
            target_price=float(target_price),
            direction=direction,
            message=message,
        )
        return key

    def remove_alert(self, alert_id: str) -> None:
        self._alerts.pop(alert_id, None)

    def list_alerts(self) -> list[PriceAlert]:
        return list(self._alerts.values())

    def check_once(self) -> None:
        """Poll current prices once and trigger alerts if matched."""
        for alert_id, alert in list(self._alerts.items()):
            try:
                ticker = self._okx.get_ticker(alert.inst_id)
                last_px = self._extract_last_price(ticker)
                if last_px is None:
                    continue
                if self._match(alert, last_px):
                    self._trigger(alert, last_px)
                    self._alerts.pop(alert_id, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Price alert check failed for %s: %s", alert.inst_id, exc)

    def _extract_last_price(self, ticker_payload: dict) -> float | None:
        data = ticker_payload.get("data")
        if not data:
            return None
        last = data[0].get("last")
        try:
            return float(last)
        except (TypeError, ValueError):
            return None

    def _match(self, alert: PriceAlert, last_px: float) -> bool:
        if alert.direction == "above":
            return last_px >= alert.target_price
        return last_px <= alert.target_price

    def _trigger(self, alert: PriceAlert, last_px: float) -> None:
        alert.last_triggered = datetime.utcnow().isoformat()
        if self._monitoring:
            self._monitoring.raise_alert(
                title="price-alert",
                detail=f"{alert.inst_id} {alert.message} @ {last_px}",
                severity="INFO",
            )
        if self._on_trigger:
            self._on_trigger(alert, last_px)
