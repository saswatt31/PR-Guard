import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import {
  formatCost,
  formatDelta,
  formatDuration,
  formatShortDate,
  shortSha,
} from "@/lib/format";
import type { RunSummary } from "@/lib/types";

function deltaClass(value: number | null): string {
  if (value === null || value === 0) return "delta-neutral";
  return value > 0 ? "delta-positive" : "delta-negative";
}

export function RunTable({ runs }: { runs: RunSummary[] }) {
  return (
    <div className="table-wrap">
      <table className="runs-table">
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Status</th>
            <th scope="col">Tests</th>
            <th scope="col">Coverage Δ</th>
            <th scope="col">Cost</th>
            <th scope="col">Duration</th>
            <th scope="col">Started (UTC)</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>
                <div className="run-repo">
                  <Link href={`/runs/${run.id}`}>{run.repo_full_name}</Link>
                  <span className="run-meta">
                    #{run.pr_number} · {shortSha(run.head_sha)}
                  </span>
                  {run.summary ? (
                    <span className="run-summary" title={run.summary}>
                      {run.summary}
                    </span>
                  ) : null}
                </div>
              </td>
              <td>
                <StatusBadge status={run.status} />
              </td>
              <td className="cell-number">
                {run.tests_verified}
                <span className="muted"> / {run.tests_generated}</span>
              </td>
              <td className={`cell-number ${deltaClass(run.coverage_delta)}`}>
                {formatDelta(run.coverage_delta)}
              </td>
              <td className="cell-number">{formatCost(run.cost_usd)}</td>
              <td className="cell-number">{formatDuration(run.duration_ms)}</td>
              <td className="run-meta">
                <time dateTime={run.created_at}>{formatShortDate(run.created_at)}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
