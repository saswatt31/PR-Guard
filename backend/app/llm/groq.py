"""Groq chat-completions adapter (OpenAI-compatible REST)."""

from __future__ import annotations

import httpx

from app.llm.base import LLMError, LLMResponse, Message
from app.llm.pricing import estimate_cost


class GroqClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.groq.com/openai/v1",
        http: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise LLMError("GROQ_API_KEY is required for the groq provider")
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
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = await self._http.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Groq request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise LLMError(f"Groq returned HTTP {response.status_code}: {_safe_text(response)}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Groq returned non-JSON content") from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Groq response did not contain choices[0].message.content") from exc
        if not isinstance(text, str):
            raise LLMError("Groq response content was not text")
        usage = data.get("usage") if isinstance(data, dict) else None
        input_tokens = int((usage or {}).get("prompt_tokens", 0) or 0)
        output_tokens = int((usage or {}).get("completion_tokens", 0) or 0)
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
