from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable, Iterable, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMProvider:
    """Single LLM provider wrapper."""

    name: str
    generate: Callable[[str], str]


@dataclass
class LLMConfig:
    """LLM client configuration."""

    max_retries: int = 2


class LLMClient:
    """Multi-provider LLM client with retry and failover."""

    def __init__(self, providers: Sequence[LLMProvider], config: LLMConfig | None = None) -> None:
        self._providers = list(providers)
        self._config = config or LLMConfig()

    def generate(self, prompt: str) -> str:
        if not self._providers:
            logger.error("LLMClient has no providers configured.")
            raise RuntimeError("No LLM providers configured.")

        last_error: Exception | None = None
        for index, provider in enumerate(self._providers, start=1):
            for attempt in range(1, self._config.max_retries + 2):
                try:
                    return provider.generate(prompt)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning(
                        "LLM generate failed (provider %s, attempt %s/%s): %s",
                        provider.name,
                        attempt,
                        self._config.max_retries + 1,
                        exc,
                    )
            logger.error(
                "LLM provider %s exhausted retries, switching to next provider.",
                provider.name,
            )
        raise RuntimeError("LLM generate failed after retries.") from last_error
