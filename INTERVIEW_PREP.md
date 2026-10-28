# Interview prep

A structured walkthrough of PR-Guard: the 60-second pitch, the architecture, the decisions
most likely to be challenged, and 41 questions with answers. Every claim matches what was
actually run; the final section lists what was **not** verified so you never overclaim.

## 60-second pitch

PR-Guard is a GitHub App that finds changed TypeScript functions with no executing test,
asks an LLM to write Vitest coverage, then **runs the generated tests in a network-disabled
Docker sandbox**. Only tests that pass *and* execute the target function are posted to the
pull request. It persists every step, cost and sandbox log to SQLite and exposes a
read-only Next.js dashboard so the decision is auditable. A public Vercel deployment replays
one sanitized local capture with **no backend and no secrets**, and says so in a permanent
banner.

The hard problem is not generating a test. It is trusting one. The design separates
**generation** (untrusted model output) from **verification** (deterministic execution) and
**publication** (verified-only comment). The model can be wrong, manipulated or offline;
the sandbox result is the gate.

## Architecture in one minute

```
GitHub webhook
  -> HMAC verify + delivery/commit dedupe + durable job row (202)
  -> asyncio worker claims the job
  -> download diff + head tarball, hardened extraction
  -> tree-sitter: changed functions
  -> baseline install + tests -> Istanbul coverage
  -> LangGraph: gaps -> writer -> sandbox execute -> fixer (<= cap) -> review
  -> persist run/steps/tests/sandbox logs/cost
  -> one PR comment with verified tests only
  -> read-only FastAPI + Next.js dashboard
```

Three trust zones:

1. **Untrusted input:** webhook JSON, repository files, `.prguard.yml`, model output.
2. **Trusted orchestrator:** FastAPI process with App key, installation tokens, LLM keys.
3. **Disposable execution:** Docker container with no network during tests, non-root,
   read-only root, dropped capabilities, limits and unconditional removal.

## Demo script (5 minutes)

1. Open the demo dashboard (<https://pr-guard-dashboard.vercel.app>) and hold on the amber
   banner: capture date, commit, `FakeLLM`, fake GitHub, `LocalSandboxRunner`, no backend.
2. Show the overview: one recorded run, 1 verified test, 78.57% → 100.00%, 9,246 ms, $0.00.
3. Open the run detail: six steps, the verified test, the captured Vitest output and the
   disabled **Open PR unavailable** action. Explain that the fake repo has no real PR.
4. Run `backend/scripts/demo_smoke.py`: real npm/Vitest in a temporary workspace, real
   SQLite persistence, fake GitHub and FakeLLM. This is the source of the capture.
5. Show `demo-repo/demo-pr.patch` and explain why `normalizeScore` is an unambiguous gap.
6. Show the comment body in `data/demo-comment.md`: verified code, unverified section,
   coverage and cost.
7. Be explicit: local runner is **not** Docker isolation; no live LLM/GitHub call was made.
   The deployed dashboard is a replay, not a live system.

## Questions

### Architecture and product

**1. Why does this exist? What is the actual user pain?**
PR authors add functions; reviewers cannot tell whether the new branch is tested. Coverage
tools report a repo-wide number, not "this new function was never executed". PR-Guard
targets the delta: changed functions, authoritative per-function hit counts, a generated
test that is executed before anyone sees it. The comment is reviewable evidence, not a
coverage badge.

**2. Why a GitHub App rather than an Action?**
An App gets installation-scoped tokens, webhooks and a stable identity across repositories.
An Action would run inside the customer's workflow with their secrets and would need a
workflow file in every repo. The trade-off is operational: we host a webhook service, keep
a private key and manage a durable queue. For a product, that is the right side of the
trade; for a one-repo demo, an Action would be simpler.

**3. Walk me through one PR end to end.**
Webhook -> HMAC -> dedupe -> run+job transaction -> 202. Worker claims, downloads the head
tarball, extracts safely, loads `.prguard.yml`, measures baseline coverage, extracts changed
functions with tree-sitter, chooses gaps, asks the model for JSON proposals, statically
validates and writes them, runs install (network optional) and tests (network disabled),
parses Vitest JSON plus coverage, fixes failures up to the cap, persists everything, and
posts one comment containing only verified tests. The dashboard reads the persisted state.

**4. Why LangGraph instead of one prompt or a plain Python function?**
The flow has a real loop with a cap, multiple failure boundaries and a need to trace each
step. LangGraph gives a typed state, explicit conditional edges and a visual graph; the
loop counter is visible in code rather than hidden in prose. It is still plain Python
functions underneath, so tests can call nodes directly. A single prompt cannot retry a
specific failed test with its error and cannot pause between generation and execution.

**5. Why SQLite? What happens at scale?**
SQLite gives zero-ops durable storage for a single instance; the queue row and run row
commit together. SQLAlchemy keeps a Postgres move straightforward. At scale I would move to
Postgres with `FOR UPDATE SKIP LOCKED` (or a real queue), multiple workers, object storage
for logs/test bodies, and a separate API/worker deployment. The queue interface is already
a row-claim function, so the worker boundary does not change.

**6. Why one worker?**
SQLite has one writer; a single in-process worker makes claim ordering deterministic and
avoids pretending to have concurrency safety we do not. The `jobs` table is the source of
truth, so splitting the worker into its own process is a deployment change, not a redesign.
The stale-job reclaimer handles crashes.

**7. What is the most important boundary in the system?**
Docker execution, not the static test checks. The model is untrusted, but so is the
repository: `npm ci` can run arbitrary lifecycle scripts. The container has no network
during tests, a read-only root, a non-root user, no capabilities, no-new-privileges and
resource limits. Everything else is defence in depth.

**8. What would you change first for production?**
Three things: (a) a dedicated sandbox runner instead of mounting the host Docker socket
into the API container; (b) Postgres + multiple workers + object storage; (c) authentication
on the dashboard. I would also add a seccomp profile and a workspace disk quota.

### Security

**9. How do you verify a webhook?**
HMAC-SHA-256 over the exact raw bytes with `hmac.compare_digest`. The route limits the body
to 10 MB, verifies before JSON parsing, and returns a uniform 401 for missing/malformed/
wrong signatures. `X-GitHub-Delivery` is required only after authentication. The signature
secret is checked at startup in production; the app refuses to boot with the default.

**10. Why dedupe both delivery id and commit SHA?**
GitHub retries deliveries, and a redelivery has the same id. But a user can also push the
same head SHA again through a different delivery (e.g. reopen), which would spend LLM money
twice. The delivery unique index makes retries no-ops; a second unique index on
`(repo, head_sha)` stops duplicate commit analysis. Both are database constraints, so they
survive restarts; on a lost insert race the handler returns the winning run instead of a 500.

**11. What is the prompt-injection threat model?**
The diff, source, tests, filenames and failure text are attacker-controlled. They are
wrapped in explicit tags, closing tags inside payloads are rewritten (`</TAG>` ->
`<\/TAG>`), and the system prompt says tagged content is data. That reduces manipulation but
does not guarantee anything. The enforcement points are the static policy and, above all,
the sandbox: no secrets in context, no host env, no network during tests, read-only root.
A successful injection can at worst produce a test that fails or wastes bounded compute.

**12. Why not just ask the LLM to verify its own test?**
Because the model cannot execute code and has no ground truth. A model saying "this test
passes" is a generation, not evidence. Verification must be a deterministic execution with
a machine-readable report, and the target function must actually be hit. That is the whole
product thesis.

**13. How do you stop a generated test from reading secrets?**
Secrets are never in the sandbox: no App key, installation token, provider key or database
URL. Docker receives a fixed environment baseline plus only allow-listed extras; secret-
looking names are rejected. The test phase has no network. The host environment is not
forwarded in Docker; local mode copies only a Node-necessary allow-list, and local mode is
labelled as not secure.

**14. What can still go wrong inside the sandbox?**
It can consume CPU/memory until the limits, fill the workspace disk, or exploit a kernel/
container escape (Docker is not a hypervisor). We cap memory/CPU/PIDs/time, use tmpfs for
`/tmp`, drop capabilities and remove the container. A production deployment should add a
seccomp profile, rootless/dedicated runner and a disk quota, or move to gVisor/Firecracker
for hostile multi-tenancy.

**15. Why is the static test policy not the boundary?**
It is syntactic: an obfuscated `process.env` access or a dangerous package API can pass a
regex deny-list. It exists to catch obvious mistakes early, keep files inside the repo and
reject known-dangerous imports, not to contain code. Saying otherwise would be dishonest.

**16. Why is the dashboard unauthenticated, and what would you do?**
It is an internal demo surface. It exposes repository names, SHAs, test code and sandbox
logs, so it must sit behind SSO/VPN or a reverse-proxy allow-list. The API is read-only, so
the immediate blast radius is data exposure, not spend or writes. Production: OIDC at the
proxy, per-repo authorization, and no public API.

**17. What is the Docker socket risk?**
Compose mounts `/var/run/docker.sock` so the API can launch sibling containers. That is
root-equivalent control of the host daemon: a compromised API process can start privileged
containers. It is acceptable only for a local demo. Production needs a dedicated runner,
a restricted socket proxy or rootless Docker, and the API should not hold the socket.

**18. How are installation tokens handled?**
Signed App JWT -> installation token, cached in memory with expiry minus one minute. A 401
forces one refresh and retries once. Tokens are never written to SQLite, never logged and
never passed to the sandbox or the model. The JWT is backdated 60s and expires in 9 minutes.

### Data and reliability

**19. What happens if the worker crashes mid-run?**
The job stays `processing`. On startup, `reclaim_stale_jobs` finds jobs older than the
install + test * attempt cap + 120s. Below the cap they go back to `pending`; at the cap
they fail with an explicit reason, so a poison PR does not loop forever. Run results are
persisted before the comment, so diagnosis survives.

**20. What happens if GitHub is down or rate-limited?**
The processor raises `GitHubAPIError`; the worker records `failed` with the message, and no
comment is posted. The webhook already returned 202 because enqueue is durable. A retry
from the dashboard is a future extension; today you would re-deliver or requeue. The key
property is that a transient downstream failure does not lose the accepted event.

**21. What happens if the LLM returns malformed JSON?**
Pydantic rejects it; the gap is skipped with an error and no file is written. If there are
other valid proposals, they continue. A budget cap breaks out of the writer loop and keeps
already written/verified drafts. The review can also be missing without failing the run.

**22. What happens if the baseline fails?**
The run continues. Install failure means the graph will try install once more (if not
marked installed) and reject drafts on failure; a failing baseline test still loads coverage
if the reporter wrote it, otherwise gap detection falls back to test-file references. The
baseline step records the failure; nothing is silently green.

**23. What happens if the Vitest report is missing?**
If the file is absent, verification falls back to the process exit status. If the file is
present but omits a draft, that draft is rejected. This distinction prevents a stale or
partial reporter output from marking everything as passed. Coverage adds a second check:
zero executions of the target rejects an otherwise passing test.

**24. How do you avoid duplicate PR comments?**
After posting, store `comment_id`; a retry with an id returns early. Results are persisted
first. The residual window is a crash after GitHub accepts the comment but before we store
the id; that can duplicate on retry. The honest fix is a hidden marker plus listing/updating
existing comments, which is not implemented (D026).

**25. Why replace commit when persisting a run?**
A retried run may have partial child rows from a previous attempt. Deleting steps/tests/
sandbox/review and re-inserting inside one transaction makes persistence idempotent and
prevents duplicate dashboard entries. The run row is updated in place.

### LLM and testing

**26. How do you keep LLM cost bounded?**
Per-run call, token and cost caps, with `.prguard.yml` able to tighten them. The call cap is
checked before the call; token/cost caps after, so one overshoot is possible if a provider
ignores `max_tokens`. The overshoot is recorded. Every run persists calls, input/output
tokens and cost; the smoke showed 2 calls / 1,294 tokens / $0 under FakeLLM.

**27. Why FakeLLM?**
Determinism and zero cost. It understands the prompt tags, emits a schema-valid Vitest
proposal, and lets the pipeline, persistence and dashboard be tested without network or
credentials. It also makes the local smoke and the public demo capture reproducible. Provider
adapters are tested with `httpx.MockTransport`, not live calls.

**28. How do you test an LLM-driven system?**
Layered: pure unit tests for parsing/safety/results; node tests with `FakeLLM` and a fake
sandbox; graph tests for routing and caps; processor tests for persistence and comments;
and one real local smoke that executes npm/Vitest. The model itself is not the test target;
the deterministic contracts around it are.

**29. How do you know the generated test covers the function?**
Two signals: Vitest's per-file report marks the test passed, and Istanbul coverage shows a
non-zero hit count for the function under test. If coverage knows the function and the hits
are zero, the draft is rejected even though the process exited zero. If coverage is absent,
the Vitest result is the only signal, and that limitation is explicit.

**30. How many fixer rounds, and why run-level?**
At most 3 by config (0-3 allowed), default 3 in settings and 2 in the demo config. The cap
is run-level rather than per-test so a single pathological test cannot multiply provider
spend; every draft is rewritten at most that many times because each fixer pass processes
all current failures. A draft that never passes is rejected with the last error.

**31. Why Vitest only? Why not generate Playwright tests?**
Vitest is fast, native to the TS/ESM ecosystem, has a JSON reporter and coverage integration,
and runs headless in a small Node container. Playwright needs browsers, more image weight
and a different result model; generating both would double the sandbox and policy surface.
The project uses Playwright for its own dashboard E2E, not for target-repo generation (D022).

**32. How do you test the UI?**
Vitest + React Testing Library with mocked `lib/api.ts` for component/page states, a
production Next build for type/route correctness, Playwright against a deterministic mock
API for overview filtering, detail evidence and not-found navigation, and a separate
no-backend Playwright journey for the static demo. The demo suite records every request and
fails if the browser touches `/api/`; the live-mode E2E does not prove live FastAPI
integration, and backend tests cover the real queries.

**33. What coverage numbers do you have, and what do they mean?**
Backend 95.16% branch-aware with 426 passed and 1 skipped (the real-Docker test). Dashboard
98.18% statements / 92.30% branches / 100% functions / 99.25% lines with 34 tests. Demo repo
100% across 11 tests. Coverage is not correctness: the skipped Docker test is a real gap,
and generated tests are only as good as their assertions.

### Frontend and operations

**34. Why Next.js server components for the dashboard?**
The API can stay private (server-to-server `PRGUARD_API_URL`), there is no browser token or
CORS surface, and the first paint has data. The cost is that every page is dynamic and the
dashboard server must reach FastAPI. Mutations stay in the webhook/worker path, so the UI is
read-only by construction. In demo mode the same server components read build-time JSON, so
the deployed app has no API base and no outbound call.

**35. Why validate pagination twice?**
The API is the hard contract for any client: limit 1-100, offset >= 0, status enum, escaped
repo substring. The page clamps the same values so a hand-edited URL produces a sane page
instead of a 422 error page. It is cheap defence in depth.

**36. How is the production image built?**
Next standalone output is opt-in via `NEXT_OUTPUT_STANDALONE=1`; the Dockerfile sets it and
copies the standalone server plus static assets into a `node:20-alpine` runner, uid/gid
1001. `outputFileTracingRoot` pins tracing to the dashboard so a parent lockfile cannot widen
the bundle. Vercel and the local demo build use Next's normal output. The image was written
but not built here because Docker is unavailable; that is a verification gap, not a claim.

**37. What does CI do?**
Four jobs: backend (ruff check/format, pytest coverage, sandbox image), dashboard (npm ci,
typecheck, Vitest/coverage, live-mode Playwright against the mock API, demo build, no-backend
demo Playwright on desktop/mobile), demo (install, typecheck, tests) and containers (build
sandbox/API/dashboard images). Timeouts and concurrency cancellation are set. The workflow
parses locally but has never run because there is no remote run yet.

### Judgment and failure modes

**38. Tell me about a trade-off you made.**
The local sandbox. Docker is not installed on this machine, so I could either skip end-to-end
verification or build a clearly labelled local runner. I chose the latter: it executes real
npm/Vitest, real extraction, real persistence and the real graph, which caught integration
issues unit tests missed (e.g. path handling and coverage parsing). But it cannot isolate
the network or filesystem, so the code reports `network_disabled=False` and every document
calls it demo-only. I would not ship it as a production backend.

**39. What is the biggest residual risk?**
The Docker boundary is unexercised here, and the comment idempotency window can duplicate a
comment after a crash. The first is a verification gap; the second is a design gap with a
documented fix (list comments, match a hidden marker, update instead of create). I would
address both before calling the system production-ready.

**40. Why is the public demo recorded instead of live?**
A live deployment would need a GitHub App installation, provider key, Docker host and a
public webhook. Those credentials are not available, and putting a demo behind them would
make it fragile and expensive. Instead, the demo replays one genuine local capture with
`NEXT_PUBLIC_DEMO_MODE=true`. The banner names the date, commit, `FakeLLM`, fake GitHub and
`LocalSandboxRunner`; live actions are disabled. I would rather show a smaller, labelled
artifact than imply a live backend exists.

**41. What would you build next?**
In order: (1) authenticated dashboard and per-repo authorization; (2) a dedicated sandbox
runner with a restricted socket/rootless Docker and seccomp; (3) Postgres + multiple
workers + object storage; (4) comment update/dedupe via the stored marker; (5) evaluation
harness with a small corpus of real TS repos and mutation testing of generated assertions;
(6) a richer fixer that can add missing test cases rather than only repair failures.

## Whiteboard prompts

**Design the verification gate.**
Input: draft test path/content, source function, config. Execute install once, test with
network off, parse per-file report, correlate coverage by file/name/line, require passed +
non-zero hits, reject with reason, cap retries. Persist evidence before publishing.

**Design webhook idempotency.**
Unique delivery id, unique `(repo, head_sha)`, insert run+job in one transaction, return 202
after commit, catch `IntegrityError` as a race. Reclaim stale processing jobs on startup.

**Design the sandbox.**
Non-root, read-only root, workspace-only rw mount, no network for tests, dropped caps,
no-new-privileges, memory/CPU/PID limits, noexec tmpfs, timeout+kill, unconditional remove,
fixed env, argv-only commands. Then name the residual risks: kernel escape, disk fill,
Docker socket.

## Numbers to remember

| Metric | Value |
| --- | --- |
| Backend tests | 426 passed, 1 skipped |
| Backend coverage | 95.16% (branch-aware) |
| Dashboard tests | 34 passed |
| Dashboard coverage | 98.18% statements, 92.30% branches, 100% functions, 99.25% lines |
| Dashboard E2E | 3 live-mode (mock API) + 4 demo (desktop/mobile) |
| Demo repo | 11 tests, 100% statements/branches/functions/lines |
| Demo capture | 1 run, 1 verified test, 6 steps, 9,246 ms, 2 FakeLLM calls, 1,294 tokens, $0.00 |
| Local smoke | 1 verified test, 78.57% → 100.00%, 2 FakeLLM calls, 1,294 tokens |
| Secret scan | 10 commits, 940,184 bytes, 0 leaks |
| LLM caps | 24 calls / 120k tokens / $0.75 defaults; `.prguard.yml` can tighten |
| Fixer cap | 3 rounds max (demo config: 2) |
| Webhook body cap | 10 MB; tarball cap 50 MB; extracted cap 200 MB / 20k files |
| Comment cap | 60,000 chars; test block 6,000 chars |

## Honesty checklist

Say this plainly:

- Docker was **not** available; the real-container test is skipped, no image build or
  Compose run is claimed.
- No live GitHub App, Groq or Anthropic call was made. GitHub is faked in processor tests
  and the smoke; adapters use mocked HTTP.
- GitHub Actions has **not** run. Local equivalents were run individually.
- Dashboard E2E uses a mock API, not live FastAPI. The public demo uses a separate static
  capture and a no-backend Playwright suite.
- The screenshots and smoke are a **local FakeLLM demo**, not a production run.
- The Vercel deployment is a **replay**, not a live service. It has one sanitized run and
  no database, model, GitHub token or backend.
- The local sandbox runner is **not** a security boundary and reports that truthfully.
- No screen recording exists yet; the guide and README say so instead of embedding a
  fabricated clip.

If asked "did it work?", the precise answer is: the backend, dashboard, demo repo, demo
build, Vercel build and local end-to-end smoke passed as measured; the Docker,
live-provider, live-GitHub, CI and recording paths remain unverified in this environment.
