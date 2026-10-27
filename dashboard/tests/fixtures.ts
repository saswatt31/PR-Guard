import type {
  GeneratedTest,
  RunDetail,
  SandboxExecution,
  Step,
} from "@/lib/types";

const NOW = "2026-10-27T12:00:00Z";

export function makeTest(overrides: Partial<GeneratedTest> = {}): GeneratedTest {
  return {
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
    ...overrides,
  };
}

export function makeStep(overrides: Partial<Step> = {}): Step {
  return {
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
    ...overrides,
  };
}

export function makeSandbox(overrides: Partial<SandboxExecution> = {}): SandboxExecution {
  return {
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
    ...overrides,
  };
}

export function makeRun(overrides: Partial<RunDetail> = {}): RunDetail {
  const base: RunDetail = {
    id: "9a5b7b0a-59e4-4c83-a3fe-5e1e4ff9f6a1",
    repo_full_name: "acme/demo",
    pr_number: 7,
    head_sha: "1234567890abcdef",
    base_sha: "abcdef1234567890",
    status: "succeeded",
    summary: "1 verified, 1 not verified; coverage 50.00% → 60.00% (+10.00 pp)",
    files_changed: 1,
    functions_found: 1,
    tests_generated: 2,
    tests_verified: 1,
    cost_usd: 0.0012,
    coverage_before: 50,
    coverage_after: 60,
    coverage_delta: 10,
    duration_ms: 18_500,
    created_at: NOW,
    updated_at: NOW,
    delivery_id: "delivery-123",
    installation_id: 99,
    sender_login: "octocat",
    is_fork: false,
    config: { max_tests: 8, run_baseline_coverage: true },
    error: null,
    llm_calls: 3,
    input_tokens: 1200,
    output_tokens: 300,
    comment_id: 123,
    comment_url: "https://github.test/acme/demo/pull/7#issuecomment-123",
    steps: [
      makeStep(),
      makeStep({
        id: "step-2",
        sequence: 2,
        node: "find_gaps",
        summary: "1 gap, 0 covered, 0 skipped",
        detail: { gaps: 1, covered: 0 },
        duration_ms: 4,
      }),
      makeStep({
        id: "step-3",
        sequence: 3,
        node: "execute",
        attempt: 2,
        summary: "verified 1, rejected 1",
        detail: { test: "passed", verified: 1, failed: 1, round: 2 },
        duration_ms: 1450,
      }),
    ],
    tests: [
      makeTest(),
      makeTest({
        id: "test-2",
        file_path: "src/broken.test.ts",
        function_name: "broken",
        content: "it('broken', () => { throw new Error(); });",
        status: "rejected",
        attempts: 2,
        last_error: "sandbox test failed",
      }),
    ],
    sandbox_runs: [makeSandbox()],
    review: {
      content: "No blocking issues.",
      cost_usd: 0,
      created_at: NOW,
    },
  };
  return { ...base, ...overrides };
}
