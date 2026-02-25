from __future__ import annotations

from typing import Any, Dict
import logging

from Monitoring import MonitoringClient
from OKX_adapter import OKXAdapter, PriceAlertManager


def build_okx_actions(
    *,
    okx: OKXAdapter,
    alert_manager: PriceAlertManager,
    monitoring: MonitoringClient | None = None,
) -> dict[str, Any]:
    """Return OKX-related action handlers for the executor."""

    logger = logging.getLogger(__name__)

    def _resolve_inst_id(inputs: dict[str, Any]) -> str | None:
        inst_id = inputs.get("inst_id") or inputs.get("symbol") or inputs.get("pair") or inputs.get("instrument")
        if isinstance(inst_id, (list, tuple)):
            inst_id = inst_id[0] if inst_id else None
        if inst_id is None:
            return None
        return str(inst_id)

    def _missing_inst_id(action: str) -> dict[str, Any]:
        logger.warning("%s missing inst_id; skip execution.", action)
        return {"outputs": {"error": "missing inst_id"}}

    def fetch_account_and_market(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        pairs = inputs.get("pairs")
        bars = inputs.get("bars")
        inst_type = inputs.get("inst_type", "SPOT")
        data = okx.fetch_account_and_market(
            inst_type=inst_type,
            pairs=list(pairs) if isinstance(pairs, (list, tuple)) else None,
            bars=list(bars) if isinstance(bars, (list, tuple)) else None,
            candle_limit=int(inputs.get("candle_limit", 100)),
        )
        return {"outputs": {
            "market_snapshot": data.get("tickers"),
            "account_snapshot": data.get("balances"),
            "position_snapshot": data.get("positions"),
            "candles": data.get("candles"),
        }}

    def place_order(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        inst_id = _resolve_inst_id(inputs)
        if not inst_id:
            return _missing_inst_id("okx.place_order")

        td_mode = (
            inputs.get("td_mode")
            or inputs.get("tdMode")
            or inputs.get("mgn_mode")
            or inputs.get("margin_mode")
        )
        if not td_mode:
            td_mode = "isolated" if str(inst_id).upper().endswith("-SWAP") else "cash"

        side = inputs.get("side")
        ord_type = inputs.get("ord_type") or inputs.get("ordType") or inputs.get("type")
        sz = inputs.get("sz") or inputs.get("size")
        px = inputs.get("px") or inputs.get("price")

        if not side or not ord_type or sz is None:
            return {
                "outputs": {"error": "missing order params"},
                "decisions": [
                    "下单参数不足：需要 side/ord_type/sz；现货 td_mode=cash，合约 td_mode=isolated/cross。"
                ],
            }

        payload = {
            "inst_id": inst_id,
            "td_mode": str(td_mode),
            "side": str(side),
            "ord_type": str(ord_type),
            "sz": str(sz),
        }
        if px is not None:
            payload["px"] = str(px)
        if inputs.get("pos_side") is not None:
            payload["pos_side"] = inputs.get("pos_side")
        if inputs.get("reduce_only") is not None:
            payload["reduce_only"] = inputs.get("reduce_only")
        if inputs.get("cl_ord_id") is not None:
            payload["cl_ord_id"] = inputs.get("cl_ord_id")

        result = okx.place_order(**payload)
        if monitoring:
            monitoring.increment_stat("trade_count")
        return {"outputs": {"order_result": result}}

    def cancel_order(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        ord_id = inputs.get("ord_id")
        if not inst_id or not ord_id:
            return _missing_inst_id("okx.cancel_order")
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.cancel_order(inst_id=inst_id, ord_id=ord_id)
        return {"outputs": {"cancel_result": result}}

    def place_algo_order(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.place_algo_order(**inputs)
        if monitoring:
            monitoring.increment_stat("trade_count")
        return {"outputs": {"algo_order_result": result}}

    def cancel_algo_order(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        algo_id = inputs.get("algo_id")
        if not inst_id or not algo_id:
            return _missing_inst_id("okx.cancel_algo_order")
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.cancel_algo_order(inst_id=inst_id, algo_id=algo_id)
        return {"outputs": {"cancel_algo_result": result}}

    def set_leverage(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        lever = inputs.get("lever")
        if not inst_id or lever is None:
            return _missing_inst_id("okx.set_leverage")
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.set_leverage(
            inst_id=inst_id,
            lever=str(lever),
            mgn_mode=str(inputs.get("mgn_mode", inputs.get("td_mode", "cross"))),
            pos_side=inputs.get("pos_side"),
            ccy=inputs.get("ccy"),
        )
        return {"outputs": {"leverage_result": result}}

    def alert_add(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        target_price = inputs.get("target_price")
        if not inst_id or target_price is None:
            return _missing_inst_id("okx.alert.add")
        alert_id = alert_manager.add_alert(
            inst_id=inst_id,
            target_price=float(target_price),
            direction=str(inputs.get("direction", "above")),
            message=str(inputs.get("message", "price alert")),
        )
        return {"outputs": {"alert_id": alert_id}}

    def alert_check(_inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        alert_manager.check_once()
        return {"outputs": {"alert_checked": True}}

    def alert_list(_inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        alerts = alert_manager.list_alerts()
        payload = [
            {
                "inst_id": a.inst_id,
                "target_price": a.target_price,
                "direction": a.direction,
                "message": a.message,
                "last_triggered": a.last_triggered,
            }
            for a in alerts
        ]
        return {"outputs": {"alerts": payload}}

    def alert_remove(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        alert_manager.remove_alert(str(inputs["alert_id"]))
        return {"outputs": {"alert_removed": True}}

    def get_ticker(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        if not inst_id:
            return _missing_inst_id("okx.get_ticker")
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.get_ticker(inst_id=inst_id)
        return {"outputs": {"ticker": result}}

    def get_candles(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        if not inst_id:
            return _missing_inst_id("okx.get_candles")
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.get_candles(
            inst_id=inst_id,
            bar=str(inputs.get("bar", "15m")),
            limit=int(inputs.get("limit", 100)),
        )
        return {"outputs": {"candles": result}}

    def get_orderbook(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        if not inst_id:
            return _missing_inst_id("okx.get_orderbook")
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.get_orderbook(inst_id=inst_id, sz=int(inputs.get("sz", 20)))
        return {"outputs": {"orderbook": result}}

    def get_trades(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        inst_id = _resolve_inst_id(inputs)
        if not inst_id:
            return _missing_inst_id("okx.get_trades")
        if monitoring:
            monitoring.increment_stat("okx_request_count")
        result = okx.get_trades(inst_id=inst_id, limit=int(inputs.get("limit", 100)))
        return {"outputs": {"trades": result}}

    return {
        "okx.fetch_account_and_market": fetch_account_and_market,
        "okx.place_order": place_order,
        "okx.cancel_order": cancel_order,
        "okx.place_algo_order": place_algo_order,
        "okx.cancel_algo_order": cancel_algo_order,
        "okx.set_leverage": set_leverage,
        "okx.get_ticker": get_ticker,
        "okx.get_candles": get_candles,
        "okx.get_orderbook": get_orderbook,
        "okx.get_trades": get_trades,
        "okx.alert.add": alert_add,
        "okx.alert.check": alert_check,
        "okx.alert.list": alert_list,
        "okx.alert.remove": alert_remove,
    }
