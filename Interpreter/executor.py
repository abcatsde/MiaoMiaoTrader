from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, Optional

from Backtest import BacktestEngine
from Memory import MemoryClient
from Monitoring import MonitoringClient
from Planner import Plan, PlanStep


ActionHandler = Callable[[dict[str, Any], "ExecutionContext"], dict[str, Any]]


@dataclass
class ExecutionContext:
    data: dict[str, Any] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    focus_pairs: list[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    success: bool
    context: ExecutionContext


class Executor:
    """Execute plan steps with monitoring, memory, and optional backtest."""

    def __init__(
        self,
        actions: dict[str, ActionHandler],
        *,
        monitoring: Optional[MonitoringClient] = None,
        memory: Optional[MemoryClient] = None,
        backtest: Optional[BacktestEngine] = None,
    ) -> None:
        self._actions = actions
        self._monitoring = monitoring
        self._memory = memory
        self._backtest = backtest

    def execute(self, plan: Plan) -> ExecutionResult:
        ctx = ExecutionContext()
        if self._monitoring:
            self._monitoring.log_event("plan.start", level="INFO")
            self._monitoring.log_metric("plan.steps", len(plan.steps))

        for step in plan.steps:
            if self._monitoring:
                start_detail = self._format_step_start(step, ctx)
                self._monitoring.log_event(start_detail)

            handler = self._actions.get(step.action)
            if handler is None:
                ctx.errors.append(f"No handler for action: {step.action}")
                if self._monitoring:
                    self._monitoring.raise_alert(
                        title="missing-action",
                        detail=f"No handler for action: {step.action}",
                        severity="ERROR",
                    )
                break

            inputs = self._resolve_inputs(step, ctx)
            result = handler(inputs, ctx)
            self._apply_result(step, result, ctx)

            if self._monitoring:
                done_detail = self._format_step_done(step, result, ctx)
                self._monitoring.log_event(done_detail)

            if ctx.errors:
                break

        success = not ctx.errors
        if self._monitoring:
            self._monitoring.log_event("plan.done" if success else "plan.failed")
        if self._memory:
            self._update_memory(ctx)
        return ExecutionResult(success=success, context=ctx)

    def _format_step_start(self, step: PlanStep, ctx: ExecutionContext) -> str:
        inputs = self._resolve_inputs(step, ctx)
        lang = self._get_log_lang()
        title = self._truncate(step.title)
        if lang == "zh":
            reason = self._truncate(step.reasoning) if step.reasoning else ""
            inputs_text = self._format_kv(inputs, lang="zh")
            parts = [f"步骤{step.step_id}开始：{title or step.action}（{step.action}）"]
            if reason:
                parts.append(f"理由：{reason}")
            if inputs_text:
                parts.append(f"输入：{inputs_text}")
            return "；".join(parts)

        inputs_text = self._format_kv(inputs)
        reasoning = f" | rationale={self._truncate(step.reasoning)}" if step.reasoning else ""
        return f"step.start:{step.step_id}:{step.action} | title={title}{reasoning} | inputs={inputs_text}"

    def _format_step_done(self, step: PlanStep, result: dict[str, Any], ctx: ExecutionContext) -> str:
        outputs = result.get("outputs")
        obs = result.get("observations")
        dec = result.get("decisions")
        err = result.get("errors")
        lang = self._get_log_lang()
        if lang == "zh":
            outputs_text = self._format_kv(outputs, lang="zh") if isinstance(outputs, dict) else self._truncate(outputs)
            parts = [f"步骤{step.step_id}完成：{step.action}"]
            if outputs is not None and outputs_text:
                parts.append(f"输出：{outputs_text}")
            if obs:
                parts.append(f"观察：{self._truncate(obs)}")
            if dec:
                parts.append(f"决策：{self._truncate(dec)}")
            if err:
                parts.append(f"错误：{self._truncate(err)}")
            return "；".join(parts)

        outputs_text = self._format_kv(outputs) if isinstance(outputs, dict) else self._truncate(outputs)
        parts = [f"step.done:{step.step_id}:{step.action}"]
        if outputs is not None:
            parts.append(f"outputs={outputs_text}")
        if obs:
            parts.append(f"observations={self._truncate(obs)}")
        if dec:
            parts.append(f"decisions={self._truncate(dec)}")
        if err:
            parts.append(f"errors={self._truncate(err)}")
        return " | ".join(parts)

    def _format_kv(self, payload: Any, limit: int = 6, lang: str = "en") -> str:
        if not isinstance(payload, dict):
            return self._truncate(payload)
        items = list(payload.items())[:limit]
        if lang == "zh":
            return "、".join(f"{self._translate_key(k)}={self._format_value(self._prettify_value(k, v))}" for k, v in items)
        return "; ".join(f"{k}={self._truncate(v)}" for k, v in items)

    def _format_value(self, value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return "[" + "、".join(self._truncate(v) for v in value) + "]"
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                return self._truncate(value)
        return self._truncate(value)

    def _prettify_value(self, key: str, value: Any) -> Any:
        if key in ("preferences", "pref", "preference") and isinstance(value, dict):
            timeframe = value.get("timeframe")
            max_pairs = value.get("max_pairs")
            market = value.get("market")
            horizon = value.get("horizon")
            parts: list[str] = []
            if timeframe:
                parts.append(f"周期{timeframe}")
            if max_pairs is not None:
                parts.append(f"最多{max_pairs}个币对")
            if isinstance(market, dict):
                m = []
                if market.get("spot"):
                    m.append("现货")
                if market.get("derivatives"):
                    m.append("合约")
                if m:
                    parts.append("市场" + "/".join(m))
            if isinstance(horizon, dict):
                h = []
                if horizon.get("scalp"):
                    h.append("短线")
                if horizon.get("intraday"):
                    h.append("日内")
                if horizon.get("swing"):
                    h.append("中长线")
                if h:
                    parts.append("周期偏好" + "/".join(h))
            return "，".join(parts) if parts else value
        return value

    def _translate_key(self, key: str) -> str:
        mapping = {
            "candidate_pairs": "候选币对",
            "candidates": "候选币对",
            "pairs": "币对",
            "pair": "币对",
            "symbol": "币对",
            "inst_id": "合约标的",
            "timeframes": "周期",
            "timeframe": "周期",
            "bar": "周期",
            "limit": "数量",
            "max_pairs": "最大币对数",
            "max_timeframes": "最大周期数",
            "preferences": "偏好",
            "focus_pairs": "关注币对",
            "focus_timeframes": "关注周期",
        }
        return mapping.get(key, key)

    def _get_log_lang(self) -> str:
        config_path = Path(__file__).resolve().parents[1] / "config" / "app.json"
        if not config_path.exists():
            return "zh"
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            value = data.get("log_lang", "zh")
            return value if value in ("zh", "en") else "zh"
        except Exception:
            return "zh"

    def _truncate(self, value: Any, max_len: int = 300) -> str:
        if isinstance(value, (dict, list, tuple)):
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                text = str(value)
        else:
            text = str(value)
        return text if len(text) <= max_len else text[:max_len] + "..."

    def _resolve_inputs(self, step: PlanStep, ctx: ExecutionContext) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        key_map = {k.lower(): k for k in ctx.data.keys()}
        for key, value in step.inputs.items():
            if isinstance(value, str):
                raw = value.strip()
                if raw in ctx.data:
                    resolved[key] = ctx.data[raw]
                    continue
                match = re.match(r"^\$?([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]$", raw)
                index = None
                var_name = None
                if match:
                    var_name = match.group(1)
                    index = int(match.group(2))
                else:
                    match = re.match(r"^\$?([A-Za-z_][A-Za-z0-9_]*)$", raw)
                    if match:
                        var_name = match.group(1)

                if var_name:
                    lookup_key = key_map.get(var_name.lower())
                    if lookup_key in ctx.data:
                        data_value = ctx.data[lookup_key]
                        if index is not None and isinstance(data_value, (list, tuple)):
                            if 0 <= index < len(data_value):
                                resolved[key] = data_value[index]
                            else:
                                resolved[key] = data_value
                        else:
                            resolved[key] = data_value
                        continue
            resolved[key] = value
        return resolved

    def _apply_result(self, step: PlanStep, result: dict[str, Any], ctx: ExecutionContext) -> None:
        outputs = result.get("outputs", {})
        if isinstance(outputs, dict):
            ctx.data.update(outputs)
        if not outputs and step.outputs and "result" in result:
            ctx.data[step.outputs[0]] = result["result"]

        obs = result.get("observations")
        if obs:
            if isinstance(obs, str):
                ctx.observations.append(obs)
            else:
                ctx.observations.extend([str(o) for o in obs])

        decisions = result.get("decisions")
        if decisions:
            if isinstance(decisions, str):
                ctx.decisions.append(decisions)
            else:
                ctx.decisions.extend([str(d) for d in decisions])

        errors = result.get("errors")
        if errors:
            if isinstance(errors, str):
                ctx.errors.append(errors)
            else:
                ctx.errors.extend([str(e) for e in errors])

        focus_pairs = result.get("focus_pairs")
        if focus_pairs:
            if isinstance(focus_pairs, str):
                ctx.focus_pairs.append(focus_pairs)
            else:
                ctx.focus_pairs.extend([str(p) for p in focus_pairs])

        metrics = result.get("metrics")
        if self._monitoring and isinstance(metrics, dict):
            for name, value in metrics.items():
                try:
                    self._monitoring.log_metric(name, float(value))
                except (TypeError, ValueError):
                    continue

        alerts = result.get("alerts")
        if self._monitoring and isinstance(alerts, Iterable):
            for alert in alerts:
                if not isinstance(alert, dict):
                    continue
                self._monitoring.raise_alert(
                    title=str(alert.get("title", "alert")),
                    detail=str(alert.get("detail", "")),
                    severity=str(alert.get("severity", "WARN")),
                )

        backtest_payload = result.get("backtest")
        if backtest_payload and self._backtest:
            candles = backtest_payload.get("candles", [])
            signal_fn = backtest_payload.get("signal_fn")
            if candles and callable(signal_fn):
                bt_result = self._backtest.run(candles, signal_fn)
                ctx.data["backtest_result"] = bt_result

    def _update_memory(self, ctx: ExecutionContext) -> None:
        if not self._memory:
            return
        observations = "\n".join(ctx.observations) if ctx.observations else None
        decisions = "\n".join(ctx.decisions) if ctx.decisions else None
        self._memory.upsert_focus_pairs(ctx.focus_pairs)
        if observations or decisions:
            self._memory.add_summary(
                kind="session",
                content="\n".join(filter(None, [observations, decisions])),
            )
        if ctx.errors:
            for err in ctx.errors:
                self._memory.add_error_learning(err, "needs-review")

        self._memory.decay_focus_pairs()
        self._memory.prune_focus_pairs()
        self._memory.apply_retention()
