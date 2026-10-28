export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";
export type StepStatus = "running" | "succeeded" | "failed" | "skipped";
export type TestStatus = "proposed" | "verified" | "rejected";
export type SandboxStatus = "passed" | "failed" | "timeout" | "error";

export interface RunSummary {
  id: string;
  repo_full_name: string;
  pr_number: number;
  head_sha: string;
  status: RunStatus;
  summary: string | null;
  files_changed: number;
  functions_found: number;
  tests_generated: number;
  tests_verified: number;
  cost_usd: number;
  coverage_delta: number | null;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
}

export interface Step {
  id: string;
  sequence: number;
  node: string;
  status: StepStatus;
  attempt: number;
  summary: string;
  detail: Record<string, unknown>;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  duration_ms: number;
  error: string | null;
  created_at: string;
}

export interface GeneratedTest {
  id: string;
  file_path: string;
  function_name: string;
  source_file: string;
  framework: string;
  content: string;
  status: TestStatus;
  attempts: number;
  last_error: string | null;
  created_at: string;
}

export interface SandboxExecution {
  id: string;
  phase: string;
  image: string;
  command: string[];
  network_disabled: boolean;
  status: SandboxStatus;
  exit_code: number | null;
  timed_out: boolean;
  duration_ms: number;
  stdout: string;
  stderr: string;
  coverage: Record<string, unknown> | null;
  created_at: string;
}

export interface CodeReview {
  content: string;
  cost_usd: number;
  created_at: string;
}

export interface RunDetail extends RunSummary {
  delivery_id: string;
  base_sha: string;
  installation_id: number;
  sender_login: string;
  is_fork: boolean;
  config: Record<string, unknown>;
  error: string | null;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  coverage_before: number | null;
  coverage_after: number | null;
  comment_id: number | null;
  comment_url: string | null;
  steps: Step[];
  tests: GeneratedTest[];
  sandbox_runs: SandboxExecution[];
  review: CodeReview | null;
}

export interface RunList {
  items: RunSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface RunStats {
  total_runs: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  skipped: number;
  tests_generated: number;
  tests_verified: number;
  total_cost_usd: number;
  avg_coverage_delta: number | null;
  avg_duration_ms: number | null;
}

export interface DemoInfo {
  enabled: boolean;
  run_count: number;
}

export interface DemoManifest {
  schema_version: number;
  captured_at: string;
  git_commit: string;
  git_commit_short: string;
  git_branch: string;
  git_dirty: boolean;
  source: string;
  repository: string;
  pull_request: number;
  provider: string;
  github: string;
  sandbox: string;
  run_config: Record<string, unknown>;
  run_count: number;
  run_ids: string[];
  repo_url: string;
  recording_url: string;
  caveats: string[];
}
