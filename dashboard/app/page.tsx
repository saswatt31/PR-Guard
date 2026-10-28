import type { Metadata } from "next";

import { MetricCard } from "@/components/MetricCard";
import { Pagination } from "@/components/Pagination";
import { RunTable } from "@/components/RunTable";
import { RunsFilter } from "@/components/RunsFilter";
import { API_URL, getRuns, getStats } from "@/lib/api";
import { DEMO_MODE } from "@/lib/demo";
import {
  formatCost,
  formatDelta,
  formatNumber,
  formatPct,
  pluralize,
} from "@/lib/format";
import type { RunStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Run console",
};

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const VALID_STATUSES: RunStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "skipped",
];

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function parseLimit(value: string): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return 25;
  return Math.min(100, Math.max(1, parsed));
}

function parseOffset(value: string): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return parsed;
}

export default async function HomePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const rawStatus = first(params.status);
  const status = VALID_STATUSES.includes(rawStatus as RunStatus)
    ? (rawStatus as RunStatus)
    : "";
  const repo = first(params.repo).trim().slice(0, 255);
  const limit = parseLimit(first(params.limit));
  const offset = parseOffset(first(params.offset));

  try {
    const [stats, runs] = await Promise.all([
      getStats(),
      getRuns({ limit, offset, status, repo }),
    ]);
    const verifiedRate =
      stats.tests_generated > 0
        ? (stats.tests_verified / stats.tests_generated) * 100
        : null;
    const averageCost =
      stats.total_runs > 0 ? stats.total_cost_usd / stats.total_runs : 0;
    const filtered = Boolean(status || repo);

    return (
      <>
        <section className="hero">
          <div>
            <p className="eyebrow">TypeScript test intelligence</p>
            <h1>
              Proof,
              <br />
              not <em>promises.</em>
            </h1>
            <p className="hero-copy">
              Every test below passed inside the sandbox before it was proposed. Inspect
              the diff coverage, the execution evidence and what it cost.
            </p>
          </div>
          <aside className="hero-aside">
            <p>
              <strong>The contract</strong>
              A generated test is only marked verified after Vitest executes it with the
              network disabled and its target function is actually hit. Everything else
              stays visible as unverified.
            </p>
          </aside>
        </section>

        <section className="stats-grid" aria-label="Run statistics">
          <MetricCard
            label="Runs"
            value={formatNumber(stats.total_runs)}
            detail={`${stats.succeeded} succeeded · ${stats.failed} failed`}
          />
          <MetricCard
            label="Verified tests"
            value={formatNumber(stats.tests_verified)}
            detail={
              verifiedRate === null
                ? "No tests generated yet"
                : `${formatPct(verifiedRate)} of ${pluralize(stats.tests_generated, "draft")}`
            }
            accent
          />
          <MetricCard
            label="Mean coverage lift"
            value={formatDelta(stats.avg_coverage_delta)}
            detail={
              stats.avg_duration_ms === null
                ? "Measured across completed runs"
                : `Mean run ${(stats.avg_duration_ms / 1000).toFixed(1)} s`
            }
          />
          <MetricCard
            label="LLM spend"
            value={formatCost(stats.total_cost_usd)}
            detail={`${formatCost(averageCost)} average per run`}
          />
        </section>

        <section className="panel" aria-labelledby="runs-title">
          <div className="panel-head">
            <div>
              <h2 id="runs-title">Recent runs</h2>
              <p>
                {filtered
                  ? `${formatNumber(runs.total)} matching run${runs.total === 1 ? "" : "s"}`
                  : "Newest webhook-triggered runs first"}
              </p>
            </div>
            <span className="panel-kicker">{DEMO_MODE ? "Recorded · read only" : "Read-only"}</span>
          </div>
          <RunsFilter status={status} repo={repo} />
          {runs.items.length > 0 ? (
            <>
              <RunTable runs={runs.items} />
              <Pagination
                total={runs.total}
                limit={limit}
                offset={offset}
                status={status}
                repo={repo}
              />
            </>
          ) : (
            <div className="empty-state">
              <span className="empty-mark" aria-hidden="true">
                {filtered ? "?" : "·"}
              </span>
              <h3>{filtered ? "No runs match those filters" : "No runs yet"}</h3>
              <p>
                {filtered
                  ? "Try a different repository fragment or clear the status filter."
                  : "Open or update a pull request on an installed repository. The webhook creates a run here automatically."}
              </p>
            </div>
          )}
        </section>
      </>
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown dashboard error";
    return (
      <>
        <section className="hero">
          <div>
            <p className="eyebrow">Run console</p>
            <h1>
              Proof,
              <br />
              not <em>promises.</em>
            </h1>
          </div>
        </section>
        <section className="error-panel" role="alert">
          <h2>Could not load the run console</h2>
          <p>{message}</p>
          {DEMO_MODE ? (
            <p>
              This deployment is in demo mode and reads only the committed capture. Re-run{" "}
              <code>scripts/capture_demo_data.py</code> to regenerate it.
            </p>
          ) : (
            <p>
              The dashboard expects the API at <code>{API_URL}</code>. Set{" "}
              <code>PRGUARD_API_URL</code> for server-side fetches and{" "}
              <code>NEXT_PUBLIC_API_URL</code> for browser links.
            </p>
          )}
        </section>
      </>
    );
  }
}
