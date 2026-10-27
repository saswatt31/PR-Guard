// Deterministic mock of the read-only PR-Guard API for Playwright E2E runs.
// It intentionally mirrors the JSON shapes served by backend/app/api/routes.py.
import { createServer } from "node:http";

const NOW = "2026-10-27T12:00:00Z";
const PORT = Number(process.env.MOCK_API_PORT ?? 4100);

const summaries = [
  {
    id: "run-verified-1",
    repo_full_name: "acme/demo",
    pr_number: 7,
    head_sha: "1234567890abcdef",
    status: "succeeded",
    summary: "1 verified, 1 not verified; coverage 50.00% → 60.00% (+10.00 pp)",
    files_changed: 1,
    functions_found: 1,
    tests_generated: 2,
    tests_verified: 1,
    cost_usd: 0.0012,
    coverage_delta: 10,
    duration_ms: 18_500,
    created_at: NOW,
    updated_at: NOW,
  },
  {
    id: "run-failed-2",
    repo_full_name: "beta/stale",
    pr_number: 12,
    head_sha: "fedcba9876543210",
    status: "failed",
    summary: "Generation failed after 3 fixer rounds",
    files_changed: 2,
    functions_found: 2,
    tests_generated: 2,
    tests_verified: 0,
    cost_usd: 0.0027,
    coverage_delta: null,
    duration_ms: 12_000,
    created_at: "2026-10-26T09:30:00Z",
    updated_at: "2026-10-26T09:31:00Z",
  },
  {
    id: "run-queued-3",
    repo_full_name: "acme/api",
    pr_number: 3,
    head_sha: "0011223344556677",
    status: "queued",
    summary: null,
    files_changed: 0,
    functions_found: 0,
    tests_generated: 0,
    tests_verified: 0,
    cost_usd: 0,
    coverage_delta: null,
    duration_ms: null,
    created_at: "2026-10-26T08:00:00Z",
    updated_at: "2026-10-26T08:00:00Z",
  },
];

const verifiedDetail = {
  ...summaries[0],
  delivery_id: "delivery-123",
  base_sha: "abcdef1234567890",
  installation_id: 99,
  sender_login: "octocat",
  is_fork: false,
  config: { max_tests: 8, run_baseline_coverage: true },
  error: null,
  llm_calls: 3,
  input_tokens: 1200,
  output_tokens: 300,
  coverage_before: 50,
  coverage_after: 60,
  comment_id: 123,
  comment_url: "https://github.test/acme/demo/pull/7#issuecomment-123",
  steps: [
    {
      id: "step-1",
      sequence: 1,
      node: "analyze",
      status: "succeeded",
      attempt: 1,
      summary: "parsed 1 changed file",
      detail: { files: 1, functions: 1 },
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: 0,
      duration_ms: 12,
      error: null,
      created_at: NOW,
    },
    {
      id: "step-2",
      sequence: 2,
      node: "find_gaps",
      status: "succeeded",
      attempt: 1,
      summary: "1 gap, 0 covered, 0 skipped",
      detail: { gaps: 1, covered: 0 },
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: 0,
      duration_ms: 4,
      error: null,
      created_at: NOW,
    },
    {
      id: "step-3",
      sequence: 3,
      node: "execute",
      status: "succeeded",
      attempt: 2,
      summary: "verified 1, rejected 1",
      detail: { test: "passed", verified: 1, failed: 1, round: 2 },
      input_tokens: 900,
      output_tokens: 220,
      cost_usd: 0.0012,
      duration_ms: 1450,
      error: null,
      created_at: NOW,
    },
  ],
  tests: [
    {
      id: "test-1",
      file_path: "src/math.test.ts",
      function_name: "add",
      source_file: "src/math.ts",
      framework: "vitest",
      content: "it('adds', () => expect(add(1, 2)).toBe(3));",
      status: "verified",
      attempts: 1,
      last_error: null,
      created_at: NOW,
    },
    {
      id: "test-2",
      file_path: "src/broken.test.ts",
      function_name: "broken",
      source_file: "src/broken.ts",
      framework: "vitest",
      content: "it('broken', () => { throw new Error(); });",
      status: "rejected",
      attempts: 2,
      last_error: "sandbox test failed",
      created_at: NOW,
    },
  ],
  sandbox_runs: [
    {
      id: "sandbox-1",
      phase: "test",
      image: "prguard-sandbox:node20",
      command: ["npx", "vitest", "run", "--coverage"],
      network_disabled: true,
      status: "passed",
      exit_code: 0,
      timed_out: false,
      duration_ms: 1450,
      stdout: "Test Files  1 passed",
      stderr: "",
      coverage: { line_pct: 60, files: 1 },
      created_at: NOW,
    },
  ],
  review: {
    content: "No blocking issues.",
    cost_usd: 0,
    created_at: NOW,
  },
};

function detailFor(id) {
  if (id === verifiedDetail.id) return verifiedDetail;
  const summary = summaries.find((run) => run.id === id);
  if (!summary) return null;
  return {
    ...summary,
    delivery_id: `delivery-${summary.id}`,
    base_sha: "abcdef1234567890",
    installation_id: 99,
    sender_login: "octocat",
    is_fork: false,
    config: {},
    error: summary.status === "failed" ? "LLM budget exhausted" : null,
    llm_calls: 1,
    input_tokens: 400,
    output_tokens: 100,
    coverage_before: null,
    coverage_after: null,
    comment_id: null,
    comment_url: null,
    steps: [],
    tests: [],
    sandbox_runs: [],
    review: null,
  };
}

function send(response, status, body) {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "content-length": Buffer.byteLength(payload),
  });
  response.end(payload);
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://${request.headers.host}`);
  const { pathname } = url;

  if (pathname === "/api/stats") {
    return send(response, 200, {
      total_runs: 3,
      queued: 1,
      running: 0,
      succeeded: 1,
      failed: 1,
      skipped: 0,
      tests_generated: 4,
      tests_verified: 1,
      total_cost_usd: 0.0039,
      avg_coverage_delta: 10,
      avg_duration_ms: 15_250,
    });
  }

  if (pathname === "/api/demo") {
    return send(response, 200, { enabled: true, run_count: 3 });
  }

  if (pathname === "/api/runs") {
    const status = url.searchParams.get("status") ?? "";
    const repo = (url.searchParams.get("repo") ?? "").toLowerCase();
    const limit = Math.min(100, Math.max(1, Number(url.searchParams.get("limit") ?? 25)));
    const offset = Math.max(0, Number(url.searchParams.get("offset") ?? 0));
    const filtered = summaries.filter(
      (run) =>
        (!status || run.status === status) &&
        (!repo || run.repo_full_name.toLowerCase().includes(repo)),
    );
    return send(response, 200, {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      limit,
      offset,
    });
  }

  if (pathname.startsWith("/api/runs/")) {
    const id = decodeURIComponent(pathname.slice("/api/runs/".length));
    const detail = detailFor(id);
    if (!detail) return send(response, 404, { detail: "Run not found" });
    return send(response, 200, detail);
  }

  return send(response, 404, { detail: "Not found" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`mock PR-Guard API listening on http://127.0.0.1:${PORT}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
