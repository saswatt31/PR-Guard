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

## D008 — Idempotency uses delivery id *and* commit SHA
**What:** A repeat delivery id is a no-op; a new delivery for a repo/PR head SHA that
was already analysed returns the existing run instead of starting a second one.
**Why:** GitHub retries and users can redeliver events. Delivery-id dedupe alone would
re-run the same commit, duplicate LLM spend and post duplicate comments.
**Alternatives:** Delivery id only (double spend on redelivery), PR number only (would
ignore pushes), no dedupe (unsafe with at-least-once webhooks).
**Limitation:** A manual "re-run" feature will need an explicit force flag later.

## D009 — GitHub App JWT uses a string `iss`
**What:** `PyJWT 2.15` rejects non-string issuers; the App id is serialized as a string.
**Why:** The installed PyJWT refuses integer `iss`, and GitHub accepts the app id in
string form. Tests decode the token and assert the claim.
**Alternatives:** Pin an older PyJWT (unnecessary), hand-roll JWT (worse).

## D010 — Installation tokens cached in memory only
**What:** A per-installation token/expiry dict, refreshed one minute early, with one
forced refresh on a 401.
**Why:** Avoids an extra token request per API call; tokens live at most one hour and
never touch SQLite or the sandbox.
**Alternatives:** Fetch a token per request (extra latency/rate limit), persist tokens
(secret at rest, invalidation complexity).

## D011 — Checkout by tarball, extracted with a hardened extractor
**What:** Download `/tarball/{sha}`, strip GitHub's single root directory, reject
absolute/traversal/symlink/hardlink/duplicate members, cap file count and expanded
size.
**Why:** Repository content is attacker-controlled even for trusted authors. A single
API call avoids git credential plumbing and guarantees the analysed commit matches the
webhook SHA.
**Alternatives:** `git clone` (extra binary + credentials), per-file API (N+1 calls).

## D012 — Tree-sitter traversal uses an explicit stack
**What:** Extraction traverses with a small `_walk()` generator over `node.children`
instead of `root.walk()` / `TreeCursor`.
**Why:** `tree-sitter` 0.26 changed cursor iteration semantics; treating a `TreeCursor`
as an iterable raises `TypeError`. Explicit traversal is version-stable and easy to
bound.
**Alternatives:** Pin an older tree-sitter (fragile), regex extraction (incorrect for
nested braces/templates/generics).

## D013 — Coverage is authoritative; name matching is a fallback
**What:** If a baseline Istanbul report contains a function entry, a zero hit count
reports a gap even when a test mentions the name. Without coverage, a test-file
reference marks the function covered; otherwise it is a gap. Default exports use a
sibling-test heuristic.
**Why:** Name matching cannot distinguish import-only usage from execution; coverage
can. When uncertain, over-reporting a gap is safer than silently skipping untested
code.
**Alternatives:** Name matching only (false negatives), AST-based call graph (large
scope, still not execution evidence), requiring coverage (blocks repos without a
baseline run).
**Limitation:** Coverage paths must be normalized; duplicate function names are matched
to the nearest/overlapping declaration, which is approximate for generated wrappers.

## D014 — Function selection uses changed new-file lines; tests cover whole functions
**What:** A function is in scope when any changed new-file line intersects its start/end
range. `is_new` requires every line in the function range to be an added line. The test
writer receives the whole function, not just the diff hunk.
**Why:** Partial-hunk tests produce broken imports; whole-function context is what a
developer would use. Deletions are mapped to the removal point because they have no new
line of their own.
**Alternatives:** Only added lines (misses pure deletions), whole changed file (wastes
LLM tokens and tests unrelated code), semantic diff (no reliable TS parser without
running Node).

## D015 — Docker is the only claimed security boundary
**What:** The sandbox runner creates a fresh container per command with a non-root user,
read-only root filesystem, only the workspace bind-mounted rw, all capabilities dropped,
`no-new-privileges`, memory/CPU/PID limits, a noexec tmpfs and unconditional removal.
Test commands are forced to `network_disabled=True`; install commands may opt into the
network.
**Why:** Generated tests and repository code are untrusted. Process-level isolation
cannot contain filesystem or network access; a container with explicit limits gives a
reviewable boundary and clean teardown.
**Alternatives:** Host subprocess (no isolation), Firecracker/gVisor (stronger but too
much operations for this project), running tests in GitHub Actions (cannot verify in the
webhook request path and still needs untrusted-code isolation).
**Residual risk:** Docker-outside-of-Docker gives the API container root-equivalent
access to the host daemon; documented in `SECURITY.md` as a demo-only deployment.

## D016 — Local sandbox mode is labelled, never silently substituted
**What:** `SANDBOX_MODE=local` runs an allow-listed Node/npm command on the host. Result
objects report `isolation="local (NOT a security boundary)"` and
`network_disabled=False` because local mode cannot enforce either.
**Why:** The build machine has no Docker daemon; demos and dashboard work must still be
possible. Reporting the truth prevents the local path from being mistaken for the
verified production boundary.
**Alternatives:** Refuse to run without Docker (no demo), pretend a subprocess is
isolated (dishonest).

## D017 — Sandbox commands are argv lists with an executable/env allow-list
**What:** Commands are validated argv tuples (no shell strings, NUL, excessive length or
argument count). The executable must be one of `node`, `npm`, `npx`, `pnpm`, `yarn`,
`vitest`, `playwright`. The host environment is not inherited; Docker gets a fixed
baseline and only explicitly allowed extras, with secret-looking/arbitrary names
rejected.
**Why:** `.prguard.yml` and LLM output are untrusted; a generic `sh -c` makes every later
control meaningless. An allow-list also stops a worker bug from forwarding
`GITHUB_TOKEN`, `DATABASE_URL` or provider keys into the sandbox.
**Alternatives:** Shell strings (injection, quoting bugs), forwarding the host
environment (secret leakage), no executable restriction (arbitrary binaries).
**Limitation:** `npm` lifecycle scripts remain arbitrary code inside the container, which
is why container isolation and network policy are the real boundary.

