"""Per-run LLM budget enforcement and accounting."""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.base import BudgetExceeded, LLMClient, LLMResponse, Message


@dataclass
class CostSummary:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, response: LLMResponse) -> None:
        self.calls += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.cost_usd += response.cost_usd

    def to_dict(self) -> dict[str, int | float]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


class BudgetedLLM:
    """Wrap a provider and stop a run before it exceeds its caps.

    The check is intentionally conservative: a call is allowed only while calls remain,
    then the response is recorded and the token/cost caps are checked. A provider that
    ignores ``max_tokens`` can therefore overshoot by one response, but the overshoot is
    visible in the run cost instead of silently continuing.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        max_calls: int,
        max_total_tokens: int,
        max_cost_usd: float,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be positive")
        if max_total_tokens < 1:
            raise ValueError("max_total_tokens must be positive")
        if max_cost_usd < 0:
            raise ValueError("max_cost_usd cannot be negative")
        self.client = client
        self.max_calls = max_calls
        self.max_total_tokens = max_total_tokens
        self.max_cost_usd = max_cost_usd
        self.summary = CostSummary()

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        if self.summary.calls >= self.max_calls:
            raise BudgetExceeded(f"LLM call cap reached ({self.max_calls})")
        response = await self.client.complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
        )
        self.summary.add(response)
        if self.summary.total_tokens > self.max_total_tokens:
            raise BudgetExceeded(
                f"LLM token cap exceeded ({self.summary.total_tokens} > {self.max_total_tokens})"
            )
        if self.summary.cost_usd > self.max_cost_usd + 1e-9:
            raise BudgetExceeded(
                f"LLM cost cap exceeded (${self.summary.cost_usd:.4f} > ${self.max_cost_usd:.4f})"
            )
        return response
