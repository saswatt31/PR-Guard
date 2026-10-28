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


## D018 — One LLM protocol, real adapters and a deterministic FakeLLM
**What:** The graph depends on `LLMClient.complete(...)`. `GroqClient` and
`AnthropicClient` implement it with `httpx`; `FakeLLM` implements it with deterministic
marker-driven responses. `build_llm_client` selects one from settings.
**Why:** Provider choice becomes configuration, the whole graph can be tested offline,
and the demo runs without spending money or requiring a user-owned API key. The adapters
return a common `LLMResponse` with text, model and usage.
**Alternatives:** LangChain model wrappers (extra abstraction for two REST APIs), one
hard-coded provider (no fallback), mocking `httpx` inside the graph (couples tests to
HTTP details).
**Limitation:** No live provider call was made in this build; adapter behaviour is tested
with `httpx.MockTransport`. Pricing is a configuration-like estimate, not a bill.

## D019 — Budget checks before calls and after usage
**What:** `BudgetedLLM` rejects a call when the call count is already at the cap. After a
response it adds tokens/cost and rejects further calls if a cap is exceeded. Repo config
can override the process defaults. The summary is returned as run cost.
**Why:** Token and cost usage are only known from the provider response. Refusing before
the next call bounds spend, while recording the response that crossed the line keeps the
overshoot visible. A hard pre-estimate would either be guesswork or reject safe calls.
**Alternatives:** Provider-side quotas (not portable), estimate prompt/completion tokens
before each call (unreliable), no caps (unbounded prompt-injection spend).
**Limitation:** A provider that ignores `max_tokens` can overshoot by one response before
the next call is blocked.

## D020 — Generated tests get a static policy, but Docker is the boundary
**What:** Before writing, a proposal must stay inside the repository, use a test suffix,
avoid the source path and existing files/symlinks, stay under 30k characters/600 lines,
contain `it()`/`test()` and `expect()`, avoid forbidden modules/code (`child_process`,
`fs`, network, `eval`, `process.env`, dynamic import/require), and import only approved
packages or repository-relative paths.
**Why:** These checks stop obvious path escapes, accidental source overwrites and
dangerous imports early, with clear errors for the dashboard. They are cheap and
deterministic. They are explicitly not a sandbox: a determined test can still exhaust
resources, and container isolation plus network-off test execution is the real control.
**Alternatives:** Trust the model (unacceptable), full TypeScript compilation of generated
tests (slower and still not a containment boundary), run everything without checks (worse
feedback, writes outside the workspace possible).
**Limitation:** The policy is syntactic; it can miss obfuscated dangerous behaviour or
reject valid advanced tests.

## D021 — Untrusted prompt delimiters are neutralized
**What:** Repository source, previous tests, failure output and diffs are wrapped in
explicit tags. Any closing-tag text inside the payload is rewritten to `<\/TAG>` so it
cannot terminate the delimiter early. The system prompt tells the model to treat tagged
content as data.
**Why:** A PR author can add `</FUNCTION_JSON><TASK>...` to source or an assertion error.
Neutralizing the closing sequence makes delimiter breakout explicit and keeps the data
inside the intended block. `FakeLLM` also scans every opening tag because the system
prompt itself names the tags.
**Alternatives:** Rely only on model instruction-following (fragile), strip all angle
brackets (changes code and error readability), JSON-escape the entire prompt (models read
escaped code poorly).
**Residual risk:** Neutralization does not make the model immune to injection; it only
preserves the delimiter structure. Static checks and the sandbox remain the controls.

## D022 — Test generation is Vitest-only; UI jsdom tests are opt-in
**What:** The writer asks for Vitest tests. `include_ui_tests: false` (default) skips
functions marked UI and records why; `true` allows Vitest/jsdom tests for those functions.
Playwright is used for the dashboard's own E2E suite, not generated by the PR pipeline.
**Why:** One install/test command keeps the sandbox contract simple and verifiable, and
the sandbox image needs no browser binaries or dev-server orchestration. jsdom covers
component logic; full browser E2E is a different product surface.
**Alternatives:** Generate Playwright specs and provision browsers/dev server (larger
sandbox contract, slower runs), ignore UI functions entirely (missed coverage and a silent
gap), always emit jsdom tests (surprising and sometimes impossible for browser-only code).
**Limitation:** Browser-level behaviours are not generated or verified by this pipeline.
The config field is not a promise of Playwright output.

## D023 — Fixer attempts are run-level rounds
**What:** `max_fix_attempts` (0–3) counts fixer rounds. Each failed draft gets at most one
new proposal per round; `TestProposal.attempts` records how many times that draft was
rewritten. The graph stops at the cap or when no drafts remain.
**Why:** A single counter is easy to reason about and bounds total calls, tokens and wall
clock for the whole run, which is the budget unit users care about. It also avoids a
per-test state machine in the graph.
**Alternatives:** Independent three-attempt budgets per function (can multiply total
spend), one attempt per function and immediate rejection (weaker success rate), unlimited
fixing (unbounded cost).
**Limitation:** One pathological test can consume the same rounds as several tests.

## D024 — Baseline coverage runs on the PR head and is best-effort
**What:** Unless `.prguard.yml` sets `run_baseline_coverage: false`, the processor runs
the repository install command once, then its own test command with coverage, before the
agent graph. A successful install is reused by the graph; a failed baseline is recorded
in a step but does not abort the run. Missing or invalid coverage falls back to the
existing test-reference heuristic.
**Why:** Running on the head shows which changed functions the repository's existing
tests actually execute, which is stronger evidence than name matching. Reusing the
install avoids paying for two `npm ci` runs. Treating baseline failure as fatal would
block runs for repositories with a flaky or currently failing suite, even though the
generated tests can still be verified in isolation.
**Alternatives:** Skip baseline entirely (cheaper but weaker gap detection), require a
green baseline (accurate but brittle), run baseline at the base commit (changed functions
may not exist there and the PR's own tests would be ignored), install twice (simpler but
slow and can double network use).
**Limitation:** The baseline test command executes untrusted repository tests before
generated tests. It has the same sandbox controls, but a malicious baseline can consume
the full time/memory budget. Baseline output is not persisted as a sandbox row; it is
summarized in the `baseline` agent step.

## D025 — The processor takes injectable collaborators and one temporary workspace
**What:** `RunProcessor` receives the database, settings, GitHub client, sandbox,
workspace root, LLM factory and pipeline runner. Production wires the real implementations
in `create_app`; tests use fakes and a temporary directory. The workspace is removed in a
`finally` block.
**Why:** The orchestration has many external boundaries. Injecting them makes the full
webhook-to-comment path testable without Docker, network, provider keys or an installation
token, while keeping one production path. A per-run temporary directory avoids collisions
between concurrent workers and keeps repository content out of the application tree.
**Alternatives:** Monkeypatching module globals (fragile, leaks state between tests),
running everything in the repository directory (collisions and accidental commits),
constructing clients inside each helper (hard to substitute).
**Limitation:** A remote Docker daemon cannot see a local temp directory; the documented
deployment needs a volume copy or a shared workspace. Local mode is not a boundary.

## D026 — Comments are rendered from verified results and posted after persistence
**What:** One Markdown comment contains a run marker, coverage/cost summary, verified test
code in collapsible fences, unverified function names/reasons and capped warnings. It is
capped at 60,000 characters; oversized test content is truncated or omitted with a note.
Results are persisted before posting; `comment_id`/`comment_url` are stored afterwards.
An existing `comment_id` suppresses a second comment.
**Why:** Posting after persistence means a GitHub failure does not throw away analysis.
The marker and stored id make the normal retry path idempotent, and the size cap stays
under GitHub's limit. Only verified code is rendered as code, so a rejected proposal
cannot be mistaken for a posted test.
**Alternatives:** Post first then persist (loses results on a database error), one comment
per test (noisy and harder to update), inline review comments (different API and diff
anchors), omit code content (users must open the dashboard to inspect the test).
**Limitation:** A crash between GitHub accepting the comment and the local `comment_id`
commit can produce a duplicate on retry. There is no comment listing/update endpoint yet.

## D027 — The dashboard API is read-only
**What:** `backend/app/api/routes.py` exposes only `GET /api/runs`, `GET /api/runs/{id}`,
`GET /api/stats` and `GET /api/demo`. The Next.js app fetches these from server components.
No endpoint can create, retry, delete, edit or comment on a run.
**Why:** Writes already belong to the webhook and worker; adding a second write path would
duplicate idempotency, authorization and state-transition logic. An unauthenticated
observability surface is much easier to reason about when it cannot change billing spend,
post to GitHub or execute code.
**Alternatives:** Full admin CRUD (needs authentication and audit logging), direct SQLite
access from Next.js (couples deployments and bypasses API validation), tRPC (extra layer
for four GET endpoints).
**Limitation:** There is no retry button or manual approval flow. Recovery still requires
the worker/operator path.

## D028 — Filtering and pagination are validated at both edges
**What:** The API accepts `limit` 1–100, non-negative `offset`, a `RunStatus` enum and a
255-character repo substring. The repo match is case-insensitive and escapes SQL wildcard
characters. The dashboard page independently clamps `limit`/`offset` and ignores unknown
status values before calling the API.
**Why:** A hand-edited query string should not be able to request the whole database or
turn a repository name into a wildcard scan. Repeating cheap validation in the UI keeps
error pages out of normal navigation and gives the API a hard contract for other clients.
**Alternatives:** Cursor pagination (better for huge histories, more UI state), client-side
filtering (downloads everything), no repo search (weaker demo).
**Limitation:** `OFFSET` pagination gets slower as the table grows; a production deployment
should move to a cursor or add an index-backed search service.

## D029 — The dashboard ships as a standalone, non-root Next.js image
**What:** `dashboard/Dockerfile` builds with `npm ci`, emits Next standalone output and
copies only the standalone server plus static assets into a `node:20-alpine` runner. The
runner uses uid/gid 1001 and `node server.js`; `outputFileTracingRoot` pins tracing to the
dashboard directory so a parent lockfile cannot widen the bundle.
**Why:** The standalone image is much smaller than copying `node_modules`, and pinning the
tracing root avoids the multi-lockfile warning/build contamination observed when the
workspace sits under a directory with another `package-lock.json`. Running as a non-root
user matches the rest of the project's container posture.
**Alternatives:** `next start` with full `node_modules` (larger, requires the Next CLI),
static export (the pages need runtime API reads), Vercel (out of scope for the Compose demo).
**Limitation:** Local E2E still uses `next start` (the standalone server needs a manual
static-copy step that the Dockerfile performs); the Docker image itself was not built
because Docker is unavailable on this machine.

## D030 — Dashboard E2E uses a deterministic mock API
**What:** Playwright starts `dashboard/e2e/mock-api.mjs` on port 4100 and the production
Next build on port 3100. The mock serves the exact response shapes for runs, detail, stats
and demo, including filtering and a 404. Three Chromium tests cover overview stats/filtering,
detail evidence and the not-found page.
**Why:** E2E should fail for UI regressions, not for an empty database, a missing webhook or
an unavailable LLM. A checked-in mock makes the suite offline and reproducible. The backend
has separate API tests against the real SQLAlchemy models.
**Alternatives:** Run FastAPI with a seeded SQLite file (heavier, still needs process
orchestration), intercept fetches in the browser (the dashboard fetches server-side, so
`page.route` cannot see it), skip E2E entirely (loses navigation coverage).
**Limitation:** This is not a live integration test. Next.js streams dynamic routes, so the
not-found UI is served with HTTP 200 plus a `noindex` hint rather than a 404 status; the E2E
asserts the UI and hint instead of the status code.

## D031 — Dev-tool dependencies were upgraded and PostCSS pinned
**What:** The dashboard uses Vitest 4.1.12, `@vitest/coverage-v8` 4.1.12, Vite 6.4.5 and
Playwright 1.64.1. An npm `overrides` entry pins PostCSS to 8.5.32 for Next 15's exact
8.4.31 dependency. `npm audit` reports zero vulnerabilities.
**Why:** The initial install reported critical Vitest/Tinypool and high Vite/Playwright
advisories. Upgrading within the existing major avoided a Next 16 migration; PostCSS 8.5 is
API-compatible with Next 15's usage and clears the remaining advisory. The full test,
coverage, typecheck and build suites were rerun after the upgrade.
**Alternatives:** `npm audit fix --force` (moves to Next 16 and Vitest 5, both breaking),
accepting dev-only findings (still ships vulnerable tooling in CI), removing coverage
(reduces evidence).
**Limitation:** The PostCSS override is an explicit compatibility bet: a future Next 15
patch may assume its pinned version. Revisit when upgrading Next. Vitest 4 required
`"type": "module"` in `dashboard/package.json` because the local Node 20.10 cannot
`require()` the ESM-only `std-env`; the full suite runs on Node 20.10 after that change.

## D032 — The demo repository is standalone and the demo PR adds a new function
**What:** `demo-repo/` is its own TypeScript/Vitest package with a lockfile and a fully
tested baseline. `demo-pr.patch` adds `normalizeScore` in a new file and exports it without
adding tests.
**Why:** PR-Guard downloads a repository tarball and treats it as the project root; keeping
the demo standalone matches that contract. A brand-new exported function has zero test
references and zero baseline coverage, so the gap is unambiguous and the resulting comment
is easy to evaluate. A fully covered baseline also makes the before/after coverage delta
meaningful.
**Alternatives:** Add the demo as a workspace (changes install and coverage paths), modify
an existing function (changed-line selection demo, but the gap is less obvious), ship an
already-failing repo (noisy baseline and unclear blame).
**Limitation:** The demo requires pushing the directory as a separate GitHub repository and
installing the App. CI only runs its baseline suite; it does not run the PR pipeline.

## D033 — CI builds every artifact and runs offline dashboard E2E
**What:** The workflow has four jobs: backend (ruff, pytest coverage, sandbox image),
dashboard (typecheck, Vitest, coverage, build, Chromium Playwright against the mock API),
demo (install, typecheck, tests) and containers (build sandbox, API and dashboard images).
Concurrency cancels superseded runs; each job has a timeout.
**Why:** The Python suite, the Next app and the analyzed demo repo have independent
dependency trees, so a single job would hide which layer broke. Building all images catches
standalone-output mistakes without requiring a long-lived Compose stack. The dashboard E2E
stays deterministic by using its checked-in mock API.
**Alternatives:** One monolithic job (slower, unclear failures), Compose up in CI (needs
secrets and a GitHub App), skipping image builds (Dockerfile drift goes unnoticed).
**Limitation:** The workflow has not been executed here: there is no GitHub remote and no
Docker daemon. Local runs of the individual commands are the only measured evidence.

## D034 — A checked-in smoke harness provides end-to-end evidence without Docker
**What:** `backend/scripts/demo_smoke.py` runs the real `Worker` and `RunProcessor` against
`demo-repo/` with a real temporary workspace, real `npm ci` and real Vitest. GitHub is a
three-method local fake, the model is `FakeLLM`, and the sandbox is `LocalSandboxRunner`
configured with `sandbox_mode="local"`. The script writes a SQLite database and the
rendered comment, then exits non-zero unless the run status is `succeeded`.
**Why:** Unit tests mock each seam, so they cannot catch integration mistakes in tarball
layout, patch application, config loading, npm invocation, JSON coverage parsing,
persistence and graph sequencing. A repeatable local harness gives one honest end-to-end
data point on a machine without Docker, and it doubles as the demo data source for the
dashboard.
**Alternatives:** Claiming the mocked tests are end-to-end (false), requiring Docker to
demo anything (blocks development on this machine), using a hand-built database seed (does
not execute the pipeline), hitting a live provider (nondeterministic, costs money, needs
credentials).
**Limitation:** This is explicitly **not** a security or Docker verification. The local
runner shares the user session and network; the stored execution truthfully reports
`network_disabled=False`. It also does not exercise webhook signatures, installation
tokens, GitHub API calls or provider-specific LLM behaviour. Every document and screenshot
caption must say "local FakeLLM demo", not "sandboxed" or "live".

## D035 — Screenshots come from the real API and demo database, with explicit captions
**What:** `docs/screenshots/dashboard-overview.png` and `docs/screenshots/run-detail.png`
were captured from FastAPI serving `data/demo.db` (the Phase 9 smoke output) and a
production Next build, not from the Playwright mock API. The README captions identify the
run as local, scripted and FakeLLM-powered.
**Why:** The screenshots then demonstrate real SQLAlchemy queries, real Pydantic
serialization and real Next rendering. The Playwright E2E remains the regression test; the
screenshots are illustrative evidence.
**Alternatives:** Capture the mock-API E2E (would show fixture data and prove less), render
a static mock (misleading), skip screenshots (weaker README).
**Limitation:** The run's repository, SHAs and comment URL are fixtures. The screenshots
must never be presented as a live GitHub installation, a Docker sandbox or a real model
response. `data/` is gitignored, so the database is reproducible only by rerunning the
smoke script.

## D036 — Evidence levels are stated explicitly in every document
**What:** The README, `ARCHITECTURE.md`, `CORE_FUNCTIONS.md`, `INTERVIEW_PREP.md`,
`SECURITY.md` and screenshot captions use an explicit distinction between **executed
locally**, **mocked**, and **not verified**. The README has a verification matrix; the
architecture has an evidence section; the interview guide has a "say this plainly"
checklist.
**Why:** A mocked test, a skipped container test and a real npm/Vitest run can all be
described as "passing" if the language is loose. That is the easiest way to lose credibility
in a code review or interview. Recording the execution mode next to each number keeps the
claims calibrated and makes the remaining work unambiguous.
**Alternatives:** A single green "all tests pass" summary (misleading), omitting the skipped
Docker test (dishonest), delegating caveats to a footnote (readers miss them).
**Limitation:** Documentation can drift from code. Phase 10 cross-checked signatures,
defaults, caps and test names, but future changes must update the matrix and captions; no
automation currently enforces that consistency.

## D037 — Repo + head SHA idempotency is enforced by a database constraint
**What:** `runs` has `UniqueConstraint("repo_full_name", "head_sha", name="uq_runs_repo_head")`.
`process_event` keeps the friendly pre-check that returns `duplicate_commit` without an
insert. If a concurrent insert loses the race, the handler catches `IntegrityError`, looks
up the winning delivery or commit and returns that outcome; if neither exists, it re-raises.
**Why:** A pre-check is not an invariant. Two requests or workers can both observe no row
and then both insert, spending LLM budget twice. The database must own the dedupe key.
Returning the winner instead of a 500 also makes GitHub's retry semantics harmless.
**Alternatives:** In-process locks (single worker only), trusting the pre-check (racy),
treating `IntegrityError` as a 500 (the run may already exist and the webhook will retry).
**Limitation:** Dedupe is per repository and head SHA; the same commit in another repository
is intentionally a separate run. SQLite serialises writers, so the race tests simulate the
`IntegrityError` rather than opening two real concurrent connections. There is no migration
tool: `create_all` applies the constraint to new databases only, so an existing SQLite file
must be recreated (or migrated by hand) to gain it.

## D038 — The public demo is a build-time static replay
**What:** `NEXT_PUBLIC_DEMO_MODE=true` makes `dashboard/lib/api.ts` delegate every accessor to
`dashboard/lib/demo.ts`, which imports committed JSON from `dashboard/public/demo-data/` at
build time. The deployed app makes no API request.
**Why:** A Vercel deployment has no backend, database, GitHub App or provider key. A static
replay is cheap, reproducible and cannot leak credentials. Keeping the same function
signatures means filters, pagination, detail pages and 404s use the production code path.
**Alternatives:** Deploy FastAPI + SQLite on a VPS (cost, credentials, attack surface), fetch
JSON from `public/` at runtime (still no backend, but an avoidable runtime dependency), rewrite
the pages with hard-coded demo branches (logic drift).
**Limitation:** The demo cannot show a new run. Regenerating it requires the capture script
and a redeploy. The page stays server-rendered rather than static-exported; that is fine on
Vercel and keeps URL filters and 404 handling simple.

## D039 — Demo captures carry provenance and are sanitized at export
**What:** `scripts/capture_demo_data.py` runs the real local smoke by default, then serialises
SQLite rows through the API's Pydantic models. It writes a `manifest.json` with capture date,
commit, branch, dirty state, provider, GitHub mode, sandbox mode, run config, run ids and
caveats. The exporter replaces absolute Windows/POSIX paths, redacts secret-named keys,
removes installation/comment identifiers, and refuses to write a payload that matches a
secret pattern.
**Why:** A demo without provenance is indistinguishable from hand-written fixtures. The
manifest drives the banner, so the date and commit cannot drift from the data. Serializing
through the response models prevents the static shape from diverging from the live API.
**Alternatives:** Hand-authored demo JSON (dishonest, drifts), commit `data/demo.db`
(binary, contains local paths, not API-shaped), fetch the live API from Vercel (requires a
backend).
**Limitation:** The capture is still a local `FakeLLM` + `LocalSandboxRunner` run. The
manifest and UI say so; it is not Docker or provider evidence. The dirty-state check ignores
the generated `dashboard/public/demo-data/` files themselves, because those are the output
being captured; tracked source changes still set `git_dirty`.

## D040 — Vercel hosts only the dashboard, with one non-secret variable
**What:** The Vercel project root is `dashboard/`, the build command is the default
`npm run build`, and the only environment variable is `NEXT_PUBLIC_DEMO_MODE=true`. No
`vercel.json`, API URL, GitHub token or provider key is committed or configured.
**Why:** The demo path needs nothing else. Keeping the root at `dashboard/` avoids shipping
the backend tests, demo repo and virtualenv to the build. The variable is public by design
(`NEXT_PUBLIC_`) and contains no secret.
**Alternatives:** Deploy the whole repository with a monorepo config (slower, more surface),
commit a `vercel.json` (unnecessary for a single app), reuse the live API URL (would make
the demo depend on an unavailable backend).
**Limitation:** Vercel cannot build the Docker image or run the backend. The demo is read-only
and has no authentication; it contains only the sanitized `acme/prguard-demo` capture. A live
dashboard would still need SSO/VPN or a proxy allow-list.

## D041 — Standalone Next output is opt-in for Docker only
**What:** `next.config.ts` sets `output: "standalone"` only when
`NEXT_OUTPUT_STANDALONE` is `1` or `true`; the dashboard Dockerfile sets `1`, while Vercel
and the local demo build use Next's normal output.
**Why:** The Docker image copies `.next/standalone`, but `next start` warns when standalone
output is enabled and Vercel does not need that layout. Making it explicit keeps both paths
correct. Both spellings are accepted because the first CI container run caught a mismatch:
the Dockerfile set `1` while the config only recognised `true`, so the runner stage's copy
failed.
**Alternatives:** Always standalone (warning, Vercel mismatch), remove Docker support (loses
the documented container path).
**Limitation:** A local `docker build` has not run here; the standalone output is verified
locally, but the full image is only exercised by CI.

## D042 — The demo E2E proves the absence of a backend
**What:** `dashboard/playwright.demo.config.ts` starts the production demo build with
`PRGUARD_API_URL` pointed at a closed port (`127.0.0.1:9`). `e2e/demo/demo.spec.ts` records
every request whose path starts with `/api/` or whose port is 8000/9 and asserts the list is
empty after a home → filter → detail journey. It runs on desktop and mobile.
**Why:** A screenshot or a green build cannot prove that the demo did not quietly call a
local API. Failing the journey on any backend request makes the zero-backend claim testable.
**Alternatives:** Only assert the banner text (does not catch a fetch), run with no network
at all (Playwright needs the local server), rely on code review (regressions slip).
**Limitation:** The check covers requests made by this browser journey, not every future
route. The build-time import itself is enforced by `lib/demo.ts` and the demo Vitest suite.

## D043 — No recording is fabricated; the guide reserves the embed slot
**What:** `docs/DEMO_RECORDING.md` contains the shot list, capture settings and embed
location. The README links to it and explicitly says no video exists yet.
**Why:** A screen recording of a live PR → comment flow is impossible without a GitHub App
installation, provider key and Docker. Embedding a stock clip or an animated mockup would
misrepresent the evidence. The guide lets the recording be added later without changing the
banner contract.
**Alternatives:** Commit an animated GIF of the static demo and call it a recording (still
not live, but at least genuine; deferred), record the local smoke only (does not show the
PR flow), omit the section (less useful to a reviewer).
**Limitation:** Until the file exists, the README has a gap. That is deliberate and labelled.
