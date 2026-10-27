"""Tests for structured LLM output parsing."""

from __future__ import annotations

import json

import pytest

from app.agents.parsing import (
    ProposalParseError,
    extract_json,
    first_proposal_for,
    parse_proposals,
)

VALID_CONTENT = (
    'import { add } from "./math";\n'
    'import { expect, it } from "vitest";\n'
    'it("adds", () => expect(add(1, 2)).toBe(3));\n'
)


def envelope(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "file_path": "src/math.add.test.ts",
        "function_name": "add",
        "source_file": "src/math.ts",
        "content": VALID_CONTENT,
        "framework": "vitest",
        "reasoning": "covers add",
    }
    item.update(overrides)
    return {"proposals": [item]}


def test_extract_json_accepts_plain_objects_and_lists() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json("[1, 2]") == [1, 2]


def test_extract_json_strips_markdown_fences() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("```\n[1]\n```") == [1]
    assert extract_json('Before\n```JSON\n{"a": 1}\n```\nAfter') == {"a": 1}


def test_extract_json_recovers_an_object_embedded_in_prose() -> None:
    assert extract_json('Here you go: {"a": {"b": 2}} thanks') == {"a": {"b": 2}}


def test_extract_json_rejects_unparseable_text() -> None:
    with pytest.raises(ProposalParseError, match="no JSON object"):
        extract_json("no json here")

    with pytest.raises(ProposalParseError, match="no JSON object"):
        extract_json("[unterminated")

    with pytest.raises(ProposalParseError, match="invalid"):
        extract_json('{"a": }')


def test_parse_proposals_accepts_an_object_envelope() -> None:
    [proposal] = parse_proposals(json.dumps(envelope()))

    assert proposal.file_path == "src/math.add.test.ts"
    assert proposal.function_name == "add"
    assert proposal.source_file == "src/math.ts"
    assert proposal.framework == "vitest"
    assert proposal.reasoning == "covers add"


def test_parse_proposals_accepts_a_bare_list_and_normalizes_slashes() -> None:
    payload = envelope()["proposals"]
    assert isinstance(payload, list)
    payload[0]["file_path"] = "src\\math.add.test.ts"
    payload[0]["source_file"] = "src\\math.ts"

    [proposal] = parse_proposals(json.dumps(payload))

    assert proposal.file_path == "src/math.add.test.ts"
    assert proposal.source_file == "src/math.ts"


def test_parse_proposals_ignores_extra_fields_and_defaults_reasoning() -> None:
    payload = envelope(extra="ignored")
    payload["more"] = True
    assert isinstance(payload["proposals"], list)
    payload["proposals"][0].pop("reasoning")

    [proposal] = parse_proposals(json.dumps(payload))

    assert proposal.reasoning == ""
    assert proposal.framework == "vitest"


def test_parse_proposals_accepts_playwright() -> None:
    [proposal] = parse_proposals(json.dumps(envelope(framework="playwright")))

    assert proposal.framework == "playwright"


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"proposals": []}, "no test proposals"),
        ({"proposals": "nope"}, "schema validation"),
        ({"proposals": [{"file_path": "x"}]}, "schema validation"),
        (envelope(content=""), "schema validation"),
        (envelope(file_path="x" * 501), "schema validation"),
        (envelope(function_name="x" * 301), "schema validation"),
        (envelope(content="x" * 40_001), "schema validation"),
        (envelope(framework="jest"), "unsupported test framework"),
    ],
)
def test_parse_proposals_rejects_invalid_payloads(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ProposalParseError, match=message):
        parse_proposals(json.dumps(payload))


@pytest.mark.parametrize("payload", ['"a string"', "42", "null"])
def test_parse_proposals_requires_an_object_or_list(payload: str) -> None:
    with pytest.raises(ProposalParseError, match="object or list"):
        parse_proposals(payload)


def test_first_proposal_for_matches_function_and_source() -> None:
    [first, second] = parse_proposals(
        json.dumps(
            {
                "proposals": [
                    {
                        "file_path": "src/other.test.ts",
                        "function_name": "other",
                        "source_file": "src/other.ts",
                        "content": VALID_CONTENT,
                    },
                    {
                        "file_path": "src/math.add.test.ts",
                        "function_name": "add",
                        "source_file": "./src/math.ts",
                        "content": VALID_CONTENT,
                    },
                ]
            }
        )
    )

    assert (
        first_proposal_for([first, second], function_name="add", source_file="src/math.ts")
        is second
    )


def test_first_proposal_for_falls_back_to_a_single_proposal() -> None:
    [only] = parse_proposals(json.dumps(envelope(function_name="renamed")))

    assert first_proposal_for([only], function_name="add", source_file="src/math.ts") is only


def test_first_proposal_for_rejects_ambiguous_mismatch() -> None:
    proposals = parse_proposals(
        json.dumps(
            {
                "proposals": [
                    {
                        "file_path": "src/a.test.ts",
                        "function_name": "a",
                        "source_file": "src/a.ts",
                        "content": VALID_CONTENT,
                    },
                    {
                        "file_path": "src/b.test.ts",
                        "function_name": "b",
                        "source_file": "src/b.ts",
                        "content": VALID_CONTENT,
                    },
                ]
            }
        )
    )

    with pytest.raises(ProposalParseError, match="did not contain"):
        first_proposal_for(proposals, function_name="add", source_file="src/math.ts")
