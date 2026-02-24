from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json as _json

from Backtest import BacktestEngine
from Interpreter import Executor, build_okx_actions
from LLM import LLMClient, LLMProvider
from Memory import MemoryClient
from Monitoring import MonitoringClient
from OKX_adapter import (
    OKXAdapter,
    OKXClient,
    OKXConfig,
    OKXPrivateWebSocket,
    OKXWebSocketConfig,
    PriceAlertManager,
)
import threading
import asyncio
from Planner import Planner, PlannerConfig, Task
from logging_setup import setup_logging

logger = logging.getLogger(__name__)
def _write_snapshot(payload: dict, name: str = "snapshot.json") -> None:
    snapshot_dir = Path(__file__).resolve().parent / "logs" / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


ROOT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = ROOT_DIR / "config"
APP_CONFIG_PATH = CONFIG_DIR / "app.json"
LLM_CONFIG_PATH = CONFIG_DIR / "llm.json"
OKX_CONFIG_PATH = CONFIG_DIR / "okx.json"


def _load_config() -> dict:
    data: dict = {}
    if APP_CONFIG_PATH.exists():
        data.update(json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8")))
    if LLM_CONFIG_PATH.exists():
        data.update(json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8")))
    if OKX_CONFIG_PATH.exists():
        data.update(json.loads(OKX_CONFIG_PATH.read_text(encoding="utf-8")))
    return data


def _openai_generate(
    endpoint: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: int = 30,
    retries: int = 2,
    backoff_base: float = 0.5,
) -> str:
    url = endpoint.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    data = _json.dumps(payload).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as exc:
            last_error = RuntimeError(f"LLM HTTPError {exc.code}: {exc.read().decode('utf-8')}")
        except URLError as exc:
            last_error = RuntimeError(f"LLM Network error: {exc}")
        else:
            payload = _json.loads(raw)
            if "choices" in payload and payload["choices"]:
                choice = payload["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    return choice["message"]["content"]
                if "text" in choice:
                    return choice["text"]
            last_error = RuntimeError("LLM response missing content")

        if attempt < retries:
            time.sleep(backoff_base * (2**attempt))

    raise last_error or RuntimeError("LLM request failed")


def _build_llm_client(config: dict, monitoring: MonitoringClient | None = None) -> LLMClient:
    providers_cfg = config.get("llm_providers", [])
    timeout = int(config.get("llm_timeout_sec", 30) or 30)
    providers: list[LLMProvider] = []
    for item in providers_cfg:
        if not item.get("enabled", True):
            continue
        endpoint = item.get("endpoint")
        api_key = item.get("api_key")
        model = item.get("model")
        name = item.get("name") or model or "provider"
        if not (endpoint and api_key and model):
            continue

        def _make(endpoint: str, api_key: str, model: str) -> Callable[[str], str]:
            return lambda prompt: _openai_generate(endpoint, api_key, model, prompt, timeout=timeout)

        providers.append(LLMProvider(name=name, generate=_make(endpoint, api_key, model)))

    if not providers:
        raise RuntimeError("No enabled LLM providers configured.")
    return LLMClient(providers=providers, monitoring=monitoring)


def _build_planner(config: dict, llm: LLMClient, memory: MemoryClient, monitoring: MonitoringClient) -> Planner:
    pref = config.get("trading_preferences", {})
    universe_cfg = pref.get("universe", {})
    horizon_cfg = pref.get("horizon", {})
    market_cfg = pref.get("market", {})
    universe = [name for name, enabled in (
        ("主流币", universe_cfg.get("mainstream")),
        ("山寨币", universe_cfg.get("alt")),
    ) if enabled]
    horizon = [name for name, enabled in (
        ("短线", horizon_cfg.get("scalp")),
        ("日内", horizon_cfg.get("intraday")),
        ("中长线", horizon_cfg.get("swing")),
    ) if enabled]
    market = [name for name, enabled in (
        ("现货", market_cfg.get("spot")),
        ("合约", market_cfg.get("derivatives")),
    ) if enabled]
    planner_cfg = PlannerConfig(
        max_pairs=int(pref.get("max_pairs", 2)),
        max_timeframes=int(pref.get("max_timeframes", 2)),
        trading_universe=universe or ["主流币"],
        trading_horizon=horizon or ["日内"],
        trading_market=market or ["现货"],
        allowed_actions=_build_allowed_actions(pref),
    )
    return Planner(llm_client=llm, memory_client=memory, monitoring_client=monitoring, config=planner_cfg)


def _build_okx(config: dict) -> OKXAdapter:
    okx_cfg = config.get("okx", {})
    client = OKXClient(
        OKXConfig(
            base_url=okx_cfg.get("base_url", "https://www.okx.com"),
            api_key=okx_cfg.get("api_key"),
            api_secret=okx_cfg.get("api_secret"),
            passphrase=okx_cfg.get("passphrase"),
            trade_mode=okx_cfg.get("trade_mode", "real"),
        )
    )
    return OKXAdapter(client)


def _start_okx_ws(config: dict, monitoring: MonitoringClient) -> None:
    okx_cfg = config.get("okx", {})
    if not (okx_cfg.get("we_enabled") or okx_cfg.get("ws_enabled")):
        return
    ws_url = okx_cfg.get("ws_url") or "wss://ws.okx.com:8443/ws/v5/business"
    if not isinstance(ws_url, str) or not ws_url.startswith("ws"):
        logger.warning("Invalid ws_url, skipping OKX WebSocket: %s", ws_url)
        return
    ws_config = OKXWebSocketConfig(
        url=ws_url,
        api_key=okx_cfg.get("api_key"),
        api_secret=okx_cfg.get("api_secret"),
        passphrase=okx_cfg.get("passphrase"),
    )
    channels = okx_cfg.get("ws_channels") or ["deposit-info", "withdrawal-info"]

    async def _run() -> None:
        client = OKXPrivateWebSocket(ws_config, monitoring=monitoring)
        await client.start(channels)

    thread = threading.Thread(target=lambda: asyncio.run(_run()), daemon=True)
    thread.start()


def _build_planner_actions(memory: MemoryClient) -> dict[str, Callable[[dict[str, Any], Any], dict[str, Any]]]:
    def select_focus_universe(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        preferences = inputs.get("preferences") or {}
        max_pairs = int(inputs.get("max_pairs", preferences.get("max_pairs", 2)) or 2)
        pairs = inputs.get("pairs") or inputs.get("candidate_pairs") or inputs.get("candidates") or []
        if isinstance(pairs, str):
            pairs = [pairs]
        if not pairs:
            pairs = memory.get_focus_pairs(limit=max_pairs)
        cleaned = [str(p) for p in pairs if p and not str(p).startswith("$")]
        timeframe = preferences.get("timeframe") or inputs.get("timeframe") or "15m"
        timeframes = inputs.get("timeframes") or preferences.get("timeframes") or [timeframe]
        if isinstance(timeframes, str):
            timeframes = [timeframes]
        return {
            "outputs": {
                "focus_pairs": cleaned[:max_pairs],
                "focus_timeframes": list(timeframes),
            }
        }

    def inspect_key_levels(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        pairs = inputs.get("pairs", [])
        timeframes = inputs.get("timeframes", ["15m"])
        obs = f"Focus on {pairs} at {timeframes}. Check trend, support/resistance, volume spikes."
        return {"observations": [obs], "outputs": {"focus_observations": obs}}

    def define_focus_metrics(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        metrics = ["trend", "support_resistance", "volume", "momentum"]
        return {"outputs": {"focus_metrics": metrics}}

    def clarify_goal(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        return {"outputs": {"goal_summary": inputs.get("goal", "")}}

    def collect_context(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        return {"outputs": {"context_snapshot": inputs.get("context", "")}}

    def compose_steps(_inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        return {"outputs": {"draft_plan": "LLM will provide executable steps."}}

    def generate_signal(_inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        return {"outputs": {"signal": "hold"}, "decisions": ["No trade signal"]}

    def risk_check(_inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        return {"outputs": {"risk_result": "ok"}}

    def add_to_watchlist(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        pairs = inputs.get("pairs") or inputs.get("pair") or []
        if isinstance(pairs, str):
            pairs = [pairs]
        memory.upsert_focus_pairs([str(p) for p in pairs])
        return {"outputs": {"watchlist_added": pairs}}

    def set_sleep(inputs: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        seconds = int(inputs.get("seconds", inputs.get("sleep", 0)) or 0)
        reason = str(inputs.get("reason", ""))
        return {"outputs": {"sleep_seconds": max(seconds, 0), "sleep_reason": reason}}

    return {
        "planner.select_focus_universe": select_focus_universe,
        "planner.inspect_key_levels": inspect_key_levels,
        "planner.define_focus_metrics": define_focus_metrics,
        "planner.clarify_goal": clarify_goal,
        "planner.collect_context": collect_context,
        "planner.compose_steps": compose_steps,
        "strategy.generate_signal": generate_signal,
        "risk.check": risk_check,
        "planner.add_to_watchlist": add_to_watchlist,
        "planner.set_sleep": set_sleep,
    }


def _build_allowed_actions(pref: dict) -> list[str]:
    market_cfg = pref.get("market", {})
    allow_spot = bool(market_cfg.get("spot", True))
    allow_deriv = bool(market_cfg.get("derivatives", False))

    actions = [
        "okx.fetch_account_and_market",
        "okx.get_ticker",
        "okx.get_candles",
        "okx.get_orderbook",
        "okx.get_trades",
        "okx.alert.add",
        "okx.alert.check",
        "okx.alert.list",
        "okx.alert.remove",
        "planner.select_focus_universe",
        "planner.inspect_key_levels",
        "planner.add_to_watchlist",
        "planner.set_sleep",
    ]

    if allow_spot or allow_deriv:
        actions.extend([
            "okx.place_order",
            "okx.cancel_order",
        ])

    if allow_deriv:
        actions.extend([
            "okx.place_algo_order",
            "okx.cancel_algo_order",
            "okx.set_leverage",
        ])

    return actions


def _suggest_timeframes(pref: dict) -> list[str]:
    horizon = pref.get("horizon", {})
    if horizon.get("scalp"):
        return ["1m", "5m"]
    if horizon.get("swing"):
        return ["4h", "1d"]
    return ["15m", "1h"]


def _pick_candidate_pairs(tickers_payload: dict, limit: int = 5) -> list[str]:
    data = tickers_payload.get("data") if isinstance(tickers_payload, dict) else None
    if not data:
        return []
    items = []
    for row in data:
        try:
            inst_id = row.get("instId")
            vol = float(row.get("volCcy24h") or row.get("vol24h") or 0)
            if inst_id:
                items.append((inst_id, vol))
        except Exception:
            continue
    items.sort(key=lambda x: x[1], reverse=True)
    return [inst_id for inst_id, _ in items[:limit]]


def _refresh_positions_stats(okx: OKXAdapter, monitoring: MonitoringClient, inst_type: str = "SWAP") -> dict:
    positions_payload: dict = {}
    try:
        positions_payload = okx.get_positions(inst_type=inst_type)
    except Exception:
        positions_payload = {}

    positions_data = positions_payload.get("data") if isinstance(positions_payload, dict) else None
    position_ids = [p.get("instId") for p in (positions_data or []) if isinstance(p, dict)]
    try:
        unrealized = 0.0
        for p in positions_data or []:
            if not isinstance(p, dict):
                continue
            upl = p.get("upl") or p.get("uPnl") or 0
            unrealized += float(upl)
        monitoring.set_stat("pnl_unrealized", str(unrealized))
        monitoring.set_stat("current_positions", json.dumps(position_ids, ensure_ascii=False))
    except Exception:
        monitoring.set_stat("current_positions", json.dumps([], ensure_ascii=False))
    return {"positions": positions_data or [], "position_ids": position_ids}


def run_robot() -> None:
    """Robot main loop using Planner + Executor."""
    setup_logging()
    logger.info("Robot service started.")

    next_check_after = 0.0
    sleep_reason = ""
    startup_positions_fetched = False
    while True:
        now = time.time()
        sleep_active = now < next_check_after

        config = _load_config()
        if not config:
            logger.info("Waiting for config...")
            time.sleep(5)
            continue

        interval = int(config.get("loop_interval_sec", 60))
        providers_cfg = config.get("llm_providers", [])
        enabled_llm = [
            p
            for p in providers_cfg
            if p.get("enabled", True)
            and p.get("endpoint")
            and p.get("api_key")
            and p.get("model")
        ]
        if not enabled_llm:
            logger.warning("LLM未配置大模型，请前往web端或config文件配置。")
            time.sleep(max(interval, 5))
            continue

        try:
            try:
                monitoring = MonitoringClient()
                llm = _build_llm_client(config, monitoring)
            except RuntimeError as exc:
                logger.warning("LLM初始化失败：%s", exc)
                time.sleep(max(interval, 5))
                continue
            memory = MemoryClient()
            planner = _build_planner(config, llm, memory, monitoring)
            okx = _build_okx(config)
            _start_okx_ws(config, monitoring)
            alert_manager = PriceAlertManager(okx, monitoring=monitoring)
            backtest = BacktestEngine()

            if not startup_positions_fetched:
                _refresh_positions_stats(okx, monitoring, inst_type="SWAP")
                startup_positions_fetched = True

            actions = {}
            full_actions = build_okx_actions(okx=okx, alert_manager=alert_manager, monitoring=monitoring)
            allowed = set(_build_allowed_actions(config.get("trading_preferences", {})))
            actions.update({name: handler for name, handler in full_actions.items() if name in allowed})
            actions.update(_build_planner_actions(memory))

            executor = Executor(actions=actions, monitoring=monitoring, memory=memory, backtest=backtest)

            positions_info = _refresh_positions_stats(okx, monitoring, inst_type="SWAP")
            positions_data = positions_info["positions"]
            position_ids = positions_info["position_ids"]
            has_positions = bool(positions_data)

            watchlist = memory.get_focus_pairs(limit=10)
            pref = config.get("trading_preferences", {})
            timeframes = _suggest_timeframes(pref)
            candidates: list[str] = []
            if not has_positions and not sleep_active:
                try:
                    tickers_payload = okx.get_tickers(inst_type="SPOT")
                    candidates = _pick_candidate_pairs(tickers_payload, limit=5)
                except Exception:
                    candidates = []
            base_context = config.get("task_context") or ""
            context = (
                f"Positions: {position_ids}\n"
                f"Watchlist: {watchlist}\n"
                f"Suggested timeframes: {timeframes}\n"
                f"Candidate pairs: {candidates}\n"
                f"Preferences: {config.get('trading_preferences', {})}\n"
                f"{base_context}"
            )

            if sleep_active and not has_positions:
                remaining = int(max(next_check_after - now, 1))
                logger.info("Sleep active (%ss remaining). No positions; skip scan.", remaining)
                time.sleep(min(5, next_check_after - now))
                continue

            if has_positions:
                goal = "优先关注持仓币对，检查风险/止损止盈与关键级别变化。"
            else:
                goal = "无持仓时主动扫描市场机会，若有兴趣币对则深入观察并加入长期关注。"

            override_goal = config.get("task_goal")
            if override_goal:
                goal = override_goal

            if sleep_active and has_positions:
                context = f"Sleep mode active: {int(next_check_after - now)}s remaining.\n" + context

            try:
                plan = planner.plan(Task(goal=goal, context=context))
            except RuntimeError as exc:
                message = str(exc)
                if "No LLM providers configured" in message:
                    logger.warning("LLM未配置大模型，请前往web端或config文件配置。")
                elif "LLM generate failed" in message:
                    logger.warning("LLM请求失败（可能是 endpoint 或 key 错误），稍后重试。")
                else:
                    logger.warning("LLM计划生成失败：%s", exc)
                time.sleep(max(interval, 5))
                continue

            result = executor.execute(plan)
            logger.info("Execution result: %s", result.success)

            sleep_seconds = result.context.data.get("sleep_seconds") if result and result.context else None
            sleep_reason = result.context.data.get("sleep_reason", "") if result and result.context else ""
            if isinstance(sleep_seconds, int) and sleep_seconds > 0:
                next_check_after = time.time() + sleep_seconds
                logger.info("Sleeping for %s seconds. Reason: %s", sleep_seconds, sleep_reason)
                continue

        except Exception as exc:  # noqa: BLE001
            logger.error("Robot loop error: %s", exc)
            try:
                _write_snapshot(
                    {
                        "error": str(exc),
                        "time": time.time(),
                        "config": config,
                    },
                    name=f"error_{int(time.time())}.json",
                )
                monitoring = MonitoringClient()
                monitoring.raise_alert(
                    title="robot-error",
                    detail=str(exc),
                    severity="ERROR",
                )
            except Exception:
                pass

        time.sleep(max(interval, 5))
