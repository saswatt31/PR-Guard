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
