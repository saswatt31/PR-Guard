import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import {
  coverageRange,
  formatCost,
  formatDelta,
  formatDuration,
  formatNumber,
  formatPct,
  shortSha,
  titleCase,
} from "@/lib/format";
import type {
  GeneratedTest,
  RunDetail,
  SandboxExecution,
  Step,
} from "@/lib/types";

function detailChips(detail: Record<string, unknown>): string[] {
  return Object.entries(detail)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .slice(0, 6)
    .map(([key, value]) => {
      if (Array.isArray(value)) return `${key}: ${value.length}`;
      if (typeof value === "object") return `${key}: object`;
      return `${key}: ${String(value)}`;
    });
}

function StepTimeline({ steps }: { steps: Step[] }) {
  if (steps.length === 0) {
    return <p className="detail-note">No agent steps recorded.</p>;
  }
  return (
    <ol className="timeline">
      {steps.map((step) => (
        <li className="timeline-item" key={step.id}>
          <span className={`timeline-dot ${step.status}`} aria-hidden="true">
            {step.sequence}
          </span>
          <div>
            <div className="timeline-topline">
              <span className="timeline-title">
                {step.node}
                {step.attempt > 1 ? ` · attempt ${step.attempt}` : ""}
              </span>
              <span className="timeline-time">{formatDuration(step.duration_ms)}</span>
            </div>
            <p className="timeline-summary">{step.summary || titleCase(step.status)}</p>
            {detailChips(step.detail).length > 0 ? (
              <div className="detail-chips">
                {detailChips(step.detail).map((chip) => (
                  <span className="chip" key={chip}>
                    {chip}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function TestCard({ test }: { test: GeneratedTest }) {
  return (
    <details className="test-card">
      <summary>
        <span className="test-name">
          {test.file_path} · {test.function_name}
        </span>
        <span className="test-arrow" aria-hidden="true">
          +
        </span>
      </summary>
      <div className="code-block">
        <pre>
          <code>{test.content}</code>
        </pre>
      </div>
    </details>
  );
}

function SandboxCard({ run }: { run: SandboxExecution }) {
  const hasLogs = Boolean(run.stdout || run.stderr);
  return (
    <div className="sandbox-card">
      <div className="sandbox-top">
        <span className="sandbox-phase">{run.phase}</span>
        <StatusBadge status={run.status} />
        <span className="chip">{run.network_disabled ? "network off" : "network on"}</span>
        <span className="chip">exit {run.exit_code ?? "—"}</span>
        <span className="chip">{formatDuration(run.duration_ms)}</span>
      </div>
      <p className="sandbox-command" title={run.command.join(" ")}>
        {run.command.join(" ")}
      </p>
      {run.coverage ? (
        <div className="detail-chips">
          <span className="chip">
            coverage line {formatPct(Number(run.coverage.line_pct))}
          </span>
        </div>
      ) : null}
      {hasLogs ? (
        <details className="log-details">
          <summary>View captured output</summary>
          {run.stdout ? <pre className="log">{run.stdout}</pre> : null}
          {run.stderr ? <pre className="log">{run.stderr}</pre> : null}
        </details>
      ) : (
        <p className="detail-note">No output captured.</p>
      )}
    </div>
  );
}

function Metadata({ run }: { run: RunDetail }) {
  const prUrl = `https://github.com/${run.repo_full_name}/pull/${run.pr_number}`;
  return (
    <section className="panel" aria-labelledby="metadata-title">
      <div className="section-head">
        <h2 id="metadata-title">Run metadata</h2>
      </div>
      <div className="section-body">
        <dl className="kv-list">
          <dt>Pull request</dt>
          <dd>
            <a href={prUrl} target="_blank" rel="noreferrer">
              #{run.pr_number} on GitHub ↗
            </a>
          </dd>
          <dt>Head</dt>
          <dd className="mono">{shortSha(run.head_sha)}</dd>
          <dt>Base</dt>
          <dd className="mono">{shortSha(run.base_sha)}</dd>
          <dt>Delivery</dt>
          <dd className="mono">{run.delivery_id}</dd>
          <dt>Sender</dt>
          <dd>{run.sender_login}</dd>
          <dt>Fork</dt>
          <dd>{run.is_fork ? "yes" : "no"}</dd>
          <dt>Files</dt>
          <dd>{formatNumber(run.files_changed)}</dd>
          <dt>Functions</dt>
          <dd>{formatNumber(run.functions_found)}</dd>
          <dt>LLM</dt>
          <dd>
            {formatNumber(run.llm_calls)} calls · {formatNumber(run.input_tokens)} in ·{" "}
            {formatNumber(run.output_tokens)} out
          </dd>
          <dt>Comment</dt>
          <dd>
            {run.comment_url ? (
              <a href={run.comment_url} target="_blank" rel="noreferrer">
                #{run.comment_id} on GitHub ↗
              </a>
            ) : (
              "not posted"
            )}
          </dd>
        </dl>
        {run.error ? (
          <div className="error-panel" role="alert">
            <h2>Run error</h2>
            <p>{run.error}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function RunDetailView({ run }: { run: RunDetail }) {
  const verified = run.tests.filter((test) => test.status === "verified");
  const rejected = run.tests.filter((test) => test.status !== "verified");
  const totalTokens = run.input_tokens + run.output_tokens;
  const prUrl = `https://github.com/${run.repo_full_name}/pull/${run.pr_number}`;

  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link href="/">Run console</Link>
        <span>/</span>
        <span>
          {run.repo_full_name} #{run.pr_number}
        </span>
      </nav>

      <header className="detail-head">
        <div>
          <div className="detail-title-row">
            <h1>{run.repo_full_name}</h1>
            <StatusBadge status={run.status} />
          </div>
          <p className="detail-subtitle">
            <span>Pull request #{run.pr_number}</span>
            <span className="sep">/</span>
            <span className="mono">{shortSha(run.head_sha)}</span>
            <span className="sep">/</span>
            <span>{formatNumber(run.files_changed)} changed files</span>
            <span className="sep">/</span>
            <span>{formatNumber(run.functions_found)} functions</span>
          </p>
        </div>
        <div className="detail-actions">
          <a className="button" href={prUrl} target="_blank" rel="noreferrer">
            Open PR ↗
          </a>
          {run.comment_url ? (
            <a className="button" href={run.comment_url} target="_blank" rel="noreferrer">
              View comment ↗
            </a>
          ) : null}
        </div>
      </header>

      <div className="summary-strip">
        <strong>Result</strong>
        <span>{run.summary ?? "No summary was recorded for this run."}</span>
      </div>

      <section className="detail-metrics" aria-label="Run metrics">
        <article className="metric-card">
          <p className="metric-label">Tests</p>
          <p className="metric-value accent">
            {run.tests_verified}
            <span className="muted" style={{ fontSize: "16px", letterSpacing: 0 }}>
              {" "}
              / {run.tests_generated}
            </span>
          </p>
          <p className="metric-detail">verified / generated</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Coverage</p>
          <p className="metric-value" style={{ fontSize: "25px" }}>
            {coverageRange(run.coverage_before, run.coverage_after)}
          </p>
          <p className="metric-detail">{formatDelta(run.coverage_delta)} across the run</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Duration</p>
          <p className="metric-value">{formatDuration(run.duration_ms)}</p>
          <p className="metric-detail">{formatNumber(run.llm_calls)} LLM calls</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Run cost</p>
          <p className="metric-value">{formatCost(run.cost_usd)}</p>
          <p className="metric-detail">{formatNumber(totalTokens)} tokens</p>
        </article>
      </section>

      <div className="detail-grid">
        <div className="detail-column">
          <section className="panel" aria-labelledby="verified-title">
            <div className="section-head">
              <h2 id="verified-title">Verified tests</h2>
              <span className="count">{verified.length}</span>
            </div>
            <div className="section-body">
              {verified.length > 0 ? (
                verified.map((test) => <TestCard key={test.id} test={test} />)
              ) : (
                <p className="detail-note">
                  No test passed verification for this run. Check the unverified section
                  and sandbox output before trusting the change.
                </p>
              )}
            </div>
          </section>

          {rejected.length > 0 ? (
            <section className="panel" aria-labelledby="unverified-title">
              <div className="section-head">
                <h2 id="unverified-title">Not verified</h2>
                <span className="count">{rejected.length}</span>
              </div>
              <div className="section-body">
                {rejected.map((test) => (
                  <div className="not-verified" key={test.id}>
                    <span className="test-name">
                      {test.file_path} · {test.function_name}
                    </span>
                    <p className="reject-reason">{test.last_error ?? "No reason recorded."}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="panel" aria-labelledby="sandbox-title">
            <div className="section-head">
              <h2 id="sandbox-title">Sandbox evidence</h2>
              <span className="count">{run.sandbox_runs.length}</span>
            </div>
            {run.sandbox_runs.length > 0 ? (
              run.sandbox_runs.map((sandboxRun) => (
                <SandboxCard key={sandboxRun.id} run={sandboxRun} />
              ))
            ) : (
              <div className="section-body">
                <p className="detail-note">
                  No generated-test execution was recorded. Baseline runs are summarized
                  in the agent trace.
                </p>
              </div>
            )}
          </section>
        </div>

        <div className="detail-column">
          <section className="panel" aria-labelledby="trace-title">
            <div className="section-head">
              <h2 id="trace-title">Agent trace</h2>
              <span className="count">{run.steps.length} steps</span>
            </div>
            <div className="section-body">
              <StepTimeline steps={run.steps} />
            </div>
          </section>

          {run.review ? (
            <section className="panel" aria-labelledby="review-title">
              <div className="section-head">
                <h2 id="review-title">Code review</h2>
                <span className="count">LLM</span>
              </div>
              <div className="section-body">
                <p className="review-copy">{run.review.content}</p>
              </div>
            </section>
          ) : null}

          <Metadata run={run} />

          <section className="panel" aria-labelledby="config-title">
            <div className="section-head">
              <h2 id="config-title">Effective config</h2>
            </div>
            <div className="section-body">
              <pre className="config-block">{JSON.stringify(run.config, null, 2)}</pre>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
