from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
from typing import List, Optional, Sequence

from LLM import LLMClient
from Memory import MemoryClient
from Monitoring import MonitoringClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Task:
    """High-level task request for the planner."""

    goal: str
    context: str | None = None


@dataclass(frozen=True)
class PlanStep:
    """A single executable step in a plan."""

    step_id: int
    title: str
    action: str
    reasoning: str | None = None
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Plan:
    """A plan composed of ordered steps."""

    task: Task
    steps: tuple[PlanStep, ...]
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PlannerConfig:
    """Planner configuration options."""

    max_steps: int = 6
    allow_fallback: bool = False
    max_pairs: int = 2
    max_timeframes: int = 2
    trading_universe: list[str] = field(default_factory=lambda: ["主流币"])
    trading_horizon: list[str] = field(default_factory=lambda: ["日内"])
    trading_market: list[str] = field(default_factory=lambda: ["现货"])
    allowed_actions: list[str] = field(default_factory=list)
    memory_focus_limit: int = 5
    memory_summary_limit: int = 5
    memory_error_limit: int = 3


class Planner:
    """LLM-assisted planner.

    The planner can use an LLM callback or fall back to a rule-based plan
    when no LLM is provided.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        memory_client: Optional[MemoryClient] = None,
        monitoring_client: Optional[MonitoringClient] = None,
        config: Optional[PlannerConfig] = None,
    ) -> None:
        self._llm_client = llm_client
        self._memory_client = memory_client
        self._monitoring_client = monitoring_client
        self._config = config or PlannerConfig()

    def plan(self, task: Task) -> Plan:
        if self._llm_client is None:
            logger.error("Planner requires LLM, but no generator was provided.")
            raise RuntimeError("No LLM client provided.")

        prompt = self._build_prompt(task)
        raw = self._llm_client.generate(prompt)
        steps = self._parse_llm_output(raw)
        if not steps:
            raise RuntimeError("LLM returned no valid steps.")
        plan = Plan(task=task, steps=tuple(steps))
        if self._monitoring_client:
            self._monitoring_client.log_event("plan.created", level="INFO")
            self._monitoring_client.log_metric("plan.steps", len(plan.steps))
        return plan

    def _build_prompt(self, task: Task) -> str:
        context_block = f"\nContext:\n{task.context}\n" if task.context else ""
        memory_block = self._build_memory_context()
        actions = self._config.allowed_actions or [
            "okx.fetch_account_and_market",
            "okx.place_order",
            "okx.cancel_order",
            "okx.place_algo_order",
            "okx.cancel_algo_order",
            "okx.set_leverage",
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
        actions_block = "\nAvailable actions:\n" + "\n".join(f"- {a}" for a in actions) + "\n"
        behavior_block = (
            "\nBehavior rules:\n"
            "- If there are open positions, prioritize monitoring positions and related pairs.\n"
            "- If there are no positions/orders, actively scan the market for opportunities.\n"
            "- When interested in a pair, request more data (other timeframes, orderbook, trades).\n"
            "- If a pair is worth long-term attention, add it to the watchlist.\n"
            "- You may set a sleep interval to pause scanning: use planner.set_sleep with seconds.\n"
        )
        policy_block = (
            "\nTrading preferences:\n"
            "- Focus on intraday trading with 15m timeframe. Avoid ultra-short-term or long-term.\n"
            "- Distinguish margin mode: tdMode='isolated' (逐仓) or tdMode='cross' (全仓) when placing orders.\n"
            f"- Universe: {', '.join(self._config.trading_universe)}\n"
            f"- Horizon: {', '.join(self._config.trading_horizon)}\n"
            f"- Market: {', '.join(self._config.trading_market)}\n"
        )
        return (
            "You are a trading assistant planner. "
            "Return an ordered list of steps, each with: title, action, inputs, outputs, and a brief rationale. "
            "Rationale must be short (<= 20 words) and can include a stance like bullish/bearish/neutral. "
            "Use concise steps and no more than the max steps."
            f"\nGoal: {task.goal}"
            f"{context_block}"
            f"{memory_block}"
            f"{actions_block}"
            f"{behavior_block}"
            f"{policy_block}"
            "\nPreferred JSON format:\n"
            '{"steps":[{"title":"...","action":"...","inputs":{...},"outputs":[...],"rationale":"...","stance":"neutral"}]}\n'
            "Fallback text format:\n"
            "1. Title | Action | Inputs=k:v;... | Outputs=a,b,c | Rationale=... | Stance=neutral\n"
        )

    def _build_memory_context(self) -> str:
        if self._memory_client is None:
            return ""
        focus_pairs = self._memory_client.get_focus_pairs(
            limit=self._config.memory_focus_limit
        )
        summaries = self._memory_client.get_recent_summaries(
            kind="session",
            limit=self._config.memory_summary_limit,
        )
        error_learnings = self._memory_client.get_recent_error_learnings(
            limit=self._config.memory_error_limit
        )
        parts: list[str] = []
        if focus_pairs:
            parts.append("Focus pairs: " + ", ".join(focus_pairs))
        if summaries:
            parts.append("Recent summaries:\n- " + "\n- ".join(summaries))
        if error_learnings:
            parts.append("Recent error learnings:\n- " + "\n- ".join(error_learnings))
        if not parts:
            return ""
        return "\nMemory:\n" + "\n".join(parts) + "\n"

    def update_memory(
        self,
        *,
        focus_pairs: Sequence[str] | None = None,
        observations: str | None = None,
        decisions: str | None = None,
        errors: Sequence[str] | None = None,
    ) -> None:
        if self._memory_client is None:
            logger.warning("Memory client not configured; skip memory update.")
            return
        if focus_pairs:
            self._memory_client.upsert_focus_pairs(focus_pairs)

        if observations or decisions:
            summary_prompt = (
                "Summarize the session into 3-5 bullet points focusing on: "
                "(1) pairs to keep watching, (2) key levels, (3) rationale. "
                "Keep it concise.\n"
                f"Observations:\n{observations or ''}\n"
                f"Decisions:\n{decisions or ''}\n"
            )
            summary = self._llm_client.generate(summary_prompt) if self._llm_client else ""
            if summary:
                self._memory_client.add_summary(kind="session", content=summary)

        if errors:
            error_text = "\n".join(f"- {e}" for e in errors if e and e.strip())
            if error_text:
                lesson_prompt = (
                    "Summarize the mistakes and the lessons learned. "
                    "Return in format: error -> lesson, one per line.\n"
                    f"Errors:\n{error_text}\n"
                )
                lessons_raw = (
                    self._llm_client.generate(lesson_prompt) if self._llm_client else ""
                )
                for line in lessons_raw.splitlines():
                    if "->" not in line:
                        continue
                    error, lesson = line.split("->", 1)
                    self._memory_client.add_error_learning(error, lesson)

        self._memory_client.decay_focus_pairs()
        self._memory_client.prune_focus_pairs()
        self._memory_client.apply_retention()

    def _parse_llm_output(self, raw: str) -> List[PlanStep]:
        json_steps = self._parse_json_steps(raw)
        if json_steps:
            return json_steps
        steps: List[PlanStep] = []
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        for line in lines:
            if not line[0].isdigit():
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            title = parts[0].split(".", 1)[-1].strip() or "Step"
            action = parts[1]
            inputs = self._parse_kv(parts[2]) if len(parts) > 2 else {}
            outputs = self._parse_list(parts[3]) if len(parts) > 3 else []
            rationale = None
            if len(parts) > 4:
                rationale = self._strip_prefix(parts[4], ["Rationale=", "理由="])
            if len(parts) > 5:
                stance = self._strip_prefix(parts[5], ["Stance=", "态度="])
                if stance:
                    rationale = f"{rationale or ''} stance={stance}".strip()
            steps.append(
                PlanStep(
                    step_id=len(steps) + 1,
                    title=title,
                    action=action,
                    reasoning=rationale,
                    inputs=inputs,
                    outputs=outputs,
                )
            )
            if len(steps) >= self._config.max_steps:
                break
        return steps

    def _parse_json_steps(self, raw: str) -> list[PlanStep] | None:
        payload = self._extract_json(raw)
        if payload is None:
            return None
        try:
            data = json.loads(payload)
        except Exception:  # noqa: BLE001
            return None

        items = None
        if isinstance(data, dict):
            items = data.get("steps")
        elif isinstance(data, list):
            items = data

        if not isinstance(items, list):
            return None

        steps: list[PlanStep] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action = item.get("action") or item.get("action_name") or item.get("tool")
            title = item.get("title") or item.get("name") or "Step"
            if not action:
                continue
            inputs = item.get("inputs") or item.get("args") or {}
            outputs = item.get("outputs") or item.get("return") or []
            rationale = item.get("rationale") or item.get("reasoning") or item.get("decision")
            stance = item.get("stance") or item.get("attitude")
            if stance:
                rationale = f"{rationale or ''} stance={stance}".strip()
            if not isinstance(inputs, dict):
                inputs = {}
            if isinstance(outputs, str):
                outputs = [outputs]
            if not isinstance(outputs, list):
                outputs = []

            steps.append(
                PlanStep(
                    step_id=len(steps) + 1,
                    title=str(title),
                    action=str(action),
                    reasoning=str(rationale) if rationale else None,
                    inputs={str(k): str(v) for k, v in inputs.items()},
                    outputs=[str(x) for x in outputs],
                )
            )
            if len(steps) >= self._config.max_steps:
                break
        return steps or None

    def _extract_json(self, raw: str) -> str | None:
        text = raw.strip()
        if not text:
            return None
        if text[0] in "[{":
            end = "]" if text[0] == "[" else "}"
            if text.endswith(end):
                return text
        first_obj = text.find("{")
        first_arr = text.find("[")
        if first_obj == -1 and first_arr == -1:
            return None
        if first_arr != -1 and (first_obj == -1 or first_arr < first_obj):
            last = text.rfind("]")
            if last != -1:
                return text[first_arr:last + 1]
        if first_obj != -1:
            last = text.rfind("}")
            if last != -1:
                return text[first_obj:last + 1]
        return None

    def _parse_kv(self, segment: str) -> dict[str, str]:
        if "=" not in segment:
            return {}
        _, payload = segment.split("=", 1)
        items = [item.strip() for item in payload.split(";") if item.strip()]
        result: dict[str, str] = {}
        for item in items:
            if ":" not in item:
                continue
            key, value = item.split(":", 1)
            result[key.strip()] = value.strip()
        return result

    def _parse_list(self, segment: str) -> list[str]:
        if "=" in segment:
            _, payload = segment.split("=", 1)
        else:
            payload = segment
        return [item.strip() for item in payload.split(",") if item.strip()]

    def _strip_prefix(self, text: str, prefixes: list[str]) -> str:
        value = text.strip()
        for prefix in prefixes:
            if value.startswith(prefix):
                return value[len(prefix):].strip()
        return value

    def _fallback_plan(self, task: Task) -> Sequence[PlanStep]:
        goal = task.goal.lower()
        steps: list[PlanStep] = []
        if "下单" in goal or "交易" in goal or "order" in goal:
            steps.extend(
                [
                    PlanStep(
                        step_id=1,
                        title="获取账户、持仓与市场数据",
                        action="okx.fetch_account_and_market",
                        inputs={
                            "scope": "balances, positions, tickers, candles",
                            "max_pairs": str(self._config.max_pairs),
                            "max_timeframes": str(self._config.max_timeframes),
                        },
                        outputs=[
                            "account_snapshot",
                            "position_snapshot",
                            "market_snapshot",
                        ],
                    ),
                    PlanStep(
                        step_id=2,
                        title="聚焦 1-2 个币对与 1-2 个需要关注的级别",
                        action="planner.select_focus_universe",
                        inputs={
                            "market": "market_snapshot",
                            "positions": "position_snapshot",
                            "max_pairs": str(self._config.max_pairs),
                            "max_timeframes": str(self._config.max_timeframes),
                        },
                        outputs=["focus_pairs", "focus_timeframes"],
                    ),
                    PlanStep(
                        step_id=3,
                        title="查看关键级别信息与关注点",
                        action="planner.inspect_key_levels",
                        inputs={
                            "pairs": "focus_pairs",
                            "timeframes": "focus_timeframes",
                            "market": "market_snapshot",
                            "positions": "position_snapshot",
                        },
                        outputs=["focus_observations", "risk_notes"],
                    ),
                    PlanStep(
                        step_id=4,
                        title="生成交易信号",
                        action="strategy.generate_signal",
                        inputs={
                            "market": "market_snapshot",
                            "observations": "focus_observations",
                        },
                        outputs=["signal"],
                    ),
                    PlanStep(
                        step_id=5,
                        title="风险检查",
                        action="risk.check",
                        inputs={"signal": "signal", "account": "account_snapshot"},
                        outputs=["risk_result"],
                    ),
                    PlanStep(
                        step_id=6,
                        title="提交订单",
                        action="okx.place_order",
                        inputs={"signal": "signal", "risk": "risk_result"},
                        outputs=["order_result"],
                    ),
                ]
            )
        else:
            steps.extend(
                [
                    PlanStep(
                        step_id=1,
                        title="理解目标",
                        action="planner.clarify_goal",
                        inputs={"goal": task.goal},
                        outputs=["goal_summary"],
                    ),
                    PlanStep(
                        step_id=2,
                        title="收集所需信息",
                        action="planner.collect_context",
                        inputs={"context": task.context or ""},
                        outputs=["context_snapshot"],
                    ),
                    PlanStep(
                        step_id=3,
                        title="聚焦 1-2 个币对与 1-2 个级别",
                        action="planner.select_focus_universe",
                        inputs={
                            "context": "context_snapshot",
                            "max_pairs": str(self._config.max_pairs),
                            "max_timeframes": str(self._config.max_timeframes),
                        },
                        outputs=["focus_pairs", "focus_timeframes"],
                    ),
                    PlanStep(
                        step_id=4,
                        title="确认需要查看的关键信息与关注点",
                        action="planner.define_focus_metrics",
                        inputs={
                            "pairs": "focus_pairs",
                            "timeframes": "focus_timeframes",
                        },
                        outputs=["focus_metrics"],
                    ),
                    PlanStep(
                        step_id=5,
                        title="生成执行步骤",
                        action="planner.compose_steps",
                        inputs={
                            "goal": "goal_summary",
                            "context": "context_snapshot",
                            "focus": "focus_metrics",
                        },
                        outputs=["draft_plan"],
                    ),
                ]
            )
        return steps[: self._config.max_steps]