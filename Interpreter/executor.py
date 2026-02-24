from __future__ import annotations

from dataclasses import dataclass, field
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
                self._monitoring.log_event(f"step.start:{step.step_id}:{step.action}")

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
                self._monitoring.log_event(f"step.done:{step.step_id}:{step.action}")

            if ctx.errors:
                break

        success = not ctx.errors
        if self._monitoring:
            self._monitoring.log_event("plan.done" if success else "plan.failed")
        if self._memory:
            self._update_memory(ctx)
        return ExecutionResult(success=success, context=ctx)

    def _resolve_inputs(self, step: PlanStep, ctx: ExecutionContext) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in step.inputs.items():
            if isinstance(value, str) and value in ctx.data:
                resolved[key] = ctx.data[value]
            else:
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
