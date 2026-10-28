/**
 * Static demo data for the public Vercel deployment.
 *
 * `NEXT_PUBLIC_DEMO_MODE=true` makes every data accessor in `lib/api.ts` read
 * these committed JSON files instead of fetching a FastAPI process. The files
 * are imported at build time, so there is no `public/` runtime read and no
 * network call in either the build or the deployed app.
 *
 * The JSON is produced by `scripts/capture_demo_data.py` from a genuine local
 * run. See `manifest.json` for provenance and caveats.
 */

import demoJson from "../public/demo-data/demo.json";
import detailsJson from "../public/demo-data/details.json";
import manifestJson from "../public/demo-data/manifest.json";
import runsJson from "../public/demo-data/runs.json";
import statsJson from "../public/demo-data/stats.json";
import type { DemoInfo, DemoManifest, RunDetail, RunList, RunStats } from "./types";

export const DEMO_MODE =
  (process.env.NEXT_PUBLIC_DEMO_MODE ?? "").toLowerCase() === "true" ||
  (process.env.NEXT_PUBLIC_DEMO_MODE ?? "") === "1";

const details = detailsJson as unknown as RunDetail[];
const summaries = runsJson as unknown as RunList;
const stats = statsJson as unknown as RunStats;
const demo = demoJson as unknown as DemoInfo;

export function getDemoManifest(): DemoManifest {
  return manifestJson as unknown as DemoManifest;
}

export function getDemoStats(): RunStats {
  return stats;
}

export function getDemoInfo(): DemoInfo {
  return demo;
}

export function getDemoRun(runId: string): RunDetail | null {
  return details.find((run) => run.id === runId) ?? null;
}

interface DemoRunQuery {
  limit?: number;
  offset?: number;
  status?: string;
  repo?: string;
}

export function getDemoRuns(query: DemoRunQuery = {}): RunList {
  const limit = Math.min(100, Math.max(1, query.limit ?? 25));
  const offset = Math.max(0, query.offset ?? 0);
  const repo = (query.repo ?? "").trim().toLowerCase();
  const status = query.status ?? "";

  const filtered = summaries.items.filter((run) => {
    if (status && run.status !== status) return false;
    if (repo && !run.repo_full_name.toLowerCase().includes(repo)) return false;
    return true;
  });

  return {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
  };
}
