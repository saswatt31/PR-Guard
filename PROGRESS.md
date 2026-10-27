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
