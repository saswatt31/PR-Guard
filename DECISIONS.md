# Decisions

Each entry records what was chosen, why, and the alternatives. Product decisions are
kept separate from environment workarounds.

## D001 — SQLite for persistence and the job queue
**What:** One SQLite database stores deliveries, runs, traces, generated tests, sandbox
executions and a durable job row per run. An in-process asyncio worker polls the table.
**Why:** Zero extra infrastructure for a portfolio project; the job row survives process
restarts, which `BackgroundTasks` would not. The workload is one webhook at a time.
**Alternatives:** Postgres + Celery/Redis (operationally heavier), pure in-memory queue
(loses jobs), FastAPI `BackgroundTasks` (no durability, no visibility).
**Migration path:** SQLAlchemy models and a single `Database` object; swap the URL and
run worker replicas with `SELECT ... FOR UPDATE SKIP LOCKED` in Postgres.

## D002 — Inline worker inside the FastAPI process
**What:** The worker is started in the FastAPI lifespan when `WORKER_ENABLED=true`.
**Why:** One deployable unit for the demo and Docker Compose. GitHub gets a fast 202;
heavy work happens after the response.
**Alternatives:** Separate worker container (cleaner at scale, more moving parts),
Celery (extra broker), GitHub Actions-based execution (cannot keep webhook latency low).
**Limitation:** A single API instance processes one job at a time; horizontal scaling
requires a Postgres-backed claim query.

## D003 — JSON columns for variable run artefacts
**What:** `runs.config`, `agent_steps.detail`, `sandbox_executions.coverage`/`command`
are JSON columns. Filterable fields stay typed.
**Why:** Config keys and coverage formats vary by target repo; normalising them would add
tables with no query benefit. SQLite's JSON1 support is sufficient.
**Alternatives:** Fully normalised config tables, storing JSON blobs in text (loses
automatic serialization).

## D004 — Python 3.11 target, Python 3.12 locally
**What:** `requires-python >=3.11`; CI and Docker use 3.11. The development machine only
has 3.12.1, so local test numbers were produced on 3.12.
**Why:** The fixed stack specifies 3.11; the code uses no 3.12-only features.
**Alternatives:** Install another interpreter (not available without admin), claim 3.11
after testing only 3.12 (dishonest).

## D005 — Repository checkout is a tarball download
**What:** The worker downloads `GET /repos/{owner}/{repo}/tarball/{head_sha}` with an
installation token and extracts it after path/size validation.
**Why:** No git binary dependency, one API call, immutable commit content, easy to hash
and clean up.
**Alternatives:** `git clone` (more moving parts, credentials handling), GitHub API file
by file (N+1 requests, no coverage execution).

## D006 — Local sandbox mode exists only for development/demo recording
**What:** `SANDBOX_MODE=local` runs Vitest through a subprocess on the host. `docker` is
the default and the only mode claimed as a security boundary.
**Why:** The project must remain demoable on machines without Docker (including the
development machine used for this build). The UI/README state the mode explicitly.
**Alternatives:** Refuse to run without Docker (loses the dashboard/demo), silently
pretend subprocess isolation is secure (unacceptable).

## D007 — Project directory moved
**What:** The build is in `C:\Users\saswa\pr-guard` instead of the initial
`...\OneDrive\Pictures\Documents\Default Project`.
**Why:** The original directory denied all file creation (OneDrive folder ACL issue),
so no build could be committed there.
**Alternatives:** Work in a temp directory (less discoverable), change system ACLs
(requires elevation and affects the user's OneDrive folder).
