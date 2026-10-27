"""Per-run budget accounting and enforcement tests."""

from __future__ import annotations

import pytest

from app.llm.base import BudgetExceeded, LLMError, LLMResponse, Message
from app.llm.budget import BudgetedLLM, CostSummary


class StubClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[Message], dict[str, object]]] = []

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        self.calls.append(
            (
                messages,
                {
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "json_mode": json_mode,
                },
            )
        )
        return self.responses.pop(0)


def response(
    text: str = "ok",
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    cost_usd: float = 0.0,
) -> LLMResponse:
    return LLMResponse(text, "stub", input_tokens, output_tokens, cost_usd)


def test_cost_summary_accumulates_and_serializes() -> None:
    summary = CostSummary()
    summary.add(response(input_tokens=10, output_tokens=5, cost_usd=0.0001))
    summary.add(response(input_tokens=20, output_tokens=7, cost_usd=0.0002))

    assert summary.calls == 2
    assert summary.input_tokens == 30
    assert summary.output_tokens == 12
    assert summary.total_tokens == 42
    assert summary.to_dict() == {
        "calls": 2,
        "input_tokens": 30,
        "output_tokens": 12,
        "cost_usd": 0.0003,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_calls": 0, "max_total_tokens": 10, "max_cost_usd": 1.0},
        {"max_calls": 1, "max_total_tokens": 0, "max_cost_usd": 1.0},
        {"max_calls": 1, "max_total_tokens": 10, "max_cost_usd": -0.1},
    ],
)
def test_invalid_caps_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        BudgetedLLM(StubClient([]), **kwargs)


async def test_passes_through_arguments_and_records_summary() -> None:
    stub = StubClient([response("hello", input_tokens=4, output_tokens=6, cost_usd=0.001)])
    llm = BudgetedLLM(stub, max_calls=3, max_total_tokens=100, max_cost_usd=1.0)
    messages: list[Message] = [{"role": "user", "content": "hi"}]

    result = await llm.complete(messages, max_tokens=42, temperature=0.5, json_mode=True)

    assert result.text == "hello"
    assert stub.calls == [(messages, {"max_tokens": 42, "temperature": 0.5, "json_mode": True})]
    assert llm.summary.to_dict() == {
        "calls": 1,
        "input_tokens": 4,
        "output_tokens": 6,
        "cost_usd": 0.001,
    }


async def test_call_cap_blocks_before_the_provider_is_called() -> None:
    stub = StubClient([response("first")])
    llm = BudgetedLLM(stub, max_calls=1, max_total_tokens=100, max_cost_usd=1.0)

    assert (await llm.complete([])).text == "first"
    with pytest.raises(BudgetExceeded, match="call cap reached"):
        await llm.complete([])

    assert len(stub.calls) == 1
    assert llm.summary.calls == 1


async def test_token_cap_is_checked_after_the_response_is_recorded() -> None:
    stub = StubClient([response(input_tokens=60, output_tokens=40)])
    llm = BudgetedLLM(stub, max_calls=2, max_total_tokens=99, max_cost_usd=1.0)

    with pytest.raises(BudgetExceeded, match="token cap exceeded"):
        await llm.complete([])

    assert llm.summary.calls == 1
    assert llm.summary.total_tokens == 100


async def test_cost_cap_is_checked_after_the_response_is_recorded() -> None:
    stub = StubClient([response(cost_usd=0.01)])
    llm = BudgetedLLM(stub, max_calls=2, max_total_tokens=100, max_cost_usd=0.005)

    with pytest.raises(BudgetExceeded, match="cost cap exceeded"):
        await llm.complete([])

    assert llm.summary.calls == 1
    assert llm.summary.cost_usd == 0.01


async def test_cost_at_the_cap_is_allowed() -> None:
    stub = StubClient([response(cost_usd=0.005)])
    llm = BudgetedLLM(stub, max_calls=2, max_total_tokens=100, max_cost_usd=0.005)

    assert (await llm.complete([])).cost_usd == 0.005


def test_budget_exceeded_is_an_llm_error() -> None:
    assert issubclass(BudgetExceeded, LLMError)
