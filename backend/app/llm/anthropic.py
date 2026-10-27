"""Anthropic Messages API adapter."""

from __future__ import annotations

import httpx

from app.llm.base import LLMError, LLMResponse, Message
from app.llm.pricing import estimate_cost


class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.anthropic.com/v1",
        http: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for the anthropic provider")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        system_parts = [
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        ]
        chat_messages = [
            {
                "role": "assistant" if message.get("role") == "assistant" else "user",
                "content": str(message.get("content", "")),
            }
            for message in messages
            if message.get("role") != "system"
        ]
        payload: dict[str, object] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if json_mode:
            # The Messages API has no OpenAI-style response_format; the prompt already
            # requires JSON. Keeping this flag explicit documents the difference.
            payload["metadata"] = {"user_id": "prguard"}
        try:
            response = await self._http.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise LLMError(
                f"Anthropic returned HTTP {response.status_code}: {_safe_text(response)}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Anthropic returned non-JSON content") from exc
        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(blocks, list):
            raise LLMError("Anthropic response did not contain content blocks")
        text = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text:
            raise LLMError("Anthropic response contained no text block")
        usage = data.get("usage") if isinstance(data, dict) else None
        input_tokens = int((usage or {}).get("input_tokens", 0) or 0)
        output_tokens = int((usage or {}).get("output_tokens", 0) or 0)
        model = str(data.get("model", self.model))
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(model, input_tokens, output_tokens),
        )


def _safe_text(response: httpx.Response) -> str:
    return response.text.replace("\n", " ")[:400] or "empty response"
