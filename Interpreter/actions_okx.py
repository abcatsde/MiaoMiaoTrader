from __future__ import annotations

from typing import Any, Dict

from Monitoring import MonitoringClient
from OKX_adapter import OKXAdapter, PriceAlertManager


def build_okx_actions(
    *,
    okx: OKXAdapter,
    alert_manager: PriceAlertManager,
    monitoring: MonitoringClient | None = None,
) -> dict[str, Any]:
    """Return OKX-related action handlers for the executor."""

    def fetch_account_and_market(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
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
            monitoring.increment_stat("request_count")
        result = okx.place_order(**inputs)
        if monitoring:
            monitoring.increment_stat("trade_count")
        return {"outputs": {"order_result": result}}

    def cancel_order(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.cancel_order(inst_id=inputs["inst_id"], ord_id=inputs["ord_id"])
        return {"outputs": {"cancel_result": result}}

    def place_algo_order(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.place_algo_order(**inputs)
        if monitoring:
            monitoring.increment_stat("trade_count")
        return {"outputs": {"algo_order_result": result}}

    def cancel_algo_order(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.cancel_algo_order(inst_id=inputs["inst_id"], algo_id=inputs["algo_id"])
        return {"outputs": {"cancel_algo_result": result}}

    def set_leverage(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.set_leverage(
            inst_id=inputs["inst_id"],
            lever=str(inputs["lever"]),
            mgn_mode=str(inputs.get("mgn_mode", inputs.get("td_mode", "cross"))),
            pos_side=inputs.get("pos_side"),
            ccy=inputs.get("ccy"),
        )
        return {"outputs": {"leverage_result": result}}

    def alert_add(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        alert_id = alert_manager.add_alert(
            inst_id=str(inputs["inst_id"]),
            target_price=float(inputs["target_price"]),
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
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.get_ticker(inst_id=str(inputs["inst_id"]))
        return {"outputs": {"ticker": result}}

    def get_candles(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.get_candles(
            inst_id=str(inputs["inst_id"]),
            bar=str(inputs.get("bar", "15m")),
            limit=int(inputs.get("limit", 100)),
        )
        return {"outputs": {"candles": result}}

    def get_orderbook(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.get_orderbook(inst_id=str(inputs["inst_id"]), sz=int(inputs.get("sz", 20)))
        return {"outputs": {"orderbook": result}}

    def get_trades(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        if monitoring:
            monitoring.increment_stat("request_count")
        result = okx.get_trades(inst_id=str(inputs["inst_id"]), limit=int(inputs.get("limit", 100)))
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
