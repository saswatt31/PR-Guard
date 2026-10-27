"""Parse and validate structured LLM output."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.models import TestProposal


class ProposalParseError(ValueError):
    """The LLM response could not be turned into a safe test proposal."""


class LLMProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_path: str = Field(min_length=1, max_length=500)
    function_name: str = Field(min_length=1, max_length=300)
    source_file: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=40_000)
    framework: str = "vitest"
    reasoning: str = Field(default="", max_length=2_000)


class LLMEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proposals: list[LLMProposal] = Field(default_factory=list)


def extract_json(text: str) -> Any:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ProposalParseError("LLM response contained no JSON object") from None
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProposalParseError(f"LLM response JSON is invalid: {exc}") from exc


def parse_proposals(text: str) -> list[TestProposal]:
    data = extract_json(text)
    if isinstance(data, list):
        payload = {"proposals": data}
    elif isinstance(data, dict):
        payload = data
    else:
        raise ProposalParseError("LLM response JSON must be an object or list")
    try:
        envelope = LLMEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise ProposalParseError(f"LLM proposal schema validation failed: {exc}") from exc
    if not envelope.proposals:
        raise ProposalParseError("LLM returned no test proposals")
    proposals: list[TestProposal] = []
    for item in envelope.proposals:
        if item.framework not in {"vitest", "playwright"}:
            raise ProposalParseError(f"unsupported test framework: {item.framework}")
        proposals.append(
            TestProposal(
                file_path=item.file_path.replace("\\", "/"),
                function_name=item.function_name,
                source_file=item.source_file.replace("\\", "/"),
                content=item.content,
                framework=item.framework,
                reasoning=item.reasoning,
            )
        )
    return proposals


def first_proposal_for(
    proposals: list[TestProposal], *, function_name: str, source_file: str
) -> TestProposal:
    for proposal in proposals:
        if proposal.function_name == function_name and proposal.source_file.lstrip(
            "./"
        ) == source_file.lstrip("./"):
            return proposal
    if len(proposals) == 1:
        return proposals[0]
    raise ProposalParseError("LLM response did not contain a proposal for the requested function")
