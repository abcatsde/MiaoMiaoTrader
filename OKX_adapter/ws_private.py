from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional

import websockets

from Monitoring import MonitoringClient

logger = logging.getLogger(__name__)


@dataclass
class OKXWebSocketConfig:
    url: str = "wss://ws.okx.com:8443/ws/v5/business"
    api_key: str | None = None
    api_secret: str | None = None
    passphrase: str | None = None
    use_server_time: bool = False
    max_retries: int = 5
    backoff_base: float = 0.8


class OKXPrivateWebSocket:
    """Minimal OKX private WebSocket client for deposit/withdrawal info."""

    def __init__(
        self,
        config: OKXWebSocketConfig,
        *,
        monitoring: Optional[MonitoringClient] = None,
        on_message: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._config = config
        self._monitoring = monitoring
        self._on_message = on_message
        self._stop_event = asyncio.Event()

    async def start(self, channels: Iterable[str]) -> None:
        if not (self._config.api_key and self._config.api_secret and self._config.passphrase):
            raise RuntimeError("Missing OKX API key/secret/passphrase for WebSocket login.")
        retry = 0
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self._config.url, ping_interval=20) as ws:
                    await self._login(ws)
                    await self._subscribe(ws, channels)
                    await self._recv_loop(ws)
            except Exception as exc:  # noqa: BLE001
                logger.warning("WS disconnected: %s", exc)
                if self._monitoring:
                    self._monitoring.raise_alert(
                        title="okx-ws-disconnect",
                        detail=str(exc),
                        severity="WARN",
                    )
                if retry >= self._config.max_retries:
                    raise
                await asyncio.sleep(self._config.backoff_base * (2**retry))
                retry += 1

    async def stop(self) -> None:
        self._stop_event.set()

    async def _login(self, ws) -> None:
        ts = self._timestamp()
        sign = self._sign(ts)
        payload = {
            "op": "login",
            "args": [
                {
                    "apiKey": self._config.api_key,
                    "passphrase": self._config.passphrase,
                    "timestamp": ts,
                    "sign": sign,
                }
            ],
        }
        await ws.send(json.dumps(payload))

    async def _subscribe(self, ws, channels: Iterable[str]) -> None:
        args = [{"channel": ch} for ch in channels]
        payload = {"op": "subscribe", "args": args}
        await ws.send(json.dumps(payload))

    async def _recv_loop(self, ws) -> None:
        while not self._stop_event.is_set():
            raw = await ws.recv()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if self._monitoring:
                self._monitoring.log_event("ws.message", level="INFO")

            if self._on_message:
                self._on_message(message)

    def _sign(self, timestamp: str) -> str:
        message = f"{timestamp}GET/users/self/verify"
        mac = hmac.new(
            self._config.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(mac).decode("utf-8")

    def _timestamp(self) -> str:
        return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
