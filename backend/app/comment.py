"""Render the single pull-request comment from a verifier result.

Only tests that the sandbox marked verified are included as code. Rejected proposals
are listed by name/reason, never as snippets that a reader could copy and run.
"""

from __future__ import annotations

from app.agents.models import PipelineResult

DEFAULT_MAX_CHARS = 60_000
DEFAULT_MAX_TEST_CHARS = 6_000
MAX_REJECTED = 10
MAX_WARNINGS = 5


def format_pr_comment(
    run_id: str,
    result: PipelineResult,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_test_chars: int = DEFAULT_MAX_TEST_CHARS,
) -> str:
    marker = f"<!-- prguard:run:{_marker_id(run_id)} -->"
    verified = len(result.verified)
    title = f"## PR-Guard: {verified} verified test{'s' if verified != 1 else ''}"
    summary = _summary_lines(result)
    header = "\n".join([marker, title, "", *summary, ""])

    tests = _test_blocks(result, max_test_chars)
    non_test = _non_test_sections(result)
    footer = ""

    selected: list[str] = []
    used = len(header) + len(non_test)
    for block in tests:
        if used + len(block) + 120 > max_chars:
            break
        selected.append(block)
        used += len(block)
    omitted = len(tests) - len(selected)
    if omitted:
        footer = (
            f"\n_{omitted} verified test(s) omitted from this comment because it exceeded "
            "the GitHub size limit; the full content is stored in the PR-Guard run._\n"
        )

    body = header + "".join(selected)
    if verified == 0:
        body += "### Verified tests\n_None._\n"
    body += non_test + footer
    if len(body) > max_chars:
        body = body[: max_chars - 80].rstrip() + "\n\n_Comment truncated at the size limit._\n"
    return body


def _summary_lines(result: PipelineResult) -> list[str]:
    before = result.coverage_before.line_pct if result.coverage_before else None
    after = result.coverage_after.line_pct if result.coverage_after else None
    if before is not None and after is not None:
        delta = result.coverage_delta
        delta_text = f" ({delta:+.2f} pp)" if delta is not None else ""
        coverage = f"{before:.2f}% → {after:.2f}%{delta_text}"
    elif after is not None:
        coverage = f"not measured → {after:.2f}%"
    else:
        coverage = "not measured"

    calls = int(result.cost.get("calls", 0))
    tokens = int(result.cost.get("input_tokens", 0)) + int(result.cost.get("output_tokens", 0))
    cost = float(result.cost.get("cost_usd", 0.0))
    analysis = result.analysis
    return [
        f"**Coverage:** {coverage}",
        f"**LLM:** {calls} call{'s' if calls != 1 else ''} · {tokens:,} tokens · ${cost:.4f}",
        (
            f"**Changed:** {analysis.changed_file_count} file(s) · "
            f"{len(analysis.functions)} function(s) · {len(result.gaps)} gap(s)"
        ),
    ]


def _test_blocks(result: PipelineResult, max_test_chars: int) -> list[str]:
    blocks: list[str] = []
    for proposal in result.verified:
        content = proposal.content
        note = ""
        if len(content) > max_test_chars:
            content = content[:max_test_chars].rstrip() + "\n// … truncated in comment …"
            note = "\n_Test content truncated in this comment._"
        fence = "````" if "```" in content else "```"
        blocks.append(
            "\n".join(
                [
                    "<details>",
                    (
                        f"<summary><code>{_inline(proposal.file_path)}</code> · "
                        f"<code>{_inline(proposal.function_name)}</code></summary>"
                    ),
                    "",
                    f"{fence}ts",
                    content.rstrip(),
                    fence,
                    note,
                    "",
                    "</details>",
                    "",
                ]
            )
        )
    return blocks


def _non_test_sections(result: PipelineResult) -> str:
    sections: list[str] = []
    rejected = result.rejected[:MAX_REJECTED]
    if rejected:
        lines = ["### Not verified", ""]
        for item in rejected:
            proposal = item.proposal
            lines.append(
                f"- `{_inline(proposal.source_file)}` · `{_inline(proposal.function_name)}` "
                f"— {_one_line(item.reason, 300)}"
            )
        if len(result.rejected) > len(rejected):
            lines.append(f"- _{len(result.rejected) - len(rejected)} more not shown._")
        sections.append("\n".join(lines) + "\n")

    warnings = result.errors[:MAX_WARNINGS]
    if warnings:
        lines = ["### Warnings", ""]
        for warning in warnings:
            lines.append(f"- {_one_line(warning, 500)}")
        if len(result.errors) > len(warnings):
            lines.append(f"- _{len(result.errors) - len(warnings)} more not shown._")
        sections.append("\n".join(lines) + "\n")

    if not result.gaps and not result.verified and not result.rejected:
        sections.append("No untested changed functions were found.\n")

    return "".join(sections)


def _inline(value: str) -> str:
    return _one_line(value, 300).replace("`", "'")


def _one_line(value: str, limit: int) -> str:
    text = " ".join(str(value).replace("\x00", "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _marker_id(value: str) -> str:
    safe = "".join(ch for ch in value if ch.isalnum() or ch in "-_:")
    return safe[:120] or "unknown"
