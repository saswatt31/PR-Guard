"""Provider factory and budget wiring."""

from __future__ import annotations

from app.config.repo import RepoConfig
from app.llm.anthropic import AnthropicClient
from app.llm.base import LLMClient, LLMError
from app.llm.budget import BudgetedLLM
from app.llm.fake import FakeLLM
from app.llm.groq import GroqClient
from app.settings import Settings


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLM()
    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is required for the groq provider")
        return GroqClient(settings.groq_api_key, settings.groq_model)
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for the anthropic provider")
        return AnthropicClient(settings.anthropic_api_key, settings.anthropic_model)
    raise LLMError(f"unsupported LLM provider: {settings.llm_provider}")


def build_budgeted_llm(settings: Settings, config: RepoConfig | None = None) -> BudgetedLLM:
    cfg = config or RepoConfig()
    return BudgetedLLM(
        build_llm_client(settings),
        max_calls=cfg.max_llm_calls or settings.max_llm_calls,
        max_total_tokens=cfg.max_total_tokens or settings.max_total_tokens,
        max_cost_usd=cfg.max_cost_usd if cfg.max_cost_usd is not None else settings.max_cost_usd,
    )
