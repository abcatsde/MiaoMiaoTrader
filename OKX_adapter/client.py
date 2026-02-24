from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


class OKXApiError(RuntimeError):
    """OKX API error."""


@dataclass
class OKXConfig:
    base_url: str = "https://www.okx.com"
    api_key: str | None = None
    api_secret: str | None = None
    passphrase: str | None = None
    timeout: int = 10
    trade_mode: str = "real"  # real or demo
    max_retries: int = 2
    backoff_base: float = 0.4


class OKXClient:
    """Minimal OKX REST client."""

    def __init__(self, config: OKXConfig) -> None:
        self._config = config

    def get_tickers(self, inst_type: str = "SPOT") -> dict[str, Any]:
        return self._request("GET", "/api/v5/market/tickers", params={"instType": inst_type})

    def get_ticker(self, inst_id: str) -> dict[str, Any]:
        return self._request("GET", "/api/v5/market/ticker", params={"instId": inst_id})

    def get_orderbook(self, inst_id: str, sz: int = 20) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v5/market/books",
            params={"instId": inst_id, "sz": str(sz)},
        )

    def get_trades(self, inst_id: str, limit: int = 100) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v5/market/trades",
            params={"instId": inst_id, "limit": str(limit)},
        )

    def get_instruments(self, inst_type: str = "SPOT") -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v5/public/instruments",
            params={"instType": inst_type},
        )

    def get_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v5/market/candles",
            params={"instId": inst_id, "bar": bar, "limit": str(limit)},
        )

    def get_account_balance(self) -> dict[str, Any]:
        return self._request("GET", "/api/v5/account/balance", signed=True)

    def get_positions(self, inst_type: str = "SPOT") -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v5/account/positions",
            params={"instType": inst_type},
            signed=True,
        )

    def set_leverage(
        self,
        *,
        inst_id: str,
        lever: str,
        mgn_mode: str,
        pos_side: str | None = None,
        ccy: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "instId": inst_id,
            "lever": lever,
            "mgnMode": mgn_mode,
        }
        if pos_side is not None:
            body["posSide"] = pos_side
        if ccy is not None:
            body["ccy"] = ccy
        return self._request("POST", "/api/v5/account/set-leverage", body=body, signed=True)

    def get_open_orders(self, inst_type: str = "SPOT", inst_id: str | None = None) -> dict[str, Any]:
        params: dict[str, str] = {"instType": inst_type}
        if inst_id:
            params["instId"] = inst_id
        return self._request("GET", "/api/v5/trade/orders-pending", params=params, signed=True)

    def get_order(self, inst_id: str, ord_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v5/trade/order",
            params={"instId": inst_id, "ordId": ord_id},
            signed=True,
        )

    def place_order(
        self,
        *,
        inst_id: str,
        td_mode: str,
        side: str,
        ord_type: str,
        sz: str,
        px: str | None = None,
        pos_side: str | None = None,
        reduce_only: bool | None = None,
        cl_ord_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
        }
        if px is not None:
            body["px"] = px
        if pos_side is not None:
            body["posSide"] = pos_side
        if reduce_only is not None:
            body["reduceOnly"] = reduce_only
        if cl_ord_id is not None:
            body["clOrdId"] = cl_ord_id
        return self._request("POST", "/api/v5/trade/order", body=body, signed=True)

    def place_algo_order(self, **payload: Any) -> dict[str, Any]:
        """Place algo order (TP/SL, conditional, OCO, etc.).

        Pass OKX API payload directly, for example:
        {
            "instId": "BTC-USDT",
            "tdMode": "cash",
            "side": "buy",
            "ordType": "conditional",
            "sz": "0.001",
            "tpTriggerPx": "65000",
            "tpOrdPx": "-1",
            "slTriggerPx": "61000",
            "slOrdPx": "-1"
        }
        """
        return self._request("POST", "/api/v5/trade/order-algo", body=payload, signed=True)

    def cancel_order(self, inst_id: str, ord_id: str) -> dict[str, Any]:
        body = {"instId": inst_id, "ordId": ord_id}
        return self._request("POST", "/api/v5/trade/cancel-order", body=body, signed=True)

    def cancel_algo_order(self, algo_id: str, inst_id: str) -> dict[str, Any]:
        body = {"algoId": algo_id, "instId": inst_id}
        return self._request("POST", "/api/v5/trade/cancel-algos", body={"algoId": [body]}, signed=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, str]] = None,
        body: Optional[dict[str, Any]] = None,
        signed: bool = False,
    ) -> dict[str, Any]:
        url = self._config.base_url + path
        if params:
            url += "?" + urlencode(params)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MiaoMiaoTrader/1.0",
        }
        if self._config.trade_mode == "demo":
            headers["x-simulated-trading"] = "1"
        body_str = json.dumps(body) if body else ""

        if signed:
            self._apply_auth_headers(headers, method, path, body_str)

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            req = Request(url, data=body_str.encode("utf-8") if body_str else None, method=method)
            for key, value in headers.items():
                req.add_header(key, value)

            try:
                with urlopen(req, timeout=self._config.timeout) as resp:
                    payload = resp.read().decode("utf-8")
            except HTTPError as exc:
                payload = exc.read().decode("utf-8") if exc.fp else str(exc)
                last_error = OKXApiError(f"HTTPError {exc.code}: {payload}")
            except URLError as exc:
                last_error = OKXApiError(f"Network error: {exc}")
            else:
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError as exc:
                    last_error = OKXApiError(f"Invalid JSON: {payload}")
                else:
                    if data.get("code") not in ("0", 0, None):
                        last_error = OKXApiError(f"OKX error {data.get('code')}: {data.get('msg')}")
                    else:
                        return data

            if attempt < self._config.max_retries:
                time.sleep(self._config.backoff_base * (2**attempt))

        raise last_error or OKXApiError("Request failed")

    def _apply_auth_headers(self, headers: dict[str, str], method: str, path: str, body_str: str) -> None:
        if not (self._config.api_key and self._config.api_secret and self._config.passphrase):
            raise OKXApiError("Missing API key/secret/passphrase for signed request.")
        timestamp = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        message = f"{timestamp}{method}{path}{body_str}"
        signature = base64.b64encode(
            hmac.new(self._config.api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        headers.update(
            {
                "OK-ACCESS-KEY": self._config.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self._config.passphrase,
            }
        )


class OKXAdapter:
    """High-level OKX interface for other modules."""

    def __init__(self, client: OKXClient) -> None:
        self._client = client

    def fetch_account_and_market(
        self,
        *,
        inst_type: str = "SPOT",
        pairs: list[str] | None = None,
        bars: list[str] | None = None,
        candle_limit: int = 100,
    ) -> dict[str, Any]:
        tickers = self._client.get_tickers(inst_type=inst_type)
        balances = self._client.get_account_balance()
        positions = self._client.get_positions(inst_type=inst_type)

        candles: dict[str, Any] = {}
        if pairs and bars:
            for inst_id in pairs:
                for bar in bars:
                    key = f"{inst_id}:{bar}"
                    candles[key] = self._client.get_candles(inst_id=inst_id, bar=bar, limit=candle_limit)

        return {
            "tickers": tickers,
            "balances": balances,
            "positions": positions,
            "candles": candles,
        }

    def place_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._client.place_order(**kwargs)

    def cancel_order(self, inst_id: str, ord_id: str) -> dict[str, Any]:
        return self._client.cancel_order(inst_id=inst_id, ord_id=ord_id)

    def place_algo_order(self, **kwargs: Any) -> dict[str, Any]:
        return self._client.place_algo_order(**kwargs)

    def cancel_algo_order(self, inst_id: str, algo_id: str) -> dict[str, Any]:
        return self._client.cancel_algo_order(algo_id=algo_id, inst_id=inst_id)

    def get_open_orders(self, inst_type: str = "SPOT", inst_id: str | None = None) -> dict[str, Any]:
        return self._client.get_open_orders(inst_type=inst_type, inst_id=inst_id)

    def get_positions(self, inst_type: str = "SWAP") -> dict[str, Any]:
        return self._client.get_positions(inst_type=inst_type)

    def set_leverage(
        self,
        *,
        inst_id: str,
        lever: str,
        mgn_mode: str,
        pos_side: str | None = None,
        ccy: str | None = None,
    ) -> dict[str, Any]:
        return self._client.set_leverage(
            inst_id=inst_id,
            lever=lever,
            mgn_mode=mgn_mode,
            pos_side=pos_side,
            ccy=ccy,
        )

    def get_order(self, inst_id: str, ord_id: str) -> dict[str, Any]:
        return self._client.get_order(inst_id=inst_id, ord_id=ord_id)

    def get_ticker(self, inst_id: str) -> dict[str, Any]:
        return self._client.get_ticker(inst_id=inst_id)

    def get_tickers(self, inst_type: str = "SPOT") -> dict[str, Any]:
        return self._client.get_tickers(inst_type=inst_type)

    def get_orderbook(self, inst_id: str, sz: int = 20) -> dict[str, Any]:
        return self._client.get_orderbook(inst_id=inst_id, sz=sz)

    def get_trades(self, inst_id: str, limit: int = 100) -> dict[str, Any]:
        return self._client.get_trades(inst_id=inst_id, limit=limit)

    def get_instruments(self, inst_type: str = "SPOT") -> dict[str, Any]:
        return self._client.get_instruments(inst_type=inst_type)

    def get_candles(self, inst_id: str, bar: str = "15m", limit: int = 100) -> dict[str, Any]:
        return self._client.get_candles(inst_id=inst_id, bar=bar, limit=limit)
