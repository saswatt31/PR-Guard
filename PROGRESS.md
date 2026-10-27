# Progress log

> Coverage numbers below are measured with `pytest --cov` / `vitest --coverage` on this
> machine. No number is estimated. Python runs on 3.12.1 locally (CI target is 3.11).

## Phase 1 — Scaffold, persistence, CI skeleton, architecture draft
**Built**
- FastAPI app factory with CORS, `/healthz`, lifespan wiring.
- Typed settings (`Settings`) covering GitHub App, LLM provider, sandbox and worker.
- SQLAlchemy 2.0 models: deliveries, runs, jobs, agent_steps, generated_tests,
  sandbox_executions, code_reviews; SQLite FK enforcement and cascade deletes.
- Pydantic v2 dashboard response schemas.
- `.env.example`, backend Dockerfile, Docker Compose draft, CI workflow skeleton.
- `ARCHITECTURE.md` draft with system/agent Mermaid diagrams, data flow, tech-stack
  rationale and every table/field. `DECISIONS.md` started (D001–D007).
- The initial OneDrive workspace was read-only; the project moved (see D007).

**Files to read**
- `backend/app/settings.py` — all configuration and secret handling.
- `backend/app/db.py` — engine/session lifecycle, SQLite foreign keys.
- `backend/app/models.py` — complete schema and relationships.
- `backend/app/schemas.py` — dashboard API contract.
- `ARCHITECTURE.md` sections 1, 2 and 5.

**Interview questions**
1. Why does the job table exist if there is an asyncio worker? (Durability, restart
   recovery, dashboard visibility; the queue is not the in-memory object.)
2. Why SQLite instead of Postgres, and what exactly would break at scale? (D002/D001:
   single writer, in-process worker, claim semantics.)
3. Why store both `payload_sha256` and run data? (Audit correlation without retaining
   the full untrusted webhook payload.)

**Simplified / deferred**
- No webhook or worker yet; CI workflow only runs the backend at this point.
- `.prguard.yml`, sandbox and agent sections are drafted, not implemented.
- Docker is not installed on the build machine, so Docker-specific tests are deferred
  and will be reported as skipped, never as passed (see Phase 4).

**Measured this phase**
- Backend: 19 tests passed, 0 failed. Coverage **98.96%** (statements+branches,
  `coverage 7.17`, measured over `backend/app`). Only `app/db.py` has 2 uncovered lines.

## Phase 2 — Webhook receiver, signature verification, durable queue, GitHub client
**Built**
- `POST /webhooks/github`: raw-body HMAC-SHA-256 verification, 10 MB body cap, 401/400
  responses, JSON parsing, 202 after enqueue. Production refuses the default secret.
- Idempotency at two levels: unique `X-GitHub-Delivery` and same repo + head SHA.
- Fork policy: fork PRs create a visible `skipped` run and no job unless
  `ALLOW_FORK_PRS=true`.
- Durable `jobs` table + async worker: claim, attempt counter, run status transitions,
  stale processing recovery, graceful shutdown, optional processor injection.
- GitHub App JWT (RS256), installation-token exchange, in-memory token cache with a
  one-minute early refresh, one retry on 401, diff/tarball/comment endpoints.
- Safe GitHub tarball extraction: traversal/symlink/hardlink/duplicate/size/file-count
  rejection before writing.
- Tests cover webhook signature (valid, missing, malformed, tampered), dedupe, fork
  policy, payload validation, queue success/failure/recovery, GitHub auth/client with
  `httpx.MockTransport`, and tarball attacks.

**Files to read**
- `backend/app/webhooks/signature.py` — constant-time HMAC check.
- `backend/app/webhooks/handler.py` — dedupe + run/job transaction and fork policy.
- `backend/app/queue/worker.py` — claim, status transitions, stale-job recovery.
- `backend/app/github/auth.py` / `client.py` — App JWT and installation tokens.
- `backend/app/github/repo.py` — untrusted archive extraction.
- `backend/tests/test_webhooks.py`, `test_worker.py`, `test_github_client.py`,
  `test_repo_extract.py`.

**Interview questions**
1. Why check both the delivery id and the head SHA? (Retries and manual redelivery use a
   new delivery id; the commit hash prevents duplicate LLM spend for the same code.)
2. How does the worker survive a crash mid-run? (Rows left in `processing` are reclaimed
   after a timeout; attempts are capped so poison jobs fail instead of looping.)
3. Why a tarball instead of cloning? (No git binary or credential helper, immutable
   commit content, one request; extraction is hardened against archive attacks.)

**Simplified / mocked**
- GitHub API calls are tested against `httpx.MockTransport`; no live App/installation was
  available (credentials are user-owned), so no real GitHub API call is claimed.
- Webhook→worker wiring is tested by injecting a fake processor; the real processor
  (LangGraph) arrives in Phase 5.
- The worker is single-concurrency by design; scaling notes are in DECISIONS D002.

**Measured this phase**
- Backend: 92 tests passed, 0 failed. Coverage **96.23%** (statements+branches over
  `backend/app`). `ruff check` and `ruff format --check` clean.

## Phase 2 decisions added
- D008 (dedupe by delivery + commit), D009 (JWT `iss` string), D010 (token cache),
  D011 (tarball-only checkout).

## Phase 3 — Diff analysis, TypeScript function extraction, coverage gaps
**Built**
- Unified diff parser: per-file status (added/modified/deleted/renamed), binary
  detection, hunk coordinates, added/removed line sets, old→new line mapping and
  quoted/CRLF path handling.
- Analyzer that reads only changed, non-deleted, non-binary files from the checkout,
  rejects absolute/traversal paths, caps file size, and maps changed lines onto whole
  functions. New files mark every extracted function as new.
- Tree-sitter extraction for TypeScript/JavaScript: top-level functions, exported
  const/let arrow and function expressions, class methods/arrow fields, object-literal
  methods, CommonJS `module.exports.*`/`exports.*`, default exports, re-export lists.
  Constructors, private/protected members, nested functions, declaration files and
  unsupported extensions are skipped.
- Istanbul/V8 coverage JSON parser: per-function hit counts, path normalization for
  absolute/container paths, duplicate-name disambiguation by line range/proximity,
  and line percentage fallback.
- Gap finder: coverage hit count is authoritative; otherwise test-file references and
  default-export sibling tests are fallbacks. Unexported functions, test files and
  paths disabled by `.prguard.yml` are recorded as skipped with reasons.
- `.gitignore` was corrected so the hand-written `backend/app/coverage/` Python package
  is tracked instead of being hidden by the generated `coverage/` output rule.

**Files to read**
- `backend/app/diff/parser.py` — unified diff semantics without a git dependency.
- `backend/app/diff/models.py` — `FileDiff.changed_new_lines` and `FunctionInfo`.
- `backend/app/diff/extract.py` — tree-sitter candidate rules and `mark_only_changed`.
- `backend/app/diff/analyzer.py` — safe path resolution and checkout reads.
- `backend/app/coverage/istanbul.py` / `gap.py` — authoritative vs fallback signals.
- `backend/tests/test_diff_parser.py`, `test_diff_analyzer.py`,
  `test_function_extract.py`, `test_istanbul_coverage.py`, `test_gap.py`.

**Interview questions**
1. Why does the diff parser track both added lines and removed-line mappings? (A pure
   deletion has no new line; mapping it to the removal point still selects the function
   that lost code, at the cost of occasionally selecting an adjacent one.)
2. Why is Istanbul coverage authoritative over “a test mentions this name”? (Name
   matching is cheap but produces false positives; an existing function hit count is
   evidence that code actually executed. The fallback deliberately over-reports gaps.)
3. Why tree-sitter instead of a TypeScript compiler or regex? (No Node process needed,
   robust syntax trees for TS/TSX/JS/JSX, and broken files still yield partial trees;
   regexes mis-handle templates, generics and nested braces.)

**Simplified / deferred**
- Extraction is declaration-oriented and heuristic: overload signatures, destructured
  default exports, decorated Angular classes and dynamic `require` patterns are not
  resolved. A missing function becomes a missed test opportunity, not a false test.
- The default-export sibling-test heuristic treats any co-located test file as evidence;
  it is intentionally a fallback, with coverage taking precedence when available.
- The baseline coverage run is not executed in this phase; Phase 4 will run Vitest in
  the sandbox and feed the resulting JSON into this parser.
- Local analysis is tested on Python 3.12.1; tree-sitter wheels installed successfully
  on Windows. Docker-based coverage execution remains unavailable on this machine.

**Measured this phase**
- Backend: 135 tests passed, 0 failed. Coverage **92.48%** (statements+branches over
  `backend/app`, `pytest-cov`). `ruff check` and `ruff format --check` clean.
- `tree-sitter==0.26.0` + `tree-sitter-typescript==0.23.2` are installed in the local
  venv; parser APIs were exercised against TypeScript, TSX and CommonJS fixtures.

## Phase 3 decisions added
- D012 (tree-sitter traversal without cursor iteration), D013 (coverage-authoritative
  gap signal with heuristic fallback), D014 (changed-line function selection and
  whole-function test scope).

## Phase 4 — Docker sandbox, resource limits, security tests
**Built**
- `DockerSandboxRunner`: one fresh container per command, non-root uid/gid 10001,
  read-only root filesystem, workspace as the only rw bind mount, `cap_drop=ALL`,
  `no-new-privileges`, memory/CPU/PID/shm limits, noexec `/tmp` tmpfs, timeout + kill,
  unconditional force removal, and typed results.
- Test phase is forced offline in code; install phase can request network. Callers
  cannot pass `network_disabled=False` for a test run.
- argv validation (no shell strings, NUL, oversized args) and an executable allow-list
  (`node`, `npm`, `npx`, `pnpm`, `yarn`, `vitest`, `playwright`).
- Environment policy: no host environment inheritance; fixed Docker baseline plus
  only `CI`, `NODE_ENV`, `NODE_OPTIONS`, npm/Vitest/Playwright/PR-Guard names; secret-
  looking and arbitrary variables are rejected.
- `LocalSandboxRunner` for development/demo, explicitly reporting
  `isolation="local (NOT a security boundary)"` and `network_disabled=False`.
- `backend/sandbox/Dockerfile` (`prguard-sandbox:node20`) with Node 20 and uid 10001.
- 19 new sandbox tests using a fake Docker client for creation kwargs, network policy,
  timeout/kill/removal, image pull, environment rejection and local execution.
- `SECURITY.md` Phase 4 draft with trust boundaries, HMAC/fork policy, threat model and
  residual risks. `ARCHITECTURE.md` now documents the sandbox contract.

**Files to read**
- `backend/app/sandbox/docker.py` — security kwargs, wait/kill, cleanup.
- `backend/app/sandbox/security.py` — argv/env policy and log truncation.
- `backend/app/sandbox/local.py` — development-only fallback.
- `backend/app/sandbox/models.py` — `SandboxResult`, limits, command validation.
- `backend/sandbox/Dockerfile` — minimal non-root Node image.
- `backend/tests/test_sandbox_docker.py` — fake-client security tests + skipped Docker
  integration test.

**Interview questions**
1. Why is `network_disabled=True` enforced for the test phase but not install? (Tests
   and generated code are the untrusted execution; installing dependencies needs the
   registry. The install phase has only repository-controlled package scripts inside the
   same hardened container.)
2. What does a read-only root filesystem actually prevent, and what does it not? (It
   blocks writes to `/etc`, `/usr` and the image; the workspace and noexec `/tmp` remain
   writable, and a malicious test can still exhaust CPU/memory/disk until limits or
   cleanup.)
3. Why is a local subprocess not an acceptable production sandbox? (No filesystem
   isolation from the host user, no network namespace, no capability drop; it is only a
   convenience mode and is labelled as such.)

**Simplified / mocked**
- Docker is not installed on the build machine. All Docker tests are marked `docker` and
  skipped when the daemon is unavailable; no real container execution is claimed here.
  Fake-client tests verify the requested isolation flags, not Docker's enforcement.
- Workspace is a bind mount, so a daemon on another host needs a volume-copy variant;
  documented in `SECURITY.md` and `ARCHITECTURE.md`.
- The sandbox does not yet run a real Vitest project; Phase 5 wires the agent graph and
  coverage execution into this runner.
- Docker-outside-of-Docker (Compose) grants host-daemon control; acceptable for the demo,
  explicitly not for multi-tenant production.

**Measured this phase**
- Backend: 171 tests passed, 0 failed, 1 skipped (`test_real_docker_container_...`,
  Docker daemon unavailable). Coverage **93.54%** (statements+branches over `backend/app`).
  `ruff check` and `ruff format --check` clean.

## Phase 4 decisions added
- D015 (Docker-only security boundary), D016 (truthful local fallback), D017 (argv and
  environment allow-lists).

## Phase 5 — `.prguard.yml`, provider-agnostic LLM, budget, safety and LangGraph pipeline
**Built**
- `.prguard.yml` loader: strict Pydantic schema, 64 KB cap, first-file-wins, defaults,
  argv command validation through the sandbox allow-list, relative output paths, and
  bounded glob patterns. The config comes from the PR head and is treated as untrusted.
- Provider-independent LLM layer: `LLMClient` protocol, `FakeLLM` for deterministic
  offline runs, Groq and Anthropic REST adapters using `httpx`, token pricing and a
  `BudgetedLLM` wrapper with per-run call/token/cost caps. Repo config can tighten (or
  relax within schema limits) the process defaults.
- Prompt builders for writer, fixer and reviewer. Repository text is wrapped in explicit
  untrusted-data tags; closing tags are neutralized so source or failure output cannot
  terminate a delimiter early. No secret is placed in any prompt.
- Structured output parsing with markdown-fence/prose recovery and Pydantic validation.
- Generated-test static policy: repository-contained test path, allowed suffixes, size
  and line caps, no source/overwrite/symlink writes, required `it()`/`expect()`, forbidden
  modules/code, approved-package and relative-import containment checks. This is early
  rejection, not the security boundary; Docker remains the boundary.
- Vitest JSON result parser with per-file attribution, absolute/Windows path matching,
  skipped/failed assertion handling and truncation.
- LangGraph pipeline nodes: analyze → find gaps → write → install/test → fix loop →
  review. Install runs once per run; every test phase is network-disabled; results and
  coverage are cleared before each run; verification requires a passing report and, when
  coverage names the function, a non-zero hit count.
- UI functions are opt-in (`include_ui_tests: true`) and receive Vitest/jsdom tests.
  Playwright generation is intentionally not part of this writer (see D022).
- Fixed a real `FakeLLM` bug: the system prompt names `<FUNCTION_JSON>`, so a naive
  regex swallowed the actual payload. Tag extraction now scans every opening tag and
  accepts the first payload that parses.
- `PipelineResult` now exposes the sandbox command/result log for later persistence.

**Files to read**
- `backend/app/config/repo.py` — untrusted YAML and command/path policy.
- `backend/app/llm/base.py`, `fake.py`, `groq.py`, `anthropic.py`, `budget.py`,
  `factory.py` — provider contract, deterministic client, adapters, caps.
- `backend/app/agents/prompts.py` — delimiter construction and neutralization.
- `backend/app/agents/parsing.py` — JSON extraction plus schema validation.
- `backend/app/agents/safety.py` — generated-test policy and safe writes.
- `backend/app/agents/results.py` — Vitest per-file results.
- `backend/app/agents/graph.py` — LangGraph state, nodes, routing, verification.
- `backend/tests/test_repo_config.py`, `test_llm_clients.py`, `test_llm_budget.py`,
  `test_agent_*.py` — config, adapters, safety, parsing, prompts, pipeline.

**Interview questions**
1. Why have both `FakeLLM` and real adapters? (Deterministic offline tests and a demo
   provider; the graph only sees one protocol, so provider choice is configuration.
   Live provider calls are not claimed because no user credentials were available.)
2. Why three validation layers after the LLM? (Pydantic rejects shape/type errors, the
   static policy rejects dangerous paths/imports/code before writing, and the sandbox is
   the only actual containment boundary. Each layer has a different failure mode.)
3. Why is the budget checked after the response as well as before the call? (The call
   cap is exact; token/cost totals are only known after usage returns. One response of
   overshoot is possible and is recorded in the run cost instead of silently ignored.)
4. Why is the fixer counter global instead of per test? (It bounds total LLM calls and
   wall-clock time for the run; per-test independent budgets would be easier to reason
   about per function but can multiply spend. Per-draft attempt counts are still stored.)
5. Why Vitest-only generation? (One install/test command and one sandbox image; browser
   binaries and a dev server make Playwright execution a different pipeline. UI logic is
   covered with jsdom when opted in; Playwright is used for dashboard E2E.)

**Simplified / mocked**
- No live Groq or Anthropic request was made. Adapter tests use `httpx.MockTransport` and
  assert URL, headers, payload, usage parsing and error wrapping; the end-to-end pipeline
  uses `FakeLLM` only.
- Pipeline tests use an in-memory fake sandbox to script install/test outcomes, result
  JSON and coverage JSON. They verify graph routing and verification logic, not Docker or
  a real Vitest process. Docker tests remain skipped on this machine.
- Playwright test generation for UI changes is not implemented; `include_ui_tests`
  enables Vitest/jsdom tests. This is recorded in D022 and must not be described as
  Playwright generation.
- The writer currently emits one test per function and accepts only `framework="vitest"`;
  a Playwright proposal is rejected before execution.
- `max_fix_attempts` is a run-level round count, not an independent cap per function.

**Measured this phase**
- Backend: 392 tests passed, 0 failed, 1 skipped (real-Docker test; daemon unavailable).
  Coverage **95.11%** (statements+branches over `backend/app`, Python 3.12.1 locally;
  CI targets 3.11). `ruff check` and `ruff format --check` clean.
- New Phase 5 modules measured: `agents/graph.py` 95%, `agents/safety.py` 99%,
  `config/repo.py` 97%, `llm/fake.py` 96%; adapter modules are fully covered by
  `httpx.MockTransport` tests.

## Phase 5 decisions added
- D018 (provider protocol + FakeLLM), D019 (post-response budget accounting),
  D020 (static generated-test policy), D021 (delimiter neutralization),
  D022 (Vitest-only generation and jsdom UI opt-in), D023 (global fixer rounds).

## Phase 6 — run processor, baseline coverage and verified-only PR comment

**Built**
- `RunProcessor` (`backend/app/run_processor.py`) now owns the work after the durable
  worker claims a job: load the run, create a per-run temporary workspace, fetch the PR
  diff and head tarball with the installation token, extract through the hardened tar
  reader, load `.prguard.yml`, analyze the diff, run the baseline, invoke the graph,
  persist results, and post one comment.
- Baseline coverage runs on the PR head before the graph (unless
  `run_baseline_coverage: false`): one repository install, then the repository test
  command with coverage and network disabled. A successful install is passed to the
  graph so it is not run twice. A failed baseline is recorded as a failed step and does
  not abort the run; missing/invalid coverage falls back to the existing test-reference
  heuristic (D024).
- The graph now records a `steps` trace (`analyze`, `find_gaps`, `write`, `execute`,
  `fix`, `review`) with status, summary, duration and small structured details. It also
  returns the gap decisions and can reuse a precomputed diff analysis and baseline
  install. This is what the dashboard and comment consume.
- Persistence writes/updates the run counters, config, cost, coverage before/after/delta
  and summary, then replaces the run's `agent_steps`, `generated_tests`,
  `sandbox_executions` and `code_reviews` rows. Retrying the same run does not duplicate
  child rows. Only tests the verifier accepted are stored as `verified`; failed drafts are
  stored as `rejected` with a capped reason.
- `comment.py` renders one Markdown comment containing the run marker, coverage and cost
  summary, collapsible verified test code, unverified names/reasons and capped warnings.
  Rejected code is never rendered as a snippet. Paths/function names are flattened and
  backticks replaced so they cannot break the inline-code structure. The body is capped at
  60,000 characters, with per-test truncation and omission notes.
- Comments are posted only after persistence, and `comment_id`/`comment_url` are stored.
  A retry for a run that already has a `comment_id` does not post a second comment (D026).
  A comment failure leaves the persisted analysis intact and lets the worker mark the run
  failed; the normal retry path remains available.
- `create_app` wires the production `RunProcessor` when the worker is enabled, while
  keeping the worker's processor injectable for tests. Workspace cleanup is unconditional.
- `.prguard.yml` now validates that `results_file` and `coverage_file` end in `.json`, so a
  configuration cannot point the cleanup/read paths at arbitrary files.

**Files to read**
- `backend/app/run_processor.py` — orchestration, baseline, persistence, comment.
- `backend/app/comment.py` — verified-only rendering and size caps.
- `backend/app/agents/graph.py` — step instrumentation, initial analysis/install reuse.
- `backend/app/agents/models.py` — gaps/steps on `PipelineResult`.
- `backend/app/config/repo.py` — baseline toggle and `.json` output validation.
- `backend/app/main.py` — default processor wiring.
- `backend/tests/test_run_processor.py` — fake GitHub/sandbox end-to-end flows.
- `backend/tests/test_comment.py` — formatting and truncation.
- `backend/tests/test_agent_graph.py` — step trace and reuse tests.

**Interview questions**
1. Why persist before posting the comment? (A GitHub 403/502 must not discard analysis
   the sandbox already produced; the database is the durable product. The stored comment
   id makes the normal retry path idempotent. The crash window between GitHub accepting
   the comment and the local id commit is documented as a residual risk.)
2. Why run baseline coverage at the PR head? (It measures whether the PR's own tests
   actually execute the changed functions; name matching is weaker. Running at the base
   commit would miss tests introduced by the PR and functions that do not exist there.)
3. Why is a failing baseline not fatal? (A repository can be red for unrelated reasons;
   generated tests can still be verified independently. We record the failure instead of
   pretending coverage was measured. This is a deliberate availability trade-off.)
4. Why build steps in the graph rather than reconstruct them later? (Durations, retry
   rounds and verification counts are known only while the node runs. Small structured
   details also avoid persisting prompts, source or secrets. The dashboard gets a stable
   trace without replaying the pipeline.)
5. Why render only verified code? (A reader could otherwise copy an unverified snippet.
   The comment is evidence, not a suggestion box. Rejected items still appear by name and
   reason so the gap is visible.)
6. What is still not idempotent? (The comment API call and the local id update are not one
   transaction. A crash after GitHub accepts the comment can duplicate it on retry. An
   update/list-comments API would close that window.)

**Simplified / mocked**
- Docker is still unavailable on this machine. Processor tests use a fake sandbox and
  assert orchestration/persistence, not container isolation. The real-Docker test remains
  skipped; no Docker execution is claimed.
- The processor tests use a fake GitHub client (no live App JWT/installation token) and
  the pipeline uses `FakeLLM` (no Groq/Anthropic request). Both remain verification gaps,
  not production claims.
- The local smoke test used `LocalSandboxRunner`, not Docker. That runner explicitly
  reports `isolation="local (NOT a security boundary)"`; it validates npm/Vitest wiring
  only.
- Baseline sandbox output is summarized in the `baseline` step but is not persisted as a
  `sandbox_executions` row; the generated-test run is. Full baseline logs are not exposed
  in the dashboard.
- The processor stores one comment per run. There is no comment update/list endpoint and
  no human-approval/edit step yet.

**Measured this phase**
- Backend: **413 passed, 0 failed, 1 skipped** (real-Docker test; daemon unavailable).
  Coverage **94.90%** (statements+branches over `backend/app`, Python 3.12.1 locally; CI
  targets 3.11). `ruff check` and `ruff format --check` clean.
- The added run-processor and comment modules are part of that total; the processor tests
  cover full fake-GitHub/fake-sandbox flows, retry cleanup, comment failure, baseline
  variants, no-gap runs and config failure.
- Local-mode smoke with the actual Node/npm/Vitest toolchain (no Docker): baseline
  coverage `0.00%` → generated test verified at `100.00%`, six persisted steps, one PR
  comment, workspace removed. This is evidence for the local runner and orchestration,
  not for the Docker security boundary. A direct processor call left the run `queued`
  because the worker owns run/job status transitions; worker tests assert `succeeded`.

## Phase 6 decisions added
- D024 (best-effort baseline at PR head), D025 (injectable processor and temporary
  workspace), D026 (persist before comment, one verified-only comment).
