"""Provider-independent LLM interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

Message = dict[str, str]


class LLMError(RuntimeError):
    """The model provider failed or returned an unusable response."""


class BudgetExceeded(LLMError):
    """A per-run call/token/cost cap would be exceeded."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse: ...


def estimate_tokens(text: str) -> int:
    """Cheap, provider-independent estimate used only by the deterministic fake."""

    return max(1, len(text) // 4)
