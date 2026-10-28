"""Tests for provider adapters, pricing, FakeLLM and factory wiring."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.agents.parsing import parse_proposals
from app.agents.prompts import build_test_prompt
from app.config.repo import RepoConfig
from app.diff.models import FunctionInfo
from app.llm.anthropic import AnthropicClient
from app.llm.base import LLMError, LLMResponse, estimate_tokens
from app.llm.budget import BudgetedLLM
from app.llm.factory import build_budgeted_llm, build_llm_client
from app.llm.fake import FakeLLM
from app.llm.groq import GroqClient
from app.llm.pricing import estimate_cost
from app.settings import Settings


def function_info(**overrides: object) -> FunctionInfo:
    values: dict[str, object] = {
        "name": "add",
        "qualified_name": "add",
        "file_path": "src/math.ts",
        "signature": "add(a: number, b: number): number",
        "source": "export function add(a: number, b: number) { return a + b; }",
        "start_line": 1,
        "end_line": 3,
        "exported": True,
    }
    values.update(overrides)
    return FunctionInfo(**values)  # type: ignore[arg-type]


def mock_http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_estimate_tokens_has_a_floor_and_scales_with_length() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("x" * 40) == 10


def test_llm_response_total_tokens() -> None:
    response = LLMResponse("ok", "m", input_tokens=7, output_tokens=5, cost_usd=0.0)

    assert response.total_tokens == 12


def test_pricing_known_unknown_and_fake_models() -> None:
    assert estimate_cost("fake", 1_000_000, 1_000_000) == 0.0
    assert estimate_cost("unknown-model", 1_000_000, 1_000_000) == 0.0
    assert estimate_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000) == pytest.approx(18.0)
    assert estimate_cost("llama-3.3-70b-versatile", 1_000_000, 1_000_000) == pytest.approx(1.38)


async def test_groq_client_sends_request_and_parses_usage() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "llama-3.3-70b-versatile",
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    http = mock_http(handler)
    client = GroqClient("unit-test-key", "llama-3.3-70b-versatile", http=http)
    try:
        response = await client.complete(
            [{"role": "user", "content": "hi"}],
            max_tokens=99,
            temperature=0.2,
            json_mode=True,
        )
    finally:
        await http.aclose()

    assert response.text == "hello"
    assert response.model == "llama-3.3-70b-versatile"
    assert response.input_tokens == 100
    assert response.output_tokens == 50
    assert response.cost_usd == pytest.approx(0.0000985)
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["auth"] == "Bearer unit-test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 99
    assert body["temperature"] == 0.2
    assert body["response_format"] == {"type": "json_object"}


async def test_groq_client_omits_json_mode_and_usage_metadata_when_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "plain"}}]})

    http = mock_http(handler)
    client = GroqClient("secret", "custom-model", http=http)
    try:
        response = await client.complete([{"role": "user", "content": "hi"}])
    finally:
        await http.aclose()

    assert response.model == "custom-model"
    assert response.input_tokens == 0
    assert response.output_tokens == 0
    assert response.cost_usd == 0.0


async def test_groq_requires_api_key() -> None:
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        GroqClient("", "model")


async def test_groq_http_error_is_sanitized_and_truncated() -> None:
    http = mock_http(lambda request: httpx.Response(500, text="bad\nrequest"))
    client = GroqClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="Groq returned HTTP 500: bad request"):
            await client.complete([])
    finally:
        await http.aclose()


async def test_groq_empty_error_body_is_reported() -> None:
    http = mock_http(lambda request: httpx.Response(401, text=""))
    client = GroqClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="empty response"):
            await client.complete([])
    finally:
        await http.aclose()


async def test_groq_network_failure_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    http = mock_http(handler)
    client = GroqClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="Groq request failed: ConnectError"):
            await client.complete([])
    finally:
        await http.aclose()


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 42}}]},
        {},
    ],
)
async def test_groq_malformed_payloads_are_rejected(payload: dict[str, object]) -> None:
    http = mock_http(lambda request: httpx.Response(200, json=payload))
    client = GroqClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError):
            await client.complete([])
    finally:
        await http.aclose()


async def test_groq_non_json_payload_is_rejected() -> None:
    http = mock_http(lambda request: httpx.Response(200, text="<html>"))
    client = GroqClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="non-JSON"):
            await client.complete([])
    finally:
        await http.aclose()


async def test_groq_aclose_only_closes_owned_clients() -> None:
    injected = mock_http(lambda request: httpx.Response(200, json={}))
    injected_client = GroqClient("secret", "model", http=injected)
    await injected_client.aclose()
    assert injected.is_closed is False
    await injected.aclose()

    owned = GroqClient("secret", "model")
    await owned.aclose()
    assert owned._http.is_closed is True


async def test_anthropic_client_moves_system_messages_and_parses_blocks() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers["x-api-key"]
        captured["version"] = request.headers["anthropic-version"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-4-20250514",
                "content": [
                    {"type": "text", "text": "first "},
                    {"type": "tool_use", "id": "x"},
                    {"type": "text", "text": "second"},
                ],
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        )

    http = mock_http(handler)
    client = AnthropicClient("secret", "claude-sonnet-4-20250514", http=http)
    try:
        response = await client.complete(
            [
                {"role": "system", "content": "sys one"},
                {"role": "system", "content": "sys two"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "tool", "content": "tool result"},
            ],
            max_tokens=77,
            temperature=0.3,
            json_mode=True,
        )
    finally:
        await http.aclose()

    assert response.text == "first second"
    assert response.input_tokens == 1000
    assert response.output_tokens == 500
    assert response.cost_usd == pytest.approx(0.0105)
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["key"] == "secret"
    assert captured["version"] == "2023-06-01"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["system"] == "sys one\n\nsys two"
    assert body["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "tool result"},
    ]
    assert body["metadata"] == {"user_id": "prguard"}


async def test_anthropic_without_system_or_json_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "system" not in body
        assert "metadata" not in body
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
        )

    http = mock_http(handler)
    client = AnthropicClient("secret", "custom", http=http)
    try:
        response = await client.complete([{"role": "user", "content": "hi"}])
    finally:
        await http.aclose()

    assert response.model == "custom"
    assert response.cost_usd == 0.0


async def test_anthropic_requires_api_key() -> None:
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        AnthropicClient("", "model")


@pytest.mark.parametrize(
    "payload",
    [
        {"content": "not a list"},
        {},
        {"content": [{"type": "tool_use"}]},
    ],
)
async def test_anthropic_malformed_payloads_are_rejected(payload: dict[str, object]) -> None:
    http = mock_http(lambda request: httpx.Response(200, json=payload))
    client = AnthropicClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError):
            await client.complete([])
    finally:
        await http.aclose()


async def test_anthropic_http_and_network_errors_are_wrapped() -> None:
    http = mock_http(lambda request: httpx.Response(400, text="bad\nrequest"))
    client = AnthropicClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="Anthropic returned HTTP 400: bad request"):
            await client.complete([])
    finally:
        await http.aclose()

    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    http = mock_http(failing)
    client = AnthropicClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="Anthropic request failed: ReadTimeout"):
            await client.complete([])
    finally:
        await http.aclose()


async def test_anthropic_non_json_and_empty_error_body() -> None:
    http = mock_http(lambda request: httpx.Response(200, text="nope"))
    client = AnthropicClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="non-JSON"):
            await client.complete([])
    finally:
        await http.aclose()

    http = mock_http(lambda request: httpx.Response(503, text=""))
    client = AnthropicClient("secret", "model", http=http)
    try:
        with pytest.raises(LLMError, match="empty response"):
            await client.complete([])
    finally:
        await http.aclose()


async def test_anthropic_aclose_only_closes_owned_clients() -> None:
    injected = mock_http(lambda request: httpx.Response(200, json={}))
    injected_client = AnthropicClient("secret", "model", http=injected)
    await injected_client.aclose()
    assert injected.is_closed is False
    await injected.aclose()

    owned = AnthropicClient("secret", "model")
    await owned.aclose()
    assert owned._http.is_closed is True


async def test_fake_llm_writes_a_valid_named_test() -> None:
    llm = FakeLLM()
    prompt = build_test_prompt(function_info(), test_path="src/math.add.test.ts", reason="no test")

    response = await llm.complete(prompt, json_mode=True)
    [proposal] = parse_proposals(response.text)

    assert proposal.file_path == "src/math.add.test.ts"
    assert proposal.function_name == "add"
    assert proposal.source_file == "src/math.ts"
    assert 'import { add } from "./math";' in proposal.content
    assert "expect(result).toBe(result);" in proposal.content
    assert response.cost_usd == 0.0
    assert response.input_tokens >= 1
    assert response.output_tokens >= 1


async def test_fake_llm_default_export_and_ui_environment() -> None:
    llm = FakeLLM()
    prompt = build_test_prompt(
        function_info(
            name="default",
            qualified_name="default",
            file_path="src/widget.tsx",
            signature="default(props: Props): JSX.Element",
            is_ui=True,
        ),
        test_path="src/widget.test.tsx",
    )

    response = await llm.complete(prompt)
    [proposal] = parse_proposals(response.text)

    assert proposal.content.startswith("// @vitest-environment jsdom")
    assert 'import target from "./widget";' in proposal.content
    assert "(target as any)(...args)" in proposal.content


async def test_fake_llm_handles_classes_objects_and_async_functions() -> None:
    llm = FakeLLM()
    class_prompt = build_test_prompt(
        function_info(
            name="increment",
            qualified_name="Counter.increment",
            file_path="src/counter.ts",
            signature="increment(by: number): number",
            is_async=True,
            container="Counter",
        ),
        test_path="src/counter.test.ts",
    )
    [class_proposal] = parse_proposals((await llm.complete(class_prompt)).text)

    assert 'import { Counter } from "./counter";' in class_proposal.content
    assert "new (Counter as any)(...args)" in class_proposal.content
    assert "await ((instance as any).increment as any)(...args)" in class_proposal.content

    object_prompt = build_test_prompt(
        function_info(
            name="fetch",
            qualified_name="api.fetch",
            file_path="src/api.ts",
            signature="fetch(id: string)",
            container="api",
        ),
        test_path="src/api.test.ts",
    )
    [object_proposal] = parse_proposals((await llm.complete(object_prompt)).text)

    assert 'import { api } from "./api";' in object_proposal.content
    assert "const instance = api as any;" in object_proposal.content
    assert "const result = ((instance as any).fetch as any)(...args);" in object_proposal.content


async def test_fake_llm_falls_back_for_missing_or_malformed_metadata() -> None:
    llm = FakeLLM()

    response = await llm.complete(
        [
            {
                "role": "user",
                "content": (
                    "<TASK>write_test</TASK>"
                    "<FUNCTION_JSON>{not json}</FUNCTION_JSON>"
                    "<TEST_PATH>src/fallback.test.ts</TEST_PATH>"
                ),
            }
        ]
    )
    [proposal] = parse_proposals(response.text)
    assert proposal.file_path == "src/fallback.test.ts"
    assert proposal.function_name == "default"

    response = await llm.complete(
        [
            {
                "role": "user",
                "content": (
                    '<TASK>write_test</TASK><FUNCTION_JSON>{"name": "add"}</FUNCTION_JSON>'
                ),
            }
        ]
    )
    [proposal] = parse_proposals(response.text)
    assert proposal.file_path == "src/index.test.ts"
    assert proposal.function_name == "add"


async def test_fake_llm_review_fallback_and_unknown_task() -> None:
    llm = FakeLLM()

    review = await llm.complete([{"role": "user", "content": "<TASK>review</TASK>"}])
    assert "FakeLLM review" in review.text

    unknown = await llm.complete([{"role": "user", "content": "<TASK>something</TASK>"}])
    assert json.loads(unknown.text) == {"proposals": []}


async def test_fake_llm_uses_scripted_responses_and_callables() -> None:
    seen: list[list[dict[str, str]]] = []

    def responder(messages: list[dict[str, str]]) -> str:
        seen.append(messages)
        return "scripted"

    llm = FakeLLM(["first", responder])
    first = await llm.complete([{"role": "user", "content": "a" * 40}])
    second = await llm.complete([{"role": "user", "content": "b" * 80}])

    assert first.text == "first"
    assert second.text == "scripted"
    assert seen == [[{"role": "user", "content": "b" * 80}]]
    assert first.input_tokens == 10
    assert second.input_tokens == 20


async def test_factory_builds_each_provider(settings: Settings) -> None:
    fake = build_llm_client(settings)
    assert isinstance(fake, FakeLLM)

    groq_settings = Settings(_env_file=None, llm_provider="groq", groq_api_key="key")
    groq = build_llm_client(groq_settings)
    assert isinstance(groq, GroqClient)
    assert groq.model == "llama-3.3-70b-versatile"
    await groq.aclose()

    anthropic_settings = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="key")
    anthropic = build_llm_client(anthropic_settings)
    assert isinstance(anthropic, AnthropicClient)
    assert anthropic.model == "claude-sonnet-4-20250514"
    await anthropic.aclose()


@pytest.mark.parametrize(
    "provider,missing",
    [("groq", "GROQ_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")],
)
def test_factory_requires_provider_keys(provider: str, missing: str) -> None:
    values: dict[str, object] = {"llm_provider": provider}
    settings = Settings.model_construct(_env_file=None, **values)
    with pytest.raises(LLMError, match=missing):
        build_llm_client(settings)


def test_factory_rejects_unknown_provider() -> None:
    settings = Settings.model_construct(llm_provider="mystery")
    with pytest.raises(LLMError, match="unsupported LLM provider"):
        build_llm_client(settings)


def test_budget_wiring_uses_repo_overrides_and_settings_fallbacks(settings: Settings) -> None:
    overridden = build_budgeted_llm(
        settings,
        RepoConfig(max_llm_calls=5, max_total_tokens=20000, max_cost_usd=0.0),
    )

    assert isinstance(overridden, BudgetedLLM)
    assert overridden.max_calls == 5
    assert overridden.max_total_tokens == 20000
    assert overridden.max_cost_usd == 0.0

    fallback = build_budgeted_llm(settings)
    assert fallback.max_calls == settings.max_llm_calls
    assert fallback.max_total_tokens == settings.max_total_tokens
    assert fallback.max_cost_usd == settings.max_cost_usd
